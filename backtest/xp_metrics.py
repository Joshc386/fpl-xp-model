"""Pure metrics for the xP backtest (brief section 7): no data access, no model calls.

Every function takes the scored rows (one per player per target gameweek) or plain arrays.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from backtest.elo_metrics import spearman


def errors(df: pd.DataFrame, preds: Sequence[str], actual: str = "points") -> pd.DataFrame:
    """Rows, MAE and RMSE of each predictor column against `actual`, over every row."""
    rows = []
    for p in preds:
        e = df[p].to_numpy(dtype="float64") - df[actual].to_numpy(dtype="float64")
        rows.append({"predictor": p, "n": int(len(e)),
                     "mae": float(np.abs(e).mean()) if len(e) else math.nan,
                     "rmse": float(np.sqrt((e ** 2).mean())) if len(e) else math.nan})
    return pd.DataFrame(rows)


def gameweek_mae(df: pd.DataFrame, preds: Sequence[str], actual: str = "points") -> pd.DataFrame:
    """MAE of each predictor in each gameweek (index `gw`, one column per predictor)."""
    err = pd.DataFrame({p: (df[p] - df[actual]).abs() for p in preds}).assign(gw=df.gw)
    return err.groupby("gw")[list(preds)].mean()


def beats_share(per_gw: pd.DataFrame, pred: str, bench: str) -> float:
    """Share of gameweeks in which `pred`'s MAE is strictly below `bench`'s (a tie loses)."""
    if per_gw.empty:
        return math.nan
    return float((per_gw[pred] < per_gw[bench]).mean())


def spearman_by_position(df: pd.DataFrame, pred: str,
                         actual: str = "points") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Spearman of `pred` against `actual` per position per gameweek, and per position.

    A group whose predictions or actuals are all equal (or with fewer than 2 rows) has no
    defined correlation: it is NaN in the first frame and counted as `undefined` in the
    second, whose `mean`, `median` and `min` are over the defined gameweeks.
    """
    rows = []
    for (gw, pos), g in df.groupby(["gw", "position"], sort=True):
        flat = g[pred].nunique() < 2 or g[actual].nunique() < 2
        rows.append({"gw": gw, "position": pos, "n": len(g),
                     "rho": math.nan if flat else spearman(g[pred], g[actual])})
    per = pd.DataFrame(rows, columns=["gw", "position", "n", "rho"])
    summary = per.groupby("position").rho.agg(
        mean="mean", median="median", min="min", gameweeks="count",
        undefined=lambda r: int(r.isna().sum())).reset_index()
    return per, summary


def top_n_hits(df: pd.DataFrame, pred: str, n: int, actual: str = "points") -> pd.Series:
    """Per gameweek, the share of the predicted top `n` who finish in the actual top `n`.

    Predicted top `n`: the first `n` by prediction, ties broken by lower `player_id`. Actual
    top `n`: every player scoring at least the `n`-th highest actual score, so ties at the cut
    all count. Indexed by `gw`.
    """
    out = {}
    for gw, g in df.groupby("gw", sort=True):
        picked = g.sort_values([pred, "player_id"], ascending=[False, True]).head(n)
        cut = g[actual].nlargest(n).min()
        out[gw] = int((picked[actual] >= cut).sum()) / n
    return pd.Series(out, name=pred, dtype="float64")


def _labels(edges: Sequence[float]) -> list[str]:
    inner = [f"{lo:g}-{hi:g}" for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    return inner + [f"{edges[-1]:g}+"]


def bin_table(pred: Sequence[float], actual: Sequence[float],
              edges: Sequence[float]) -> pd.DataFrame:
    """Count, mean predicted, mean actual and their difference (actual minus predicted) in
    each bin of `pred`.

    `edges` are lower edges: a value on an edge goes in the upper bin, the last bin is open,
    and a value below the first edge goes in the first bin. Every bin is listed; an empty
    one has null means.
    """
    p, a = np.asarray(pred, dtype="float64"), np.asarray(actual, dtype="float64")
    idx = np.clip(np.searchsorted(np.asarray(edges, dtype="float64"), p, side="right") - 1,
                  0, None)
    rows = []
    for i, label in enumerate(_labels(edges)):
        hit = idx == i
        k = int(hit.sum())
        mp = float(p[hit].mean()) if k else math.nan
        ma = float(a[hit].mean()) if k else math.nan
        rows.append({"bin": label, "count": k, "mean_pred": mp, "mean_actual": ma,
                     "diff": ma - mp})
    return pd.DataFrame(rows)


def brier(p: Sequence[float], y: Sequence[float]) -> float:
    """Mean of (probability - outcome) squared; NaN with no rows. Raises `ValueError` for a
    probability outside [0, 1]."""
    pa, ya = np.asarray(p, dtype="float64"), np.asarray(y, dtype="float64")
    if len(pa) == 0:
        return math.nan
    if ((pa < 0) | (pa > 1) | np.isnan(pa)).any():
        raise ValueError("every probability must be in [0, 1]")
    return float(((pa - ya) ** 2).mean())
