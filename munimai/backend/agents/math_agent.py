"""
The Math agent: proposes formulas and reads the owner's numbers with them, but never does the arithmetic.

Loop:  series (code)  ->  candidate formulas (Gemma 3n "math" model)  ->  strict parse + unit check (code)
       ->  backtest / sanity (code)  ->  market benchmarks (web, grounded)  ->  insight text (Qwen)
       ->  number-grounding check (Verifier)  ->  saved.

Everything that could change a number or a verdict is code. A formula the model invents is only text until
it passes safe_expr and the backtest, and an insight is blocked if it quotes a number the code did not compute.
Most candidates will be sensible recombinations of standard metrics; we do not claim novelty. Results on
short histories are labelled indicative. Nothing here touches a GST return or its approval snapshot.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from ..analytics import backtest, library, market, series as S
from ..analytics.safe_expr import FormulaError, compile_formula, unit_label
from ..llm import LLM, LLMError
from ..trace import Trace
from .verifier import Claim, Verifier

MAX_CANDIDATES = 8
JUDGEMENT = re.compile(r"\b(significant\w*|substantial\w*|steady|strong\w*|healthy|efficien\w+|excellent|poor\w*|good|bad|savings?|benefit\w*|concerning|alarming|impressive|robust|solid|promising|worrying)\b", re.I)

SEEDS = [
    dict(name="Gross margin", expression="gross_profit / sales", kind="descriptive", target=None,
         rationale="Share of sales left after buying goods."),
    dict(name="Purchases as a share of sales", expression="purchases / sales", kind="descriptive", target=None,
         rationale="How much of each sale goes back into buying stock."),
    dict(name="Input tax credit as a share of tax charged", expression="input_tax / output_tax", kind="descriptive", target=None,
         rationale="Input tax credit relative to the tax you charge; high values mean you are claiming a lot of credit."),
    dict(name="Monthly sales growth", expression="growth(sales)", kind="descriptive", target=None,
         rationale="Month-on-month change in sales."),
    dict(name="Do purchases this month predict next month's sales?", expression="purchases", kind="predictive", target="sales",
         rationale="Shops often stock up before selling more; the backtest decides if that holds here."),
]

_SYSTEM = (
    "You are a careful business mathematician for a small Indian business. Propose formulas over MONTHLY series. "
    "Grammar: names of the given series, numbers, + - * / and ** with a small constant exponent, and ONLY these functions "
    "with exactly these arguments: log(x), sqrt(x), abs(x), mean(x), diff(x), growth(x), lag(x, k), roll(x, k), minimum(a, b), "
    "maximum(a, b). k is a plain whole number. No keyword arguments, no other functions, no extra arguments. Never invent a "
    "series name. Only add or subtract series with the same unit. Valid examples: gross_profit / sales ; growth(sales) ; "
    "roll(sales, 3) ; (sales - lag(sales, 1)) / lag(sales, 1) ; purchases / roll(purchases, 3) ; input_tax / output_tax. "
    "Each formula should answer a real decision (cash safety, margin, tax credit, seasonality, stocking, pricing). "
    "Prefer simple, explainable formulas."
)


def _series_hint(units, months, series) -> str:
    lines = []
    for k in series:
        v = series[k]
        last = [round(float(x), 2) for x in v[-3:] if np.isfinite(x)]
        lines.append(f"- {k} ({unit_label(units[k])}): {S.DESCRIPTIONS.get(k, '')}; last values {last}")
    return f"{len(months)} months of data.\n" + "\n".join(lines)


class MathAgent:
    def __init__(self, conn: psycopg.Connection, math_llm: Optional[LLM] = None, writer_llm: Optional[LLM] = None,
                 second_llm: Optional[LLM] = None) -> None:
        self.conn = conn
        self.math = math_llm          # the main proposer (Qwen: fast and, after the repair round, mostly valid)
        self.writer = writer_llm
        self.second = second_llm      # optional second opinion (Gemma 3n on system RAM); slower, adds variety

    # ------------------------------------------------------------------ candidates
    def propose(self, units, months, series, trace: Optional[Trace] = None) -> list[dict]:
        if self.math is None:
            return []
        try:
            parsed = self.math.json_call(
                _SYSTEM,
                _series_hint(units, months, series) + f"\nPropose up to {MAX_CANDIDATES} formulas. For a formula that should forecast "
                "next month's value of a series, set kind=predictive and target to that series; otherwise kind=descriptive.",
                schema_hint='{"formulas": [{"name": string, "expression": string, "kind": "predictive|descriptive", '
                            '"target": string or null, "why": string}]}',
                trace=trace, agent="math", max_tokens=900)
        except LLMError:
            return []
        out = self._to_candidates(parsed)
        # one repair round: the checker's own error messages go back to the model, which fixes only the broken ones
        bad = []
        for c in out:
            try:
                compile_formula(c["expression"], units)
            except FormulaError as e:
                bad.append((c, str(e)))
        if bad and self.math is not None:
            listing = "\n".join(f"{i}. {c['expression']}  ->  ERROR: {err}" for i, (c, err) in enumerate(bad))
            try:
                fixed = self.math.json_call(
                    _SYSTEM, "These formulas were rejected by the checker. Rewrite each one so it is valid, keeping its meaning, "
                    "or drop it. Series available: " + ", ".join(units) + "." + "\n" + listing,
                    schema_hint='{"formulas": [{"name": string, "expression": string, "kind": "predictive|descriptive", '
                                '"target": string or null, "why": string}]}', trace=trace, agent="math", max_tokens=700)
                repaired = self._to_candidates(fixed)
                bad_expr = {c["expression"] for c, _ in bad}
                out = [c for c in out if c["expression"] not in bad_expr] + repaired
            except LLMError:
                pass
        return out

    @staticmethod
    def _to_candidates(parsed: dict) -> list[dict]:
        out = []
        for f in (parsed.get("formulas") or [])[:MAX_CANDIDATES]:
            if isinstance(f, dict) and f.get("expression"):
                out.append(dict(name=str(f.get("name") or f["expression"])[:80], expression=str(f["expression"]).strip(),
                                kind="predictive" if f.get("kind") == "predictive" else "descriptive",
                                target=f.get("target") if isinstance(f.get("target"), str) else None,
                                rationale=str(f.get("why") or "")[:300], source="llm"))
        return out

    def evaluate(self, cand: dict, units, series, n: int, n_cands: int) -> tuple[dict, Optional[object]]:
        """Returns (record, compiled). The record always says why it was kept or rejected."""
        rec = dict(cand)
        try:
            f = compile_formula(cand["expression"], units)
        except FormulaError as e:
            rec.update(status="rejected", unit=None, evidence=backtest.Evidence(cand["kind"], "rejected", str(e), n).to_dict())
            return rec, None
        if cand["kind"] == "predictive" and cand.get("target"):
            ev = backtest.evaluate_predictive(f, series, cand["target"], n, n_cands)
        else:
            rec["kind"] = "descriptive"
            ev = backtest.evaluate_descriptive(f, series, n)
        rec.update(status=ev.status, unit=unit_label(f.unit), evidence=ev.to_dict())
        if (cand.get("source") != "seed" and f.unit and ev.status != "rejected"
                and re.search(r"\b(ratio|rate|share|margin|percent)\b|%", cand["name"], re.I)):
            rec["status"] = "rejected"
            rec["evidence"]["status"] = "rejected"
            rec["evidence"]["reason"] = f"named like a ratio but its result is in {unit_label(f.unit)}"
        return rec, f

    # ------------------------------------------------------------------ run
    def run(self, bid: int, end_month: tuple[int, int], *, task_id: Optional[int] = None, sector: Optional[str] = None,
            use_web: bool = True, trace: Optional[Trace] = None) -> dict:
        months, series = S.load(self.conn, bid, end_month)
        n = len(months)
        if trace:
            trace.emit("math", "agent_start", {"months": n, "web": use_web})
        if n == 0:
            return {"formulas": [], "insights": [], "note": "No books yet, nothing to analyse."}
        units = S.UNITS
        proposals = self.propose(units, months, series, trace)
        if self.second is not None:
            from concurrent.futures import ThreadPoolExecutor
            other = MathAgent(None, math_llm=self.second)
            with ThreadPoolExecutor(1) as ex:
                fut = ex.submit(other.propose, units, months, series, None)
                try:
                    proposals += fut.result(timeout=420)
                except Exception:
                    pass                                   # a slow or absent second opinion never holds up the month-close
        cands = [dict(c, source="seed") for c in SEEDS] + proposals
        seen, records = set(), []
        for c in cands:
            if c["expression"] in seen:
                continue
            seen.add(c["expression"])
            rec, _ = self.evaluate(c, units, series, n, len(cands))
            records.append(rec)
            self.conn.execute(
                "INSERT INTO formulas (business_id, name, expression, kind, target, unit, rationale, source, status, evidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (business_id, expression) DO UPDATE SET "
                "status=EXCLUDED.status, evidence=EXCLUDED.evidence, unit=EXCLUDED.unit",
                (bid, rec["name"], rec["expression"], rec["kind"], rec.get("target"), rec.get("unit"),
                 rec.get("rationale"), rec["source"], rec["status"], Jsonb(rec["evidence"])))
        self.conn.commit()
        if trace:
            trace.emit("math", "tool_result", {"candidates": len(records),
                       "validated": sum(r["status"] == "validated" for r in records),
                       "rejected": sum(r["status"] == "rejected" for r in records)}, tool_name="formulas.evaluate")

        bench = []
        if use_web and sector and self.math is not None:
            bench = market.collect(self.conn, self.math, sector)
        insights = self.write_insights(bid, task_id, records, bench, n, trace)
        return {"months": n, "formulas": records, "market": bench, "insights": insights}

    # ------------------------------------------------------------------ insights
    # The model does NOT write the insight sentences. Every sentence is built from a fixed template and the
    # computed numbers, so it cannot misdescribe a formula, invent a figure or add a judgement. The
    # model's only voice here is its own proposed "why", shown as such and screened for judgement words.
    def write_insights(self, bid, task_id, records, bench, n, trace) -> list[dict]:
        usable = [r for r in records if r["status"] in ("validated", "descriptive", "indicative")
                  and r["evidence"].get("latest_value") is not None]
        if not usable:
            return []
        facts, allowed = [], [float(n)]
        for r in usable:
            ev = r["evidence"]
            facts.append({"name": r["name"], "expression": r["expression"], "kind": r["kind"], "target": r.get("target"),
                          "value": ev["latest_value"], "unit": r.get("unit"), "status": r["status"], "source": r["source"],
                          "why": r.get("rationale") or "", "improvement": ev.get("improvement")})
            allowed.append(ev["latest_value"])
            allowed.append(ev["latest_value"] * 100 if r.get("unit") == "ratio" else ev["latest_value"])
            if ev.get("improvement") is not None:
                allowed.append(100 * ev["improvement"])
        for b in bench:
            facts.append({"market": b["metric"], "low": b["value"], "high": b.get("value_high"), "unit": b["unit"],
                          "official": b["official"], "source": b["url"]})
            allowed += [b["value"]] + ([b["value_high"]] if b.get("value_high") is not None else [])
        text = self._compose(facts, n)
        # defence in depth: the template cannot invent numbers, but check anyway
        ok = Verifier(self.conn).check(Claim(business_id=bid, agent="math", text=text, needs_citation=False, allowed_numbers=allowed)).passed
        notes = self._reading_notes([f for f in facts if "market" not in f])
        if notes:                                 # after the number check: these are definitions, not figures about the business
            text += "\n\nReading notes (definitions from open textbooks, not about your numbers):\n" + "\n".join(notes)
        title = "What your numbers say this month"
        self.conn.execute("INSERT INTO insights (business_id, task_id, title, body, numbers, grounded) VALUES (%s,%s,%s,%s,%s,%s)",
                          (bid, task_id, title, text, Jsonb(facts), ok))
        self.conn.commit()
        return [{"title": title, "body": text, "facts": facts}]

    def _reading_notes(self, own_facts) -> list[str]:
        """One short attributed definition for a few formulas, from the retrieval-only library. Excerpts that contain
        digits are skipped so a textbook example can never be mistaken for the owner's figure."""
        out, seen = [], set()
        try:
            for f in own_facts[:6]:
                for h in library.search(self.conn, f["name"], 2):
                    ex = library.excerpt(h["text"], f["name"])
                    words = [w for w in re.findall(r"[a-z]{4,}", f["name"].lower()) if w not in ("share", "charged", "level", "this", "that", "with")]
                    need = min(2, len(words))
                    relevant = sum(w in ex.lower() for w in words) >= need
                    if (ex and relevant and not re.search(r"[0-9]", ex) and not JUDGEMENT.search(ex)
                            and ex not in seen and len(ex) > 60):
                        seen.add(ex)
                        out.append(f'- {f["name"]}: "{ex}" ({h["attribution"]})')
                        break
        except Exception:
            self.conn.rollback()
        return out[:3]

    @staticmethod
    def _fmt(value: float, unit: Optional[str]) -> str:
        if unit == "ratio":
            return f"{value * 100:.1f}%"
        if unit and unit.startswith("rupees"):
            return f"Rs {value:,.0f}" + (" per item" if "per item" in unit else "")
        return f"{value:,.2f}".rstrip("0").rstrip(".") + (f" {unit}" if unit and unit != "count" else "")

    @classmethod
    def _compose(cls, facts, n: int) -> str:
        own = [f for f in facts if "market" not in f]
        lines: list[str] = []
        for f in own:
            val = cls._fmt(f["value"], f["unit"])
            tag = f" (indicative only, {n} months of data)" if f["status"] == "indicative" else ""
            if f["kind"] == "predictive" and f["status"] == "validated":
                lines.append(f"- Test result: {f['name']} Over past months, using this month's {f['expression']} to forecast next month's "
                             f"{f['target']} had {100 * f['improvement']:.0f}% less error than the best simple guess. "
                             f"This month's {f['expression']} is {val}. This is evidence of a pattern, not a forecast.")
            elif f["kind"] == "predictive":
                lines.append(f"- Not proven: {f['name']} The test did not show a reliable pattern{tag}.")
            else:
                lines.append(f"- {f['name']}: {val}{tag}.")
            why = (f["why"] or "").strip()
            if why and f["source"] == "llm" and not JUDGEMENT.search(why):
                lines[-1] += ' (Model idea: "' + why + '")'
        for b in (f for f in facts if "market" in f):
            rng = f"{b['low']:g}" + (f" to {b['high']:g}" if b.get("high") is not None else "")
            tag = "official source" if b["official"] else "not official"
            lines.append(f"- Market note ({tag}): {b['market']} {rng}{b['unit'] or ''}. Source: {b['source']}")
        lines.append("These figures come from your books. Please confirm them with your CA.")
        return "\n".join(lines)
