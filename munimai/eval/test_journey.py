"""
Tests for the Journey agent (the loan-readiness plan): it starts incomplete, each step flips only when its own
data exists, a finished plan says so, the kill switch freezes it, and the chat intent reaches it.

Run (from munimai/):  python -m pytest eval/test_journey.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, timedelta

import psycopg
import pytest
from dotenv import load_dotenv

from backend import docstore, schema_ext
from backend.agents import journey
from backend.filing import gate
from backend.router import classify

load_dotenv()


@pytest.fixture()
def conn():
    c = psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
                        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], connect_timeout=20)
    schema_ext.ensure(c)
    docstore.ensure_table(c)
    yield c
    c.rollback()
    c.close()


@pytest.fixture()
def bid(conn):
    phone = f"+9196{uuid.uuid4().int % 100_000_000:08d}"
    b = conn.execute("INSERT INTO businesses (whatsapp_phone, display_name) VALUES (%s,%s) RETURNING id",
                     (phone, "Journey Test Unit")).fetchone()[0]
    conn.commit()
    return b


def _by_key(plan):
    return {s["key"]: s for s in plan["steps"]}


def test_fresh_business_has_an_incomplete_plan_with_a_next_step(conn, bid):
    plan = journey.advance(conn, bid)
    s = _by_key(plan)
    assert plan["state"] == "active" and plan["total"] == 8
    assert s["profile"]["status"] == "needs_you" and plan["next"]["key"] == "profile"
    assert s["bank_file"]["status"] == "pending"
    assert s["audit"]["status"] == "pending"                      # nothing in the books to check yet


def _complete_everything(conn, bid):
    conn.execute("UPDATE businesses SET attrs=%s, gstin=%s, udyam_number=%s WHERE id=%s",
                 (json.dumps({"activity": "manufacturing", "loan_amount": 500000, "age": 34, "gender": "female",
                              "new_business": False, "entity_type": "proprietorship", "years_incorporated": 3}),
                  "29ABCDE1234F1Z5", "UDYAM-KA-03-0001234", bid))
    for kind in ("udyam_certificate", "gst_certificate", "id_proof", "bank_statement", "invoice"):
        conn.execute("INSERT INTO documents (business_id, filename, path, kind) VALUES (%s,%s,%s,%s)",
                     (bid, f"{kind}.pdf", f"/tmp/{kind}.pdf", kind))
    today = date.today()
    for i in range(12):
        d = today - timedelta(days=35 * (i % 4) + 2)
        conn.execute(
            "INSERT INTO ledger_entries (business_id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp, source,"
            " invoice_no, counterparty_gstin) VALUES (%s,%s,'in',%s,'sales','Customer %s',1800,'manual',%s,%s)",
            (bid, d, 1_180_000 + i, i, f"INV-{i}", "29AAAAA0000A1Z5"))
    conn.execute("INSERT INTO consents (business_id, purpose, scope, expires_at, granted_via) "
                 "VALUES (%s,'loan_eligibility_assessment',%s, now() + interval '1 day','simulated')", (bid, ["ledger"]))
    conn.commit()


def test_plan_completes_only_when_every_step_has_its_data(conn, bid):
    before = journey.advance(conn, bid)
    assert before["state"] == "active"
    _complete_everything(conn, bid)
    plan = journey.advance(conn, bid)
    s = _by_key(plan)
    assert {k: v["status"] for k, v in s.items() if k != "audit"} == {k: "done" for k in s if k != "audit"}
    assert s["audit"]["status"] in ("done", "needs_you")
    if s["audit"]["status"] == "done":
        assert plan["state"] == "completed" and plan["done"] == plan["total"] and s["bank_file"]["action"] == "build_file"
        assert {"profile", "identity", "documents", "books", "consent"} <= set(plan["newly_done"])
    else:                                                          # a critical finding would correctly hold the plan back
        assert plan["state"] == "active" and plan["next"]["key"] == "audit"


def test_removing_a_proof_reopens_that_step(conn, bid):
    _complete_everything(conn, bid)
    journey.advance(conn, bid)
    conn.execute("DELETE FROM documents WHERE business_id=%s AND kind='bank_statement'", (bid,))
    conn.commit()
    s = _by_key(journey.advance(conn, bid))
    assert s["documents"]["status"] == "needs_you" and "Bank statement" in s["documents"]["detail"]
    assert s["bank_file"]["status"] == "pending"


def test_kill_switch_freezes_the_plan(conn, bid):
    gate.set_autonomy(conn, bid, False)
    conn.commit()
    plan = journey.advance(conn, bid)
    assert plan["state"] == "blocked" and "switched off" in plan["note"]
    gate.set_autonomy(conn, bid, True)
    conn.commit()
    assert journey.advance(conn, bid)["state"] == "active"


def test_reply_text_is_built_from_the_plan(conn, bid):
    text = journey.reply_text(journey.advance(conn, bid))
    assert "0 of 8" in text and "Your next step: Tell me about the business" in text and "nothing is submitted" in text


@pytest.mark.parametrize("q", ["What should I do next?", "help me get a loan", "show my progress", "where do I stand"])
def test_chat_phrases_route_to_the_journey(q):
    assert classify(q) == "journey"


@pytest.mark.parametrize("q,intent", [("Can I get a MUDRA loan?", "eligibility"), ("Am I eligible for PMEGP?", "eligibility"),
                                      ("What do I need to do to qualify?", "fit")])
def test_scheme_questions_still_route_as_before(q, intent):
    assert classify(q) == intent
