"""Team goals v1 on the real upstream checkout (skipped when it is not there).

Internal consistency only: keys, ranges, agreement with the Elo goals model, and the penalty
pool against the shots file. Nothing here compares a prediction with an outcome; 2026/27 is
the holdout.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pandas as pd
import pytest

from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models import elo
from fpl.models.elo import load_history, model_config
from fpl.models.team_goals import OUT_COLUMNS, TEAM_GOALS_COLUMNS, elo_goals, team_goals
from fpl.models.team_penalties import penalty_pool, penalty_prior, penalty_rates

CFG = load_config(ROOT / "config" / "pipeline.yaml")
pytestmark = pytest.mark.skipif(
    not (upstream_data_dir(CFG) / "2026-2027" / "By Gameweek" / "GW10").exists(),
    reason="no upstream checkout",
)
READS = [("2025-2026", 32, "backtest"), ("2026-2027", 10, "live")]   # GW33 has six doubles
TOLERANCE = CFG["shot_reconciliation"]["penalty_xg_tolerance"]       # the contract's, per side


@pytest.fixture(scope="module")
def load() -> Iterator[Callable[[str, int, str], dict]]:
    """A memoised `load_as_of`, patched into the Elo component for the module."""
    cache: dict[tuple[str, int, str], dict] = {}

    def memo(season: str, as_of: int, mode: str) -> dict:
        if (season, as_of, mode) not in cache:
            cache[(season, as_of, mode)] = load_as_of(season, as_of, mode)
        return cache[(season, as_of, mode)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(elo, "load_as_of", memo)
        yield memo


@pytest.fixture(scope="module")
def real(load: Callable) -> dict:
    """team_goals and elo_goals for each of `READS`."""
    return {read: (team_goals(*read), elo_goals(*read)) for read in READS}


@pytest.fixture(scope="module")
def season(load: Callable) -> tuple[pd.DataFrame, dict]:
    """2025/26 in full: the penalty pool (its only season) and the read's tables."""
    reads = load_history("2025-2026", 38, "backtest")
    return penalty_pool(reads, CFG["premier_league_tag"]), reads[-1].tables


@pytest.mark.parametrize("read", READS)
def test_the_rows_are_the_elo_goals_rows_with_two_columns_added(real: dict, read: tuple) -> None:
    out, goals = real[read]
    assert list(out.columns) == TEAM_GOALS_COLUMNS
    pd.testing.assert_frame_equal(out[OUT_COLUMNS], goals)
    assert not out.duplicated(["team_id", "match_id"]).any() and out.notna().all().all()


@pytest.mark.parametrize("read", READS)
def test_each_club_has_one_penalty_rate_below_its_expected_goals(real: dict, read: tuple) -> None:
    out, _ = real[read]
    assert (out.groupby("team_id").lambda_pen.nunique() == 1).all()
    assert (out.lambda_pen > 0).all() and (out.lambda_pen < out.lambda_for).all()
    assert out.lambda_league.nunique() == 1 and (out.lambda_league > 0).all()


def test_the_penalty_pool_matches_the_shots_penalty_xg(season: tuple) -> None:
    # Each club-match side within the contract's tolerance, so each club's total within it
    # per side; and no penalty shot outside the pool.
    pool, tables = season
    codes = tables["dim_team"].set_index("team_id").team_code
    shots = tables["fact_shot"].query("is_penalty")
    shot_pen = (shots.assign(team_code=shots.team_id.map(codes))
                .groupby(["match_id", "team_code"]).xg.sum())
    side = pool.set_index(["match_id", "team_code"]).pen_xg
    assert len(side) == 760 and shot_pen.index.isin(side.index).all()
    assert (side - shot_pen.reindex(side.index, fill_value=0.0)).abs().max() <= TOLERANCE
    by_club = shot_pen.groupby(level="team_code").sum().reindex(
        pool.team_code.unique(), fill_value=0.0)
    gap = (pool.groupby("team_code").pen_xg.sum() - by_club).abs()
    assert (gap <= TOLERANCE * pool.groupby("team_code").size()).all()


def test_at_the_seasons_end_the_matches_weighted_mean_rate_is_the_league_mean(
        season: tuple) -> None:
    pool, _ = season
    rates, mean = penalty_rates(pool, penalty_prior(model_config()))
    matches = pool.groupby("team_code").size()
    assert len(matches) == 20 and (matches == 38).all()
    assert (rates * matches).sum() / matches.sum() == pytest.approx(mean, abs=1e-12)
    assert mean == pytest.approx(pool.pen_xg.sum() / 760, abs=1e-12)
