"""
Shared shape for anything that brings books into the ledger (Tally, CSV, later others).

Imports are read-only with respect to the source system and idempotent on our side:
each entry carries an `external_ref` (Tally voucher GUID, or a CSV row hash) and a
unique index on (business_id, external_ref) makes a second import a no-op.
All money is integer paise. Gross is tax-inclusive, matching ledger_entries.amount_paise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import psycopg

_SLABS_BP = (0, 500, 1200, 1800, 2800)


def snap_rate_bp(tax_paise: int, gross_paise: int) -> Optional[int]:
    """Turn (tax, gross) into the nearest standard GST slab, in basis points.
    Returns None when the split is not recognisable, so a human reviews it."""
    taxable = gross_paise - tax_paise
    if taxable <= 0:
        return None
    raw = tax_paise * 10000 / taxable
    best = min(_SLABS_BP, key=lambda s: abs(s - raw))
    return best if abs(best - raw) <= 60 else None   # within 0.6 percentage points


@dataclass
class ImportedEntry:
    entry_date: date
    direction: str                    # 'in' (sale) or 'out' (purchase)
    amount_paise: int                 # gross, tax-inclusive
    category: str
    counterparty: str
    gst_rate_bp: Optional[int]
    invoice_no: str = ""
    counterparty_gstin: str = ""
    external_ref: str = ""
    source: str = "csv"               # 'tally' or 'csv'


def save(conn: psycopg.Connection, business_id: int, entries: list[ImportedEntry]) -> dict:
    """Insert entries; skip any whose external_ref is already present. Rows with no recognisable
    GST rate are saved but flagged needs_review, so they are never silently included in a return."""
    added = skipped = flagged = 0
    for e in entries:
        review = e.gst_rate_bp is None
        row = conn.execute(
            """INSERT INTO ledger_entries
               (business_id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp,
                source, needs_review, invoice_no, counterparty_gstin, external_ref)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, external_ref) WHERE external_ref IS NOT NULL DO NOTHING
               RETURNING id""",
            (business_id, e.entry_date, e.direction, e.amount_paise, e.category, e.counterparty,
             e.gst_rate_bp, e.source, review, e.invoice_no or None, e.counterparty_gstin or None,
             e.external_ref or None)).fetchone()
        if row is None:
            skipped += 1
        else:
            added += 1
            flagged += 1 if review else 0
    conn.commit()
    return {"added": added, "skipped_duplicates": skipped, "flagged_for_review": flagged}
