"""
Monthly series built from the ledger, in code. This is the only numeric input the Math agent's formulas see.

Rupee figures are floats here (analysis only). Nothing computed here feeds a GST return or a loan figure.
Each series carries a unit so formulas can be unit-checked: rupees, count.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

import numpy as np

R = (("rupees", 1),)
C = (("count", 1),)

UNITS = {
    "sales": R, "purchases": R, "gross_profit": R, "output_tax": R, "input_tax": R,
    "net_cash": R, "sales_count": C, "purchase_count": C, "avg_sale": R,
}

DESCRIPTIONS = {
    "sales": "taxable sales in the month", "purchases": "taxable purchases in the month",
    "gross_profit": "sales minus purchases", "output_tax": "GST charged on sales",
    "input_tax": "GST paid on purchases", "net_cash": "money in minus money out (tax-inclusive)",
    "sales_count": "number of sales entries", "purchase_count": "number of purchase entries",
    "avg_sale": "average sale value",
}


def _tax(gross: int, rate_bp: int) -> int:
    return 0 if rate_bp <= 0 else round(gross * rate_bp / (10000 + rate_bp))


def month_key(d: date) -> tuple[int, int]:
    return d.year, d.month


def months_between(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + (m == 12), (m % 12) + 1)
    return out


def series_from_rows(rows: Iterable[dict], end_month: tuple[int, int], n_months: int = 12) -> tuple[list[tuple[int, int]], dict]:
    """rows: dicts with entry_date, direction, amount_paise, gst_rate_bp, needs_review. Returns (months, series)."""
    y, m = end_month
    ms = []
    yy, mm = y, m
    for _ in range(n_months):
        ms.append((yy, mm))
        yy, mm = (yy - 1, 12) if mm == 1 else (yy, mm - 1)
    ms.reverse()
    idx = {k: i for i, k in enumerate(ms)}
    z = lambda: np.zeros(len(ms))
    s = {k: z() for k in UNITS}
    for r in rows:
        if r.get("needs_review"):
            continue
        i = idx.get(month_key(r["entry_date"]))
        if i is None:
            continue
        gross = int(r["amount_paise"]); tax = _tax(gross, r.get("gst_rate_bp") or 0)
        if r["direction"] == "in":
            s["sales"][i] += (gross - tax) / 100; s["output_tax"][i] += tax / 100
            s["sales_count"][i] += 1; s["net_cash"][i] += gross / 100
        else:
            s["purchases"][i] += (gross - tax) / 100; s["input_tax"][i] += tax / 100
            s["purchase_count"][i] += 1; s["net_cash"][i] -= gross / 100
    s["gross_profit"] = s["sales"] - s["purchases"]
    with np.errstate(divide="ignore", invalid="ignore"):
        s["avg_sale"] = np.where(s["sales_count"] > 0, s["sales"] / np.where(s["sales_count"] == 0, 1, s["sales_count"]), np.nan)
    return ms, s


def trim_leading_empty(months, series):
    """Drop months before the first month that has any entry, so a new business is not padded with zeros."""
    active = [i for i in range(len(months)) if series["sales_count"][i] + series["purchase_count"][i] > 0]
    if not active:
        return months[:0], {k: v[:0] for k, v in series.items()}
    a = active[0]
    return months[a:], {k: v[a:] for k, v in series.items()}


def load(conn, bid: int, end_month: tuple[int, int], n_months: int = 12):
    cur = conn.execute(
        "SELECT entry_date, direction, amount_paise, gst_rate_bp, needs_review FROM ledger_entries WHERE business_id=%s", (bid,))
    cols = [c.name for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return trim_leading_empty(*series_from_rows(rows, end_month, n_months))
