"""
Business memory: what the assistant remembers about this owner between messages.

Everything here is deterministic code (patterns and counters), no model summarises or invents it, so the owner
can read exactly what is stored (GET /sim/memory) and erase it (DELETE /sim/memory). Remembered facts are only
ever offered to the models as owner-stated context; they are never a source for a scheme rule or a citation.

Stored per business (table business_memory):
  profile  facts the owner stated in chat (sector, state, loan amount asked, headcount) and scheme interests
  recent   the last few exchanges, shortened
"""

from __future__ import annotations

import re
from collections import Counter

import psycopg
from psycopg.types.json import Jsonb

from .scheme import _ALIASES, _family

MAX_RECENT = 6
CONTEXT_CHARS = 700

_STATES = ["andhra pradesh", "assam", "bihar", "chhattisgarh", "delhi", "goa", "gujarat", "haryana", "himachal pradesh",
           "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "odisha", "punjab", "rajasthan",
           "tamil nadu", "telangana", "uttar pradesh", "uttarakhand", "west bengal"]
_SECTORS = {
    "tailoring": "tailoring", "garment": "garments", "kirana": "grocery retail", "grocery": "grocery retail",
    "bakery": "bakery", "garage": "auto repair", "auto repair": "auto repair", "tea stall": "tea stall",
    "street vendor": "street vending", "food stall": "street vending", "dairy": "dairy", "poultry": "poultry",
    "furniture": "furniture", "printing": "printing", "stationery": "stationery", "jewellery": "jewellery",
    "agarbatti": "agarbatti", "mobile repair": "mobile repair", "flour mill": "flour milling",
    "carpenter": "carpentry", "plumb": "plumbing", "electric": "electrical work", "restaurant": "food service",
    "boutique": "garments", "salon": "salon", "tuition": "education", "farm": "farming", "weav": "handloom weaving",
}
_AMOUNT = re.compile(r"(?:rs\.?|₹|inr)?\s*(\d+(?:\.\d+)?)\s*(lakh|lac|crore|cr|k|thousand)\b", re.I)
_STAFF = re.compile(r"\b(\d{1,3})\s+(?:employees|workers|staff|people|labou?rers)\b", re.I)
_UNITS = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000, "cr": 10_000_000, "k": 1_000, "thousand": 1_000}


def ensure(conn: psycopg.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS business_memory (
               business_id BIGINT PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
               profile     JSONB       NOT NULL DEFAULT '{}'::jsonb,
               recent      JSONB       NOT NULL DEFAULT '[]'::jsonb,
               turns       INTEGER     NOT NULL DEFAULT 0,
               updated_at  TIMESTAMPTZ NOT NULL DEFAULT now())""")


def schemes_in(text: str) -> list[str]:
    low = text.lower()
    return sorted({_family(fam) for alias, fam in _ALIASES.items() if alias in low})


def extract_facts(text: str) -> dict:
    """Facts the owner stated, by pattern. Nothing is inferred."""
    low = text.lower()
    facts: dict = {}
    for key, label in _SECTORS.items():
        if key in low:
            facts["sector"] = label
            break
    for st in _STATES:
        if st in low:
            facts["state"] = st.title()
            break
    m = _AMOUNT.search(text)
    if m and re.search(r"\b(loan|need|want|borrow|require|amount|finance)\b", low):
        facts["loan_amount_asked_rupees"] = int(float(m.group(1)) * _UNITS[m.group(2).lower()])
    m = _STAFF.search(text)
    if m:
        facts["employees"] = int(m.group(1))
    return facts


def _load(conn, bid: int) -> tuple[dict, list, int]:
    row = conn.execute("SELECT profile, recent, turns FROM business_memory WHERE business_id=%s", (bid,)).fetchone()
    return (row[0] or {}, row[1] or [], row[2]) if row else ({}, [], 0)


def record_turn(conn: psycopg.Connection, bid: int, question_en: str, reply_en: str, intent: str, lang: str) -> None:
    """Update memory after one exchange. Never raises into the chat path."""
    try:
        profile, recent, turns = _load(conn, bid)
        profile.update(extract_facts(question_en))
        profile["language"] = lang
        interests = Counter(profile.get("interests") or {})
        found = schemes_in(question_en) or (schemes_in(reply_en) if intent == "eligibility" else [])
        for s in found:
            interests[s] += 1
        profile["interests"] = dict(interests.most_common(8))
        recent.append({"q": question_en.strip()[:140], "intent": intent, "schemes": found})
        recent = recent[-MAX_RECENT:]
        conn.execute(
            """INSERT INTO business_memory (business_id, profile, recent, turns) VALUES (%s,%s,%s,1)
               ON CONFLICT (business_id) DO UPDATE SET profile=EXCLUDED.profile, recent=EXCLUDED.recent,
                   turns=business_memory.turns+1, updated_at=now()""",
            (bid, Jsonb(profile), Jsonb(recent)))
        conn.commit()
    except Exception:
        conn.rollback()


def view(conn: psycopg.Connection, bid: int) -> dict:
    profile, recent, turns = _load(conn, bid)
    return {"profile": profile, "recent": recent, "turns": turns}


def forget(conn: psycopg.Connection, bid: int) -> None:
    conn.execute("DELETE FROM business_memory WHERE business_id=%s", (bid,))
    conn.commit()


def context(conn: psycopg.Connection, bid: int) -> str:
    """A short, owner-stated context block for prompts. Empty when nothing is known."""
    profile, recent, _ = _load(conn, bid)
    attrs = conn.execute("SELECT attrs FROM businesses WHERE id=%s", (bid,)).fetchone()
    attrs = (attrs[0] if attrs else None) or {}
    bits = []
    sector = profile.get("sector") or attrs.get("sector") or attrs.get("activity")
    if sector:
        bits.append(f"business: {sector}")
    if profile.get("state"):
        bits.append(f"state: {profile['state']}")
    if profile.get("employees"):
        bits.append(f"about {profile['employees']} staff")
    if profile.get("loan_amount_asked_rupees"):
        bits.append(f"asked about a loan of about Rs {profile['loan_amount_asked_rupees']:,}")
    if profile.get("interests"):
        bits.append("interested in " + ", ".join(list(profile["interests"])[:4]))
    if recent:
        bits.append("recent questions: " + " | ".join(r["q"] for r in recent[-3:]))
    return ("Owner context (stated by the owner, not verified; never a source for scheme rules): " + "; ".join(bits))[:CONTEXT_CHARS] if bits else ""


def augment_query(conn: psycopg.Connection, bid: int, question: str) -> str:
    """Resolve a short follow-up such as 'what about the subsidy?' by adding the scheme just discussed."""
    if schemes_in(question) or len(re.findall(r"[A-Za-z]{3,}", question)) > 6:
        return question
    _, recent, _ = _load(conn, bid)
    for r in reversed(recent):
        if r.get("schemes"):
            return f"{question} ({' '.join(r['schemes'])})"
    return question
