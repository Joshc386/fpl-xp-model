"""The minutes component's public function on the synthetic upstream season.

The synthetic season (tests/synth.py): 4 clubs, 8 players, GW5 blank for clubs 2 and 4, GW7
a double for clubs 1 and 2, player 2 moving from club 1 to club 3 from GW20, and poisoned
master files (every player injured), which only live mode reads.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

import synth
from fpl.ingest import load_config
from fpl.models import elo, minutes
from fpl.models.elo import model_config
from fpl.models.minutes import (
    OUT_COLUMNS,
    PROBABILITIES,
    MinutesSettings,
    minutes_from_tables,
    player_minutes,
)
from fpl.models.team_goals import elo_goals


@pytest.fixture
def on_synth(monkeypatch: pytest.MonkeyPatch, synth_load: Callable[[int, str], dict]) -> None:
    """Point the minutes and Elo components' loader at the synthetic 2025-2026 season."""
    def load(season: str, as_of: int, mode: str) -> dict:
        return synth_load(as_of, mode)

    monkeypatch.setattr(minutes, "load_as_of", load)
    monkeypatch.setattr(elo, "load_as_of", load)


pytestmark = pytest.mark.usefixtures("on_synth")


def test_rows_are_every_player_at_every_fixture_of_his_club_in_the_horizon() -> None:
    out = player_minutes(synth.SEASON, 20, "backtest")
    assert list(out.columns) == OUT_COLUMNS
    assert not out.duplicated(["player_id", "match_id"]).any()
    assert sorted(set(out.gw)) == [21, 22, 23, 24, 25]
    # Two clubs a fixture, two players a club: 4 rows a fixture, 2 fixtures a gameweek.
    assert len(out) == 4 * 2 * 5 and set(out.player_id) == set(synth.PLAYER_CLUB)
    assert out.notna().all().all()


def test_the_fixtures_are_the_ones_the_elo_goals_model_chooses() -> None:
    for as_of in (15, 20):  # the first as-of with the 30 matches the Elo goals model needs
        mine = player_minutes(synth.SEASON, as_of, "backtest")[["team_id", "match_id", "gw"]]
        theirs = elo_goals(synth.SEASON, as_of, "backtest")[["team_id", "match_id", "gw"]]
        assert set(mine.itertuples(index=False)) == set(theirs.itertuples(index=False))


def test_a_blank_gameweek_has_no_rows_and_a_double_has_two() -> None:
    out = player_minutes(synth.SEASON, 4, "backtest")
    assert set(out[out.gw == 5].team_id) == {1, 3}           # clubs 2 and 4 are blank
    gw7 = out[out.gw == 7].groupby("player_id").size()
    assert gw7.to_dict() == {p: 2 if synth.club(p, 4) in (1, 2) else 1 for p in synth.PLAYER_CLUB}


def test_the_second_fixture_of_the_double_has_the_lower_start_chance() -> None:
    out = player_minutes(synth.SEASON, 6, "backtest")
    gw7 = out[(out.gw == 7) & out.team_id.isin([1, 2])]
    for _, two in gw7.groupby("player_id"):
        first, second = two.iloc[0], two.iloc[1]     # rows come in kickoff order
        assert second.p_start <= first.p_start
        assert second.p_start < first.p_start or first.p_start == 0


def test_a_player_who_moved_gets_his_new_clubs_fixtures() -> None:
    out = player_minutes(synth.SEASON, 20, "backtest")
    assert set(out[out.player_id == synth.MOVER].team_id) == {3}


def test_the_probabilities_are_ordered_and_minutes_are_within_a_match() -> None:
    out = player_minutes(synth.SEASON, 20, "backtest")
    assert out[PROBABILITIES].stack().between(0, 1).all()
    assert (out.p_60 <= out.p_start + 1e-12).all() and (out.p_start <= out.p_appear + 1e-12).all()
    assert out.exp_minutes.between(0, 90).all()
    assert (out.p_start > 0).any()


def test_live_mode_takes_status_from_the_master_files() -> None:
    # The synthetic master files mark every player injured: live mode reads them.
    live = player_minutes(synth.SEASON, 20, "live")
    back = player_minutes(synth.SEASON, 20, "backtest")
    pd.testing.assert_frame_equal(live[["player_id", "match_id", "gw"]],
                                  back[["player_id", "match_id", "gw"]])
    assert (live[[*PROBABILITIES, "exp_minutes"]] == 0).all().all()
    assert (back.p_start > 0).any()


OUTPUTS = [*PROBABILITIES, "exp_minutes"]


def with_and_without_player_3s_chance(synth_load: Callable[[int, str], dict],
                                      as_of: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`player_minutes` at `as_of`, and the same read with player 3's 50% chance cleared, both
    by (player_id, gw, match_id). Player 3 (club 2) carries 50% in every synthetic snapshot."""
    out = player_minutes(synth.SEASON, as_of, "backtest")
    tables = dict(synth_load(as_of, "backtest"))
    dp = tables["dim_player"].copy()
    dp.loc[dp.player_id == 3, "chance_next"] = pd.NA
    tables["dim_player"] = dp
    settings = MinutesSettings.from_config(model_config(), load_config(minutes.SCORING_CONFIG))
    clear = minutes_from_tables(tables, as_of, settings, "prem")
    keys = ["player_id", "gw", "match_id"]
    return out.set_index(keys)[OUTPUTS], clear.set_index(keys)[OUTPUTS]


def test_a_chance_of_50_halves_player_3s_next_gameweek_only(
        synth_load: Callable[[int, str], dict]) -> None:
    out, clear = with_and_without_player_3s_chance(synth_load, 20)
    mine, theirs = out.xs(3), clear.xs(3)
    assert (theirs.loc[[21]] > 0).any().all()
    pd.testing.assert_frame_equal(mine.loc[[21]], 0.5 * theirs.loc[[21]])
    pd.testing.assert_frame_equal(mine.loc[[22, 23, 24, 25]], theirs.loc[[22, 23, 24, 25]])
    pd.testing.assert_frame_equal(out.drop(index=3, level=0), clear.drop(index=3, level=0))


def test_a_chance_of_50_halves_both_fixtures_of_a_next_gameweek_double(
        synth_load: Callable[[int, str], dict]) -> None:
    # At as-of 6 the next gameweek, GW7, is a double for clubs 1 and 2.
    out, clear = with_and_without_player_3s_chance(synth_load, 6)
    mine, theirs = out.xs(3), clear.xs(3)
    assert len(theirs.loc[[7]]) == 2 and (theirs.loc[[7]] > 0).any().all()
    pd.testing.assert_frame_equal(mine.loc[[7]], 0.5 * theirs.loc[[7]])
    pd.testing.assert_frame_equal(mine.loc[[8, 9, 10, 11]], theirs.loc[[8, 9, 10, 11]])


def test_as_of_0_has_no_players_and_returns_no_rows() -> None:
    out = player_minutes(synth.SEASON, 0, "backtest")
    assert list(out.columns) == OUT_COLUMNS and out.empty


def test_as_of_38_has_no_horizon_and_returns_no_rows() -> None:
    assert player_minutes(synth.SEASON, 38, "backtest").empty
