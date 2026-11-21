"""
The Auditor: a deterministic rule engine over the ledger, with no model in the loop.

It finds the problems a careful accountant would flag before a GST return goes out. Every finding
has a rule id, a severity, the exact ledger rows involved and a plain message. Every figure is
integer paise computed in Python.

Severity: info (FYI), warn (owner should look), critical (blocks approval until resolved).
Statutory references are pointers for the owner's CA to confirm, not legal advice; the agent
is an assistant and does not certify anything.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Iterable, Optional

import psycopg

from .compliance import _tax_component_paise

REF_ITC_INVOICE = "CGST Act 2017, s.16(2)(a): ITC needs a valid tax invoice (confirm with your CA)"
REF_ITC_2B = "CGST Act 2017, s.16(2)(aa): ITC only for invoices reflected in GSTR-2B (confirm with your CA)"


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    entry_ids: list[int] = field(default_factory=list)
    rule_ref: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def audit_rows(rows: list[dict], gstr2b: list[dict], today: date) -> list[Finding]:
    """rows: dicts with id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp,
    needs_review, invoice_no, counterparty_gstin. gstr2b: dicts with supplier_gstin, invoice_no, tax_paise."""
    out: list[Finding] = []
    live = [r for r in rows if not r.get("needs_review")]

    review = [r["id"] for r in rows if r.get("needs_review")]
    if review:
        out.append(Finding("awaiting_review", "warn",
                           f"{len(review)} entr{'y is' if len(review) == 1 else 'ies are'} waiting for your confirmation "
                           "and left out of the return.", review))

    # duplicates: same party and invoice number
    seen: dict[tuple, list[dict]] = defaultdict(list)
    for r in live:
        if r.get("invoice_no"):
            seen[(r["direction"], (r.get("counterparty") or "").lower(), r["invoice_no"].lower())].append(r)
    for (direction, _, inv), grp in seen.items():
        if len(grp) > 1:
            sev = "critical" if direction == "out" else "warn"
            out.append(Finding("duplicate_invoice", sev,
                               f"Invoice {inv} from {grp[0].get('counterparty') or 'the same party'} appears "
                               f"{len(grp)} times." + (" Claiming its credit twice is a serious error." if direction == "out" else ""),
                               [g["id"] for g in grp], REF_ITC_INVOICE if direction == "out" else None))

    # likely duplicates without an invoice number
    same: dict[tuple, list[dict]] = defaultdict(list)
    for r in live:
        if not r.get("invoice_no"):
            same[(r["entry_date"], r["direction"], (r.get("counterparty") or "").lower(), r["amount_paise"])].append(r)
    for grp in same.values():
        if len(grp) > 1:
            out.append(Finding("possible_duplicate", "warn",
                               f"{len(grp)} entries on {grp[0]['entry_date']} with the same party and amount "
                               f"({_rupees(grp[0]['amount_paise'])}) and no invoice number.", [g["id"] for g in grp]))

    purchases = [r for r in live if r["direction"] == "out" and (r.get("gst_rate_bp") or 0) > 0]
    for r in purchases:
        tax = _tax_component_paise(r["amount_paise"], r["gst_rate_bp"])
        if not r.get("invoice_no"):
            out.append(Finding("itc_no_invoice_no", "warn",
                               f"Purchase from {r.get('counterparty') or 'unknown'} ({_rupees(r['amount_paise'])}) has no invoice "
                               f"number, so its credit of {_rupees(tax)} cannot be claimed safely.", [r["id"]], REF_ITC_INVOICE))
        elif not r.get("counterparty_gstin"):
            out.append(Finding("itc_no_gstin", "warn",
                               f"Purchase from {r.get('counterparty') or 'unknown'} has no supplier GSTIN, so the credit of "
                               f"{_rupees(tax)} cannot be matched.", [r["id"]], REF_ITC_INVOICE))

    # reconciliation with GSTR-2B (only when a file is loaded)
    if gstr2b:
        idx = {((g.get("supplier_gstin") or "").lower(), (g["invoice_no"] or "").lower()): g for g in gstr2b}
        used: set[tuple] = set()
        for r in purchases:
            if not (r.get("invoice_no") and r.get("counterparty_gstin")):
                continue
            key = (r["counterparty_gstin"].lower(), r["invoice_no"].lower())
            tax = _tax_component_paise(r["amount_paise"], r["gst_rate_bp"])
            g = idx.get(key)
            if g is None:
                out.append(Finding("itc_not_in_2b", "critical",
                                   f"Invoice {r['invoice_no']} from {r.get('counterparty') or 'supplier'} is not in GSTR-2B, "
                                   f"so credit of {_rupees(tax)} is at risk until the supplier files.", [r["id"]], REF_ITC_2B))
                continue
            used.add(key)
            if abs(g["tax_paise"] - tax) > 100:
                out.append(Finding("itc_amount_mismatch", "warn",
                                   f"Invoice {r['invoice_no']}: your books show tax {_rupees(tax)} but GSTR-2B shows "
                                   f"{_rupees(g['tax_paise'])}.", [r["id"]], REF_ITC_2B))
        missing = [g for k, g in idx.items() if k not in used]
        if missing:
            total = sum(g["tax_paise"] for g in missing)
            out.append(Finding("in_2b_not_in_books", "info",
                               f"{len(missing)} GSTR-2B invoice(s) worth {_rupees(total)} of tax are not in your books. "
                               "You may have missed bills.", []))
    elif purchases:
        out.append(Finding("no_2b_loaded", "info",
                           "No GSTR-2B file is loaded, so purchase credits could not be matched against what suppliers filed."))

    # one category sold at several rates
    rates: dict[str, set] = defaultdict(set)
    ids: dict[str, list[int]] = defaultdict(list)
    for r in live:
        if r["direction"] == "in" and r.get("gst_rate_bp") is not None:
            rates[r["category"]].add(r["gst_rate_bp"]); ids[r["category"]].append(r["id"])
    for cat, rs in rates.items():
        if len(rs) > 1:
            out.append(Finding("rate_inconsistency", "warn",
                               f"Sales in '{cat}' were charged at different GST rates ({', '.join(f'{x / 100:g}%' for x in sorted(rs))}). "
                               "One of them is probably wrong.", ids[cat]))

    future = [r["id"] for r in rows if r["entry_date"] > today]
    if future:
        out.append(Finding("future_dated", "critical", f"{len(future)} entr{'y is' if len(future) == 1 else 'ies are'} dated in the future.", future))

    for direction, label in (("in", "sale"), ("out", "purchase")):
        amts = [r["amount_paise"] for r in live if r["direction"] == direction]
        if len(amts) >= 5:
            med = statistics.median(amts)
            big = [r for r in live if r["direction"] == direction and med > 0 and r["amount_paise"] > 5 * med]
            if big:
                out.append(Finding("outlier_amount", "info",
                                   f"{len(big)} {label}(s) are more than five times the usual size (typical {_rupees(int(med))}). Please double-check.",
                                   [r["id"] for r in big]))
    return out


class Auditor:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def load(self, bid: int, start: date, end: date) -> tuple[list[dict], list[dict]]:
        cur = self.conn.execute(
            """SELECT id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp,
                      needs_review, invoice_no, counterparty_gstin
               FROM ledger_entries WHERE business_id=%s AND entry_date BETWEEN %s AND %s ORDER BY id""",
            (bid, start, end))
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur = self.conn.execute(
            "SELECT supplier_gstin, supplier_name, invoice_no, invoice_date, taxable_paise, tax_paise "
            "FROM gstr2b_lines WHERE business_id=%s AND invoice_date BETWEEN %s AND %s",
            (bid, start, end))
        cols = [c.name for c in cur.description]
        return rows, [dict(zip(cols, r)) for r in cur.fetchall()]

    def run(self, bid: int, start: date, end: date, task_id: Optional[int] = None,
            today: Optional[date] = None) -> list[Finding]:
        rows, b2 = self.load(bid, start, end)
        found = audit_rows(rows, b2, today or date.today())
        if task_id is not None:
            self.conn.execute("DELETE FROM findings WHERE task_id=%s AND status='open'", (task_id,))
        for f in found:
            self.conn.execute(
                "INSERT INTO findings (business_id, task_id, rule, severity, entry_ids, message, rule_ref) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (bid, task_id, f.rule, f.severity, f.entry_ids, f.message, f.rule_ref))
        self.conn.commit()
        return found
