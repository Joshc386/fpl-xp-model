"""Tune the Elo settings against upstream Elo: `python -m fpl.models.elo_tune`.

A grid search over K, the home advantage and the margin power (`elo.tuning.grid` in
config/model.yaml) on the tuning season only (2025/26; never a later season, the holdout). The
objective is the mean absolute gap between our `elo_before` and upstream kickoff Elo at the
target gameweeks, where upstream is a before-match rating. Reported alongside, never tuned on:
Spearman rank correlation per gameweek, the match-result log-loss, and each club's rating after
its last match of the season against upstream's value there (ClubElo's end-of-season rating in
2025/26). It logs the results and writes nothing; copy the chosen settings into
config/model.yaml by hand.
"""

from __future__ import annotations

import itertools
import logging

import numpy as np
import pandas as pd

from fpl.features import load_as_of
from fpl.models.elo import (
    EloSettings,
    SeasonRead,
    expected_home,
    model_config,
    pipeline_config,
    play,
    prepare,
)

log = logging.getLogger(__name__)


def target_gameweeks(ranges: list[list[int]]) -> list[int]:
    """Gameweeks from inclusive [first, last] ranges."""
    return sorted({gw for first, last in ranges for gw in range(first, last + 1)})


def kickoff_sides(matches: pd.DataFrame) -> pd.DataFrame:
    """One row per team per match: gw, kickoff, team_code, our elo_before (`ours`) and
    elo_after (`after`), and upstream kickoff Elo."""
    names = ["gw", "kickoff_utc", "team_code", "ours", "after", "upstream"]
    return pd.concat([
        matches[["gw", "kickoff_utc", f"{side}_code", f"{side}_elo_before", f"{side}_elo_after",
                 f"{side}_upstream_elo"]].set_axis(names, axis=1)
        for side in ("home", "away")
    ]).sort_values(["kickoff_utc", "team_code"], ignore_index=True)


def mean_gaps(sides: pd.DataFrame, gws: list[int]) -> tuple[float, float]:
    """Mean absolute and mean signed (ours - upstream) gap over the rows of `gws`."""
    rows = sides[sides.gw.isin(gws)].dropna(subset=["upstream"])
    diff = rows.ours - rows.upstream
    return float(diff.abs().mean()), float(diff.mean())


def spearman_by_gw(sides: pd.DataFrame) -> pd.DataFrame:
    """Per gameweek: clubs, Spearman of our rating v upstream (each club's first kickoff)."""
    first = sides.dropna(subset=["upstream"]).groupby(["gw", "team_code"]).first().reset_index()
    out = [
        (gw, len(g), g.ours.rank().corr(g.upstream.rank())) for gw, g in first.groupby("gw")
    ]
    return pd.DataFrame(out, columns=["gw", "clubs", "spearman"])


def end_of_season(sides: pd.DataFrame) -> pd.Series:
    """Each club's rating after its last match against upstream's value at that match."""
    last = sides.drop_duplicates("team_code", keep="last").dropna(subset=["upstream"])
    diff = last.after - last.upstream
    return pd.Series({"clubs": len(last), "spearman": last.after.rank().corr(last.upstream.rank()),
                      "mean_signed_gap": diff.mean(), "mean_gap": diff.abs().mean()})


def result_log_loss(matches: pd.DataFrame, s: EloSettings) -> float:
    """Mean log-loss of the pre-match expected score against the result (draw = 1/2)."""
    e = np.array([expected_home(h, a, s) for h, a in
                  zip(matches.home_elo_before, matches.away_elo_before, strict=True)])
    hg, ag = matches.home_goals.to_numpy(dtype="float64"), matches.away_goals.to_numpy("float64")
    result = np.where(hg > ag, 1.0, np.where(hg == ag, 0.5, 0.0))
    return float(-(result * np.log(e) + (1 - result) * np.log(1 - e)).mean())


def grid_search(results: pd.DataFrame, seeds: dict, grid: dict, gws: list[int],
                scale: float) -> pd.DataFrame:
    """Every grid point's mean absolute gap at `gws` and log-loss, best gap first."""
    rows = []
    for k, hfa, power in itertools.product(grid["k"], grid["home_advantage"],
                                           grid["margin_power"]):
        s = EloSettings(float(k), float(hfa), float(power), scale)
        matches = play(results, seeds, s).matches
        gap, bias = mean_gaps(kickoff_sides(matches), gws)
        rows.append((k, hfa, power, gap, bias, result_log_loss(matches, s)))
    cols = ["k", "home_advantage", "margin_power", "mean_gap", "mean_signed_gap", "log_loss"]
    return pd.DataFrame(rows, columns=cols).sort_values("mean_gap", ignore_index=True)


def tune(history: list[SeasonRead], cfg: dict,
         prem_tag: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """The grid results, and the best grid point's Spearman per gameweek and end of season."""
    tuning = cfg["elo"]["tuning"]
    gws = target_gameweeks(tuning["target_gameweeks"])
    results, seeds = prepare(history, prem_tag)
    grid = grid_search(results, seeds, tuning["grid"], gws, float(cfg["elo"]["scale"]))
    best = grid.iloc[0]
    s = EloSettings(float(best.k), float(best.home_advantage), float(best.margin_power),
                    float(cfg["elo"]["scale"]))
    sides = kickoff_sides(play(results, seeds, s).matches)
    by_gw = spearman_by_gw(sides)
    return grid, by_gw.assign(target=by_gw.gw.isin(gws)), end_of_season(sides)


def _log_report(grid: pd.DataFrame, by_gw: pd.DataFrame, eos: pd.Series, cfg: dict) -> None:
    """Log the best grid points, Spearman per gameweek, the end-of-season comparison, and
    whether config/model.yaml holds the best settings."""
    tuning = cfg["elo"]["tuning"]
    best = grid.iloc[0]
    log.info("Grid: %d points. Best 10 by mean gap:\n%s", len(grid), grid.head(10).to_string())
    log.info("Best log-loss on the grid:\n%s",
             grid.sort_values("log_loss").head(3).to_string())
    log.info("Spearman by gameweek (target = tuned and checked there):\n%s", by_gw.to_string())
    checked = by_gw[by_gw.target & (by_gw.gw >= tuning["check_from_gw"])]
    worst = checked.spearman.min()
    log.info("Lowest Spearman at target gameweeks from GW%d: %.3f (flag below %.2f: %s)",
             tuning["check_from_gw"], worst, tuning["check_min_spearman"],
             worst < tuning["check_min_spearman"])
    log.info("End of season (reported only): %d clubs, Spearman %.3f, mean signed gap %.1f, "
             "mean gap %.1f", eos.clubs, eos.spearman, eos.mean_signed_gap, eos.mean_gap)
    in_config = (cfg["elo"]["k"], cfg["elo"]["home_advantage"], cfg["elo"]["margin_power"])
    chosen = (best.k, best.home_advantage, best.margin_power)
    log.info("Best: k=%s home_advantage=%s margin_power=%s; config/model.yaml has %s (%s)",
             *chosen, in_config, "matches" if tuple(map(float, chosen)) == tuple(
                 map(float, in_config)) else "DIFFERS")


def _tuning_season(cfg: dict, pcfg: dict) -> tuple[str, int]:
    """The tuning season and its gameweek count; refuse any season after the run's first."""
    season, start = cfg["elo"]["tuning"]["season"], cfg["elo"]["start_season"]
    ids = [s["id"] for s in pcfg["seasons"]]
    if season not in ids or start not in ids:
        raise ValueError(f"tuning season {season} and start season {start} must be in {ids}")
    if ids.index(season) > ids.index(start) or season == ids[-1]:
        raise ValueError(f"tuning season {season} is after the run's first season {start} or "
                         f"is the newest season: never tune on the holdout")
    return season, int(pcfg["seasons"][ids.index(season)]["gameweeks"])


def main() -> None:
    """Load the tuning season in full (backtest mode), tune, and log the report."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg, pcfg = model_config(), pipeline_config()
    season, n_gw = _tuning_season(cfg, pcfg)
    history = [SeasonRead(season, n_gw, load_as_of(season, n_gw, "backtest"))]
    _log_report(*tune(history, cfg, pcfg["premier_league_tag"]), cfg)


if __name__ == "__main__":
    main()
