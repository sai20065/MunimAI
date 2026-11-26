"""The faithfulness check inside the Verifier: scheme answers that overreach their cited clause are blocked, others are untouched."""

from __future__ import annotations

import os

import psycopg
import pytest
from dotenv import load_dotenv

from backend.agents.verifier import Claim, Verifier

load_dotenv()


@pytest.fixture()
def conn():
    c = psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
                        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], connect_timeout=20)
    yield c
    c.rollback()
    c.close()


@pytest.fixture()
def biz(conn):
    row = conn.execute("SELECT id FROM businesses ORDER BY id LIMIT 1").fetchone()
    if not row:
        pytest.skip("no business in DB")
    return row[0]


@pytest.fixture()
def clause(conn):
    """A current Karnataka clause with the capital-subsidy table."""
    row = conn.execute("SELECT id FROM scheme_clauses WHERE superseded_at IS NULL AND scheme_code='KARNATAKA_INDUSTRIAL_POLICY_2025_30' "
                       "AND clause_text ILIKE '%30% of VFA%' ORDER BY id LIMIT 1").fetchone()
    if not row:
        pytest.skip("Karnataka clauses are not loaded")
    return row[0]


def _claim(text, cid, biz_id, check=True):
    return Claim(business_id=biz_id, agent="scheme", text=text, cited_clause_ids=[cid], needs_citation=True, check_faithfulness=check)


def test_a_supported_answer_passes(conn, clause, biz):
    v = Verifier(conn).check(_claim("Micro enterprises in Zone-1 get 30% of VFA up to Rs 30 lakhs.", clause, biz))
    assert v.passed and not v.unfaithful


def test_an_overreaching_answer_is_blocked_with_a_reason_the_model_can_act_on(conn, clause, biz):
    v = Verifier(conn).check(_claim("Micro enterprises in Zone-1 get 45% of VFA up to Rs 30 lakhs.", clause, biz))
    assert not v.passed and v.unfaithful
    assert "unsupported by the cited clauses" in v.reasons[0] and "45" in v.reasons[0]
    assert v.valid_clause_ids == [clause]                         # the citation itself was fine


def test_the_check_is_off_unless_the_claim_asks_for_it(conn, clause, biz):
    assert Verifier(conn).check(_claim("Micro enterprises get 45% of VFA.", clause, biz, check=False)).passed


def test_a_missing_citation_is_still_reported_as_a_citation_problem(conn, biz):
    v = Verifier(conn).check(Claim(business_id=biz, agent="scheme", text="Anything at all.", needs_citation=True, check_faithfulness=True))
    assert not v.passed and not v.unfaithful and "no citation" in v.reasons[0]
