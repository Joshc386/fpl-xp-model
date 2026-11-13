"""The Elo goals model (brief section 6.2): Poisson goals on the Elo gap and home advantage.

A team's goals in a match are Poisson with
    log lambda = intercept + gap * (own elo_before - opponent's elo_before) + home * is_home,
fitted by maximum likelihood (Newton's method, numpy only) on one row per team per finished
Premier League match of this season and last, up to and including the as-of gameweek, using
our own ratings at kickoff. Future fixtures use each club's current rating. Below
`goals_model.min_matches` finished matches in the pool there is no fit: the model raises
`InsufficientSampleError` rather than invent coefficients.

It supplies `fixture_difficulty.csv` in phase 1: per team per unfinished Premier League fixture
in the next `max_horizon` gameweeks, `lambda_for`, `lambda_against` (the opponent's
`lambda_for`) and `p_cs` = exp(-`lambda_against`). `lambda_pen` comes in phase 2.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl.models.elo import (
    EloSettings,
    SeasonRead,
    load_history,
    model_config,
    pipeline_config,
    prem_fixtures,
    run_elo,
)

log = logging.getLogger(__name__)

OUT_COLUMNS = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for",
               "lambda_against", "p_cs"]


class GoalsModelError(ValueError):
    """The Elo goals model cannot be fitted or applied."""


class InsufficientSampleError(GoalsModelError):
    """The training pool holds fewer finished matches than `goals_model.min_matches`."""


@dataclass(frozen=True)
class GoalsSettings:
    """The goals model's settings (`goals_model` and `max_horizon` in config/model.yaml)."""

    pool_seasons: int
    min_matches: int
    tol: float
    max_iter: int
    max_horizon: int

    @classmethod
    def from_config(cls, cfg: dict) -> GoalsSettings:
        """The settings in the parsed config/model.yaml; `pool_seasons` must be at least 1."""
        g = cfg["goals_model"]
        pool_seasons = int(g["pool_seasons"])
        if pool_seasons < 1:
            raise ValueError(f"goals_model.pool_seasons must be at least 1, got {pool_seasons}")
        return cls(pool_seasons, int(g["min_matches"]), float(g["newton_tol"]),
                   int(g["newton_max_iter"]), int(cfg["max_horizon"]))


@dataclass(frozen=True)
class GoalsFit:
    """Fitted coefficients (gap is per rating point) and the size of the pool."""

    intercept: float
    gap: float
    home: float
    n_matches: int
    mean_goals: float

    def lam(self, gap: np.ndarray, home: np.ndarray) -> np.ndarray:
        """Expected goals for a team at rating gap `gap` (own minus opponent), home 1 or 0."""
        return np.exp(self.intercept + self.gap * np.asarray(gap, dtype="float64")
                      + self.home * np.asarray(home, dtype="float64"))


def clean_sheet_probability(lambda_against: np.ndarray) -> np.ndarray:
    """P(no goals conceded) under Poisson: exp(-lambda_against)."""
    return np.exp(-np.asarray(lambda_against, dtype="float64"))


def poisson_fit(x: np.ndarray, y: np.ndarray, tol: float, max_iter: int) -> np.ndarray:
    """Maximum-likelihood coefficients of a log-link Poisson regression, by Newton's method.

    Column 0 of `x` must be the intercept. Starts from the intercept-only solution and stops
    when every coefficient's step is below `tol`. Raises `GoalsModelError` if there are no
    goals, the design is singular, or it does not converge in `max_iter` steps.
    """
    if y.sum() <= 0:
        raise GoalsModelError("the training pool has no goals")
    beta = np.zeros(x.shape[1])
    beta[0] = np.log(y.mean())
    for _ in range(max_iter):
        mu = np.exp(x @ beta)
        try:
            step = np.linalg.solve(x.T @ (x * mu[:, None]), x.T @ (y - mu))
        except np.linalg.LinAlgError as exc:
            raise GoalsModelError(f"singular design in the Poisson fit: {exc}") from exc
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            return beta
    raise GoalsModelError(f"the Poisson fit did not converge in {max_iter} steps")


def goals_pool(matches: pd.DataFrame, seasons: Sequence[str]) -> pd.DataFrame:
    """One row per team per finished match of `seasons`: goals, gap (elo_before) and home."""
    m = matches[matches.season.isin(list(seasons))]
    gap = (m.home_elo_before - m.away_elo_before).to_numpy(dtype="float64")
    return pd.DataFrame({
        "goals": np.concatenate([m.home_goals.to_numpy(dtype="float64"),
                                 m.away_goals.to_numpy(dtype="float64")]),
        "gap": np.concatenate([gap, -gap]),
        "home": np.concatenate([np.ones(len(m)), np.zeros(len(m))]),
    })


def fit_goals_model(pool: pd.DataFrame, s: GoalsSettings) -> GoalsFit:
    """Fit the three-parameter Poisson; raise `InsufficientSampleError` below the minimum."""
    n_matches = len(pool) // 2
    if n_matches < s.min_matches:
        raise InsufficientSampleError(
            f"{n_matches} finished matches in the training pool, below goals_model.min_matches "
            f"({s.min_matches}); no Elo goals model is fitted"
        )
    x = np.column_stack([np.ones(len(pool)), pool.gap, pool.home])
    b0, b1, b2 = poisson_fit(x, pool.goals.to_numpy(dtype="float64"), s.tol, s.max_iter)
    return GoalsFit(float(b0), float(b1), float(b2), n_matches, float(pool.goals.mean()))


def fixture_difficulty(fixtures: pd.DataFrame, as_of_gw: int, horizon: int,
                       ratings: dict[int, float], fit: GoalsFit) -> pd.DataFrame:
    """Per team per fixture with `gw` in (as_of_gw, as_of_gw + horizon].

    Every such fixture is unfinished as of the read (the loader makes later fixtures schedule
    only). Its `finished` flag is not read, so a leaked later result cannot change the rows.
    """
    fut = fixtures[(fixtures.gw > as_of_gw) & (fixtures.gw <= as_of_gw + horizon)]
    rh, ra = fut.home_code.map(ratings), fut.away_code.map(ratings)
    if rh.isna().any() or ra.isna().any():
        raise GoalsModelError("a club in the horizon has no rating")
    gap = (rh - ra).to_numpy(dtype="float64")
    lam_home, lam_away = fit.lam(gap, 1.0), fit.lam(-gap, 0.0)
    sides = []
    for i, (team, opp, lam_for, lam_against) in enumerate([
        ("home_team_id", "away_team_id", lam_home, lam_away),
        ("away_team_id", "home_team_id", lam_away, lam_home),
    ]):
        sides.append(pd.DataFrame({
            "team_id": fut[team].to_numpy(dtype="int64"), "match_id": fut.match_id.to_numpy(),
            "gw": fut.gw.to_numpy(dtype="int64"), "opponent_id": fut[opp].to_numpy(dtype="int64"),
            "home": i == 0, "lambda_for": lam_for, "lambda_against": lam_against,
            "p_cs": clean_sheet_probability(lam_against),
            "_kickoff": fut.kickoff_utc.to_numpy(), "_side": i,
        }))
    out = pd.concat(sides).sort_values(["gw", "_kickoff", "match_id", "_side"])
    return out[OUT_COLUMNS].astype({"home": "bool"}).reset_index(drop=True)


def goals_from_history(history: Sequence[SeasonRead], elo_s: EloSettings, s: GoalsSettings,
                       prem_tag: str) -> tuple[pd.DataFrame, GoalsFit]:
    """The pure core: fixture difficulty for the last read in `history`, and the fit."""
    run = run_elo(history, elo_s, prem_tag)
    seasons = [read.season for read in history][-s.pool_seasons:]
    fit = fit_goals_model(goals_pool(run.matches, seasons), s)
    current = history[-1]
    out = fixture_difficulty(prem_fixtures(current, prem_tag), current.as_of_gw, s.max_horizon,
                             run.ratings, fit)
    return out, fit


def elo_goals(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """Fixture difficulty for `season`'s next `max_horizon` gameweeks after `as_of_gw`.

    `mode` goes to `load_as_of`. Returns the `fixture_difficulty.csv` rows. Raises
    `MissingSeedError` (a club with no Elo seed) or `InsufficientSampleError` (too few
    finished matches to fit).
    """
    cfg = model_config()
    out, fit = goals_from_history(load_history(season, as_of_gw, mode),
                                  EloSettings.from_config(cfg), GoalsSettings.from_config(cfg),
                                  pipeline_config()["premier_league_tag"])
    log.info("Elo goals %s as-of %d (%s): %d rows; intercept %.4f, gap %.6f/pt, home %.4f, "
             "%d matches", season, as_of_gw, mode, len(out), fit.intercept, fit.gap, fit.home,
             fit.n_matches)
    return out
