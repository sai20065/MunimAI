"""
Database tests for the virtual-CA gate and autonomy engine. Each test asserts that something the
product must NEVER do is refused (by the database or the gate), plus the happy path.

Needs the schema from backend/schema_ext.py applied (it runs on gateway start).
Run (from munimai/):  python -m pytest eval/test_filing_gate.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import psycopg
import pytest
from dotenv import load_dotenv

from backend import schema_ext
from backend.agents import coordinator
from backend.agents.verifier import Claim, Verifier
from backend.filing import gate

load_dotenv()
START, END = date(2026, 10, 1), date(2026, 10, 31)


@pytest.fixture()
def conn():
    c = psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
                        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], connect_timeout=20)
    schema_ext.ensure(c)
    yield c
    c.rollback()
    c.close()


@pytest.fixture()
def bid(conn):
    phone = f"+9198{uuid.uuid4().int % 100_000_000:08d}"
    b = conn.execute("INSERT INTO businesses (whatsapp_phone, display_name) VALUES (%s,%s) RETURNING id",
                     (phone, "Gate Test Unit")).fetchone()[0]
    conn.commit()
    return b


def _entry(conn, bid, d, direction, rupees, inv, party="Silk Traders", gstin="29AAAAA0000A1Z5", gst=1800):
    conn.execute(
        "INSERT INTO ledger_entries (business_id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp,"
        " source, invoice_no, counterparty_gstin) VALUES (%s,%s,%s,%s,%s,%s,%s,'manual',%s,%s)",
        (bid, d, direction, rupees * 100, "sales" if direction == "in" else "purchases", party, gst, inv, gstin))
    conn.commit()


def _clean_books(conn, bid):
    _entry(conn, bid, date(2026, 10, 5), "in", 11800, "S1", party="Anita")
    _entry(conn, bid, date(2026, 10, 7), "out", 5900, "P1")


def _ready(conn, bid):
    _clean_books(conn, bid)
    tid = coordinator.ensure_task(conn, bid, START, END)
    st = coordinator.run_task(conn, tid)
    assert st["state"] == "ready_for_review", st
    return tid, st["snapshot_id"]


# ----------------------------------------------------- what the database itself refuses
def test_db_refuses_filing_without_an_approval(conn, bid):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO filing_attempts (business_id, approval_id, snapshot_hash, adapter, status) "
                     "VALUES (%s, 999999999, 'x', 'sandbox', 'filed')", (bid,))


def test_db_refuses_an_approval_with_the_wrong_hash(conn, bid):
    _, snap = _ready(conn, bid)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO approvals (business_id, snapshot_id, snapshot_hash, approver) VALUES (%s,%s,'deadbeef','x')",
                     (bid, snap))


def test_db_refuses_editing_a_snapshot(conn, bid):
    _, snap = _ready(conn, bid)
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE snapshots SET sha256='tampered' WHERE id=%s", (snap,))


def test_db_labels_sandbox_receipts_simulated(conn, bid):
    _, snap = _ready(conn, bid)
    code = gate.issue_code(conn, snap)
    aid = gate.approve(conn, bid, snap, "owner", code)
    h = conn.execute("SELECT snapshot_hash FROM approvals WHERE id=%s", (aid,)).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO filing_attempts (business_id, approval_id, snapshot_hash, adapter, simulated, status) "
                     "VALUES (%s,%s,%s,'sandbox', FALSE, 'filed')", (bid, aid, h))


# ----------------------------------------------------- the gate
def test_happy_path_prepare_approve_file(conn, bid):
    _, snap = _ready(conn, bid)
    code = gate.issue_code(conn, snap)
    aid = gate.approve(conn, bid, snap, "owner", code)
    receipt = gate.file_return(conn, bid, aid)
    assert receipt["simulated"] is True and receipt["reference"].startswith("SIM-")
    again = gate.file_return(conn, bid, aid)                         # idempotent
    assert again["reference"] == receipt["reference"]
    assert conn.execute("SELECT count(*) FROM filing_attempts WHERE approval_id=%s", (aid,)).fetchone()[0] == 1


def test_wrong_code_is_refused_and_a_code_works_once(conn, bid):
    _, snap = _ready(conn, bid)
    code = gate.issue_code(conn, snap)
    with pytest.raises(gate.GateError):
        gate.approve(conn, bid, snap, "owner", "000000" if code != "000000" else "111111")
    gate.approve(conn, bid, snap, "owner", code)
    with pytest.raises(gate.GateError):
        gate.approve(conn, bid, snap, "owner", code)


def test_changing_the_books_after_approval_blocks_filing(conn, bid):
    _, snap = _ready(conn, bid)
    aid = gate.approve(conn, bid, snap, "owner", gate.issue_code(conn, snap))
    _entry(conn, bid, date(2026, 10, 20), "in", 2360, "S2", party="Late Customer")
    with pytest.raises(gate.StaleApproval):
        gate.file_return(conn, bid, aid)


def test_open_critical_finding_blocks_approval(conn, bid):
    _clean_books(conn, bid)
    _entry(conn, bid, date(2026, 10, 8), "out", 5900, "P1")           # same supplier and invoice again: double credit
    tid = coordinator.ensure_task(conn, bid, START, END)
    st = coordinator.run_task(conn, tid)
    assert st["state"] == "ready_for_review"
    code = gate.issue_code(conn, st["snapshot_id"])
    with pytest.raises(gate.GateError, match="critical"):
        gate.approve(conn, bid, st["snapshot_id"], "owner", code)


def test_kill_switch_stops_the_coordinator_and_the_filer(conn, bid):
    _, snap = _ready(conn, bid)
    aid = gate.approve(conn, bid, snap, "owner", gate.issue_code(conn, snap))
    gate.set_autonomy(conn, bid, False)
    with pytest.raises(gate.GateError, match="kill switch"):
        gate.file_return(conn, bid, aid)
    _clean_books(conn, bid)
    tid = coordinator.ensure_task(conn, bid, date(2026, 9, 1), date(2026, 9, 30))
    assert coordinator.run_task(conn, tid)["state"] == "blocked"
    gate.set_autonomy(conn, bid, True)


# ----------------------------------------------------- the autonomy engine
def test_step_budget_escalates_instead_of_running_on(conn, bid):
    _clean_books(conn, bid)
    tid = coordinator.ensure_task(conn, bid, date(2026, 8, 1), date(2026, 8, 31), max_steps=2)
    assert coordinator.run_task(conn, tid)["state"] == "escalated"


def test_a_restart_resumes_from_the_saved_state(conn, bid):
    _clean_books(conn, bid)
    tid = coordinator.ensure_task(conn, bid, START, END)
    conn.execute("UPDATE tasks SET state='self_audit', steps_used=2 WHERE id=%s", (tid,))
    conn.commit()
    st = coordinator.run_task(conn, tid)                               # a "new process" picks it up
    assert st["state"] == "ready_for_review" and st["snapshot_id"]


def test_task_is_idempotent_per_business_and_period(conn, bid):
    a = coordinator.ensure_task(conn, bid, START, END)
    b = coordinator.ensure_task(conn, bid, START, END)
    assert a == b


# ----------------------------------------------------- the verifier's new rule 4
def test_verifier_blocks_a_filed_claim_without_a_receipt(conn, bid):
    v = Verifier(conn).check(Claim(business_id=bid, agent="x", text="Your return has been filed.", needs_citation=False))
    assert not v.passed and "no receipt" in v.reasons[0]


def test_verifier_allows_a_filed_claim_only_with_a_simulated_label(conn, bid):
    _, snap = _ready(conn, bid)
    aid = gate.approve(conn, bid, snap, "owner", gate.issue_code(conn, snap))
    gate.file_return(conn, bid, aid)
    rid = conn.execute("SELECT id FROM filing_attempts WHERE approval_id=%s", (aid,)).fetchone()[0]
    bad = Verifier(conn).check(Claim(business_id=bid, agent="x", text="Your return has been filed.", needs_citation=False, receipt_id=rid))
    good = Verifier(conn).check(Claim(business_id=bid, agent="x", text="Your return has been filed (SIMULATED sandbox).",
                                      needs_citation=False, receipt_id=rid))
    assert not bad.passed and good.passed
