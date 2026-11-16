"""Tune the Elo goals model's priors: `python -m fpl.models.goals_tune`.

A walk-forward search over one shared prior sd (`goals_model.tuning` in config/model.yaml) on
the tuning season only (the Elo run's first season, 2025/26; never a later season, the
holdout). A grid value sd sets `prior_sd_home` = sd and `prior_sd_gap` = sd per `gap_points`
rating points. Each team-fixture of a scored gameweek g is predicted once, from the fit as of
g-1 in backtest mode (the `lambda_for` that `elo_goals(season, g - 1, "backtest")` returns), and
scored by its Poisson log-loss against the goals in the read as of the last scored gameweek.
Each read is loaded once and every grid point is fitted on it. The no-prior fit (sd inf) is
logged as a reference row. It logs the curve and its minimum and writes nothing; copy the
chosen values into config/model.yaml by hand.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import time

import numpy as np
import pandas as pd

from fpl.models.elo import (
    EloSettings,
    SeasonRead,
    finished_results,
    load_history,
    model_config,
    pipeline_config,
    prem_fixtures,
)
from fpl.models.team_goals import GoalsSettings, goals_from_history

log = logging.getLogger(__name__)

KEYS = ["match_id", "team_id"]


def poisson_log_loss(goals: np.ndarray, lam: np.ndarray) -> np.ndarray:
    """-ln P(goals) under Poisson(lam), per row: lam - goals ln lam + ln goals!."""
    log_factorial = np.array([math.lgamma(y + 1.0) for y in goals], dtype="float64")
    return lam - goals * np.log(lam) + log_factorial


def grid_settings(cfg: dict) -> dict[float, GoalsSettings]:
    """The settings per shared sd, the no-prior reference row (sd inf) first.

    Each grid point goes through `GoalsSettings.from_config`, so the units guard checks it.
    """
    goals, tuning = cfg["goals_model"], cfg["goals_model"]["tuning"]
    grid = {math.inf: dataclasses.replace(GoalsSettings.from_config(cfg),
                                          prior_sd_gap=math.inf, prior_sd_home=math.inf)}
    for sd in tuning["shared_sd_grid"]:
        priors = {"prior_sd_gap": sd / tuning["gap_points"], "prior_sd_home": sd}
        grid[float(sd)] = GoalsSettings.from_config({**cfg, "goals_model": goals | priors})
    return grid


def as_of_predictions(history: list[SeasonRead], elo_s: EloSettings,
                      grid: dict[float, GoalsSettings], prem_tag: str, gw: int) -> pd.DataFrame:
    """Each grid point's `lambda_for` for the team-fixtures of `gw`, from one as-of read.

    Uses `goals_from_history`, the pure core of `elo_goals`, so the predictions are the model's.
    """
    parts = []
    for sd, s in grid.items():
        out, _ = goals_from_history(history, elo_s, s, prem_tag)
        parts.append(out.loc[out.gw == gw, [*KEYS, "lambda_for"]].assign(shared_sd=sd))
    return pd.concat(parts, ignore_index=True)


def actual_goals(read: SeasonRead, prem_tag: str, gws: list[int]) -> pd.DataFrame:
    """Each team's goals in the finished Premier League fixtures of `gws` in the read."""
    played = finished_results(prem_fixtures(read, prem_tag), read.as_of_gw)
    played = played[played.gw.isin(gws)]
    return pd.concat([
        played[["match_id", f"{side}_team_id", f"{side}_goals"]].set_axis(
            [*KEYS, "goals"], axis=1) for side in ("home", "away")
    ], ignore_index=True).astype({"team_id": "int64", "goals": "float64"})


def log_loss_curve(preds: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    """Mean Poisson log-loss per shared sd, largest sd first.

    Raises `ValueError` unless each shared sd has exactly one prediction per scored
    team-fixture and every prediction has a result.
    """
    if preds.duplicated(["shared_sd", *KEYS]).any():
        raise ValueError("a team-fixture has more than one prediction for a shared sd")
    rows = preds.merge(actual, on=KEYS, how="left", validate="many_to_one")
    if rows.goals.isna().any():
        raise ValueError(f"{rows.goals.isna().sum()} predictions have no result")
    counts = rows.groupby("shared_sd").size()
    if (counts != len(actual)).any():
        raise ValueError(f"a scored team-fixture has no prediction: {counts.to_dict()} of "
                         f"{len(actual)}")
    rows["loss"] = poisson_log_loss(rows.goals.to_numpy(), rows.lambda_for.to_numpy())
    curve = rows.groupby("shared_sd").agg(team_fixtures=("loss", "size"),
                                          log_loss=("loss", "mean"))
    return curve.sort_index(ascending=False).reset_index()


def tune(season: str, gws: list[int], cfg: dict, prem_tag: str) -> pd.DataFrame:
    """The walk-forward curve over the scored gameweeks `gws`, with each row's two priors."""
    elo_s, grid = EloSettings.from_config(cfg), grid_settings(cfg)
    preds = pd.concat([as_of_predictions(load_history(season, gw - 1, "backtest"), elo_s, grid,
                                         prem_tag, gw) for gw in gws], ignore_index=True)
    actual = actual_goals(load_history(season, gws[-1], "backtest")[-1], prem_tag, gws)
    curve = log_loss_curve(preds, actual)
    curve = curve.assign(prior_sd_gap=curve.shared_sd.map(lambda sd: grid[sd].prior_sd_gap),
                         prior_sd_home=curve.shared_sd.map(lambda sd: grid[sd].prior_sd_home))
    return curve[["shared_sd", "prior_sd_gap", "prior_sd_home", "team_fixtures", "log_loss"]]


def tuning_plan(cfg: dict, pcfg: dict) -> tuple[str, list[int]]:
    """The tuning season and its scored gameweeks.

    Refuses any season but the Elo run's first, and that one too if it is the newest or the
    current season (the holdout), before anything is read.
    """
    tuning, start = cfg["goals_model"]["tuning"], cfg["elo"]["start_season"]
    season, ids = tuning["season"], [s["id"] for s in pcfg["seasons"]]
    if season not in ids:
        raise ValueError(f"tuning season {season} must be in {ids}")
    if season != start or season in (ids[-1], pcfg["current_season"]):
        raise ValueError(f"tuning season {season} must be the Elo run's first season ({start}) "
                         f"and neither the newest nor the current season: never tune on the "
                         f"holdout")
    first, last = tuning["scored_gameweeks"]
    n_gw = int(pcfg["seasons"][ids.index(season)]["gameweeks"])
    if not 1 <= first <= last <= n_gw:
        raise ValueError(f"goals_model.tuning.scored_gameweeks must lie in 1..{n_gw}, first "
                         f"<= last, got {[first, last]}")
    return season, list(range(first, last + 1))


def _log_report(curve: pd.DataFrame, season: str, gws: list[int], cfg: dict,
                seconds: float) -> None:
    """Log the curve, its minimum over the grid, and whether config/model.yaml holds it."""
    log.info("Walk-forward Poisson log-loss per team-fixture, %s GW%d-%d, each from the fit as "
             "of the gameweek before (backtest mode); shared_sd inf is the no-prior "
             "reference:\n%s", season, gws[0], gws[-1],
             curve.to_string(index=False, formatters={"log_loss": "{:.5f}".format}))
    grid = curve[np.isfinite(curve.shared_sd)]
    best = grid.loc[grid.log_loss.idxmin()]
    g = cfg["goals_model"]
    same = (math.isclose(g["prior_sd_gap"], best.prior_sd_gap)
            and math.isclose(g["prior_sd_home"], best.prior_sd_home))
    log.info("Minimum: shared sd %s (prior_sd_gap %.6g per rating point, prior_sd_home %s), "
             "log-loss %.5f over %d team-fixtures; config/model.yaml has prior_sd_gap %s and "
             "prior_sd_home %s (%s)", best.shared_sd, best.prior_sd_gap, best.prior_sd_home,
             best.log_loss, best.team_fixtures, g["prior_sd_gap"], g["prior_sd_home"],
             "matches" if same else "DIFFERS")
    log.info("Runtime %.0f s", seconds)


def main() -> None:
    """Score the grid walk-forward on the tuning season and log the report."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    started = time.perf_counter()
    cfg, pcfg = model_config(), pipeline_config()
    season, gws = tuning_plan(cfg, pcfg)
    curve = tune(season, gws, cfg, pcfg["premier_league_tag"])
    _log_report(curve, season, gws, cfg, time.perf_counter() - started)


if __name__ == "__main__":
    main()
