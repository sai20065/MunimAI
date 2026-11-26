"""
Score retrieval: BM25 only vs hybrid (BM25 + BGE-M3 dense, reciprocal rank fusion).

For each benchmark question, retrieval returns the clauses the Scheme agent would see. A question counts as a
hit at K if its gold clause is among the first K. A "family hit" means the right scheme was found even if a
neighbouring clause answered. The gold clause is the one the question was drafted from; another clause of the
same scheme may also answer it, so recall is slightly conservative.

Run:  python -m eval.benchmark.retrieval_bench [K ...]      (default K = 8 12)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

from backend.agents.scheme import SchemeAgent, _family, rank_clauses
from backend.config import DBSettings

FIXTURE = Path(__file__).parent / "retrieval_bench.json"
REPORTS = Path(__file__).parent / "reports"


def evaluate(ks: list[int]) -> dict:
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
    kmax = max(ks)
    out: dict = {}
    with psycopg.connect(DBSettings.from_env().conninfo) as conn:
        # clause ids change when a page is re-fetched; (scheme, ref) is stable, so resolve gold to today's id
        current = {(r[1], r[2]): r[0] for r in conn.execute(
            "SELECT id, scheme_code, clause_ref FROM scheme_clauses WHERE superseded_at IS NULL").fetchall()}
        for it in items:
            it["gold_id"] = current.get((it["gold_scheme"], it["gold_ref"]))
        skipped = sum(it["gold_id"] is None for it in items)
        items = [it for it in items if it["gold_id"] is not None]
        out["_meta"] = {"questions": len(items), "skipped_gold_no_longer_current": skipped, "current_clauses": len(current)}
        agent = SchemeAgent(conn, None)
        rows = [tuple(r) for r in conn.execute(
            "SELECT id, scheme_code, clause_ref, clause_text FROM scheme_clauses WHERE superseded_at IS NULL").fetchall()]
        dense_cache: dict[str, dict] = {}                  # one embedding call per question, shared by both modes
        for it in items:
            dense_cache[it["question"]] = agent._dense_ranks(it["question"])
        for mode in ("bm25", "hybrid"):
            hits = {v: {k: 0 for k in ks} for v in ("en", "hinglish", "hi", "all")}
            fam = {v: 0 for v in hits}
            total = defaultdict(int)
            for it in items:
                # same steps as SchemeAgent.retrieve, with the clause rows loaded once for the whole run
                got = rank_clauses(rows, it["question"], kmax, dense_ranks=dense_cache[it["question"]] if mode == "hybrid" else None)
                ids = [c[0] for c in got]
                for v in (it["variant"], "all"):
                    total[v] += 1
                    for k in ks:
                        hits[v][k] += it["gold_id"] in ids[:k]
                    fam[v] += _family(it["gold_scheme"]) in {_family(c[1]) for c in got}
            out[mode] = {v: {"n": total[v], **{f"recall@{k}": round(hits[v][k] / total[v], 3) for k in ks},
                             "family_hit": round(fam[v] / total[v], 3)} for v in hits if total[v]}
    return out


def main() -> None:
    ks = [int(a) for a in sys.argv[1:]] or [8, 12]
    res = evaluate(ks)
    print(f"{'variant':9} {'mode':7} " + " ".join(f"R@{k:<3}" for k in ks) + "  family")
    for v in ("en", "hinglish", "hi", "all"):
        for mode in ("bm25", "hybrid"):
            r = res[mode].get(v)
            if r:
                print(f"{v:9} {mode:7} " + " ".join(f"{r[f'recall@{k}']:<5}" for k in ks) + f"  {r['family_hit']}  (n={r['n']})")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "retrieval_bench.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
