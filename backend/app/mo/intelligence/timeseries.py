"""
Forecasting and anomaly detection. Classical statistics, deterministic, stdlib only.

These are honest baselines: Holt's linear trend (optionally with an additive seasonal
component) and robust outlier tests. They are not neural models and the results say so.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Optional

MAX_POINTS = 10_000
MAX_HORIZON = 500


def clean_series(series: Any, *, minimum: int) -> list[float]:
    if not isinstance(series, list) or not series:
        raise ValueError("series must be a non-empty list of numbers")
    if len(series) > MAX_POINTS:
        raise ValueError(f"series is limited to {MAX_POINTS} points")
    out = []
    for v in series:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("series must contain only finite numbers")
        out.append(float(v))
    if len(out) < minimum:
        raise ValueError(f"at least {minimum} points are required")
    return out


def _holt_fit(y: list[float], alpha: float, beta: float) -> tuple[float, float, list[float]]:
    level, trend = y[0], y[1] - y[0]
    errors = []
    for v in y[1:]:
        pred = level + trend
        errors.append(v - pred)
        new_level = alpha * v + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        level = new_level
    return level, trend, errors


def forecast(series: Any, horizon: int = 6, season: int = 0) -> dict[str, Any]:
    y = clean_series(series, minimum=4)
    if not isinstance(horizon, int) or not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"horizon must be an integer between 1 and {MAX_HORIZON}")
    if not isinstance(season, int) or season < 0 or season == 1:
        raise ValueError("season must be 0 (none) or an integer >= 2")
    seasonal: Optional[list[float]] = None
    work = y
    if season:
        if len(y) < 2 * season:
            raise ValueError(f"a season of {season} needs at least {2 * season} points")
        # Centred moving average: a plain window for odd seasons, a 2xm window (half weight on
        # both ends) for even ones, so the trend estimate carries no seasonal component.
        r = season // 2
        trend_est: list[Optional[float]] = [None] * len(y)
        for i in range(r, len(y) - r):
            window = y[i - r:i + r + 1]
            if season % 2:
                trend_est[i] = statistics.fmean(window)
            else:
                trend_est[i] = (sum(window) - 0.5 * (window[0] + window[-1])) / season
        buckets: list[list[float]] = [[] for _ in range(season)]
        for i, t in enumerate(trend_est):
            if t is not None:
                buckets[i % season].append(y[i] - t)
        idx = [statistics.fmean(b) if b else 0.0 for b in buckets]
        mean_idx = statistics.fmean(idx)
        seasonal = [v - mean_idx for v in idx]
        work = [v - seasonal[i % season] for i, v in enumerate(y)]

    best = None
    grid = [i / 10 for i in range(1, 10)]
    for a in grid:
        for b in grid:
            level, trend, errs = _holt_fit(work, a, b)
            sse = sum(e * e for e in errs)
            if best is None or sse < best[0]:
                best = (sse, a, b, level, trend, errs)
    _, alpha, beta, level, trend, errs = best  # type: ignore[misc]
    sd = math.sqrt(sum(e * e for e in errs) / max(1, len(errs) - 2))
    pts, lo, hi = [], [], []
    for h in range(1, horizon + 1):
        v = level + h * trend + (seasonal[(len(y) + h - 1) % season] if seasonal else 0.0)
        half_width = 1.96 * sd * math.sqrt(h)
        pts.append(round(v, 6)); lo.append(round(v - half_width, 6)); hi.append(round(v + half_width, 6))
    pairs = [(abs(e), abs(v)) for e, v in zip(errs, work[1:]) if v != 0]
    mape = round(100 * statistics.fmean(a / b for a, b in pairs), 3) if pairs else None
    return {"method": "holt-linear" + ("+additive-seasonal" if seasonal else ""),
            "model_class": "classical-statistical (not a neural model)",
            "forecast": pts, "lower_95": lo, "upper_95": hi, "alpha": alpha, "beta": beta,
            "residual_sd": round(sd, 6), "in_sample_mape_pct": mape, "n": len(y), "season": season or None}


def anomalies(series: Any, method: str = "mad", threshold: Optional[float] = None) -> dict[str, Any]:
    y = clean_series(series, minimum=5)
    if method not in ("zscore", "mad", "iqr"):
        raise ValueError("method must be one of zscore, mad, iqr")
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold <= 0):
        raise ValueError("threshold must be a positive number")
    found = []
    if method == "zscore":
        thr = threshold or 3.0
        mu, sd = statistics.fmean(y), statistics.pstdev(y)
        stats = {"mean": mu, "stdev": sd, "threshold": thr}
        if sd > 0:
            found = [(i, (v - mu) / sd) for i, v in enumerate(y) if abs((v - mu) / sd) > thr]
    elif method == "mad":
        thr = threshold or 3.5
        med = statistics.median(y)
        mad = statistics.median(abs(v - med) for v in y)
        stats = {"median": med, "mad": mad, "threshold": thr}
        if mad > 0:
            scale = 0.6745 / mad
        else:
            mean_ad = statistics.fmean(abs(v - med) for v in y)
            scale = 1 / (1.253314 * mean_ad) if mean_ad > 0 else 0
            stats["fallback"] = "mean absolute deviation (MAD was 0)"
        if scale:
            found = [(i, (v - med) * scale) for i, v in enumerate(y) if abs((v - med) * scale) > thr]
    else:
        k = threshold or 1.5
        qs = statistics.quantiles(y, n=4, method="inclusive")
        q1, q3 = qs[0], qs[2]
        iqr = q3 - q1
        lo, hi = q1 - k * iqr, q3 + k * iqr
        stats = {"q1": q1, "q3": q3, "iqr": iqr, "lower_fence": lo, "upper_fence": hi, "k": k}
        found = [(i, (v - q1) / iqr if v < q1 and iqr else (v - q3) / iqr if iqr else 0.0)
                 for i, v in enumerate(y) if v < lo or v > hi]
    return {"method": method, "stats": stats, "n": len(y),
            "anomalies": [{"index": i, "value": y[i], "score": round(s, 4)} for i, s in found]}
