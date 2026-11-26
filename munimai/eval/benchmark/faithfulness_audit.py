"""
Audit the faithfulness checker on REAL answers: run owner questions through the Scheme agent (Qwen boss) and record
the answer, the clauses it cited and the checker's verdict. A person then reads the flagged answers (and a sample of the
passed ones) against the clause text to judge whether the checker was right.

Run:  python -m eval.benchmark.faithfulness_audit [n_retrieval_questions]
Out:  eval/benchmark/reports/faithfulness_audit.json
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

from backend.agents import faithfulness as F
from backend.agents.scheme import SchemeAgent
from backend.config import DBSettings, LLMSettings
from backend.llm import LLM, LLMError

HERE = Path(__file__).parent
OUT = HERE / "reports" / "faithfulness_audit.json"

# Hand-written owner questions about the sources added most recently, where numbers and categories matter.
EXTRA = [
    "What capital subsidy does Karnataka give to small enterprises in Zone 2 under the industrial policy?",
    "Do women entrepreneurs get a higher subsidy under the Karnataka industrial policy 2025-30?",
    "What stamp duty exemption do MSMEs get in Karnataka?",
    "What is the subsidy under the credit linked capital subsidy scheme for SC/ST enterprises?",
    "What does the Telangana MSME handbook say about WE-Hub programmes for women?",
    "Which cluster development support exists for MSMEs?",
    "What is the maximum project cost under PMEGP for manufacturing and for service units?",
    "What subsidy rate does PMEGP give to rural beneficiaries from special categories?",
    "What are the MSME classification limits for micro small and medium enterprises?",
    "Under UP MSME policy what interest subsidy do new micro enterprises get?",
    "What extra do SC ST and women entrepreneurs get under the UP MSME policy?",
    "What seed funding does the Andhra Pradesh startup policy offer?",
    "What interest subsidy does Andhra Pradesh give startups on term loans?",
    "What is NIDHI PRAYAS and how long is a project?",
    "What is the PRAYAS grant and sustenance allowance?",
    "What interest subsidy does the Gujarat industrial policy 2022 give MSMEs?",
    "Does Gujarat reimburse EPF for MSMEs?",
    "How much seed fund can an eligible startup get under the Startup India Seed Fund Scheme?",
    "What is the guarantee cover under CGTMSE for micro enterprises?",
    "What loan does PM SVANidhi give to street vendors?",
]


def one(question: str) -> dict:
    with psycopg.connect(DBSettings.from_env().conninfo) as conn:
        llm = LLM(LLMSettings.from_env())
        try:
            ans, _claim = SchemeAgent(conn, llm).answer(1, question)
        except LLMError as e:
            return {"question": question, "error": str(e)[:120]}
        ids = ans.cited_clause_ids
        rows = conn.execute("SELECT id, scheme_code, clause_ref, clause_text FROM scheme_clauses WHERE id = ANY(%s)", (ids,)).fetchall() if ids else []
    clauses = [{"id": r[0], "scheme_code": r[1], "ref": r[2], "text": r[3]} for r in rows]
    res = F.check(ans.text, clauses)
    return {"question": question, "answer": ans.text, "cited": [c["ref"] for c in clauses], "clauses": clauses,
            "passed": res.passed, "score": res.score, "checked": res.checked,
            "issues": [{"kind": i.kind, "sentence": i.sentence[:200], "detail": i.detail} for i in res.issues]}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    bench = json.loads((HERE / "retrieval_bench.json").read_text(encoding="utf-8"))["items"]
    qs = [i["question"] for i in bench if i["variant"] == "en"][:n] + EXTRA
    with ThreadPoolExecutor(3) as ex:
        rows = list(ex.map(one, qs))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in rows if "answer" in r]
    cited = [r for r in ok if r["clauses"]]
    flagged = [r for r in cited if not r["passed"]]
    print(f"{len(rows)} questions, {len(ok)} answered, {len(cited)} with citations, {len(flagged)} flagged")
    kinds: dict[str, int] = {}
    for r in flagged:
        for i in r["issues"]:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print("flag kinds:", kinds)


if __name__ == "__main__":
    main()
