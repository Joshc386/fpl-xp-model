"""Pure metrics for the Elo component check (brief section 7): no data access, no model calls."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd


def step_edges(width: float) -> list[float]:
    """Lower bin edges 0, width, 2*width ... below 1; the last bin runs to 1 inclusive."""
    n = int(round(1.0 / width))
    return [round(i * width, 10) for i in range(n)]


def _labels(edges: Sequence[float]) -> list[str]:
    inner = [f"{lo:g}-{hi:g}" for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    return inner + [f"{edges[-1]:g}+"]


def calibration(pred: Sequence[float], actual: Sequence[float], edges: Sequence[float],
                tol: float, min_count: int, decimals: int) -> pd.DataFrame:
    """Mean predicted against mean actual in each bin of `pred`.

    `edges` are lower edges; a value on an edge goes in the upper bin, and the last bin is
    open-ended. Every bin is listed, empty ones with null means. A bin is `scored` from
    `min_count` rows, and a scored bin `passed` if |mean actual - mean predicted| is at most
    `tol` after rounding to `decimals`; `passed` is null for unscored bins.
    """
    p, a = np.asarray(pred, dtype="float64"), np.asarray(actual, dtype="float64")
    idx = np.searchsorted(np.asarray(edges, dtype="float64"), p, side="right") - 1
    if (idx < 0).any():
        raise ValueError(f"a prediction is below the lowest bin edge {edges[0]}")
    rows = []
    for i, label in enumerate(_labels(edges)):
        hit = idx == i
        n = int(hit.sum())
        mp = float(p[hit].mean()) if n else math.nan
        ma = float(a[hit].mean()) if n else math.nan
        diff = ma - mp
        scored = n >= min_count
        passed = bool(round(abs(diff), decimals) <= tol) if scored else None
        rows.append({"bin": label, "count": n, "mean_pred": mp, "mean_actual": ma,
                     "diff": diff, "scored": scored, "passed": passed})
    return pd.DataFrame(rows).astype({"passed": "object"})


def calibration_ok(table: pd.DataFrame) -> bool:
    """True if every scored bin passed (vacuously true when no bin is scored)."""
    return bool(table.loc[table.scored, "passed"].all())


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman rank correlation: the Pearson correlation of average ranks (NaN below 2)."""
    if len(a) < 2:
        return math.nan
    return float(a.rank().corr(b.rank()))


def gap_summary(pairs: pd.DataFrame) -> dict[str, float]:
    """Pairs of `elo_before` and `upstream_elo`: count, Spearman, mean and mean absolute gap.

    The gap is ours minus upstream.
    """
    gap = pairs.elo_before - pairs.upstream_elo
    return {"n": int(len(pairs)), "spearman": spearman(pairs.elo_before, pairs.upstream_elo),
            "mean_gap": float(gap.mean()), "mean_abs_gap": float(gap.abs().mean())}


def poisson_nll(lam: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Poisson negative log-likelihood of each count `y` at rate `lam`."""
    lam = np.asarray(lam, dtype="float64")
    y = np.asarray(y, dtype="float64")
    if (lam <= 0).any() or np.isnan(lam).any():
        raise ValueError("every Poisson rate must be positive")
    log_fact = np.array([math.lgamma(v + 1.0) for v in y])
    return lam - y * np.log(lam) + log_fact


def league_means(pool: pd.DataFrame) -> tuple[float, float]:
    """Mean home goals and mean away goals per match over a pool of results."""
    if pool.empty:
        raise ValueError("the baseline pool is empty")
    home, away = float(pool.home_goals.mean()), float(pool.away_goals.mean())
    if home <= 0 or away <= 0:
        raise ValueError("the baseline pool has no home or no away goals")
    return home, away
