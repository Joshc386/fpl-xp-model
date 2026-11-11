"""Recent minutes and starts: the last N gameweeks in which the player's club had a fixture."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

import synth
from fpl.features import recent_minutes

PREM = "prem"


def tables(pgw: list[tuple], fixtures: list[tuple], extra_players: tuple[int, ...] = ()) -> dict:
    """pgw rows are (player, team, gw, minutes, starts); fixtures (gw, home, away[, tournament])."""
    gw = pd.DataFrame(pgw, columns=["player_id", "team_id", "gw", "minutes", "starts"])
    gw = gw.astype({"team_id": "Int64", "gw": "int64"})
    fx = pd.DataFrame(
        [(g, h, a, t[0] if t else PREM) for g, h, a, *t in fixtures],
        columns=["gw", "home_team_id", "away_team_id", "tournament"],
    ).astype({"home_team_id": "Int64", "away_team_id": "Int64"})
    players = sorted(set(gw.player_id) | set(extra_players))
    return {"fact_player_gw": gw, "fact_fixture": fx,
            "dim_player": pd.DataFrame({"player_id": players})}


def recent(t: dict, as_of: int, windows: list[int]) -> pd.DataFrame:
    return recent_minutes(t, as_of, windows, PREM)


def row(df: pd.DataFrame, player: int, window: int) -> list[int]:
    r = df[(df.player_id == player) & (df.window == window)].iloc[0]
    return [int(r.minutes), int(r.starts), int(r.fixtures)]


def test_a_blank_gameweek_is_skipped_so_the_window_reaches_further_back() -> None:
    # Club 1 plays in GW1, 2, 4 and 5 and is blank in GW3 (the player's row has 0 minutes).
    weeks = [(1, 90, 1), (2, 80, 1), (3, 0, 0), (4, 60, 1), (5, 30, 0)]
    t = tables(
        [(10, 1, g, m, s) for g, m, s in weeks],
        [(1, 1, 2), (2, 1, 2), (4, 1, 2), (5, 1, 2), (3, 2, 3)],
    )
    # Last 3 gameweeks with a fixture, up to GW5: GW5, GW4 and GW2 (not the blank GW3).
    assert row(recent(t, 5, [3]), 10, 3) == [30 + 60 + 80, 1 + 1, 3]
    assert row(recent(t, 5, [4]), 10, 4) == [30 + 60 + 80 + 90, 3, 4]


def test_a_double_gameweek_counts_as_one_gameweek_with_two_fixtures() -> None:
    t = tables(
        [(10, 1, 1, 90, 1), (10, 1, 2, 135, 2), (10, 1, 3, 70, 1)],
        [(1, 1, 2), (2, 1, 2), (2, 3, 1), (3, 1, 2)],
    )
    # Two gameweeks (GW3 and the double GW2), not three fixtures' worth.
    assert row(recent(t, 3, [2]), 10, 2) == [70 + 135, 1 + 2, 1 + 2]
    assert row(recent(t, 3, [3]), 10, 3) == [90 + 135 + 70, 4, 4]


def test_a_mid_season_transfer_follows_the_club_of_each_gameweek() -> None:
    # Club 1 is blank in GW2 and club 2 plays; the player is at club 1 in GW1 and club 2 later.
    t = tables(
        [(10, 1, 1, 90, 1), (10, 2, 2, 60, 1), (10, 2, 3, 75, 1)],
        [(1, 1, 3), (2, 2, 3), (3, 1, 3), (3, 2, 4)],
    )
    assert row(recent(t, 3, [3]), 10, 3) == [90 + 60 + 75, 3, 3]
    # Had he stayed at club 1, GW2 would have been a blank gameweek and was skipped.
    stayed = {**t, "fact_player_gw": t["fact_player_gw"].assign(team_id=pd.array([1] * 3, "Int64"))}
    assert row(recent(stayed, 3, [3]), 10, 3) == [90 + 75, 2, 2]


def test_a_window_longer_than_the_history_covers_all_of_it() -> None:
    t = tables([(10, 1, 1, 90, 1), (10, 1, 2, 45, 0)], [(1, 1, 2), (2, 1, 2)])
    assert row(recent(t, 2, [38]), 10, 38) == [135, 1, 2]
    assert recent(t, 2, [1, 38]).shape == (2, 5)


def test_several_windows_give_one_row_per_player_and_window() -> None:
    t = tables(
        [(p, 1, g, 10 * g, 1) for p in (10, 11) for g in (1, 2, 3)], [(g, 1, 2) for g in (1, 2, 3)]
    )
    out = recent(t, 3, [1, 2, 3])
    assert list(out.columns) == ["player_id", "window", "minutes", "starts", "fixtures"]
    assert len(out) == 6
    assert [row(out, 10, n)[0] for n in (1, 2, 3)] == [30, 50, 60]
    assert out.dtypes.map(str).eq("int64").all()


def test_gameweeks_after_as_of_are_ignored() -> None:
    t = tables([(10, 1, g, 90, 1) for g in (1, 2, 3, 4)], [(g, 1, 2) for g in (1, 2, 3, 4)])
    assert row(recent(t, 2, [5]), 10, 5) == [180, 2, 2]


def test_a_player_whose_rows_all_come_after_as_of_gets_zeros() -> None:
    # Player 11's club has fixtures in GW3 and GW4 and he has rows for both.
    t = tables(
        [(10, 1, 1, 90, 1), (11, 1, 3, 90, 1), (11, 1, 4, 90, 1)],
        [(1, 1, 2), (3, 1, 2), (4, 1, 2)],
    )
    out = recent(t, 2, [5])
    assert row(out, 11, 5) == [0, 0, 0] and row(out, 10, 5) == [90, 1, 1]
    assert row(recent(t, 4, [5]), 11, 5) == [180, 2, 2]


def test_only_premier_league_fixtures_make_a_gameweek_count() -> None:
    t = tables(
        [(10, 1, 1, 90, 1), (10, 1, 2, 88, 1), (10, 1, 3, 70, 1)],
        [(1, 1, 2), (2, 1, 9, "efl-cup"), (3, 1, 2)],
    )
    assert row(recent(t, 3, [2]), 10, 2) == [90 + 70, 2, 2]


def test_a_row_with_no_club_is_skipped_and_a_player_without_history_gets_zeros() -> None:
    t = tables(
        [(10, 1, 1, 90, 1), (11, None, 1, 0, 0)], [(1, 1, 2)], extra_players=(12,)
    )
    out = recent(t, 1, [2])
    assert row(out, 10, 2) == [90, 1, 1]
    assert row(out, 11, 2) == [0, 0, 0] and row(out, 12, 2) == [0, 0, 0]
    assert sorted(out.player_id) == [10, 11, 12]


def test_the_tables_are_not_modified() -> None:
    t = tables([(10, 1, 1, 90, 1)], [(1, 1, 2)])
    before = {k: v.copy() for k, v in t.items()}
    recent(t, 1, [1])
    for k, v in before.items():
        pd.testing.assert_frame_equal(t[k], v)


@pytest.mark.parametrize("bad", [[], [0], [-1], [3, 3], [2.5], [True, 1]])
def test_windows_must_be_distinct_positive_integers(bad: list) -> None:
    t = tables([(10, 1, 1, 90, 1)], [(1, 1, 2)])
    with pytest.raises(ValueError, match="windows"):
        recent(t, 1, bad)


def expected(player: int, as_of: int, n: int) -> list[int]:
    """Recent minutes by hand from the synthetic season's formulas."""
    out, gws = [0, 0, 0], 0
    for gw in range(as_of, 0, -1):
        club = synth.club(player, gw)
        fx = [m for m in synth.schedule()
              if m["gw"] == gw and m["tournament"] == "prem" and club in (m["home"], m["away"])]
        if not fx or gws == n:
            continue
        gws += 1
        mins = synth.minutes(player, gw)
        out = [out[0] + mins * len(fx), out[1] + (mins >= 60) * len(fx), out[2] + len(fx)]
    return out


@pytest.mark.parametrize("as_of", [4, 6, 8, 19, 20, 25, 38])
def test_the_synthetic_season_blank_double_and_transfer_cases(
    synth_load: Callable, as_of: int
) -> None:
    t = synth_load(as_of)
    out = recent_minutes(t, as_of, [1, 3, 5, 99], PREM)
    for player in synth.PLAYER_CLUB:
        for n in (1, 3, 5, 99):
            assert row(out, player, n) == expected(player, as_of, n), (player, as_of, n)


def test_the_expected_values_really_exercise_the_blank_double_and_transfer() -> None:
    assert expected(3, 6, 3)[2] == 3  # club 2 is blank in GW5: GW6, GW4 and GW3 count
    assert expected(1, 8, 2)[2] == 3  # club 1 has two fixtures in GW7, one in GW8
    assert synth.club(synth.MOVER, 19) != synth.club(synth.MOVER, 20)
