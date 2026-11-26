"""
The Scheme agent.

Given a business profile and a question, it decides whether the business looks
eligible for a MUDRA category, and it may ONLY argue from clauses retrieved out
of the database. The model phrases the answer; it does not supply the facts.

The flow that keeps it honest:
  1. retrieve the most relevant clauses across ALL loaded schemes (Postgres,
     official sources only), or only one scheme if the caller names it
  2. hand ONLY those clauses to the model, with their ids
  3. the model returns a verdict plus the ids of the clauses it relied on
  4. we keep only ids that were actually in the retrieved set (no hallucinated ids)
  5. the Verifier then confirms those ids are real and current before the owner
     sees anything

So a clause the model invents cannot become a citation: step 4 drops unknown
ids, and step 5 blocks the claim if nothing real is left.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import psycopg

from .. import embed_client
from ..llm import LLM
from ..trace import Trace
from .verifier import Claim


@dataclass
class SchemeAnswer:
    text: str
    scheme_code: str
    cited_clause_ids: list[int]
    retrieved_clause_ids: list[int]


_SYSTEM = (
    "You are a cautious adviser on Indian government loan, subsidy and startup-funding "
    "schemes for micro-enterprises. You may ONLY use the numbered clauses provided; each "
    "is labelled with its scheme. Never state an eligibility rule, amount, rate or "
    "subsidy that is not in them. Name the scheme(s) your answer relies on. If the "
    "clauses come from different schemes, do not mix their rules: keep each scheme's "
    "rules separate. If the clauses do not settle the question, say what is still "
    "needed. Never say a scheme does NOT offer something just because the clauses you were given do not "
    "mention it: say that the clauses you have do not state it. Do not claim any application was filed or submitted. "
    "If the question is NOT about loans, subsidies, eligibility, documents or scheme "
    "rules, do NOT force an answer from the clauses: set cited_ids to [] and say in "
    "answer that this question is outside your scheme knowledge."
)

_STOP = frozenset(
    "the a an and or of to in for on is are was be can could do does did i my me we our you your "
    "it this that with from as at by how what which who when where why any have has will would "
    "should about get need want under into than then there their them also not no yes".split())

# words an owner uses for a scheme -> family key (forces that scheme into the candidate set)
_ALIASES = {
    "pmegp": "PMEGP", "employment generation": "PMEGP",
    "cgtmse": "CGTMSE", "credit guarantee": "CGTMSE", "guarantee fund": "CGTMSE",
    "svanidhi": "PM_SVANIDHI", "street vendor": "PM_SVANIDHI",
    "stand-up": "STANDUP_INDIA", "standup": "STANDUP_INDIA", "stand up": "STANDUP_INDIA",
    "vishwakarma": "PM_VISHWAKARMA", "artisan": "PM_VISHWAKARMA",
    "nsic": "NSIC", "single point registration": "NSIC", "raw material assistance": "NSIC",
    "sidbi": "SIDBI",
    "seed fund": "SISFS", "sisfs": "SISFS",
    "startup": "STARTUP_INDIA", "start-up": "STARTUP_INDIA", "dpiit": "STARTUP_INDIA",
    "fund of funds": "STARTUP_PLAYBOOK",
    "mudra": "MUDRA", "shishu": "MUDRA", "kishore": "MUDRA", "tarun": "MUDRA",
    "udyam": "UDYAM", "msme classification": "UDYAM", "msme definition": "UDYAM", "micro enterprise": "UDYAM",
    "nidhi": "NIDHI", "prayas": "NIDHI",
    "jan samarth": "JAN_SAMARTH", "jansamarth": "JAN_SAMARTH",
    "uttar pradesh": "UP_MSME_POLICY", "up msme": "UP_MSME_POLICY",
    "gujarat": "GUJARAT_IND_POLICY_2022",
    "tamil nadu": "TAMILNADU_STARTUP_POLICY", "tamilnadu": "TAMILNADU_STARTUP_POLICY",
    "andhra pradesh": "ANDHRA_PRADESH_STARTUP_POLICY_2024_29",
    "karnataka": "KARNATAKA_INDUSTRIAL_POLICY_2025_30",
    "telangana": "TELANGANA_MSME_HANDBOOK_2024", "we-hub": "TELANGANA_MSME_HANDBOOK_2024", "wehub": "TELANGANA_MSME_HANDBOOK_2024",
    "clcss": "TELANGANA_MSME_HANDBOOK_2024", "sclcss": "TELANGANA_MSME_HANDBOOK_2024",
    "credit linked capital subsidy": "TELANGANA_MSME_HANDBOOK_2024", "cluster development": "TELANGANA_MSME_HANDBOOK_2024",
}


def _family(scheme_code: str) -> str:
    return "MUDRA" if scheme_code.startswith("MUDRA") else scheme_code


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3 or w in _STOP:
            continue
        out.append(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


RRF_K = 60
DENSE_MIN = 0.50      # cosine floor for a dense hit to count at all
DENSE_TOP = 24
BM25_W, DENSE_W = 1.0, 2.0      # fusion weights, picked from an 18-setting grid on eval/benchmark/retrieval_bench.py


def rank_clauses(rows: list[tuple[int, str, str, str]], question: str,
                 limit: int = 12, max_schemes: int = 3,
                 dense_ranks: Optional[dict[int, int]] = None) -> list[tuple[int, str, str, str]]:
    """BM25-style relevance over every current clause, then keep the best 1-3
    schemes so one answer never mixes unrelated schemes' rules.
    rows: (id, scheme_code, clause_ref, text).
    dense_ranks: optional {clause id: 0-based rank} from embedding search; when given, BM25 and
    dense ranks are merged by reciprocal rank fusion before the scheme-family step."""
    q = _tokens(question)
    if not rows or (not q and not dense_ranks):
        return []
    docs = [_tokens(f"{r[1].replace('_', ' ')} {r[3]}") for r in rows]
    n = len(docs)
    avg = sum(len(d) for d in docs) / n or 1
    df = Counter(w for d in docs for w in set(d))
    k1, b = 1.5, 0.75
    qset = set(q)
    scores = []
    for d in docs:
        tf = Counter(d)
        sc = 0.0
        for w in qset:
            if w in tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                sc += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scores.append(sc)

    if dense_ranks:
        order = sorted(range(n), key=lambda i: -scores[i])
        bm_rank = {rows[i][0]: pos for pos, i in enumerate(order) if scores[i] > 0}
        scores = [(BM25_W / (RRF_K + bm_rank[r[0]] + 1) if r[0] in bm_rank else 0.0)
                  + (DENSE_W / (RRF_K + dense_ranks[r[0]] + 1) if r[0] in dense_ranks else 0.0) for r in rows]

    ql = question.lower()
    named = {fam for alias, fam in _ALIASES.items() if alias in ql}

    by_fam: dict[str, list[float]] = {}
    for r, sc in zip(rows, scores):
        by_fam.setdefault(_family(r[1]), []).append(sc)
    fam_total = {f: sum(sorted(v, reverse=True)[:3]) for f, v in by_fam.items()}
    for f in named:                       # an explicit scheme name always wins a slot
        fam_total[f] = fam_total.get(f, 0.0) + 1000.0
    best = max(fam_total.values(), default=0.0)
    if best <= 0:
        return []
    chosen = [f for f, v in sorted(fam_total.items(), key=lambda kv: -kv[1])
              if v >= 0.5 * best][:max_schemes]

    ranked = sorted(
        ((sc, r) for r, sc in zip(rows, scores) if _family(r[1]) in chosen and sc > 0),
        key=lambda x: -x[0])
    return [r for _, r in ranked[:limit]]


class SchemeAgent:
    def __init__(self, conn: psycopg.Connection, llm: LLM) -> None:
        self.conn = conn
        self.llm = llm
        self.last_method = "bm25"

    def retrieve(self, scheme_code: Optional[str] = None, limit: int = 12,
                 question: str = "") -> list[tuple[int, str, str, str]]:
        """Current clauses as (id, scheme_code, clause_ref, text).
        With a scheme_code: that scheme (plus the general MUDRA rules) as before.
        Without: relevance search across every loaded scheme."""
        if scheme_code:
            rows = self.conn.execute(
                """SELECT id, scheme_code, clause_ref, clause_text FROM scheme_clauses
                   WHERE superseded_at IS NULL
                     AND (scheme_code = %s OR scheme_code = 'MUDRA_GENERAL')
                   ORDER BY scheme_code, clause_ref LIMIT %s""",
                (scheme_code, limit)).fetchall()
            return [(r[0], r[1], r[2], r[3]) for r in rows]
        rows = self.conn.execute(
            """SELECT id, scheme_code, clause_ref, clause_text FROM scheme_clauses
               WHERE superseded_at IS NULL""").fetchall()
        dense = self._dense_ranks(question)
        self.last_method = "hybrid" if dense else "bm25"
        return rank_clauses([(r[0], r[1], r[2], r[3]) for r in rows], question, limit, dense_ranks=dense)

    def _dense_ranks(self, question: str) -> dict[int, int]:
        """{clause id: rank} from the embedding search, or {} when the service or the vectors are missing."""
        if not question.strip():
            return {}
        vec = embed_client.embed([question], timeout=6)
        if not vec:
            return {}
        try:
            rows = self.conn.execute(
                """SELECT id, 1 - (embedding <=> %s::vector) AS sim FROM scheme_clauses
                   WHERE superseded_at IS NULL AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector LIMIT %s""",
                (embed_client.to_pg(vec[0]), embed_client.to_pg(vec[0]), DENSE_TOP)).fetchall()
        except psycopg.Error:
            self.conn.rollback()
            return {}
        return {r[0]: pos for pos, r in enumerate([r for r in rows if r[1] >= DENSE_MIN])}

    def answer(
        self,
        business_id: int,
        question: str,
        scheme_code: Optional[str] = None,
        *,
        trace: Optional[Trace] = None,
        memory: str = "",
        revise: str = "",
    ) -> tuple[SchemeAnswer, Claim]:
        if trace:
            trace.emit("scheme", "agent_start", {"question": question,
                                                 "scheme": scheme_code or "auto"})
        clauses = self.retrieve(scheme_code, question=question)
        retrieved_ids = [c[0] for c in clauses]
        if trace:
            trace.emit("scheme", "tool_call",
                       {"retrieved": len(clauses), "clause_ids": retrieved_ids, "method": self.last_method,
                        "schemes": sorted({_family(c[1]) for c in clauses})},
                       tool_name="kb.retrieve")

        clause_block = "\n".join(
            f"[{cid}] ({code} / {ref}) {text}" for cid, code, ref, text in clauses)
        user = (
            f"Business question: {question}\n\n"
            + (f"{memory}\n\n" if memory else "")
            + (f"Your previous answer was rejected by the checker: {revise}. Revise it: use only the numbered "
               "clauses below and cite their numbers.\n\n" if revise else "")
            + f"Clauses you may use:\n{clause_block}\n\n"
            "Answer the question, naming the scheme(s) used and citing clause numbers. "
            'Return JSON: {"answer": "<plain-language answer naming the scheme and the clause '
            'numbers you used>", "cited_ids": [<clause numbers>]}'
        )
        parsed = self.llm.json_call(
            _SYSTEM, user,
            schema_hint='{"answer": string, "cited_ids": [int]}',
            trace=trace, agent="scheme", max_tokens=400,
        )

        answer_text = str(parsed.get("answer", "")).strip()
        raw_ids = parsed.get("cited_ids", []) or []
        # keep only ids that were actually retrieved (drop any hallucinated id)
        retrieved_set = set(retrieved_ids)
        cited = [int(i) for i in raw_ids if isinstance(i, (int, str))
                 and str(i).isdigit() and int(i) in retrieved_set]
        dropped = [i for i in raw_ids if i not in cited]
        if trace and dropped:
            trace.emit("scheme", "verifier",
                       {"dropped_unknown_ids": dropped,
                        "note": "model cited ids that were not retrieved"})

        claim = Claim(
            business_id=business_id,
            agent="scheme",
            text=answer_text,
            cited_clause_ids=cited,
            needs_citation=True,
            check_faithfulness=True,
        )
        if trace:
            trace.emit("scheme", "agent_end",
                       {"answer": answer_text[:300], "cited": cited})
        code_by_id = {c[0]: c[1] for c in clauses}
        used = [code_by_id[i] for i in (cited or retrieved_ids) if i in code_by_id]
        resolved = scheme_code or (Counter(used).most_common(1)[0][0] if used else "")
        return (
            SchemeAnswer(answer_text, resolved, cited, retrieved_ids),
            claim,
        )
