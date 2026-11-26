"""
Tests for business memory: what is extracted, what is stored, that follow-ups resolve, and that the owner can erase it.

Pure-function tests need nothing; the database tests need the schema from backend/schema_ext.py.
Run (from munimai/):  python -m pytest eval/test_memory.py -v
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from dotenv import load_dotenv

from backend import schema_ext
from backend.agents import memory

load_dotenv()


def test_extracts_only_what_the_owner_stated():
    f = memory.extract_facts("I run a tailoring unit in Karnataka with 6 workers and need a loan of 5 lakh")
    assert f == {"sector": "tailoring", "state": "Karnataka", "employees": 6, "loan_amount_asked_rupees": 500_000}
    assert memory.extract_facts("what is the weather") == {}


def test_amount_without_loan_context_is_not_stored():
    assert "loan_amount_asked_rupees" not in memory.extract_facts("my shop sells things for 2 lakh a month")


def test_scheme_names_found_by_alias():
    assert memory.schemes_in("tell me about pmegp and the credit guarantee scheme") == ["CGTMSE", "PMEGP"]


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
    phone = f"+9197{uuid.uuid4().int % 100_000_000:08d}"
    b = conn.execute("INSERT INTO businesses (whatsapp_phone, display_name) VALUES (%s,%s) RETURNING id",
                     (phone, "Memory Test Unit")).fetchone()[0]
    conn.commit()
    return b


def test_turns_accumulate_and_context_is_owner_stated(conn, bid):
    memory.record_turn(conn, bid, "I run a bakery in Gujarat, can I get PMEGP?", "PMEGP supports new units.", "eligibility", "en")
    memory.record_turn(conn, bid, "and what about CGTMSE", "CGTMSE is a guarantee.", "eligibility", "hi")
    v = memory.view(conn, bid)
    assert v["turns"] == 2 and v["profile"]["sector"] == "bakery" and v["profile"]["state"] == "Gujarat"
    assert v["profile"]["interests"]["PMEGP"] >= 1 and v["profile"]["language"] == "hi"
    ctx = memory.context(conn, bid)
    assert "bakery" in ctx and "not verified" in ctx and len(ctx) <= memory.CONTEXT_CHARS


def test_a_plan_reply_that_mentions_udyam_is_not_an_interest(conn, bid):
    memory.record_turn(conn, bid, "what should I do next", "1. GSTIN and Udyam number on file: missing", "journey", "en")
    assert memory.view(conn, bid)["profile"]["interests"] == {}


def test_short_follow_up_resolves_to_last_scheme(conn, bid):
    memory.record_turn(conn, bid, "tell me about pmegp", "ok", "eligibility", "en")
    assert "PMEGP" in memory.augment_query(conn, bid, "what about the subsidy?")
    assert memory.augment_query(conn, bid, "tell me about cgtmse") == "tell me about cgtmse"
    long_q = "can you explain in detail how the interest rates are decided for small borrowers in rural areas"
    assert memory.augment_query(conn, bid, long_q) == long_q


def test_recent_is_capped_and_forget_erases(conn, bid):
    for i in range(memory.MAX_RECENT + 4):
        memory.record_turn(conn, bid, f"question number {i}", "a", "unknown", "en")
    assert len(memory.view(conn, bid)["recent"]) == memory.MAX_RECENT
    memory.forget(conn, bid)
    assert memory.view(conn, bid) == {"profile": {}, "recent": [], "turns": 0}
    assert memory.context(conn, bid) == ""
