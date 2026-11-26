"""Guards on the scheme library's sources: every fetched host is allowlisted, only .gov.in/.nic.in or a named exception is trusted, and state questions reach the Scheme agent."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

from backend.config import CITATION_ALLOWLIST
from backend.kb.fetch import EXCLUDES, FILTERS, PDF_WINDOWS, SOURCES
from backend.router import classify

NAMED_NON_GOV_EXCEPTIONS = {"www.nsic.co.in", "nsic.co.in", "www.sidbi.in", "sidbi.in", "www.standupmitra.in",
                            "mudra.org.in", "www.mudra.org.in", "cgtmse.in", "www.cgtmse.in", "jansamarth.in", "www.jansamarth.in",
                            "rbi.org.in", "www.rbi.org.in",          # Reserve Bank of India, a statutory body
                            "investkarnataka.co.in"}                 # Government of Karnataka's own guidelines; see config.py


def test_every_source_host_is_allowlisted():
    missing = {urlparse(u).netloc.lower() for _, u in SOURCES} - CITATION_ALLOWLIST
    assert not missing, f"loader would reject these hosts: {missing}"


def test_only_government_domains_or_named_exceptions_are_trusted():
    odd = {h for h in CITATION_ALLOWLIST if not re.search(r"\.(gov|nic)\.in$", h)} - NAMED_NON_GOV_EXCEPTIONS
    assert not odd, f"unexplained non-government hosts in the allowlist: {odd}"


def test_page_windows_filters_and_excludes_point_at_real_sources():
    urls = {u for _, u in SOURCES}
    for table in (PDF_WINDOWS, FILTERS, EXCLUDES):
        assert set(table) <= urls
    for first, last, cap in PDF_WINDOWS.values():
        assert 1 <= first <= last and cap > 0


@pytest.mark.parametrize("q", [
    "What capital subsidy does Karnataka give to micro enterprises under its industrial policy?",
    "Does Telangana have an MSME incentive for women?",
    "What is CLCSS?",
    "What are the Udyam size limits?",
    "Tell me about the Andhra Pradesh startup policy incentives",
])
def test_state_and_central_scheme_questions_route_to_the_scheme_agent(q):
    assert classify(q) == "eligibility"
