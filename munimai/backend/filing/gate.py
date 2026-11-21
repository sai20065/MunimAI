"""
The approval and filing gate.

Flow: snapshot (immutable, hashed) -> owner approves it with a one-time code -> only then may a
filing adapter run, and only if the books still produce exactly the approved return.

The strongest guarantees live in the database (see schema_ext._autonomy): a filing row cannot exist
without an approval whose hash matches, approvals cannot point at a snapshot with a different hash,
and snapshots cannot be edited. This module adds the checks a database cannot express: the one-time
code, open critical findings, the kill switch, and re-deriving the return from the live ledger.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import psycopg
from psycopg.types.json import Jsonb

from ..agents.compliance import ComplianceAgent
from .sandbox import SandboxFiler

CODE_TTL_MIN = 10


class GateError(Exception):
    """A rule of the gate was not met. The message is safe to show the owner."""


class StaleApproval(GateError):
    """The books changed after approval, so the approved return is no longer the current one."""


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def build_return(conn: psycopg.Connection, bid: int, start: date, end: date) -> dict:
    """The return as it would be filed right now: figures from the draft plus a digest of the exact
    ledger rows behind it, so any later change to those rows changes the hash."""
    draft = ComplianceAgent(conn, None).prepare_gstr3b(bid, start, end, explain=False)
    rows = conn.execute(
        """SELECT id, entry_date, direction, amount_paise, gst_rate_bp, needs_review, COALESCE(invoice_no,''),
                  COALESCE(counterparty_gstin,'')
           FROM ledger_entries WHERE business_id=%s AND entry_date BETWEEN %s AND %s ORDER BY id""",
        (bid, start, end)).fetchall()
    digest = sha([[r[0], str(r[1]), r[2], int(r[3]), r[4], bool(r[5]), r[6], r[7]] for r in rows])
    return {
        "kind": "GSTR-3B-sandbox",
        "business_id": bid,
        "period": f"{start.isoformat()}..{end.isoformat()}",
        "figures": {
            "outward_taxable_paise": draft.outward_taxable_paise, "output_tax_paise": draft.output_tax_paise,
            "inward_taxable_paise": draft.inward_taxable_paise, "input_credit_paise": draft.input_credit_paise,
            "net_payable_paise": draft.net_payable_paise, "credit_carry_forward_paise": draft.credit_carry_forward_paise,
        },
        "entry_count": len(rows),
        "ledger_digest": digest,
    }


def create_snapshot(conn: psycopg.Connection, bid: int, task_id: Optional[int], start: date, end: date,
                    findings: list[dict]) -> int:
    ret = build_return(conn, bid, start, end)
    payload = {"return": ret, "findings": findings}
    row = conn.execute(
        "INSERT INTO snapshots (business_id, task_id, kind, payload, sha256) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (bid, task_id, ret["kind"], Jsonb(payload), sha(ret))).fetchone()
    conn.commit()
    return row[0]


def _code_hash(code: str, snapshot_id: int) -> str:
    return hashlib.sha256(f"{snapshot_id}:{code}".encode()).hexdigest()


def issue_code(conn: psycopg.Connection, snapshot_id: int) -> str:
    """A one-time code the owner must type to approve. In the sandbox it is shown on screen
    (a stand-in for the OTP the real portal would send to the owner's phone)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    conn.execute("INSERT INTO approval_codes (snapshot_id, code_hash, expires_at) VALUES (%s,%s,%s)",
                 (snapshot_id, _code_hash(code, snapshot_id), datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MIN)))
    conn.commit()
    return code


def _snapshot(conn, snapshot_id: int, bid: int):
    row = conn.execute("SELECT id, task_id, payload, sha256 FROM snapshots WHERE id=%s AND business_id=%s",
                       (snapshot_id, bid)).fetchone()
    if not row:
        raise GateError("That return snapshot does not exist for this business.")
    return row


def approve(conn: psycopg.Connection, bid: int, snapshot_id: int, approver: str, code: str) -> int:
    sid, task_id, payload, digest = _snapshot(conn, snapshot_id, bid)
    open_critical = conn.execute(
        "SELECT count(*) FROM findings WHERE business_id=%s AND task_id IS NOT DISTINCT FROM %s "
        "AND severity='critical' AND status='open'", (bid, task_id)).fetchone()[0]
    if open_critical:
        raise GateError(f"{open_critical} critical finding(s) are still open. Resolve or correct them before approving.")
    codes = conn.execute(
        "SELECT id, code_hash FROM approval_codes WHERE snapshot_id=%s AND used_at IS NULL AND expires_at > now() "
        "ORDER BY id DESC", (snapshot_id,)).fetchall()
    ok = next((c for c in codes if hmac.compare_digest(c[1], _code_hash(code.strip(), snapshot_id))), None)
    if not ok:
        raise GateError("That code is wrong or has expired. Ask for a new one.")
    conn.execute("UPDATE approval_codes SET used_at=now() WHERE id=%s", (ok[0],))
    aid = conn.execute(
        "INSERT INTO approvals (business_id, snapshot_id, snapshot_hash, approver) VALUES (%s,%s,%s,%s) RETURNING id",
        (bid, sid, digest, approver or "owner")).fetchone()[0]
    if task_id is not None:
        conn.execute("UPDATE tasks SET state='approved', updated_at=now() WHERE id=%s AND state='ready_for_review'", (task_id,))
    conn.commit()
    return aid


def autonomy_enabled(conn: psycopg.Connection, bid: int) -> bool:
    row = conn.execute("SELECT enabled FROM autonomy_state WHERE business_id=%s", (bid,)).fetchone()
    return True if row is None else bool(row[0])


def set_autonomy(conn: psycopg.Connection, bid: int, enabled: bool) -> None:
    conn.execute(
        "INSERT INTO autonomy_state (business_id, enabled) VALUES (%s,%s) "
        "ON CONFLICT (business_id) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()", (bid, enabled))
    conn.commit()


def file_return(conn: psycopg.Connection, bid: int, approval_id: int, adapter=None) -> dict:
    """File an approved return. Raises StaleApproval if the books changed since the owner said yes."""
    adapter = adapter or SandboxFiler()
    app = conn.execute(
        "SELECT a.id, a.snapshot_id, a.snapshot_hash, s.payload, s.task_id FROM approvals a "
        "JOIN snapshots s ON s.id=a.snapshot_id WHERE a.id=%s AND a.business_id=%s", (approval_id, bid)).fetchone()
    if not app:
        raise GateError("No such approval for this business.")
    aid, snap_id, digest, payload, task_id = app

    done = conn.execute("SELECT receipt FROM filing_attempts WHERE approval_id=%s AND status='filed'", (aid,)).fetchone()
    if done:
        return done[0]                                   # idempotent: never file twice
    if not autonomy_enabled(conn, bid):
        raise GateError("Autonomy is switched off for this business (kill switch).")

    ret = payload["return"]
    start, end = (date.fromisoformat(x) for x in ret["period"].split(".."))
    if sha(build_return(conn, bid, start, end)) != digest:
        raise StaleApproval("Your books changed after you approved this return. Review the new version and approve again.")

    receipt = adapter.file(ret, digest)
    conn.execute(
        "INSERT INTO filing_attempts (business_id, approval_id, snapshot_hash, adapter, simulated, status, receipt) "
        "VALUES (%s,%s,%s,%s,%s,'filed',%s)",
        (bid, aid, digest, adapter.name, adapter.simulated, Jsonb(receipt)))
    if task_id is not None:
        conn.execute("UPDATE tasks SET state='filed', updated_at=now() WHERE id=%s", (task_id,))
    conn.commit()
    return receipt
