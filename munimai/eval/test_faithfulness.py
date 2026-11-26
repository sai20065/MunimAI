"""Offline tests for the faithfulness checker: supported answers pass, each kind of unsupported claim is caught, hedges are left alone."""

from __future__ import annotations

import pytest

from backend.agents import faithfulness as F

KA = {"scheme_code": "KARNATAKA_INDUSTRIAL_POLICY_2025_30",
      "text": "11.1 Capital Subsidy for Micro and Small Enterprises Micro Enterprises Entrepreneur category Zone-1 Zone-2 "
              "General 30% of VFA Rs.30 lakhs 25% of VFA Rs.25 lakhs Special (SC/ST, Women, Minorities, Physically Challenged "
              "and Ex- Servicemen) 35% of VFA Rs.35 lakhs 30% of VFA Rs.30 lakhs"}
CL = {"scheme_code": "TELANGANA_MSME_HANDBOOK_2024",
      "text": "Credit Linked Capital Subsidy Scheme (CLCSS). A special provision of 25% subsidy to SC/ST MSEs under National SC/ST Hub (NSSH) on institutional finance up to "
              "Rs.1 Cr. for procurement of Plant & Machinery (i.e. a subsidy cap of Rs.25 Lakhs)."}
UP = {"scheme_code": "UP_MSME_POLICY",
      "text": "The Capital interest subsidy for the new Micro Enterprises in the State, 50 percent of the interest payable on the "
              "loan, subject to a maximum of Rs 25 lakh per unit, in 5 years. The Scheduled Caste, Scheduled Tribe and women "
              "entrepreneurs would be given an additional 10 percent that is 60 percent interest subsidy. The cost of land would not be "
              "considered as eligible fixed capital investment."}


def kinds(answer, clauses):
    return {i.kind for i in F.check(answer, clauses).issues}


def test_a_faithful_answer_passes_with_unit_equivalence():
    ok = F.check("Karnataka gives a capital subsidy of 30% of VFA up to Rs 30 lakh to general micro enterprises in Zone-1, and 35% "
                 "up to Rs. 35 lakhs to women and SC/ST entrepreneurs.\n\n(Sources: karnataka_pdf.page_95.1)", [KA])
    assert ok.passed and ok.score == 1.0 and ok.checked >= 1
    assert F.check("CLCSS gives 25% subsidy to SC/ST MSEs on finance up to Rs 1 crore, a subsidy cap of Rs 25 lakh.", [CL]).passed
    assert F.check("The subsidy is 50 percent of interest, up to 25 lakh per unit over 60 months.", [UP]).passed   # 5 years = 60 months


@pytest.mark.parametrize("answer,clauses,expected", [
    ("The subsidy is 40% of VFA up to Rs 30 lakhs for general micro enterprises.", [KA], "number_not_in_clause"),
    ("General micro enterprises in Zone-1 get a maximum of Rs 3 lakhs.", [KA], "number_not_in_clause"),
    ("Medium enterprises get 30% of VFA under this section.", [KA], "category_not_in_clause"),
    ("Rural women entrepreneurs get 35% of VFA.", [KA], "category_not_in_clause"),
    ("The CLCSS subsidy applies for 5 percent.", [CL], "number_not_in_clause"),
])
def test_wrong_numbers_and_categories_are_caught(answer, clauses, expected):
    assert expected in kinds(answer, clauses)


def test_the_up_absence_claim_that_started_this_is_caught():
    bad = "The Uttar Pradesh MSME policy does not provide a capital subsidy to micro units."
    assert "unsupported_negative" in kinds(bad, [UP])
    good = "The cost of land is not counted as eligible fixed capital investment."
    assert "unsupported_negative" not in kinds(good, [UP])


def test_hedges_about_the_clauses_are_not_checked():
    r = F.check("The specific details of the subsidy are not provided in the given clauses. Please confirm with your bank.", [KA])
    assert r.passed and r.checked == 0


def test_naming_a_scheme_the_clauses_do_not_belong_to_is_caught():
    assert "scheme_not_cited" in kinds("Under PMEGP you also get 25% of VFA in Zone-2.", [KA])
    assert "scheme_not_cited" not in kinds("The Karnataka policy gives 25% of VFA up to Rs 25 lakhs in Zone-2.", [KA])


def test_invented_sentence_with_no_overlap_is_caught():
    r = F.check("Applicants must also deposit a refundable security amount with the district magistrate before inspection begins.", [KA])
    assert not r.passed and "low_overlap" in {i.kind for i in r.issues}


def test_reasons_are_readable_and_score_is_a_fraction():
    r = F.check("Micro units get 30% of VFA up to Rs 30 lakhs. Medium units get 99%.", [KA])
    assert 0.0 < r.score < 1.0 and r.reasons() and "unsupported by the cited clauses" in r.reasons()[0]


def test_no_cited_clauses_means_nothing_to_check():
    assert F.check("anything", []).passed
