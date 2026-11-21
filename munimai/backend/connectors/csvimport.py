"""
CSV/Excel-export importer, for owners who do not run Tally or want a quick start.

Columns (header row, any order, case-insensitive):
  date (YYYY-MM-DD or DD/MM/YYYY), type (sale|purchase), party, gstin, invoice_no,
  amount (gross, rupees), gst_rate (percent, e.g. 18), category (optional)

Also parses a GSTR-2B-style supplier file (supplier_gstin, supplier_name, invoice_no,
invoice_date, taxable, tax) for ITC reconciliation. In the hackathon demo this file is synthetic:
we do not call the GST portal.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime

from .base import ImportedEntry


def _date(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date '{s}'")


def _paise(s: str) -> int:
    return round(float(s.replace(",", "").strip()) * 100)


def parse_books(csv_text: str) -> tuple[list[ImportedEntry], dict]:
    rd = csv.DictReader(io.StringIO(csv_text))
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rd]
    out: list[ImportedEntry] = []
    bad: list[str] = []
    for i, r in enumerate(rows, start=2):
        try:
            kind = r.get("type", "").lower()
            if kind not in ("sale", "sales", "purchase", "purchases"):
                raise ValueError(f"type must be sale or purchase, got '{kind}'")
            rate = r.get("gst_rate", "")
            rate_bp = None if rate == "" else round(float(rate) * 100)
            ref = hashlib.sha256("|".join([r.get("date", ""), kind, r.get("party", ""), r.get("invoice_no", ""),
                                           r.get("amount", "")]).encode()).hexdigest()[:24]
            out.append(ImportedEntry(
                entry_date=_date(r["date"]), direction="in" if kind.startswith("sale") else "out",
                amount_paise=_paise(r["amount"]), category=r.get("category") or ("sales" if kind.startswith("sale") else "purchases"),
                counterparty=r.get("party", ""), gst_rate_bp=rate_bp, invoice_no=r.get("invoice_no", ""),
                counterparty_gstin=r.get("gstin", ""), external_ref=f"csv:{ref}", source="csv"))
        except (KeyError, ValueError) as e:
            bad.append(f"row {i}: {e}")
    return out, {"rows_ok": len(out), "rows_rejected": bad}


def parse_gstr2b(csv_text: str) -> list[dict]:
    rd = csv.DictReader(io.StringIO(csv_text))
    out = []
    for r in rd:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        out.append({"supplier_gstin": r.get("supplier_gstin", ""), "supplier_name": r.get("supplier_name", ""),
                    "invoice_no": r["invoice_no"], "invoice_date": _date(r["invoice_date"]) if r.get("invoice_date") else None,
                    "taxable_paise": _paise(r["taxable"]), "tax_paise": _paise(r["tax"])})
    return out
