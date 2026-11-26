"""
Benchmark for the faithfulness checker. The gold label is known by construction, no model decides it.

Faithful cases (should pass), built from real clauses in the library:
  verbatim      one sentence copied from the clause
  framed        the same sentence behind "According to the official text, ..."
  units         the same sentence with "N lakh" written as digits and "N crore" as lakh (same meaning, new units)
Unfaithful cases (should be caught), each a verbatim sentence changed by one planted error:
  number        a figure replaced by one that is not in the clause
  category      a category swapped for one the clause never mentions (micro->medium, rural->urban, ...)
  negation      a "does not provide" claim added to a clause that contains no negation at all
  cross_scheme  a sentence taken from a clause of a different scheme
  invented      a plausible rule the clause does not contain

Run:  python -m eval.benchmark.faithfulness_bench [clauses]      (default 300)
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

from backend.agents import faithfulness as F
from backend.agents.scheme import _family
from backend.config import DBSettings

REPORTS = Path(__file__).parent / "reports"
_NUM_TOKEN = re.compile(r"(\d[\d,]*(?:\.\d+)?)(\s*(?:%|per\s?cent|percent|lakhs?|crores?))?", re.I)
_SWAPS = [("micro", "medium"), ("medium", "micro"), ("rural", "urban"), ("urban", "rural"), ("manufacturing", "service sector"),
          ("women", "minorities"), ("Women", "Minorities"), ("small", "medium")]
_INVENTED = [
    "Applicants must also deposit a refundable security amount equal to 5% of the project cost with the district office.",
    "The benefit is paid within 30 days of the application and no inspection is required.",
    "Entrepreneurs above 55 years of age are not eligible to apply under this provision.",
    "A processing fee of Rs 10,000 must be paid before the proposal is considered.",
    "The subsidy is available only to units located within 10 km of a state highway.",
]


def sentences_with_rules(text: str) -> list[str]:
    out = []
    for s in F._sentences(text):
        if 8 <= len(s.split()) <= 45 and re.search(r"\d|\b(eligible|subsidy|loan|shall|will be|maximum|minimum)\b", s, re.I):
            out.append(s)
    return out


def rewrite_units(s: str) -> str | None:
    def lakh(m):
        return f"Rs {int(m.group(1)) * 100000:,}"            # 2,500,000 is a legitimate way to write 25 lakh
    t = re.sub(r"(?<![\d.,])(?:Rs\.?\s*)?(\d{1,3})\s*lakhs?\b(?!\s*\d)", lakh, s)
    t = re.sub(r"(?<![\d.,])(?:Rs\.?\s*)?(\d{1,2})\s*crores?\b", lambda m: f"{int(m.group(1)) * 100} lakh", t)
    return t if t != s else None


def corrupt_number(s: str, clause_nums) -> str | None:
    for m in _NUM_TOKEN.finditer(s):
        v = float(m.group(1).replace(",", ""))
        if 1900 <= v <= 2100 or not m.group(2):             # change only figures with a unit; bare numbers are often section or page refs
            continue
        for new in (v + 10, v * 2, v + 7):
            if new != v and not any(_c and F._close(new, x) for x, _c in [(x, True) for x, _ in clause_nums]):
                txt = f"{new:g}" if new != int(new) else f"{int(new)}"
                return s[:m.start(1)] + txt + s[m.end(1):]
    return None


def corrupt_category(s: str, clause_text: str) -> str | None:
    for a, b in _SWAPS:
        if re.search(rf"\b{re.escape(a)}\b", s) and not re.search(rf"\b{re.escape(b)}\b", clause_text, re.I):
            return re.sub(rf"\b{re.escape(a)}\b", b, s, count=1)
    return None


def build(n_clauses: int, seed: int = 11) -> list[dict]:
    with psycopg.connect(DBSettings.from_env().conninfo) as conn:
        rows = conn.execute("SELECT id, scheme_code, clause_text FROM scheme_clauses WHERE superseded_at IS NULL "
                            "AND length(clause_text) BETWEEN 150 AND 900").fetchall()
    rng = random.Random(seed)
    rng.shuffle(rows)
    by_fam: dict[str, list] = defaultdict(list)
    for r in rows:
        by_fam[_family(r[1])].append(r)
    cases: list[dict] = []
    for cid, code, text in rows[:n_clauses]:
        sents = sentences_with_rules(text)
        if not sents:
            continue
        s = rng.choice(sents)
        clause = {"scheme_code": code, "text": text}
        base = {"clause_id": cid, "scheme": _family(code)}
        cases.append({**base, "type": "verbatim", "faithful": True, "answer": s, "clause": clause})
        cases.append({**base, "type": "framed", "faithful": True, "answer": "According to the official text, " + s[0].lower() + s[1:], "clause": clause})
        u = rewrite_units(s)
        if u:
            cases.append({**base, "type": "units", "faithful": True, "answer": u, "clause": clause})
        n = corrupt_number(s, F._nums(text))
        if n:
            cases.append({**base, "type": "number", "faithful": False, "answer": n, "clause": clause})
        c = corrupt_category(s, text)
        if c:
            cases.append({**base, "type": "category", "faithful": False, "answer": c, "clause": clause})
        if not F._NEG_CUE.search(text):
            cases.append({**base, "type": "negation", "faithful": False,
                          "answer": "This provision does not provide any subsidy or assistance to the applicants described here.", "clause": clause})
        other = [r for f, rs in by_fam.items() if f != _family(code) for r in rs]
        if other:
            o = rng.choice(other)
            os_ = [x for x in sentences_with_rules(o[2]) if re.search(r"\d", x) and len(F._content(x)) >= 5 and x.isascii()]
            if os_:
                cases.append({**base, "type": "cross_scheme", "faithful": False, "answer": rng.choice(os_), "clause": clause})
        inv = rng.choice(_INVENTED)
        if not re.search(r"deposit|processing fee|highway|55 years|30 days", text, re.I):
            cases.append({**base, "type": "invented", "faithful": False, "answer": inv, "clause": clause})
    return cases


def evaluate(cases: list[dict]) -> dict:
    stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "flagged": 0})
    misses: dict[str, list] = defaultdict(list)
    for c in cases:
        r = F.check(c["answer"], [c["clause"]])
        st = stats[c["type"]]
        st["n"] += 1
        flagged = not r.passed
        st["flagged"] += flagged
        if flagged == c["faithful"] and len(misses[c["type"]]) < 4:          # a wrong call
            misses[c["type"]].append({"answer": c["answer"][:200], "issues": [i.kind for i in r.issues], "scheme": c["scheme"]})
    f_n = sum(s["n"] for t, s in stats.items() if t in ("verbatim", "framed", "units"))
    f_flag = sum(s["flagged"] for t, s in stats.items() if t in ("verbatim", "framed", "units"))
    u_n = sum(s["n"] for t, s in stats.items() if t not in ("verbatim", "framed", "units"))
    u_flag = sum(s["flagged"] for t, s in stats.items() if t not in ("verbatim", "framed", "units"))
    tp, fp, fn = u_flag, f_flag, u_n - u_flag
    return {"by_type": dict(stats), "false_positive_rate": round(f_flag / max(f_n, 1), 3), "detection_rate": round(u_flag / max(u_n, 1), 3),
            "precision": round(tp / max(tp + fp, 1), 3), "faithful_cases": f_n, "unfaithful_cases": u_n, "wrong_calls": dict(misses)}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    cases = build(n)
    res = evaluate(cases)
    print(f"{res['faithful_cases']} faithful + {res['unfaithful_cases']} unfaithful cases")
    for t in ("verbatim", "framed", "units", "number", "category", "negation", "cross_scheme", "invented"):
        s = res["by_type"].get(t)
        if s:
            want = "passed" if t in ("verbatim", "framed", "units") else "caught"
            got = s["n"] - s["flagged"] if want == "passed" else s["flagged"]
            print(f"  {t:13} {want} {got}/{s['n']} = {got / s['n']:.2f}")
    print(f"false-positive rate on faithful: {res['false_positive_rate']}   detection of unfaithful: {res['detection_rate']}   precision: {res['precision']}")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "faithfulness_bench.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
