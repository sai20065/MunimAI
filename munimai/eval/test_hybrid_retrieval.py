"""Offline tests for the hybrid (BM25 + dense) fusion in rank_clauses; no database or embedding service needed."""

from backend.agents.scheme import rank_clauses

ROWS = [
    (1, "PMEGP", "a", "PMEGP subsidy for new manufacturing units set up by first generation entrepreneurs"),
    (2, "CGTMSE", "b", "Collateral free credit guarantee cover for loans to micro and small enterprises"),
    (3, "PM_SVANIDHI", "c", "Working capital loan for street vendors with repayment incentives"),
    (4, "SIDBI", "d", "Machinery loan for existing enterprises to buy equipment"),
]


def test_bm25_unchanged_without_dense():
    q = "collateral free guarantee for small enterprise loans"
    assert rank_clauses(ROWS, q) == rank_clauses(ROWS, q, dense_ranks=None) == rank_clauses(ROWS, q, dense_ranks={})
    assert rank_clauses(ROWS, q)[0][0] == 2


def test_non_latin_question_found_by_dense_alone():
    hindi = "बिना गारंटी के छोटे कारोबार के लिए कर्ज"
    assert rank_clauses(ROWS, hindi) == []                       # BM25 has no Latin tokens to match
    got = rank_clauses(ROWS, hindi, dense_ranks={2: 0, 4: 1})
    assert got and got[0][0] == 2


def test_clause_ranked_by_both_beats_one_list():
    q = "loan for equipment"
    got = rank_clauses(ROWS, q, dense_ranks={4: 0, 3: 1}, max_schemes=4)
    assert got[0][0] == 4


def test_alias_still_forces_named_scheme_in():
    got = rank_clauses(ROWS, "tell me about pmegp", dense_ranks={2: 0})
    assert {r[1] for r in got} >= {"PMEGP"}
