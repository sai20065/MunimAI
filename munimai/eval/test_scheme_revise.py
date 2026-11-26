"""The Scheme agent's one-shot revision: the checker's reasons reach the model's prompt, and unknown clause ids are still dropped."""

from __future__ import annotations

import os

import psycopg
import pytest
from dotenv import load_dotenv

from backend.agents.scheme import SchemeAgent

load_dotenv()


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def json_call(self, system, user, **kw):
        self.prompts.append(user)
        return {"answer": "PMEGP gives a subsidy.", "cited_ids": [999999999]}


@pytest.fixture()
def conn():
    c = psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
                        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], connect_timeout=20)
    yield c
    c.rollback()
    c.close()


def test_revision_note_is_in_the_prompt_only_when_asked(conn):
    llm = FakeLLM()
    agent = SchemeAgent(conn, llm)
    agent.answer(1, "what subsidy does pmegp give")
    agent.answer(1, "what subsidy does pmegp give", revise="no valid clause cited")
    assert "rejected by the checker" not in llm.prompts[0]
    assert "rejected by the checker: no valid clause cited" in llm.prompts[1]


def test_invented_clause_ids_are_still_dropped_after_revision(conn):
    ans, claim = SchemeAgent(conn, FakeLLM()).answer(1, "what subsidy does pmegp give", revise="x")
    assert ans.cited_clause_ids == [] and claim.cited_clause_ids == []
    assert ans.retrieved_clause_ids                      # the clauses were retrieved; the model just cited none of them
