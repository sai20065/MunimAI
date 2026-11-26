"""
Build the retrieval benchmark: for sampled scheme clauses, Gemma (CPU worker) drafts an owner's question
whose answer lives in that clause, in plain English, Hinglish and Hindi script. The gold clause is the
sampled one, known by construction; no model decides what is correct.

Run:  python -m eval.benchmark.make_retrieval_bench [clauses_per_family]
Out:  eval/benchmark/retrieval_bench.json
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

from backend.agents.scheme import _family
from backend.config import DBSettings, LLMSettings
from backend.llm import LLM, LLMError

OUT = Path(__file__).parent / "retrieval_bench.json"

_SYSTEM = (
    "You write test questions for a search system about Indian government loan, subsidy and startup schemes. "
    "Given a passage, write ONE question a small shop owner or first-time founder would ask whose answer is in the passage. "
    "Use everyday words and do NOT copy phrases from the passage. Never mention 'the passage'. "
    "Then write the same question in Hinglish (Hindi words in English letters) and in Hindi (Devanagari script)."
)


def sample_clauses(per_family: int, seed: int = 7) -> list[tuple]:
    with psycopg.connect(DBSettings.from_env().conninfo) as conn:
        rows = conn.execute(
            "SELECT id, scheme_code, clause_ref, clause_text FROM scheme_clauses "
            "WHERE superseded_at IS NULL AND length(clause_text) BETWEEN 180 AND 900 ORDER BY id").fetchall()
    by_fam: dict[str, list] = defaultdict(list)
    for r in rows:
        by_fam[_family(r[1])].append(r)
    rng = random.Random(seed)
    out = []
    for fam in sorted(by_fam):
        pool = by_fam[fam]
        out += rng.sample(pool, min(per_family, len(pool)))
    return out


def draft(llm: LLM, row: tuple) -> list[dict]:
    cid, code, ref, text = row
    try:
        p = llm.json_call(_SYSTEM, f"Passage (scheme {code.replace('_', ' ')}):\n{text}",
                          schema_hint='{"english": string, "hinglish": string, "hindi": string}', max_tokens=300, agent="bench")
    except LLMError:
        return []
    items = []
    for variant, key in (("en", "english"), ("hinglish", "hinglish"), ("hi", "hindi")):
        q = str(p.get(key) or "").strip()
        if len(q) >= 12:
            items.append({"variant": variant, "question": q, "gold_scheme": code, "gold_ref": ref, "gold_id": cid})
    return items


def main() -> None:
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    rows = sample_clauses(per)
    llm = LLM(LLMSettings.from_env_worker())
    with ThreadPoolExecutor(2) as ex:                      # the worker serves two requests at a time
        results = list(ex.map(lambda r: draft(llm, r), rows))
    items = [i for grp in results for i in grp]
    OUT.write_text(json.dumps({"built_from_clauses": len(rows), "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    by_v = defaultdict(int)
    for i in items:
        by_v[i["variant"]] += 1
    print(f"{len(rows)} clauses -> {len(items)} questions {dict(by_v)} -> {OUT}")


if __name__ == "__main__":
    main()
