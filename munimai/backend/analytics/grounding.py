"""
Number grounding: an insight may only quote numbers the code actually computed.

`ungrounded_numbers(text, allowed)` returns every number in `text` that does not match something in
`allowed` (within rounding). The Verifier blocks an insight if this list is not empty, so a model cannot
slip in an invented figure.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(\s*(?:%|(?:percent|lakh|crore|k)\b))?", re.I)
_SMALL_OK = re.compile(r"^\s*(?:month|months|day|days|week|weeks|quarter|formula|formulas|candidate|candidates)\b", re.I)


def _close(x: float, y: float) -> bool:
    if y == 0:
        return abs(x) < 0.005
    return abs(x - y) <= max(0.051, 0.006 * abs(y))


def numbers_in(text: str) -> list[tuple[float, str, bool]]:
    """(value, shown, is_percent) for every number in the text."""
    out = []
    for m in _NUM.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        tail = text[m.end():m.end() + 14]
        mult = (m.group(2) or "").strip().lower()
        pct = mult in ("%", "percent")
        if mult == "lakh":
            v *= 1e5
        elif mult == "crore":
            v *= 1e7
        elif mult == "k":
            v *= 1e3
        if 2000 <= v <= 2100 and float(raw) == v and not mult:       # a year
            continue
        if v <= 12 and float(raw) == v and not mult and _SMALL_OK.match(tail):    # "3 months"
            continue
        out.append((v, m.group(0).strip(), pct))
    return out


def ungrounded_numbers(text: str, allowed: list[float]) -> list[str]:
    """A plain number must match a computed value. A percentage may match a computed ratio times 100,
    so "0.499" can be written "49.9%" but never "49.9 rupees"."""
    bad = []
    for v, shown, pct in numbers_in(text):
        ok = any(_close(v, a) or _close(v, abs(a)) or (pct and _close(v, a * 100)) for a in allowed)
        if not ok:
            bad.append(shown)
    return bad
