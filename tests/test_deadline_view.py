"""The pre-deadline view's pure builders: newest rows, cleaning rules, commits and deadlines."""

from __future__ import annotations

import pandas as pd
import pytest

from deadline_view_helpers import (
    DEADLINE,
    POSITIONS,
    PRICES,
    TEAMS,
    build,
    history,
    players,
    stats,
    stats_row,
    view_frame,
)
from fpl.clean import build_dim_player
from fpl.deadline_view import (
    ViewError,
    build_view_rows,
    check_before_deadline,
    ends_early,
    newest_player_rows,
    pick_commit,
)
from helpers import SWAPPED, blank_frame, player_row

# ---- the newest row of each player --------------------------------------------------------


def test_the_newest_row_of_each_player_is_the_one_with_the_highest_gw() -> None:
    ps = stats([stats_row(1, 3, status="i"), stats_row(1, 5, status="a"), stats_row(1, 4),
                stats_row(2, 2)])
    out = newest_player_rows(ps).set_index("id")
    assert out.loc[1, "gw"] == 5 and out.loc[1, "status"] == "a" and out.loc[2, "gw"] == 2
    assert len(out) == 2


def test_two_rows_for_one_player_and_gameweek_fail_rather_than_pick_one() -> None:
    ps = stats([stats_row(1, 5, status="i"), stats_row(1, 5, status="a")])
    with pytest.raises(ViewError, match="duplicate"):
        newest_player_rows(ps)


def test_a_row_with_no_gameweek_fails() -> None:
    with pytest.raises(ViewError, match="null"):
        newest_player_rows(stats([stats_row(1, 5), stats_row(2, None)]))


# ---- the cleaning rules are the snapshot's ------------------------------------------------


def test_the_view_rows_are_the_snapshot_cleaning_applied_to_the_newest_rows() -> None:
    rows = [stats_row(1, 1, now_cost=9.0), stats_row(1, 2, now_cost=9.5, status="d",
                                                      chance_of_playing_next_round=75.0,
                                                      news="Knock", penalties_order=1),
            stats_row(2, 2)]
    view, counts = build([1, 2], rows)
    want, _ = build_dim_player(players([1, 2]), stats([rows[1], rows[2]]), TEAMS, POSITIONS)
    pd.testing.assert_frame_equal(view, want)
    assert view.loc[view.player_id == 1, "price_tenths"].item() == 95
    assert counts == {"no_playerstats_row": 0}


def test_a_player_with_no_playerstats_row_is_dropped_and_counted() -> None:
    view, counts = build([1, 2, 3], [stats_row(1, 2), stats_row(2, 2)])
    assert view.player_id.tolist() == [1, 2]
    assert counts == {"no_playerstats_row": 1}


def test_the_view_joins_clubs_by_team_code_not_team_id() -> None:
    # SWAPPED: id 1 has code 3, id 3 has code 1, so a join on id would swap the clubs.
    ps = stats([stats_row(1, 2)])
    view, _ = build_view_rows(
        blank_frame("players", [player_row(1, 3)]), ps, SWAPPED,
        POSITIONS, PRICES, [1, 10], [1, 10],
    )
    assert view.team_id.tolist() == [1]  # code 3 is team 1


@pytest.mark.parametrize("price", [2.9, 20.1, None, 58.0])
def test_a_price_outside_the_bounds_fails_and_is_not_converted(price: float | None) -> None:
    # 58.0 is a price in tenths: it is not silently divided by ten.
    with pytest.raises(ViewError, match="now_cost"):
        build([1], [stats_row(1, 2, now_cost=price)])


def test_a_duplicate_player_id_in_the_master_players_fails() -> None:
    with pytest.raises(ViewError, match="player_id"):
        build([1, 1], [stats_row(1, 2)])


def test_a_row_count_outside_the_snapshot_bounds_fails() -> None:
    with pytest.raises(ViewError, match="rows"):
        build([1, 2], [stats_row(1, 2), stats_row(2, 2)], bounds=[3, 10])


def test_a_missing_status_fails() -> None:
    with pytest.raises(ViewError, match="status"):
        build([1], [stats_row(1, 2, status=None)])



def test_the_commit_is_the_newest_one_strictly_before_the_deadline() -> None:
    log = history(["2026-08-20T12:00:00Z", "2026-08-20T10:00:00Z", "2026-08-20T08:00:00Z"])
    sha, time = pick_commit(log, pd.Timestamp("2026-08-20T11:00:00Z"))
    assert sha == log.sha[2 - 1] and time == pd.Timestamp("2026-08-20T10:00:00Z")


def test_a_commit_at_the_deadline_is_not_before_it() -> None:
    log = history(["2026-08-20T10:00:00Z", "2026-08-20T08:00:00Z"])
    sha, _ = pick_commit(log, pd.Timestamp("2026-08-20T10:00:00Z"))
    assert sha == log.sha[1]


def test_a_deadline_before_the_history_starts_fails() -> None:
    with pytest.raises(ViewError, match="no commit before"):
        pick_commit(history(["2026-08-20T10:00:00Z"]), pd.Timestamp("2026-08-01T00:00:00Z"))


def test_history_out_of_order_fails() -> None:
    with pytest.raises(ViewError, match="order"):
        pick_commit(history(["2026-08-20T08:00:00Z", "2026-08-20T10:00:00Z"]),
                    pd.Timestamp("2026-08-21T00:00:00Z"))


def test_a_deadline_after_the_newest_commit_is_flagged() -> None:
    log = history(["2026-08-20T10:00:00Z", "2026-08-20T08:00:00Z"])
    assert ends_early(log, pd.Timestamp("2026-08-20T10:00:01Z"))
    assert not ends_early(log, pd.Timestamp("2026-08-20T10:00:00Z"))  # nothing is missing
    assert not ends_early(log, pd.Timestamp("2026-08-20T09:00:00Z"))



# ---- failures a snapshot's checks would also catch ------------------------------------------


def test_a_cleaning_rule_failure_is_reported_as_a_view_error() -> None:
    bad = blank_frame("players", [player_row(1, 31, position="Wizard")])
    with pytest.raises(ViewError, match="cleaning rule failed.*unknown position"):
        build_view_rows(bad, stats([stats_row(1, 2)]), TEAMS, POSITIONS, PRICES, [1, 10], [1, 10])


def test_a_player_whose_club_code_is_not_in_teams_is_a_view_error() -> None:
    bad = blank_frame("players", [player_row(1, 99)])
    with pytest.raises(ViewError, match="cleaning rule failed"):
        build_view_rows(bad, stats([stats_row(1, 2)]), TEAMS, POSITIONS, PRICES, [1, 10], [1, 10])


def test_a_playerstats_row_count_outside_the_snapshots_bound_fails() -> None:
    rows = [stats_row(1, 2), stats_row(2, 2)]
    with pytest.raises(ViewError, match="master playerstats: 2 rows"):
        build([1, 2], rows, stats_bounds=[3, 10])
    assert len(build([1, 2], rows, stats_bounds=[2, 10])[0]) == 2


# ---- the read's check of each row's commit against both deadlines --------------------------


def rows_with(commit: str, deadline: str) -> pd.DataFrame:
    return view_frame([2]).assign(commit_utc=commit, deadline_utc=deadline)


DERIVED = pd.Timestamp("2026-08-20T12:00:00Z")


def test_a_commit_before_both_deadlines_passes() -> None:
    check_before_deadline(rows_with("2026-08-20T11:59:59Z", "2026-08-20T12:00:00Z"), 2, DERIVED)


@pytest.mark.parametrize("deadline", ["2026-08-20T12:00:00Z", "2026-08-20T13:00:00Z"])
def test_a_commit_exactly_at_the_derived_deadline_is_refused(deadline: str) -> None:
    with pytest.raises(ViewError, match="at or after the deadline"):
        check_before_deadline(rows_with("2026-08-20T12:00:00Z", deadline), 2, DERIVED)


def test_a_commit_exactly_at_the_rows_own_earlier_deadline_is_refused() -> None:
    # FPL's deadline (the row's) was earlier than the derived one: the stricter applies.
    with pytest.raises(ViewError, match="at or after the deadline"):
        check_before_deadline(rows_with("2026-08-20T11:00:00Z", "2026-08-20T11:00:00Z"), 2,
                              DERIVED)


def test_a_commit_between_the_rows_earlier_deadline_and_the_derived_one_is_refused() -> None:
    with pytest.raises(ViewError, match="2 rows"):
        check_before_deadline(rows_with("2026-08-20T11:30:00Z", "2026-08-20T11:00:00Z"), 2,
                              DERIVED)


def test_a_gameweek_with_no_derived_deadline_is_refused() -> None:
    with pytest.raises(ViewError, match="GW2 has no deadline"):
        check_before_deadline(rows_with("2026-08-20T11:00:00Z", DEADLINE), 2, pd.NaT)
