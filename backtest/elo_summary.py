"""Summaries, weakest areas and the verdict of the Elo component check (pure, frames in)."""

from __future__ import annotations

import pandas as pd

from backtest.elo_metrics import calibration, calibration_ok, gap_summary, step_edges

# The criteria the verdict needs, in report order (brief section 7, Elo component check).
CRITERIA = ["ratings", "goals", "clean_sheets", "log_loss", "perturbation",
            "planted_leak_caught", "copy_reached", "within_gameweek", "read_stability",
            "refit"]


# A reporting group's key: (scope, season). Scope is "pooled" (every season from
# `pass_from_gw`; the only group with pass marks), "late" (one season from it) or "early"
# (one season before it).
GroupKey = tuple[str, str | None]
POOLED: GroupKey = ("pooled", None)


def split_groups(df: pd.DataFrame, s: dict) -> dict[GroupKey, pd.DataFrame]:
    """The scored team-fixtures by reporting group, pooled first, then late, then early."""
    cut = int(s["pass_from_gw"])
    seasons = [x["id"] for x in s["seasons"]]
    out: dict[GroupKey, pd.DataFrame] = {POOLED: df[df.gw >= cut]}
    out |= {("late", x): df[(df.season == x) & (df.gw >= cut)] for x in seasons}
    out |= {("early", x): df[(df.season == x) & (df.gw < cut)] for x in seasons}
    return out


def group_label(key: GroupKey, s: dict) -> str:
    """A group's display name, for example "Pooled, GW6 on" or "2025-2026, GW1-5"."""
    cut = int(s["pass_from_gw"])
    scope, season = key
    if scope == "pooled":
        return f"Pooled, GW{cut} on"
    return f"{season}, GW{cut} on" if scope == "late" else f"{season}, GW1-{cut - 1}"


def group_summary(df: pd.DataFrame, s: dict) -> dict:
    """Goals and clean-sheet calibration tables and both log-losses for one group."""
    common = {"min_count": int(s["min_bin_count"]), "decimals": int(s["compare_decimals"]),
              "k": float(s["calibration_k"])}
    goals = calibration(df.lambda_for, df.goals_for, s["goals"]["bin_edges"],
                        tol=float(s["goals"]["tolerance"]), var=df.lambda_for, **common)
    cs = calibration(df.p_cs, df.clean_sheet.astype(float),
                     step_edges(float(s["clean_sheets"]["bin_width"])),
                     tol=float(s["clean_sheets"]["tolerance"]), var=df.p_cs * (1 - df.p_cs),
                     **common)
    model, base = float(df.nll_model.mean()), float(df.nll_base.mean())
    return {"n": int(len(df)), "goals": goals, "cs": cs, "nll_model": model, "nll_base": base,
            "beats_baseline": bool(model < base), "goals_ok": calibration_ok(goals),
            "cs_ok": calibration_ok(cs)}


def _mark(gw: int, s: dict) -> str:
    r = s["ratings"]
    if any(lo <= gw <= hi for lo, hi in r["pass_gameweeks"]):
        return "pass mark"
    for u in r["unscored"]:
        if u["range"][0] <= gw <= u["range"][1]:
            return f"no pass mark: {u['why']}"
    return "no pass mark: outside the configured ranges"


def ratings_table(pairs: pd.DataFrame, s: dict) -> pd.DataFrame:
    """Per gameweek: pairs, Spearman, signed and absolute mean gap, mark, and pass or not."""
    rows = []
    for gw, grp in pairs.groupby("gw", sort=True):
        mark = _mark(int(gw), s)
        stats = gap_summary(grp)
        passed = bool(stats["spearman"] >= s["ratings"]["min_spearman"]) \
            if mark == "pass mark" else None
        rows.append({"gw": int(gw), **stats, "mark": mark, "passed": passed})
    return pd.DataFrame(rows).astype({"passed": "object"})


def verdict(met: dict[str, bool]) -> tuple[bool, list[str]]:
    """PASS only if every criterion in `CRITERIA` is met; returns the ones missed."""
    missed = [c for c in CRITERIA if not met[c]]
    return not missed, missed


def weakest_clubs(df: pd.DataFrame, pred: str, actual: str, top_n: int) -> pd.DataFrame:
    """Clubs with the largest |mean actual - mean predicted|; ties go to more rows first."""
    g = df.assign(_err=df[actual] - df[pred]).groupby("team_name").agg(
        count=("_err", "size"), mean_pred=(pred, "mean"), mean_actual=(actual, "mean"),
        diff=("_err", "mean"))
    g = g.assign(_abs=g["diff"].abs()).sort_values(["_abs", "count"], ascending=[False, False])
    return g.drop(columns="_abs").head(top_n).reset_index()


def weakest_gameweeks(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Gameweeks where the model's mean log-loss most exceeds the baseline's."""
    g = df.assign(_x=df.nll_model - df.nll_base).groupby(["season", "gw"]).agg(
        count=("_x", "size"), nll_model=("nll_model", "mean"), nll_base=("nll_base", "mean"),
        excess=("_x", "mean"))
    return g.sort_values("excess", ascending=False).head(top_n).reset_index()


def weakest_bins(summary: dict, top_n: int) -> pd.DataFrame:
    """The goals and clean-sheet bins furthest from calibration, among non-empty bins."""
    parts = [summary[k].assign(kind=name) for k, name in (("goals", "goals"),
                                                          ("cs", "clean sheet"))]
    b = pd.concat(parts, ignore_index=True)
    b = b[b["count"] > 0].assign(_abs=lambda x: x["diff"].abs())
    return b.sort_values("_abs", ascending=False).head(top_n).drop(columns="_abs")
