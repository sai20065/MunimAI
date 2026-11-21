"""
Baselines for all three models on three skills where CODE decides the score (no model grades another model):

  formula  : propose analysis formulas; score = share that compile, pass unit checks and survive the evaluation
  classify : put bill lines into categories; score = exact-match against a fixed answer key
  ledger   : the existing bill-field extraction benchmark (direction, amount, GST rate), first N scenarios

Nothing here trains anything. It tells us where a model has room to improve, so training is only started where there is.
Run from munimai/:  python scripts/skill_baselines.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
load_dotenv(HERE.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

from backend.agents.math_agent import SEEDS, MathAgent
from backend.analytics import series as S
from backend.config import LLMSettings
from backend.llm import LLM, LLMError
from scripts import run_benchmark

LEDGER_N = 30
MODELS = {
    "qwen2.5-7b (boss)": lambda: LLM(),
    "gemma-3-4b (worker)": lambda: LLM(LLMSettings.from_env_worker()),
    "gemma-3n-e4b (math)": lambda: LLM(LLMSettings.from_env_math()),
}

# ----------------------------------------------------------------------------- formula task
def synthetic_books(kind: str, seed: int):
    rng = np.random.default_rng(seed)
    n = 12
    t = np.arange(n)
    if kind == "trend":
        purchases = 60000 + 2500 * t + rng.normal(0, 2000, n); sales = 1.5 * purchases + rng.normal(0, 3000, n)
    elif kind == "seasonal":
        purchases = 60000 + 12000 * np.sin(t / 12 * 2 * np.pi) + rng.normal(0, 1500, n); sales = 1.6 * np.roll(purchases, 1) + rng.normal(0, 2500, n)
    elif kind == "noisy":
        purchases = 70000 + rng.normal(0, 9000, n); sales = 100000 + rng.normal(0, 12000, n)
    else:
        purchases = 50000 + 3000 * (t % 4) + rng.normal(0, 1500, n); sales = 1.4 * purchases + rng.normal(0, 2000, n)
    s = {k: np.zeros(n) for k in S.UNITS}
    s["sales"], s["purchases"] = np.maximum(sales, 1000), np.maximum(purchases, 1000)
    s["gross_profit"] = s["sales"] - s["purchases"]
    s["output_tax"], s["input_tax"] = s["sales"] * 0.12, s["purchases"] * 0.12
    s["net_cash"] = s["sales"] * 1.12 - s["purchases"] * 1.12
    s["sales_count"], s["purchase_count"] = np.full(n, 20.0), np.full(n, 8.0)
    s["avg_sale"] = s["sales"] / s["sales_count"]
    months = [(2026 - (1 if m < 0 else 0), 1 + m) for m in range(n)]
    return months, s


def run_formula(llm: LLM) -> dict:
    seeds = {c["expression"] for c in SEEDS}
    proposed = valid = useful = json_fail = 0
    for i, kind in enumerate(["trend", "seasonal", "noisy", "steady"]):
        months, s = synthetic_books(kind, 11 + i)
        agent = MathAgent(None, math_llm=llm)
        cands = agent.propose(S.UNITS, months, s)
        if not cands:
            json_fail += 1
            continue
        for c in cands:
            proposed += 1
            rec, _ = agent.evaluate(c, S.UNITS, s, len(months), len(cands))
            ok = rec["status"] != "rejected"
            valid += ok
            useful += ok and c["expression"] not in seeds and c["expression"].strip() not in S.UNITS
    return {"proposed": proposed, "valid": valid, "useful": useful, "no_json": json_fail,
            "score": round(valid / proposed, 3) if proposed else 0.0}


# ----------------------------------------------------------------------------- classify task
CATS = ["raw_material", "utilities", "rent", "wages", "transport", "equipment", "packaging", "professional_fees", "repairs", "sales"]
KEY = {
    "raw_material": ["silk cloth 10 metres", "cotton thread spools", "buttons and zips lot", "wheat flour 50 kg bag", "steel rods 2 tonne", "dye powder 5 kg", "leather hides 12 pcs", "sugar 100 kg", "lining fabric 8 m", "yarn cones"],
    "utilities": ["electricity bill october", "water charges quarterly", "internet broadband monthly", "mobile recharge business line", "gas cylinder commercial", "power bill motor shed"],
    "rent": ["shop rent november", "godown monthly rent", "workshop premises rent", "stall rent market"],
    "wages": ["salary tailor helper", "daily wages cutting staff", "driver monthly pay", "labour charges loading", "stitching piece rate payout"],
    "transport": ["lorry freight to Bengaluru", "auto charges delivery", "courier charges parcels", "tempo hire for goods", "diesel for delivery van"],
    "equipment": ["sewing machine new", "weighing scale digital", "mixer grinder commercial", "display rack steel", "computer for billing"],
    "packaging": ["carton boxes 200 pcs", "plastic covers bundle", "gift wrap rolls", "printed labels tags"],
    "professional_fees": ["ca fees for return filing", "lawyer fee agreement", "audit fee annual", "consultant charges design"],
    "repairs": ["sewing machine servicing", "shop shutter repair", "freezer compressor repair", "painting of shop front"],
    "sales": ["blouse stitching order delivered", "sold sarees to customer", "bulk order uniforms invoice", "retail sale of groceries today", "catering order payment received"],
}


def classify_items(seed: int = 3):
    rng = random.Random(seed)
    items = [(txt, cat) for cat, lst in KEY.items() for txt in lst]
    rng.shuffle(items)
    return items


def run_classify(llm: LLM) -> dict:
    items = classify_items()
    hit = 0
    errors = 0
    for b in range(0, len(items), 10):
        batch = items[b:b + 10]
        listing = "\n".join(f"{i}. {t}" for i, (t, _) in enumerate(batch))
        try:
            out = llm.json_call(
                "You classify small-business bill lines. Categories: " + ", ".join(CATS) + ". Use 'sales' only for money received from customers.",
                "Classify each line:\n" + listing, schema_hint='{"items": [{"i": int, "category": string}]}', max_tokens=500, retries=1)
        except LLMError:
            errors += 1
            continue
        got = {int(x.get("i", -1)): str(x.get("category", "")).strip().lower() for x in out.get("items", []) if isinstance(x, dict)}
        hit += sum(1 for i, (_, gold) in enumerate(batch) if got.get(i) == gold)
    return {"n": len(items), "correct": hit, "batch_errors": errors, "score": round(hit / len(items), 3)}


# ----------------------------------------------------------------------------- ledger task
def run_ledger(llm: LLM) -> dict:
    rep = run_benchmark.evaluate(llm, run_benchmark.load_scenarios()[:LEDGER_N])
    return {"n": rep["n_scenarios"], "score": round(rep["weighted_score"], 3), "fields": {k: round(v, 3) for k, v in rep["field_accuracy"].items()}}


def run_model(label: str) -> dict:
    llm = MODELS[label]()
    out = {"healthy": llm.health()}
    if not out["healthy"]:
        return out
    only = os.environ.get("SKILLS")
    for name, fn in (("formula", run_formula), ("classify", run_classify), ("ledger", run_ledger)):
        if only and name not in only.split(","):
            continue
        t = time.time()
        try:
            out[name] = fn(llm)
        except Exception as e:
            out[name] = {"error": str(e)[:200]}
        out[name]["seconds"] = round(time.time() - t)
        print(f"[{label}] {name}: {out[name]}", flush=True)
    return out


if __name__ == "__main__":
    keep = os.environ.get("MODEL_FILTER")
    if keep:
        MODELS = {k: v for k, v in MODELS.items() if any(x in k for x in keep.split(","))}
    with ThreadPoolExecutor(3) as ex:
        results = dict(zip(MODELS, ex.map(run_model, MODELS)))
    path = HERE / "eval" / "benchmark" / "reports" / f"skills_baseline_{time.strftime('%Y-%m-%dT%H-%M-%S')}.json"
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nSUMMARY (score = share correct, higher is better)")
    for label, r in results.items():
        print(f"{label:22} formula={r.get('formula', {}).get('score')} (useful {r.get('formula', {}).get('useful')})  classify={r.get('classify', {}).get('score')}  ledger={r.get('ledger', {}).get('score')}")
    print("report:", path)
