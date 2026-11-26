"""
The Journey agent: turns a goal ("get my business ready for a bank loan") into a visible, persistent plan and
keeps it up to date by itself.

It never asks a model anything. Each step is a deterministic check over data the other agents already
produce (profile, documents, ledger, auditor findings, scheme fit, consent), so the plan shows exactly what is
done, what only the owner can do next, and what is waiting. State lives in Postgres (goals, goal_steps), so a
restart resumes where it was, and every re-evaluation is idempotent. The kill switch (gate.autonomy_enabled)
freezes it. It can read and plan; it cannot approve, file or submit anything.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional

import psycopg

from ..filing import gate
from .auditor import Auditor, audit_rows
from .dossier import _REQUIRED
from .fit import FIELDS, FitAgent
from .readiness import CONSENT_PURPOSE

KIND = "loan_readiness"
MIN_ENTRIES, MIN_MONTHS = 10, 3
_PROFILE_MUST = ("activity", "loan_amount")


def ensure(conn: psycopg.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS goals (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               kind TEXT NOT NULL,
               state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','completed','blocked')),
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               UNIQUE (business_id, kind))""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS goal_steps (
               goal_id BIGINT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
               seq INTEGER NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL, agent TEXT NOT NULL,
               status TEXT NOT NULL CHECK (status IN ('done','needs_you','pending')),
               detail TEXT NOT NULL DEFAULT '', action TEXT,
               updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               PRIMARY KEY (goal_id, seq))""")


Result = tuple[str, str, Optional[str]]          # (status, detail, action)


def _profile(conn, bid) -> Result:
    attrs = conn.execute("SELECT attrs FROM businesses WHERE id=%s", (bid,)).fetchone()[0] or {}
    labels = {k: lbl for k, lbl, _, _ in FIELDS}
    missing = [labels[k] for k in _PROFILE_MUST if attrs.get(k) in (None, "")]
    if missing:
        return "needs_you", "Still needed: " + "; ".join(missing), "open_profile"
    return "done", f"{len([v for v in attrs.values() if v not in (None, '')])} profile answers on file.", None


def _identity(conn, bid) -> Result:
    g, u = conn.execute("SELECT gstin, udyam_number FROM businesses WHERE id=%s", (bid,)).fetchone()
    missing = [n for n, v in (("GSTIN", g), ("Udyam number", u)) if not v]
    if missing:
        return "needs_you", "Missing: " + " and ".join(missing) + ". Uploading the certificate fills it in.", "upload_docs"
    return "done", "GSTIN and Udyam number are on file.", None


def _documents(conn, bid) -> Result:
    have = {r[0] for r in conn.execute("SELECT DISTINCT kind FROM documents WHERE business_id=%s", (bid,)).fetchall()}
    missing = [label for kind, label in _REQUIRED if kind not in have]
    if missing:
        return "needs_you", f"{len(_REQUIRED) - len(missing)} of {len(_REQUIRED)} proofs on file. Missing: " + "; ".join(missing), "upload_docs"
    return "done", "All the usual proofs are on file.", None


def _books(conn, bid) -> Result:
    n, months = conn.execute(
        "SELECT count(*), count(DISTINCT date_trunc('month', entry_date)) FROM ledger_entries "
        "WHERE business_id=%s AND needs_review=FALSE", (bid,)).fetchone()
    if n < MIN_ENTRIES or months < MIN_MONTHS:
        return ("needs_you", f"{n} entries across {months} month(s) so far. Banks look for at least {MIN_ENTRIES} entries "
                f"over {MIN_MONTHS} months; add bills or import your books.", "import_books")
    return "done", f"{n} entries across {months} months.", None


def _audit(conn, bid) -> Result:
    today = date.today()
    rows, b2 = Auditor(conn).load(bid, today - timedelta(days=365), today)
    if not rows:
        return "pending", "Nothing to check until your books have entries.", None
    found = audit_rows(rows, b2, today)
    crit = sum(f.severity == "critical" for f in found)
    warn = sum(f.severity == "warn" for f in found)
    if crit:
        return "needs_you", f"{crit} critical problem(s) in the books must be fixed first ({warn} smaller warning(s)).", "review_findings"
    return "done", f"No critical problems ({warn} warning(s) to look at).", None


def _schemes(conn, bid) -> Result:
    attrs = conn.execute("SELECT attrs FROM businesses WHERE id=%s", (bid,)).fetchone()[0] or {}
    if not attrs:
        return "pending", "Waiting for your profile answers.", None
    fits = FitAgent(conn).evaluate(bid, attrs)
    ok = [f.name for f in fits if f.status == "eligible"]
    almost = [f.name for f in fits if f.status == "almost"]
    if ok:
        return "done", "You meet the published conditions for: " + ", ".join(ok[:3]) + ".", None
    if almost:
        return "needs_you", "Close, but more facts are needed for: " + ", ".join(almost[:3]) + ".", "open_profile"
    return "done", "No scheme fully matched your answers yet; ask me what would make you eligible.", None


def _consent(conn, bid) -> Result:
    if conn.execute("SELECT has_active_consent(%s,%s)", (bid, CONSENT_PURPOSE)).fetchone()[0]:
        return "done", "You have allowed your books to be used for the bank file.", None
    return "needs_you", "I need your permission before using your books in a bank file. You can withdraw it any time.", "grant_consent"


STEPS: list[tuple[str, str, str, Callable[..., Result]]] = [
    ("profile", "Tell me about the business", "fit", _profile),
    ("identity", "GSTIN and Udyam number on file", "docstore", _identity),
    ("documents", "Proof documents uploaded", "docstore", _documents),
    ("books", "Books recorded", "ledger", _books),
    ("audit", "Books checked for errors", "auditor", _audit),
    ("schemes", "Best-fit schemes identified", "fit", _schemes),
    ("consent", "Your permission to use the books", "consent", _consent),
]
FINAL = ("bank_file", "Bank file ready to build", "dossier")


def advance(conn: psycopg.Connection, bid: int) -> dict:
    """Re-evaluate every step, save the result and return the plan. Safe to call at any time."""
    ensure(conn)
    goal_id, old_state = conn.execute(
        "INSERT INTO goals (business_id, kind) VALUES (%s,%s) ON CONFLICT (business_id, kind) DO UPDATE SET kind=EXCLUDED.kind "
        "RETURNING id, state", (bid, KIND)).fetchone()
    before = {r[0]: r[1] for r in conn.execute("SELECT key, status FROM goal_steps WHERE goal_id=%s", (goal_id,)).fetchall()}
    if not gate.autonomy_enabled(conn, bid):
        conn.execute("UPDATE goals SET state='blocked', updated_at=now() WHERE id=%s", (goal_id,))
        conn.commit()
        return _plan(conn, goal_id, [], note="Autonomy is switched off, so the plan is frozen.")

    results: list[tuple[str, str, str, Result]] = []
    for key, title, agent, check in STEPS:
        try:
            res = check(conn, bid)
        except Exception as exc:                       # one broken check must not hide the rest of the plan
            conn.rollback()
            res = ("pending", f"Could not check this step ({type(exc).__name__}).", None)
        results.append((key, title, agent, res))
    waiting = [r for r in results if r[3][0] != "done"]
    if waiting:
        final = ("pending", f"Waiting on {len(waiting)} earlier step(s).", None)
    else:
        final = ("done", "Everything needed is in place. You can build the bank file now.", "build_file")
    results.append((FINAL[0], FINAL[1], FINAL[2], final))

    for seq, (key, title, agent, (status, detail, action)) in enumerate(results, 1):
        conn.execute(
            """INSERT INTO goal_steps (goal_id, seq, key, title, agent, status, detail, action) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (goal_id, seq) DO UPDATE SET key=EXCLUDED.key, title=EXCLUDED.title, agent=EXCLUDED.agent,
                   status=EXCLUDED.status, detail=EXCLUDED.detail, action=EXCLUDED.action,
                   updated_at=CASE WHEN goal_steps.status<>EXCLUDED.status OR goal_steps.detail<>EXCLUDED.detail
                                   THEN now() ELSE goal_steps.updated_at END""",
            (goal_id, seq, key, title, agent, status, detail, action))
    state = "completed" if final[0] == "done" else "active"
    conn.execute("UPDATE goals SET state=%s, updated_at=now() WHERE id=%s", (state, goal_id))
    conn.commit()
    newly = [r[0] for r in results if r[3][0] == "done" and before.get(r[0]) not in (None, "done")]
    return _plan(conn, goal_id, newly)


def _plan(conn, goal_id: int, newly_done: list[str], note: str = "") -> dict:
    state = conn.execute("SELECT state FROM goals WHERE id=%s", (goal_id,)).fetchone()[0]
    steps = [dict(seq=r[0], key=r[1], title=r[2], agent=r[3], status=r[4], detail=r[5], action=r[6])
             for r in conn.execute("SELECT seq, key, title, agent, status, detail, action FROM goal_steps "
                                   "WHERE goal_id=%s ORDER BY seq", (goal_id,)).fetchall()]
    done = sum(s["status"] == "done" for s in steps)
    nxt = next((s for s in steps if s["status"] == "needs_you"), None)
    return {"kind": KIND, "title": "Get ready for a bank loan", "state": state, "done": done, "total": len(steps),
            "next": nxt, "steps": steps, "newly_done": newly_done, "note": note}


_MARK = {"done": "[done]", "needs_you": "[you]", "pending": "[waiting]"}


def reply_text(plan: dict) -> str:
    """The chat answer, written in code from the saved plan."""
    lines = [f"Here is your plan to get ready for a bank loan: {plan['done']} of {plan['total']} steps done."]
    for s in plan["steps"]:
        lines.append(f"{s['seq']}. {_MARK[s['status']]} {s['title']}: {s['detail']}")
    if plan["note"]:
        lines.append(plan["note"])
    elif plan["next"]:
        lines.append(f"Your next step: {plan['next']['title']}. {plan['next']['detail']}")
    elif plan["state"] == "completed":
        lines.append("Everything is ready. Ask me for the bank file whenever you want it.")
    lines.append("I check these steps myself each time you ask. I prepare, you decide; nothing is submitted for you.")
    return "\n".join(lines)
