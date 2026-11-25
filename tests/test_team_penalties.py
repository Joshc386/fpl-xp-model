"""Team penalty rates (`lambda_pen`'s parts): the pool, the shrinkage and its config key.

Hand-computed on season A with `PENS_A` (tests/penalty_tables.py): 12 team-matches holding
2.36 penalty xG, so the league mean is 0.196667 and, with k = 3, 3 x mean = 0.59. Each club
has 3 matches: code 31 (1.57 + 0.59) / 6 = 0.36, code 32 (0.79 + 0.59) / 6 = 0.23, codes 33
and 34 0.59 / 6 = 0.098333.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from elo_tables import CODES_A, CODES_B, FIXTURES_A, FIXTURES_B, PREM, season_read
from fpl.models.elo import SeasonRead, model_config
from fpl.models.team_penalties import (
    PenaltyError,
    penalty_pool,
    penalty_prior,
    penalty_rates,
)
from penalty_tables import PENS_A, PENS_B, complete


def season_a(as_of: int = 3, cups: list | None = None) -> SeasonRead:
    return complete(season_read("2025-2026", as_of, CODES_A, FIXTURES_A, cups=cups), PENS_A)


def test_the_pool_is_one_row_per_club_per_complete_match_with_its_penalty_xg() -> None:
    pool = penalty_pool([season_a()], PREM)
    assert list(pool.columns) == ["season", "match_id", "team_code", "pen_xg"]
    assert len(pool) == 12 and not pool.duplicated(["match_id", "team_code"]).any()
    assert pool.groupby("team_code").size().to_dict() == {31: 3, 32: 3, 33: 3, 34: 3}
    totals = pool.groupby("team_code").pen_xg.sum()
    assert totals.to_numpy() == pytest.approx([1.57, 0.79, 0.0, 0.0])
    assert pool.pen_xg.sum() == pytest.approx(2.36)


def test_the_pool_ignores_rows_after_the_as_of_gameweek_even_with_xg() -> None:
    pool = penalty_pool([season_a(as_of=2)], PREM)  # GW3 is complete in the table: a leak
    assert len(pool) == 8 and pool.pen_xg.sum() == pytest.approx(1.57)  # GW3's 0.79 left out


def test_the_pool_leaves_out_cup_matches_and_finished_matches_that_are_not_complete() -> None:
    cup = [(2, 1, None, 1, 0, 1600.0, None)]
    read = season_a(cups=cup)
    fx = read.tables["fact_fixture"]
    fx.loc[fx.tournament != PREM, ["stats_complete", "home_xg", "home_npxg"]] = [True, 2.0, 0.4]
    fx.loc[5, ["stats_complete", "home_xg", "home_npxg", "away_xg", "away_npxg"]] = [
        False, np.nan, np.nan, np.nan, np.nan]  # finished, xG not in yet
    pool = penalty_pool([read], PREM)
    assert len(pool) == 10 and pool.pen_xg.sum() == pytest.approx(1.57)


def test_two_seasons_pool_on_team_code() -> None:
    b = complete(season_read("2026-2027", 2, CODES_B, FIXTURES_B), PENS_B)
    pool = penalty_pool([season_a(), b], PREM)
    assert len(pool) == 20
    assert pool.groupby("team_code").size().to_dict() == {31: 5, 32: 5, 33: 5, 34: 3, 35: 2}
    assert pool[pool.team_code == 33].pen_xg.sum() == pytest.approx(0.79)  # B's id 1


@pytest.mark.parametrize("npxg", [1.6, np.nan])
def test_a_complete_match_with_npxg_above_xg_or_missing_raises(npxg: float) -> None:
    read = season_a()
    read.tables["fact_fixture"].loc[2, "away_npxg"] = npxg
    with pytest.raises(PenaltyError, match="match"):
        penalty_pool([read], PREM)


def test_rates_are_shrunk_toward_the_league_mean_by_k_matches() -> None:
    rates, mean = penalty_rates(penalty_pool([season_a()], PREM), 3.0)
    assert mean == pytest.approx(2.36 / 12)
    assert isinstance(rates, pd.Series) and rates.index.tolist() == [31, 32, 33, 34]
    assert rates.to_numpy() == pytest.approx([0.36, 0.23, 0.59 / 6, 0.59 / 6])


def test_rates_approach_the_raw_rate_as_k_falls_and_the_mean_as_it_grows() -> None:
    pool = penalty_pool([season_a()], PREM)
    raw, _ = penalty_rates(pool, 1e-9)
    flat, mean = penalty_rates(pool, 1e9)
    assert raw.to_numpy() == pytest.approx([1.57 / 3, 0.79 / 3, 0.0, 0.0], abs=1e-9)
    assert flat.to_numpy() == pytest.approx([mean] * 4)


def test_an_empty_pool_raises() -> None:
    read = complete(season_read("2025-2026", 0, CODES_A, FIXTURES_A), PENS_A)
    with pytest.raises(PenaltyError, match="no complete Premier League match"):
        penalty_rates(penalty_pool([read], PREM), 3.0)


def test_the_prior_strength_is_read_from_config() -> None:
    cfg = model_config()
    assert penalty_prior(cfg) == cfg["team_goals"]["penalty_prior_matches"] == 65


@pytest.mark.parametrize("value", [0, -5])
def test_a_prior_strength_that_is_not_positive_is_rejected(value: float) -> None:
    cfg = model_config()
    cfg["team_goals"]["penalty_prior_matches"] = value
    with pytest.raises(ValueError, match="penalty_prior_matches must be positive"):
        penalty_prior(cfg)
