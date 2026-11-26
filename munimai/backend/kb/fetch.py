"""
Fetch official scheme pages and turn them into verbatim clauses.

No model ever touches clause text: pages are fetched, converted to text with the
stdlib HTML parser, split by heading into paragraph-sized pieces, and stored as
JSON exactly as printed. Boilerplate (nav, cookie banners, counters) is dropped
by rule. Each clause carries its source URL, domain and fetch time.

Run:  python -m backend.kb.fetch            # fetch every source in SOURCES
      python -m backend.kb.fetch --inspect URL   # print the clauses for one URL
      python -m backend.kb.fetch --only PMEGP,NIDHI   # fetch only these scheme codes
Set PYTHONUTF8=1 on Windows so rupee signs and curly quotes print.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests

KB_DIR = Path(__file__).parent
UA = "SaralcreditAI-KB/1.0 (research prototype; official-source clause extraction)"
DELAY_S = 1.5
TIMEOUT_S = 30
MAX_CLAUSE_CHARS = 700
MIN_CLAUSE_CHARS = 60
MAX_CLAUSES_PER_PAGE = 45

# (scheme_code, url). Verified reachable and content-bearing; see SOURCES.md.
_CG = "https://www.cgtmse.in"
_SI = "https://www.startupindia.gov.in"
SOURCES: list[tuple[str, str]] = [
    ("PMEGP", "https://pmegp.msme.gov.in/Home/FAQ"),
    ("PMEGP", "https://pmegp.msme.gov.in/Home/TermsAndConditions"),
    ("PMEGP", "https://pmegp.msme.gov.in/Home/HomePage"),
    ("CGTMSE", f"{_CG}/"),
    ("CGTMSE", f"{_CG}/Home/VS/71"),
    ("CGTMSE", f"{_CG}/Default/ViewFile/?id=1743176302611_CGTMSE+-+Scheme+Document+CGS+I_updated+as+on+Apr+1+2025.pdf&path=Page"),
    ("PM_SVANIDHI", "https://pmsvanidhi.mohua.gov.in"),
    ("STANDUP_INDIA", "https://www.standupmitra.in/"),
    ("PM_VISHWAKARMA", "https://pmvishwakarma.gov.in/"),
    ("NSIC", "https://www.nsic.co.in/Schemes/SinglePointRegistration"),
    ("NSIC", "https://www.nsic.co.in/Schemes/RawMaterialAgainstBG"),
    ("NSIC", "https://www.nsic.co.in/Schemes/MSMESaarthi"),
    ("SIDBI", "https://www.sidbi.in/en/working-capital"),
    ("SIDBI", "https://www.sidbi.in/en/machinery-loan"),
    ("SIDBI", "https://www.sidbi.in/en/business-loan"),
    ("STARTUP_INDIA", f"{_SI}/content/sih/en/startup-scheme.html"),
    ("STARTUP_INDIA", f"{_SI}/content/sih/en/startupgov/startup_recognition_page.html"),
    ("SISFS", f"{_SI}/content/dam/invest-india/Templates/public/Guidelines%20for%20Startup%20India%20Seed%20Fund%20Scheme.pdf"),
    ("STARTUP_PLAYBOOK", f"{_SI}/content/dam/startupindia/homebanners/Startup-Schemes-Playbook-June-2026.pdf"),
    # added 2026-11-25: central gaps and state policies, each checked for a current validity period (see SOURCES.md)
    ("PMEGP", "https://dkvib.delhi.gov.in/dkvib/revised-scheme-guidelines-prime-minister-employeement-generation-programmepmegp"),
    ("UDYAM", "https://www.msme.gov.in/static/uploads/2026/05/1bfda06b460e72543530b40817573495.pdf"),
    ("NIDHI", "https://cdnbbsr.s3waas.gov.in/s312b1e42dc0746f22cf361267de07073f/uploads/2026/05/20260520803129779.pdf"),
    ("JAN_SAMARTH", "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2022/jun/doc20226963001.pdf"),
    ("UP_MSME_POLICY", "https://invest.up.gov.in/wp-content/uploads/2023/06/English_MSME-Policy-2022.pdf"),
    ("GUJARAT_IND_POLICY_2022", "https://static.investindia.gov.in/s3fs-public/2022-10/Gujarat%20Industrial%20Policy%202022-%20Brochure.pdf"),
    ("TAMILNADU_STARTUP_POLICY", f"{_SI}/content/dam/invest-india/Templates/public/state_startup_policies/Tamil_Nadu_Startup_Policy.pdf"),
    ("ANDHRA_PRADESH_STARTUP_POLICY_2024_29", f"{_SI}/content/dam/invest-india/Templates/public/state_startup_policies/AP-Innovation-Policy-2024-29.pdf"),
    ("KARNATAKA_INDUSTRIAL_POLICY_2025_30", "https://investkarnataka.co.in/wp-content/uploads/2026/04/Karnataka.pdf"),
    ("TELANGANA_MSME_HANDBOOK_2024", "https://ipass.telangana.gov.in/Industries/Library/Total%20%20Book%20-%20MSME%20-%20Grand%20Final%20-%2007_10_2024.pdf"),
]

# Sources that are a long document of which only some clauses are rules: keep a clause only if it matches.
# The text kept is still verbatim; this only drops chapters that are not rules (history, budgets, statistics).
# Long PDFs where the rules for small businesses sit in a known page range: url -> (first page, last page, max clauses).
# Karnataka's operative guidelines run to 186 pages; the first 30 are large-industry incentives, Section 11 (MSME) starts on page 95.
PDF_WINDOWS: dict[str, tuple[int, int, int]] = {
    "https://investkarnataka.co.in/wp-content/uploads/2026/04/Karnataka.pdf": (95, 125, 150),
    "https://ipass.telangana.gov.in/Industries/Library/Total%20%20Book%20-%20MSME%20-%20Grand%20Final%20-%2007_10_2024.pdf": (3, 142, 330),
}

# Clauses to drop from a source (the opposite of FILTERS). The handbook below is a state compilation of state and central schemes:
# officials' contact details are removed, and so are schemes for which we hold the direct, newer official text (their figures
# in a 2024 compilation could conflict with it).
EXCLUDES: dict[str, str] = {
    "https://ipass.telangana.gov.in/Industries/Library/Total%20%20Book%20-%20MSME%20-%20Grand%20Final%20-%2007_10_2024.pdf":
        r"(?i)mail id|e-?mail|@[a-z0-9.-]*\.(gov|nic)\.in|\b\d{10}\b|Room No|PMEGP|Prime Minister.?s Employment Generation|SVANidhi|MUDRA|Stand[- ]?Up India|CGTMSE|Credit Guarantee",
}

FILTERS: dict[str, str] = {
    "https://www.msme.gov.in/static/uploads/2026/05/1bfda06b460e72543530b40817573495.pdf":
        r"(?i)revised classification|limits for classification|where the investment in plant",
}

_SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer",
              "aside", "form", "button", "select", "option", "iframe"}
_BLOCK_TAGS = {"p", "li", "td", "th", "dt", "dd", "div", "section", "article",
               "tr", "br", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BOILER = re.compile(
    r"cookie|copyright|all rights reserved|visitor|last updated|javascript|skip to|"
    r"screen reader|font size|sitemap|privacy policy|terms (&|and) conditions|"
    r"disclaimer|website content|designed (and|&) developed|hyperlink|feedback|"
    r"toll free|follow us|download app|^home$|^login|^register$|^faq$|click here",
    re.I)


_NOISE_HEADING = re.compile(
    r"stor(y|ies)|testimonial|news|gallery|success|event|tender|vacanc|career|"
    r"press|media|video|blog|latest|notification|circular|contact|follow", re.I)


class _Blocks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.cur: list[str] = []
        self.heading_tag: str | None = None
        self.items: list[tuple[str, str]] = []   # (kind, text) kind = 'h' | 'p'

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        self.cur = []
        if text:
            self.items.append(("h" if self.heading_tag else "p", text))

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            self.heading_tag = tag if tag in _HEADINGS else None

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            self.heading_tag = None

    def handle_data(self, data):
        if not self.skip:
            self.cur.append(data)


def html_to_clauses(html: str) -> list[tuple[str, str]]:
    """Return [(heading, verbatim text), ...] with boilerplate removed."""
    p = _Blocks()
    p.feed(html)
    p._flush()
    out: list[tuple[str, str]] = []
    heading, buf = "overview", ""
    seen: set[str] = set()

    def emit() -> None:
        nonlocal buf
        t = buf.strip()
        if len(t) >= MIN_CLAUSE_CHARS and t not in seen:
            seen.add(t)
            out.append((heading, t))
        buf = ""

    for kind, text in p.items:
        if kind == "h":
            emit()
            heading = text[:80]
            continue
        if _NOISE_HEADING.search(heading):
            continue
        if _BOILER.search(text) or (len(text) < 25 and not re.search(r"\d", text)):
            continue                                  # short numeric cells (rates, limits) are kept
        if len(text) > MAX_CLAUSE_CHARS:           # long paragraph: split on sentence ends
            emit()
            for part in re.split(r"(?<=[.;:])\s+(?=[A-Z0-9(])", text):
                if buf and len(buf) + len(part) > MAX_CLAUSE_CHARS:
                    emit()
                buf = f"{buf} {part}".strip()
            emit()
            continue
        if buf and len(buf) + len(text) > MAX_CLAUSE_CHARS:
            emit()
        buf = f"{buf}\n{text}".strip() if buf else text
    emit()
    return out[:MAX_CLAUSES_PER_PAGE]


def fetch_any(url: str) -> tuple[str, bytes | str]:
    """Return ('html', text) or ('pdf', bytes)."""
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT_S)
            if r.status_code == 200 and r.content:
                if "pdf" in r.headers.get("content-type", "").lower() or r.content[:4] == b"%PDF":
                    return "pdf", r.content
                r.encoding = r.encoding or "utf-8"
                return "html", r.text
            last = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as exc:
            last = exc
        time.sleep(2)
    raise RuntimeError(f"fetch failed for {url}: {last}")


def fetch_html(url: str) -> str:
    kind, data = fetch_any(url)
    return data if kind == "html" else ""


def pdf_to_clauses(data: bytes, max_pages: int = 30, max_clauses: int = 120, first_page: int = 1) -> list[tuple[str, str]]:
    """Verbatim sentence-grouped chunks per page of a text PDF (no OCR), from first_page to max_pages (1-based, inclusive)."""
    import pymupdf

    out: list[tuple[str, str]] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for n, page in enumerate(list(doc)[first_page - 1:max_pages], first_page):
            text = re.sub(r"[ \t]+", " ", page.get_text("text"))
            text = re.sub(r"\n(?=[a-z(])", " ", text)      # re-join wrapped lines
            text = re.sub(r"\s*\n\s*", " ", text).strip()
            buf = ""
            for part in re.split(r"(?<=[.;:])\s+(?=[A-Z0-9(])", text):
                if buf and len(buf) + len(part) > MAX_CLAUSE_CHARS:
                    if len(buf) >= MIN_CLAUSE_CHARS and not _BOILER.search(buf):
                        out.append((f"page {n}", buf))
                    buf = ""
                buf = f"{buf} {part}".strip()
            if len(buf) >= MIN_CLAUSE_CHARS and not _BOILER.search(buf):
                out.append((f"page {n}", buf))
            if len(out) >= max_clauses:
                break
    return out[:max_clauses]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:36] or "section"


def build_scheme_file(scheme_code: str, urls: list[str]) -> list[dict]:
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict] = []
    for url in urls:
        try:
            kind, data = fetch_any(url)
        except RuntimeError as exc:
            print(f"  GAP {url}: {exc}")
            continue
        domain = urlparse(url).netloc.lower()
        if kind == "pdf":
            first, last, cap = PDF_WINDOWS.get(url, (1, 30, 120))
            pieces = pdf_to_clauses(data, max_pages=last, max_clauses=cap, first_page=first)
        else:
            pieces = html_to_clauses(data)
        if url in FILTERS:
            pieces = [p for p in pieces if re.search(FILTERS[url], p[1])]
        if url in EXCLUDES:
            pieces = [p for p in pieces if not re.search(EXCLUDES[url], p[1])]
        if not pieces:
            print(f"  GAP {url}: no extractable text")
        for i, (heading, text) in enumerate(pieces, 1):
            rows.append({
                "scheme_code": scheme_code,
                "clause_ref": f"{_slug(urlparse(url).path.rsplit('/', 1)[-1] or 'home')[:20]}.{_slug(heading)}.{i}",
                "clause_text": text,
                "source_url": url,
                "source_domain": domain,
                "fetched_at": fetched,
            })
        time.sleep(DELAY_S)
    return rows


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--inspect":
        kind, data = fetch_any(sys.argv[2])
        for h, t in (pdf_to_clauses(data) if kind == "pdf" else html_to_clauses(data)):
            print(f"[{h}] {t}\n")
        return
    only = set(sys.argv[2].upper().split(",")) if len(sys.argv) > 2 and sys.argv[1] == "--only" else None
    by_scheme: dict[str, list[str]] = {}
    for code, url in SOURCES:
        if only is None or code in only:
            by_scheme.setdefault(code, []).append(url)
    for code, urls in by_scheme.items():
        rows = build_scheme_file(code, urls)
        if rows:
            (KB_DIR / f"{code.lower()}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{code}: {len(rows)} clauses")


if __name__ == "__main__":
    main()
