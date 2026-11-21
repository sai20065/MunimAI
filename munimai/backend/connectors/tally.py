"""
Tally connector (read-only).

Tally Prime exposes an XML-over-HTTP interface (default http://localhost:9000). We send a
"Voucher Register" export request and parse the reply. `parse_vouchers(xml)` works on any XML
text, so tests and demos run from fixtures without a live Tally.

Mapping rules (kept deliberately simple and explicit):
- Sales voucher -> direction 'in'; Purchase voucher -> direction 'out'. Other voucher types
  (Journal, Payment, Receipt, Contra...) are skipped and counted, never guessed.
- The party ledger line carries the gross amount (sign ignored). Ledger lines whose name contains
  CGST, SGST, UTGST or IGST make up the tax. The rate is snapped to a standard slab; if the split
  is not recognisable the entry is flagged for review.
- No write-back to Tally in this version.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Optional

import requests

from .base import ImportedEntry, snap_rate_bp

_TAX_WORDS = ("CGST", "SGST", "UTGST", "IGST")

EXPORT_REQUEST = """<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>
<TYPE>Collection</TYPE><ID>Voucher Register</ID></HEADER><BODY><DESC><STATICVARIABLES>
<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT><SVFROMDATE>{start}</SVFROMDATE><SVTODATE>{end}</SVTODATE>
</STATICVARIABLES></DESC></BODY></ENVELOPE>"""


def fetch(host: str, port: int, start: date, end: date, timeout: int = 30) -> str:
    """Ask a running Tally for vouchers in [start, end]. Read-only request."""
    body = EXPORT_REQUEST.format(start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
    r = requests.post(f"http://{host}:{port}", data=body.encode("utf-8"), timeout=timeout)
    r.raise_for_status()
    return r.text


def _paise(text: Optional[str]) -> int:
    if not text:
        return 0
    return abs(round(float(text.replace(",", "").strip()) * 100))


def _text(node: ET.Element, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_vouchers(xml_text: str) -> tuple[list[ImportedEntry], dict]:
    root = ET.fromstring(xml_text)
    entries: list[ImportedEntry] = []
    skipped_types: dict[str, int] = {}
    for v in root.iter("VOUCHER"):
        vtype = (v.get("VCHTYPE") or _text(v, "VOUCHERTYPENAME")).strip()
        kind = vtype.lower()
        if kind not in ("sales", "purchase"):
            skipped_types[vtype or "unknown"] = skipped_types.get(vtype or "unknown", 0) + 1
            continue
        raw_date = _text(v, "DATE")
        try:
            d = datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError:
            skipped_types["bad-date"] = skipped_types.get("bad-date", 0) + 1
            continue
        party = _text(v, "PARTYLEDGERNAME")
        gross = tax = 0
        for led in list(v.iter("ALLLEDGERENTRIES.LIST")) + list(v.iter("LEDGERENTRIES.LIST")):
            name = _text(led, "LEDGERNAME")
            amt = _paise(_text(led, "AMOUNT"))
            if any(w in name.upper() for w in _TAX_WORDS):
                tax += amt
            elif name == party:
                gross = amt
        if gross <= 0:
            skipped_types["no-party-amount"] = skipped_types.get("no-party-amount", 0) + 1
            continue
        guid = _text(v, "GUID") or hashlib.sha256(f"{raw_date}|{party}|{_text(v, 'VOUCHERNUMBER')}|{gross}".encode()).hexdigest()[:24]
        entries.append(ImportedEntry(
            entry_date=d, direction="in" if kind == "sales" else "out", amount_paise=gross,
            category=("sales" if kind == "sales" else "purchases"), counterparty=party,
            gst_rate_bp=snap_rate_bp(tax, gross), invoice_no=_text(v, "VOUCHERNUMBER"),
            counterparty_gstin=_text(v, "PARTYGSTIN"), external_ref=f"tally:{guid}", source="tally"))
    return entries, {"vouchers_imported": len(entries), "skipped_by_type": skipped_types}
