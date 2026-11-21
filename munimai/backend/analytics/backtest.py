"""
Does a formula actually help, or did it just get lucky? Decided here, by code, never by the model.

Predictive formula: a rolling-origin backtest. For each test month t we use ONLY data up to t. The
formula's value at t is turned into a forecast of the target at t+1 by a simple straight-line fit on the
earlier months (so the formula must carry real signal), and compared with two honest baselines:
"same as last month" and "average of the last three months". It passes only if it beats the best baseline
by a margin that grows with the number of candidates tried (a guard against picking winners by luck).

Descriptive formula: it only has to be finite and reproducible, and is never called predictive.
With fewer than MIN_MONTHS of history nothing is validated; results are labelled indicative.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

from .safe_expr import Compiled

MIN_MONTHS = 6
MIN_TRAIN = 3
BASE_MARGIN = 0.10


@dataclass
class Evidence:
    kind: str                    # predictive | descriptive
    status: str                  # validated | rejected | indicative | descriptive
    reason: str
    n_months: int
    test_points: int = 0
    mae_model: Optional[float] = None
    mae_naive: Optional[float] = None
    mae_ma3: Optional[float] = None
    improvement: Optional[float] = None
    required: Optional[float] = None
    latest_value: Optional[float] = None
    mae_trend: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in asdict(self).items()}


def _finite_latest(vals: np.ndarray) -> Optional[float]:
    v = np.asarray(vals, dtype=float).ravel()
    v = v[np.isfinite(v)]
    return float(v[-1]) if len(v) else None


def evaluate_descriptive(f: Compiled, series: dict, n: int) -> Evidence:
    vals = np.atleast_1d(f.evaluate(series))
    share = float(np.mean(np.isfinite(vals))) if len(vals) else 0.0
    latest = _finite_latest(vals)
    if share < 0.6 or latest is None:
        return Evidence("descriptive", "rejected", "too many undefined months (division by zero or missing data)", n, latest_value=latest)
    fin = vals[np.isfinite(vals)]
    if len(fin) >= 3 and float(np.std(fin)) < 1e-9:
        return Evidence("descriptive", "rejected", "constant across months, so it tells you nothing", n, latest_value=latest)
    if np.nanmax(np.abs(fin)) > 1e12:
        return Evidence("descriptive", "rejected", "values are unbounded", n, latest_value=latest)
    status = "descriptive" if n >= MIN_MONTHS else "indicative"
    why = "computed from your books; not claimed to predict anything" + ("" if n >= MIN_MONTHS else f" (only {n} months of data)")
    return Evidence("descriptive", status, why, n, latest_value=latest)


def evaluate_predictive(f: Compiled, series: dict, target: str, n: int, n_candidates: int = 1) -> Evidence:
    if target not in series:
        return Evidence("predictive", "rejected", f"unknown target '{target}'", n)
    if n < MIN_MONTHS:
        return Evidence("predictive", "indicative", f"only {n} months of data; at least {MIN_MONTHS} are needed to test a prediction", n,
                        latest_value=_finite_latest(f.evaluate(series)))
    y = np.asarray(series[target], dtype=float)
    # formula value at month t computed from data up to t only (truncate, then take the last value)
    feats = []
    for t in range(n):
        trunc = {k: np.asarray(v, dtype=float)[:t + 1] for k, v in series.items()}
        v = np.atleast_1d(f.evaluate(trunc))
        feats.append(float(v[-1]) if len(v) and np.isfinite(v[-1]) else np.nan)
    feats = np.array(feats)
    errs_m, errs_n, errs_a, errs_t = [], [], [], []
    for t in range(MIN_TRAIN, n - 1):
        xs, ys = feats[:t], y[1:t + 1]                      # pairs (feature at s, target at s+1) for s < t
        ok = np.isfinite(xs) & np.isfinite(ys)
        if ok.sum() < MIN_TRAIN or not np.isfinite(feats[t]):
            continue
        xs, ys = xs[ok], ys[ok]
        if np.ptp(xs) < 1e-12:
            pred = float(np.mean(ys))
        else:
            slope, icpt = np.polyfit(xs, ys, 1)
            pred = float(slope * feats[t] + icpt)
        truth = y[t + 1]
        errs_m.append(abs(pred - truth))
        errs_n.append(abs(y[t] - truth))
        errs_a.append(abs(float(np.mean(y[max(0, t - 2):t + 1])) - truth))
        # trend baseline: a straight line through the target's own history. Anything that only rides a rising
        # (or falling) trend cannot beat this, which is what stops two trending series looking "predictive".
        idx, yy = np.arange(t + 1), y[:t + 1]
        okt = np.isfinite(yy)
        sl, ic = np.polyfit(idx[okt], yy[okt], 1) if okt.sum() >= 2 else (0.0, float(np.nanmean(yy)))
        errs_t.append(abs(float(sl * (t + 1) + ic) - truth))
    pts = len(errs_m)
    latest = _finite_latest(feats)
    if pts < 3:
        return Evidence("predictive", "indicative", "too few testable months to judge", n, pts, latest_value=latest)
    mm, mn, ma, mt = (float(np.mean(e)) for e in (errs_m, errs_n, errs_a, errs_t))
    base = min(mn, ma, mt)
    improvement = (base - mm) / base if base > 0 else 0.0
    required = min(0.30, BASE_MARGIN + 0.02 * max(0, n_candidates - 1))
    if improvement >= required:
        return Evidence("predictive", "validated", f"beat the best simple baseline (last month, 3-month average, trend line) by {improvement:.0%}; needed {required:.0%}",
                        n, pts, mm, mn, ma, improvement, required, latest, mae_trend=mt)
    return Evidence("predictive", "rejected", f"did not beat the simple baselines (last month, 3-month average, trend line) enough: {improvement:.0%} vs needed {required:.0%}",
                    n, pts, mm, mn, ma, improvement, required, latest, mae_trend=mt)
