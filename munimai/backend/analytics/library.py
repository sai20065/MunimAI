"""
A small reading library for the consulting side: definitions and explanations from openly licensed textbooks.

RETRIEVAL ONLY. These texts are never used to train a model. They are stored with their licence and source,
shown as short attributed excerpts, and can be switched off in one line.

Current sources (prototype): OpenStax Principles of Finance 2e, Principles of Marketing and Entrepreneurship, all
CC BY-NC-SA 4.0 (non-commercial, share-alike). Set LIBRARY_ALLOW_NC=0 to hide every NC book before any commercial
use. Source files are read from a local clone of the official OpenStax GitHub repositories.

Facts such as tax rules do NOT come from here. They stay in the cited clause library.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import psycopg

NS = {"c": "http://cnx.rice.edu/cnxml", "m": "http://www.w3.org/1998/Math/MathML"}
BOOKS = {
    "osbooks-principles-finance": ("Principles of Finance 2e", "principles-finance-2e"),
    "osbooks-principles-marketing": ("Principles of Marketing", "principles-marketing"),
    "osbooks-entrepreneurship": ("Entrepreneurship", "entrepreneurship"),
}
LICENSE_NC = "CC BY-NC-SA 4.0"
ATTRIBUTION = "OpenStax, Rice University, {book}, {license}"


def _text(el: ET.Element) -> str:
    """Plain text of an element, dropping equations (MathML) and collapsing whitespace."""
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        tag = e.tag.split("}")[-1]
        if tag in ("math", "media", "image", "table", "figure"):
            return
        if e.text:
            parts.append(e.text)
        for ch in e:
            walk(ch)
            if ch.tail:
                parts.append(ch.tail)

    walk(el)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def module_chunks(path: Path, max_chars: int = 1100) -> list[tuple[str, str]]:
    """(section title, chunk text) for one OpenStax CNXML module."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    title = (root.findtext("c:title", default="", namespaces=NS) or "").strip()
    out: list[tuple[str, str]] = []
    buf = ""
    for p in root.iter("{%s}para" % NS["c"]):
        t = _text(p)
        if len(t) < 60:
            continue
        if buf and len(buf) + len(t) > max_chars:
            out.append((title, buf)); buf = ""
        buf = (buf + " " + t).strip()
    if buf:
        out.append((title, buf))
    return out


def ingest(conn: psycopg.Connection, src_root: Path) -> dict:
    """Load every book found under src_root. Replaces that book's rows, so it is safe to re-run."""
    counts = {}
    for repo, (book, slug) in BOOKS.items():
        mods = src_root / repo / "modules"
        if not mods.is_dir():
            continue
        conn.execute("DELETE FROM library_chunks WHERE book=%s", (book,))
        n = 0
        for d in sorted(mods.iterdir()):
            f = d / "index.cnxml"
            if not f.exists():
                continue
            for section, text in module_chunks(f):
                conn.execute(
                    "INSERT INTO library_chunks (book, section, text, license, nc, source_url, attribution) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (book, section, text, LICENSE_NC, True, f"https://openstax.org/details/books/{slug}",
                     ATTRIBUTION.format(book=book, license=LICENSE_NC)))
                n += 1
        conn.commit()
        counts[book] = n
    return counts


def allow_nc() -> bool:
    return os.environ.get("LIBRARY_ALLOW_NC", "1") == "1"


def search(conn: psycopg.Connection, query: str, k: int = 3) -> list[dict]:
    """Top chunks for a query using Postgres full-text search. Honours LIBRARY_ALLOW_NC."""
    q = re.sub(r"[^A-Za-z0-9 ]", " ", query).strip()
    if not q:
        return []
    rows = conn.execute(
        """SELECT book, section, text, license, source_url, attribution,
                  ts_rank_cd(to_tsvector('english', text), websearch_to_tsquery('english', %s)) AS r
           FROM library_chunks
           WHERE to_tsvector('english', text) @@ websearch_to_tsquery('english', %s)
             AND (%s OR NOT nc)
           ORDER BY r DESC LIMIT %s""", (q, q, allow_nc(), k)).fetchall()
    return [dict(book=r[0], section=r[1], text=r[2], license=r[3], url=r[4], attribution=r[5], score=float(r[6])) for r in rows]


def excerpt(text: str, query: str, width: int = 260) -> str:
    """A short, sentence-aligned excerpt around the first query word, for attribution-friendly quoting."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", query)]
    low = text.lower()
    pos = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
    start = text.rfind(". ", 0, pos) + 2 if text.rfind(". ", 0, pos) > 0 else 0
    cut = text[start:start + width]
    end = max(cut.rfind(". "), -1)
    return (cut[:end + 1] if end > 80 else cut).strip()
