"""Summaries of the scored rows: windows, headline errors, ranking, calibration, the gate dry
run and the weakest groups (brief section 7). Pure over the scored frame."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from backtest.xp_metrics import (
    beats_share,
    bin_table,
    errors,
    gameweek_mae,
    spearman_by_position,
    top_n_hits,
)

BENCH = "ep_next"


def windows(df: pd.DataFrame, early: tuple[int, int],
            late_gws: set[tuple[str, int]]) -> dict[str, pd.DataFrame]:
    """The scored rows split for reporting: all, early season and the rest, and by whether
    the GW g-1 snapshot was late (`late_gws` holds (season, target gameweek))."""
    lo, hi = early
    is_early = df.gw.between(lo, hi)
    is_late = pd.Series([(s, g) in late_gws for s, g in zip(df.season, df.gw, strict=True)],
                        index=df.index, dtype=bool)
    return {"all": df, f"GW{lo}-{hi}": df[is_early], f"GW{hi + 1}+": df[~is_early],
            "pre-deadline snapshots": df[~is_late], "late snapshots": df[is_late]}


def _per_gw(df: pd.DataFrame, preds: Sequence[str]) -> pd.DataFrame:
    """Gameweek MAEs, keyed by (season, gw) so two seasons' gameweeks stay apart."""
    keyed = df.assign(gw=list(zip(df.season, df.gw, strict=True)))
    return gameweek_mae(keyed, preds)


def headline(df: pd.DataFrame, preds: Sequence[str]) -> pd.DataFrame:
    """MAE, RMSE, rows, gameweeks and the share of gameweeks beating `ep_next`."""
    out = errors(df, preds)
    per = _per_gw(df, preds)
    out["gameweeks"] = len(per)
    out["beats_ep_next"] = [np.nan if p == BENCH else beats_share(per, p, BENCH) for p in preds]
    return out


def ranking(df: pd.DataFrame, pred: str, top_n: int) -> tuple[pd.DataFrame, float]:
    """Spearman per position (over gameweeks) and the mean top-N hit rate."""
    keyed = df.assign(gw=list(zip(df.season, df.gw, strict=True)))
    _, summary = spearman_by_position(keyed, pred)
    return summary, float(top_n_hits(keyed, pred, top_n).mean())


def gate_dry_run(df: pd.DataFrame, pred: str, gate: dict, edges: Sequence[float],
                 leakage_ok: bool) -> dict:
    """The acceptance gate's criteria for `pred` on these rows (brief section 7): MAE below
    `ep_next`'s, at least `beat_share` of gameweeks won, every calibration bin with at least
    `calibration_min_count` rows within `calibration_tolerance`, and every leakage check
    passed. A dry run: the gate itself is decided only on the holdout."""
    err = errors(df, [pred, BENCH]).set_index("predictor").mae
    share = beats_share(_per_gw(df, [pred, BENCH]), pred, BENCH)
    cal = bin_table(df[pred], df.points, edges)
    big = cal[cal["count"] >= int(gate["calibration_min_count"])]
    gap = big["diff"].abs().round(int(gate["compare_decimals"]))
    bad = big[gap > float(gate["calibration_tolerance"])]
    out = {"mae": float(err[pred]), "mae_ep_next": float(err[BENCH]),
           "mae_below_ep_next": bool(err[pred] < err[BENCH]), "beats_share": share,
           "share_ok": bool(share >= float(gate["beat_share"])),
           "calibration_ok": bad.empty, "calibration_failed_bins": bad.bin.tolist(),
           "leakage_ok": leakage_ok}
    out["passed"] = all(out[k] for k in ("mae_below_ep_next", "share_ok", "calibration_ok",
                                         "leakage_ok"))
    return out


def _bands(values: pd.Series, edges: Sequence[int], label: str) -> pd.Series:
    """Band labels: `price` bands in £m from tenths, `minutes` bands in minutes."""
    idx = np.clip(np.searchsorted(np.asarray(edges), values.to_numpy(), side="right") - 1,
                  0, None)
    names = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] - 1 if i + 1 < len(edges) else None
        if label == "price":
            names.append(f"£{lo / 10:.1f}m+" if hi is None else f"£{lo / 10:.1f}-{hi / 10:.1f}m")
        else:
            names.append(f"{lo}+" if hi is None else (str(lo) if hi == lo else f"{lo}-{hi}"))
    return pd.Series([names[i] for i in idx], index=values.index)


def weakest_groups(df: pd.DataFrame, pred: str, w: dict) -> pd.DataFrame:
    """The `top_n` groups by position, price band and minutes band (FPL minutes over the
    last `minutes_window` club-fixture gameweeks) with the largest MAE of `pred`, among
    groups of at least `min_rows` rows; `ep_next`'s MAE on the same rows alongside."""
    dims = {"position": df.position,
            "price band": _bands(df.price_tenths, w["price_edges_tenths"], "price"),
            "minutes band": _bands(df.recent_minutes, w["minutes_edges"], "minutes")}
    err = (df[pred] - df.points).abs()
    bench = (df[BENCH] - df.points).abs()
    rows = []
    for order, (dim, groups) in enumerate(dims.items()):
        for group, idx in groups.groupby(groups).groups.items():
            if len(idx) >= int(w["min_rows"]):
                rows.append({"dimension": dim, "group": group, "n": len(idx),
                             "mae": float(err[idx].mean()),
                             "mae_ep_next": float(bench[idx].mean()), "_o": order})
    out = pd.DataFrame(rows, columns=["dimension", "group", "n", "mae", "mae_ep_next", "_o"])
    out = out.sort_values(["mae", "_o", "group"], ascending=[False, True, True], kind="stable")
    return out.head(int(w["top_n"])).drop(columns="_o").reset_index(drop=True)
