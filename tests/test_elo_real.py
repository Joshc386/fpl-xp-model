"""The Elo component on the real upstream checkout (skipped when it is not there).

Five reads in all, memoised: 2025/26 at as-of 20 and 38, and 2026/27 at as-of 1 and 10 (both
modes). Nothing here compares a prediction with a 2026/27 result: that season is the holdout.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest

from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models import elo
from fpl.models.elo import MissingSeedError, elo_ratings
from fpl.models.team_goals import elo_goals

CFG = load_config(ROOT / "config" / "pipeline.yaml")
pytestmark = pytest.mark.skipif(
    not (upstream_data_dir(CFG) / "2026-2027" / "By Gameweek" / "GW10").exists(),
    reason="no upstream checkout",
)
PREM = CFG["premier_league_tag"]
PROMOTED_SEEDS = {"Coventry City": 1661.48, "Hull City": 1532.88, "Ipswich Town": 1640.0}


@pytest.fixture(scope="module")
def real() -> Iterator[dict]:
    """The latest outputs in both modes, with the memoised loader patched in for the module."""
    cache: dict[tuple[str, int, str], dict] = {}

    def load(season: str, as_of: int, mode: str) -> dict:
        if (season, as_of, mode) not in cache:
            cache[(season, as_of, mode)] = load_as_of(season, as_of, mode)
        return cache[(season, as_of, mode)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(elo, "load_as_of", load)
        yield {"load": load, **{mode: (elo_ratings("2026-2027", 10, mode),
                                       elo_goals("2026-2027", 10, mode))
                                for mode in ("backtest", "live")}}


def test_real_both_modes_give_the_same_output(real: dict) -> None:
    for back, live in zip(real["backtest"], real["live"], strict=True):
        pd.testing.assert_frame_equal(back, live)


def test_real_rows_keys_and_ranges(real: dict) -> None:
    ratings, goals = real["backtest"]
    fx = real["load"]("2026-2027", 10, "backtest")["fact_fixture"]
    horizon = fx[(fx.tournament == PREM) & fx.gw.between(11, 15)]
    assert len(ratings) == 2 * (380 + 100) and len(goals) == 2 * len(horizon)
    assert not ratings.duplicated(["season", "team_id", "match_id"]).any()
    assert not goals.duplicated(["team_id", "match_id"]).any()
    assert not ratings.isna().any().any() and not goals.isna().any().any()
    assert (goals.lambda_for > 0).all() and goals.p_cs.between(0, 1).all()


def test_real_seeds_are_gw1_kickoff_values(real: dict) -> None:
    ratings, _ = real["backtest"]
    fx = real["load"]("2025-2026", 38, "backtest")["fact_fixture"]
    gw1 = fx[(fx.tournament == PREM) & (fx.gw == 1)]
    want = dict(zip(gw1.home_team_id, gw1.home_upstream_elo, strict=True)) | dict(
        zip(gw1.away_team_id, gw1.away_upstream_elo, strict=True))
    first = ratings[ratings.season == "2025-2026"].groupby("team_id").elo_before.first()
    assert first.to_dict() == want and len(want) == 20


def last_kickoff_elo(fx: pd.DataFrame) -> pd.Series:
    """Each club's upstream Elo at its last Premier League kickoff (team_id -> Elo)."""
    prem = fx[(fx.tournament == PREM) & fx.finished]
    sides = pd.concat([prem[["kickoff_utc", f"{s}_team_id", f"{s}_upstream_elo"]].set_axis(
        ["kickoff_utc", "team_id", "elo"], axis=1) for s in ("home", "away")])
    return sides.sort_values("kickoff_utc").drop_duplicates("team_id", keep="last").set_index(
        "team_id").elo


def test_real_2026_27_is_reseeded_from_the_2025_26_last_match_value_by_team_code(
    real: dict
) -> None:
    ratings, _ = real["backtest"]
    old_read = real["load"]("2025-2026", 38, "backtest")
    old_t = old_read["dim_team"].set_index("team_id")
    new_t = real["load"]("2026-2027", 10, "backtest")["dim_team"].set_index("team_id")
    end_value = last_kickoff_elo(old_read["fact_fixture"]).rename(old_t.team_code)
    old = ratings[ratings.season == "2025-2026"]
    end_rating = old.groupby("team_id").elo_after.last().rename(old_t.team_code)
    new = ratings[(ratings.season == "2026-2027") & (ratings.gw == 1)].set_index("team_id")
    first = new.elo_before.rename(new_t.team_code)
    continuing = first.index.intersection(end_value.index)
    assert len(first) == 20 and len(continuing) == 17
    assert first[continuing].to_dict() == end_value[continuing].to_dict()
    assert (first[continuing] != end_rating[continuing]).all()  # no carry-over
    names = new_t.set_index("team_code").name
    assert first.rename(names)[["Arsenal", "Brentford"]].tolist() == [2063.76, 1836.59]
    assert first.drop(continuing).rename(names).to_dict() == PROMOTED_SEEDS


def test_real_ratings_up_to_gw20_match_the_full_run(real: dict) -> None:
    part = elo_ratings("2025-2026", 20, "backtest")
    full = real["backtest"][0]
    pd.testing.assert_frame_equal(
        part, full[(full.season == "2025-2026") & (full.gw <= 20)].reset_index(drop=True))


def test_real_2026_27_as_of_1_has_no_seed_for_coventry(real: dict) -> None:
    with pytest.raises(MissingSeedError, match="Coventry City"):
        elo_ratings("2026-2027", 1, "backtest")
