"""Team penalty rates for team goals v1 (brief section 6.2): the parts of `lambda_pen`.

`lambda_pen` is a club's expected penalty goals per match. A club's penalty xG in a complete
Premier League match is its team xG minus its non-penalty xG in `fact_fixture`, which is
matches.csv's, as the brief says. matches.csv rounds both to two decimals, so a penalty reads
0.78 or 0.79 against the provider's 0.7884 per penalty in `fact_shot`, and a match without one
reads exactly 0.

The pool is the Elo goals model's seasons (this season and last, `goals_model.pool_seasons`):
complete matches up to and including each read's as-of gameweek, with clubs matched across
seasons on `team_code`. Each club's rate is shrunk toward the pool's league mean, with k =
`team_goals.penalty_prior_matches` team-matches:
    lambda_pen = (club's penalty xG + k * league mean) / (club's matches + k)
A club with no match in the pool (promoted, early in a season) gets the league mean. Every
fixture of a club gets the same rate, home or away. Why: docs/decisions.md, "model - team
goals v1".
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from fpl.models.elo import SeasonRead, prem_fixtures

POOL_COLUMNS = ["season", "match_id", "team_code", "pen_xg"]


class PenaltyError(ValueError):
    """Team penalty rates cannot be computed from the read."""


def penalty_prior(cfg: dict) -> float:
    """k, `team_goals.penalty_prior_matches` in the parsed config/model.yaml.

    It must be positive: a raw per-match rate is never used (small samples are shrunk).
    """
    k = float(cfg["team_goals"]["penalty_prior_matches"])
    if not k > 0:
        raise ValueError(f"team_goals.penalty_prior_matches must be positive, got {k}")
    return k


def penalty_pool(reads: Sequence[SeasonRead], prem_tag: str) -> pd.DataFrame:
    """One row per club per complete Premier League match up to each read's as-of gameweek.

    Columns `POOL_COLUMNS`: `pen_xg` is the club's team xG minus its non-penalty xG. A later
    row is never used, even if it holds xG. Raises `PenaltyError` if a complete match has no
    xG or non-penalty xG, or a non-penalty xG above the xG.
    """
    parts = []
    for read in reads:
        fx = prem_fixtures(read, prem_tag)
        fx = fx[fx.stats_complete & (fx.gw <= read.as_of_gw)]
        parts += [pd.DataFrame({
            "season": read.season, "team_code": fx[f"{side}_code"].to_numpy(dtype="int64"),
            "pen_xg": (fx[f"{side}_xg"] - fx[f"{side}_npxg"]).to_numpy(dtype="float64"),
            "match_id": fx.match_id.to_numpy(),
        }) for side in ("home", "away")]
    pool = pd.concat(parts, ignore_index=True)
    bad = pool[pool.pen_xg.isna() | (pool.pen_xg < 0)]
    if not bad.empty:
        raise PenaltyError(
            f"{len(bad)} club-matches have no xG or non-penalty xG, or a non-penalty xG above "
            f"the xG, in a complete Premier League match: {sorted(set(bad.match_id))[:5]}")
    return pool[POOL_COLUMNS]


def penalty_rates(pool: pd.DataFrame, k: float) -> tuple[pd.Series, float]:
    """Each club's penalty xG per match shrunk toward the league mean (team_code -> rate), and
    the league mean: the pool's penalty xG per team-match.

    Raises `PenaltyError` if the pool is empty, as there is then no league mean.
    """
    if pool.empty:
        raise PenaltyError("no complete Premier League match in the penalty pool")
    mean = float(pool.pen_xg.mean())
    by_club = pool.groupby("team_code").pen_xg
    return (by_club.sum() + k * mean) / (by_club.size() + k), mean
