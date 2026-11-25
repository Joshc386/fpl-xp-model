"""Team goals v1 (brief section 6.2): the Elo goals model, plus `lambda_pen`.

The hand-off is `team_goals`: the Elo goals model's rows (below) with `lambda_pen`, each club's
expected penalty goals per match (`models/team_penalties.py`), and `lambda_league`, the pool's
mean goals per team-match, the league average that `lambda_for` is on.

The Elo goals model is Poisson goals on the Elo gap and home advantage.

A team's goals in a match are Poisson with
    log lambda = intercept + gap * (own elo_before - opponent's elo_before) + home * is_home.
The gap and home coefficients carry zero-centred Gaussian priors (`goals_model.prior_sd_gap`,
`prior_sd_home`), which pull small pools towards league-average goals; the intercept carries
none, so the fitted total always equals the pool's. Why the priors: docs/decisions.md,
"model - Elo goals fix round".

It is fitted by penalised maximum likelihood (Newton's method, numpy only) on one row per team
per finished Premier League match of this season and last, up to and including the as-of
gameweek, using our own ratings at kickoff. Future fixtures use each club's current rating.
Below `goals_model.min_matches` finished matches in the pool there is no fit: the model raises
`InsufficientSampleError` rather than invent coefficients.

It supplies `fixture_difficulty.csv` in phase 1: per team per unfinished Premier League fixture
in the next `max_horizon` gameweeks, `lambda_for`, `lambda_against` (the opponent's
`lambda_for`) and `p_cs` = exp(-`lambda_against`).
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
from fpl.models.team_penalties import penalty_pool, penalty_prior, penalty_rates

log = logging.getLogger(__name__)

OUT_COLUMNS = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for",
               "lambda_against", "p_cs"]
TEAM_GOALS_COLUMNS = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for",
                      "lambda_against", "lambda_pen", "lambda_league", "p_cs"]


class GoalsModelError(ValueError):
    """The Elo goals model cannot be fitted or applied."""


class InsufficientSampleError(GoalsModelError):
    """The training pool holds fewer finished matches than `goals_model.min_matches`."""


@dataclass(frozen=True)
class GoalsSettings:
    """The goals model's settings (`goals_model` and `max_horizon` in config/model.yaml).

    `prior_sd_gap` is in log goals per rating point and `prior_sd_home` in log goals.
    """

    pool_seasons: int
    min_matches: int
    tol: float
    max_iter: int
    max_horizon: int
    prior_sd_gap: float
    prior_sd_home: float

    @classmethod
    def from_config(cls, cfg: dict) -> GoalsSettings:
        """The settings in the parsed config/model.yaml.

        `pool_seasons` must be at least 1 and both prior standard deviations positive.
        `prior_sd_gap` must be below `prior_sd_gap_max`: it is per rating point, and a value
        per 100 points would turn the gap prior off without any other sign.
        """
        g = cfg["goals_model"]
        pool_seasons = int(g["pool_seasons"])
        if pool_seasons < 1:
            raise ValueError(f"goals_model.pool_seasons must be at least 1, got {pool_seasons}")
        for key in ("prior_sd_gap", "prior_sd_home"):
            if not float(g[key]) > 0:
                raise ValueError(f"goals_model.{key} must be positive, got {g[key]}")
        if not float(g["prior_sd_gap"]) < float(g["prior_sd_gap_max"]):
            raise ValueError(
                f"goals_model.prior_sd_gap is per rating point (log goals per point of Elo gap) "
                f"and must be below goals_model.prior_sd_gap_max ({g['prior_sd_gap_max']}), got "
                f"{g['prior_sd_gap']}: is it a value per 100 rating points?")
        return cls(pool_seasons, int(g["min_matches"]), float(g["newton_tol"]),
                   int(g["newton_max_iter"]), int(cfg["max_horizon"]),
                   float(g["prior_sd_gap"]), float(g["prior_sd_home"]))

    @property
    def precision(self) -> np.ndarray:
        """Prior precisions of (intercept, gap, home): none on the intercept."""
        return np.array([0.0, self.prior_sd_gap**-2, self.prior_sd_home**-2])


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


def poisson_fit(x: np.ndarray, y: np.ndarray, precision: np.ndarray, tol: float,
                max_iter: int) -> np.ndarray:
    """Penalised maximum-likelihood coefficients of a log-link Poisson, by Newton's method.

    Maximises the Poisson log-likelihood minus sum(precision * beta ** 2) / 2, so each
    coefficient has a zero-centred Gaussian prior with variance 1 / precision (0: no prior).
    Column 0 of `x` must be the intercept. Starts from the intercept-only solution and stops
    when every coefficient's step is below `tol`. Raises `GoalsModelError` if there are no
    goals, the system is singular, or it does not converge in `max_iter` steps.
    """
    if y.sum() <= 0:
        raise GoalsModelError("the training pool has no goals")
    beta = np.zeros(x.shape[1])
    beta[0] = np.log(y.mean())
    for _ in range(max_iter):
        mu = np.exp(x @ beta)
        try:
            step = np.linalg.solve(x.T @ (x * mu[:, None]) + np.diag(precision),
                                   x.T @ (y - mu) - precision * beta)
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
    b0, b1, b2 = poisson_fit(x, pool.goals.to_numpy(dtype="float64"), s.precision, s.tol,
                             s.max_iter)
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


def team_goals_from_history(history: Sequence[SeasonRead], elo_s: EloSettings,
                            s: GoalsSettings, k: float, prem_tag: str) -> pd.DataFrame:
    """The pure core of `team_goals`: `goals_from_history`'s rows with two columns added.

    `lambda_pen` is each club's shrunk penalty rate over the same seasons as the goals
    model's pool (`models/team_penalties.py`; prior strength `k`), the league mean for a club
    with no match there. `lambda_league` is the goals pool's mean goals per team-match.
    `match_id` is cast to `str`, which it already is unless the frame is empty, so an empty
    read has a full one's dtypes.
    """
    out, fit = goals_from_history(history, elo_s, s, prem_tag)
    rates, league_pen = penalty_rates(penalty_pool(history[-s.pool_seasons:], prem_tag), k)
    codes = history[-1].tables["dim_team"].set_index("team_id").team_code
    lambda_pen = out.team_id.map(codes).map(rates).fillna(league_pen).astype("float64")
    out = out.assign(lambda_pen=lambda_pen, lambda_league=fit.mean_goals)
    return out.astype({"match_id": "str"})[TEAM_GOALS_COLUMNS]


def team_goals(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """Team goals v1 for `season`'s next `max_horizon` gameweeks after `as_of_gw` (brief 6.2).

    `mode` goes to `load_as_of`. The `elo_goals` rows, one per team per Premier League
    fixture with `gw` in (as_of_gw, as_of_gw + max_horizon], with `lambda_pen` and
    `lambda_league` added (`TEAM_GOALS_COLUMNS`). Raises by design where `elo_goals` does,
    `MissingSeedError` or `InsufficientSampleError` (docs/data_contract.md, Elo seed notes).
    Raises `PenaltyError` on bad penalty data, a complete match in the pool with no xG or
    npxG, or npxG above xG: a data error, never a read that raises by design.
    """
    cfg = model_config()
    out = team_goals_from_history(load_history(season, as_of_gw, mode),
                                  EloSettings.from_config(cfg), GoalsSettings.from_config(cfg),
                                  penalty_prior(cfg), pipeline_config()["premier_league_tag"])
    log.info("team goals %s as-of %d (%s): %d rows; lambda_pen %.4f-%.4f", season, as_of_gw,
             mode, len(out), out.lambda_pen.min(), out.lambda_pen.max())
    return out
