"""
The verifier gate.

Nothing an agent produces reaches the owner without passing here. The gate is
deliberately dumb and strict: it does not reason, it checks facts against the
database. A clever answer with no citation loses to a plain answer that has one.

Four checks, matching the four promises on the pitch:
  1. citation    — a claim tagged as needing a source must cite >=1 real clause
  2. rule_version— each cited clause must be current (not superseded)
  3. consent     — a claim that used financial data must have active consent
  4. no_filing   — the claim text must not assert that something was filed/submitted

A claim that passes is recorded with its citations; a claim that fails is
recorded with the reason. Both are auditable later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import psycopg

# Phrases that would mean we crossed the prepare/file line. The gate blocks a
# claim that asserts a filing or submission actually happened.
_FILING_ASSERTIONS = [
    r"\bI have filed\b", r"\bhas been filed\b", r"\byour return is filed\b",
    r"\bsubmitted to the (bank|portal|gst)\b", r"\bapplication (has been )?submitted\b",
    r"\bfiled your (gst|return)\b", r"\bloan (has been )?disbursed\b",
]


@dataclass
class Claim:
    """What an agent wants to tell the owner."""
    business_id: int
    agent: str
    text: str
    cited_clause_ids: list[int] = field(default_factory=list)
    needs_citation: bool = True          # scheme-eligibility claims do
    used_financial_data: bool = False    # credit claims do
    consent_purpose: Optional[str] = None
    allowed_numbers: Optional[list] = None   # if set, every number in the text must match one of these
    receipt_id: Optional[int] = None     # a filing_attempts row; the only thing that lets a claim say "filed"


@dataclass
class Verdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    valid_clause_ids: list[int] = field(default_factory=list)


class Verifier:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def check(self, claim: Claim) -> Verdict:
        reasons: list[str] = []
        valid_ids: list[int] = []

        # 4. prepare/file line — a text check, cheapest, do first
        for pat in _FILING_ASSERTIONS:
            if re.search(pat, claim.text, re.IGNORECASE):
                reasons.extend(self._filing_reasons(claim))
                break

        # 1 + 2. citation and rule version
        if claim.needs_citation:
            if not claim.cited_clause_ids:
                reasons.append("no citation: an eligibility claim must cite a clause")
            else:
                rows = self.conn.execute(
                    """SELECT id, superseded_at FROM scheme_clauses
                       WHERE id = ANY(%s)""",
                    (claim.cited_clause_ids,),
                ).fetchall()
                found = {r[0]: r[1] for r in rows}
                for cid in claim.cited_clause_ids:
                    if cid not in found:
                        reasons.append(f"cited clause {cid} does not exist")
                    elif found[cid] is not None:
                        reasons.append(f"cited clause {cid} is superseded (stale rule)")
                    else:
                        valid_ids.append(cid)
                if not valid_ids:
                    reasons.append("no current clause among the citations")

        # 5. number grounding: an analysis may only quote numbers the code computed
        if claim.allowed_numbers is not None:
            from ..analytics.grounding import ungrounded_numbers
            bad = ungrounded_numbers(claim.text, claim.allowed_numbers)
            if bad:
                reasons.append("quotes numbers that were not computed: " + ", ".join(bad[:5]))

        # 3. consent
        if claim.used_financial_data:
            if not claim.consent_purpose:
                reasons.append("used financial data but named no consent purpose")
            else:
                active = self.conn.execute(
                    "SELECT has_active_consent(%s, %s)",
                    (claim.business_id, claim.consent_purpose),
                ).fetchone()[0]
                if not active:
                    reasons.append(
                        f"no active consent for '{claim.consent_purpose}'"
                    )

        verdict = Verdict(passed=not reasons, reasons=reasons, valid_clause_ids=valid_ids)
        self._record(claim, verdict)
        return verdict

    def _filing_reasons(self, claim: Claim) -> list[str]:
        """A claim may say something was filed only if a real receipt row backs it, and a sandbox
        receipt must be labelled SIMULATED in the text. No receipt means the claim is blocked."""
        if claim.receipt_id is None:
            return ["asserts a filing/submission happened with no receipt; SaralcreditAI only prepares"]
        row = self.conn.execute(
            "SELECT simulated, status FROM filing_attempts WHERE id=%s AND business_id=%s",
            (claim.receipt_id, claim.business_id)).fetchone()
        if not row or row[1] != "filed":
            return ["cites a filing receipt that does not exist for this business"]
        if row[0] and "simulated" not in claim.text.lower():
            return ["a sandbox filing must be labelled SIMULATED"]
        return []

    def _record(self, claim: Claim, verdict: Verdict) -> None:
        """Persist the decision. A blocked claim must carry its reason (the DB
        enforces this too), so the owner can always be told why."""
        import uuid
        row = self.conn.execute(
            """INSERT INTO claims
               (business_id, trace_id, agent, claim_text, verdict, blocked_reason)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (claim.business_id, str(uuid.uuid4()), claim.agent, claim.text,
             "passed" if verdict.passed else "blocked",
             None if verdict.passed else "; ".join(verdict.reasons)),
        ).fetchone()
        claim_id = row[0]
        for cid in verdict.valid_clause_ids:
            self.conn.execute(
                "INSERT INTO claim_citations (claim_id, clause_id) VALUES (%s,%s)"
                " ON CONFLICT DO NOTHING",
                (claim_id, cid),
            )
        self.conn.commit()
