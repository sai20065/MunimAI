"""
The Coordinator: the autonomous loop of the "virtual CA".

It owns a goal ("close the month"), turns it into a task, and walks that task through a fixed
state machine on its own:

    queued -> preparing -> self_audit -> verifier -> ready_for_review
                                   (blocked / escalated on a problem)

It stops at ready_for_review. Approval and filing belong to the owner and the gate
(backend/filing/gate.py); the coordinator can never approve or file.

Safety rails, all enforced here and in the database:
- a step budget and a deadline per task (a stuck or looping task escalates instead of running on)
- the per-business kill switch (autonomy_state) is checked before every step
- state is saved after every step, so a restart or reboot resumes where it stopped
- every step is written to the trace
All numbers come from deterministic code; the language model is optional and only words things.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import psycopg

from ..filing import gate
from ..trace import Trace
from .auditor import Auditor
from .compliance import ComplianceAgent
from .verifier import Claim, Verifier

KIND_MONTH_CLOSE = "month_close"
TERMINAL = ("ready_for_review", "approved", "filed", "blocked", "escalated")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    return start, nxt - timedelta(days=1)


def previous_month(today: date) -> tuple[date, date]:
    first = today.replace(day=1)
    last_prev = first - timedelta(days=1)
    return month_bounds(last_prev.year, last_prev.month)


def ensure_task(conn: psycopg.Connection, bid: int, start: date, end: date,
                kind: str = KIND_MONTH_CLOSE, max_steps: int = 12, ttl_minutes: int = 30) -> int:
    key = f"{bid}:{kind}:{start.isoformat()}"
    row = conn.execute("SELECT id FROM tasks WHERE idempotency_key=%s", (key,)).fetchone()
    if row:
        return row[0]
    tid = conn.execute(
        "INSERT INTO tasks (business_id, kind, idempotency_key, period_start, period_end, max_steps, deadline_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (bid, kind, key, start, end, max_steps, datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes))).fetchone()[0]
    conn.commit()
    return tid


def reopen(conn: psycopg.Connection, task_id: int, ttl_minutes: int = 30) -> None:
    """Re-run a task after new data arrived. Approved or filed tasks are never reopened."""
    conn.execute(
        "UPDATE tasks SET state='queued', steps_used=0, note=NULL, snapshot_id=NULL, updated_at=now(), "
        "deadline_at=%s WHERE id=%s AND state IN ('ready_for_review','blocked','escalated','queued')",
        (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes), task_id))
    conn.commit()


def _set(conn, task_id, state, note=None, snapshot_id=None):
    conn.execute("UPDATE tasks SET state=%s, note=COALESCE(%s,note), snapshot_id=COALESCE(%s,snapshot_id), "
                 "steps_used=steps_used+1, updated_at=now() WHERE id=%s", (state, note, snapshot_id, task_id))
    conn.commit()


def run_task(conn: psycopg.Connection, task_id: int, trace: Optional[Trace] = None, analyser=None) -> dict:
    """Advance a task as far as it can go on its own. Safe to call again at any time."""
    while True:
        t = conn.execute(
            "SELECT id, business_id, state, period_start, period_end, max_steps, steps_used, deadline_at "
            "FROM tasks WHERE id=%s", (task_id,)).fetchone()
        tid, bid, state, start, end, max_steps, used, deadline = t
        if trace:
            trace.business_id = bid
        if state in TERMINAL:
            break
        if not gate.autonomy_enabled(conn, bid):
            _set(conn, tid, "blocked", "Autonomy is switched off (kill switch).")
            if trace:
                trace.emit("coordinator", "error", {"task": tid, "reason": "kill_switch"})
            break
        if used >= max_steps or datetime.now(timezone.utc) > deadline:
            _set(conn, tid, "escalated", "Step or time budget exceeded; a person should look.")
            if trace:
                trace.emit("coordinator", "error", {"task": tid, "reason": "budget"})
            break

        if state == "queued":
            _set(conn, tid, "preparing")
        elif state == "preparing":
            d = ComplianceAgent(conn, None).prepare_gstr3b(bid, start, end, trace=trace, explain=False)
            if trace:
                trace.emit("coordinator", "tool_result", {"task": tid, "net_payable_paise": d.net_payable_paise,
                                                          "issues": len(d.issues)}, tool_name="gstr3b.compute")
            _set(conn, tid, "self_audit")
        elif state == "self_audit":
            found = Auditor(conn).run(bid, start, end, task_id=tid)
            if trace:
                trace.emit("coordinator", "tool_result",
                           {"task": tid, "findings": len(found),
                            "critical": sum(f.severity == "critical" for f in found)}, tool_name="auditor.run")
            if analyser is not None:                    # the Math agent: insights beside the findings, never in the return
                try:
                    analyser(conn, bid, start, end, tid, trace)
                except Exception as e:                  # an analysis failure must never block the month-close
                    conn.rollback()
                    if trace:
                        trace.emit("coordinator", "error", {"task": tid, "analyser": str(e)[:200]})
            _set(conn, tid, "verifier")
        elif state == "verifier":
            findings = [dict(rule=r[0], severity=r[1], message=r[2], entry_ids=r[3], rule_ref=r[4]) for r in conn.execute(
                "SELECT rule, severity, message, entry_ids, rule_ref FROM findings WHERE task_id=%s AND status='open' ORDER BY id",
                (tid,)).fetchall()]
            crit = sum(f["severity"] == "critical" for f in findings)
            text = (f"GST draft for {start}..{end} prepared for your review. "
                    f"{len(findings)} finding(s), {crit} critical. This is a draft for your review only.")
            verdict = Verifier(conn).check(Claim(business_id=bid, agent="coordinator", text=text, needs_citation=False))
            if trace:
                trace.emit("coordinator", "verifier", {"task": tid, "passed": verdict.passed, "reasons": verdict.reasons})
            if not verdict.passed:
                _set(conn, tid, "blocked", "; ".join(verdict.reasons))
                break
            snap = gate.create_snapshot(conn, bid, tid, start, end, findings)
            _set(conn, tid, "ready_for_review", f"{len(findings)} finding(s), {crit} critical", snapshot_id=snap)
    return task_status(conn, task_id)


def task_status(conn: psycopg.Connection, task_id: int) -> dict:
    r = conn.execute("SELECT id, business_id, kind, state, period_start, period_end, steps_used, max_steps, note, snapshot_id "
                     "FROM tasks WHERE id=%s", (task_id,)).fetchone()
    keys = ("id", "business_id", "kind", "state", "period_start", "period_end", "steps_used", "max_steps", "note", "snapshot_id")
    d = dict(zip(keys, r))
    d["period_start"], d["period_end"] = str(d["period_start"]), str(d["period_end"])
    return d


def consultant_brief(conn: psycopg.Connection, bid: int, start: date, end: date) -> dict:
    """Plain numbers a consultant would look at first. Deterministic; any narrative is written later from these."""
    rows = conn.execute(
        """SELECT direction, amount_paise, gst_rate_bp FROM ledger_entries
           WHERE business_id=%s AND entry_date BETWEEN %s AND %s AND needs_review=FALSE""", (bid, start, end)).fetchall()
    from .compliance import _tax_component_paise
    sales = sum(r[1] - _tax_component_paise(r[1], r[2] or 0) for r in rows if r[0] == "in")
    buys = sum(r[1] - _tax_component_paise(r[1], r[2] or 0) for r in rows if r[0] == "out")
    margin = None if sales == 0 else round(100 * (sales - buys) / sales, 1)
    return {"sales_taxable_paise": sales, "purchases_taxable_paise": buys,
            "gross_margin_pct": margin, "net_cash_paise": sum(r[1] if r[0] == "in" else -r[1] for r in rows)}
