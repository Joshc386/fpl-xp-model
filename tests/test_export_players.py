"""players.csv metrics on hand-built tables (see export_tables.py), answers by hand."""

from __future__ import annotations

import pandas as pd
import pytest

from export_tables import AS_OF, PREM, fixture, frame, gw_row, pm_row, tables
from fpl.frames import JoinError
from fpl.output_schema import output_columns
from fpl.player_metrics import player_metrics
from fpl.validate import ValidationError


def metrics(t: dict | None = None) -> pd.DataFrame:
    return player_metrics(t or tables(), AS_OF, PREM).set_index("player_id")


def test_identity_and_price_columns() -> None:
    a = metrics().loc[10]
    assert (a.web_name, a.team, a.position, a.status, a.news) == (
        "P10", "ALP", "MID", "d", "Knock")
    assert a.price_m == 5.6 and a.chance_next == 75 and a.selected_pct == 12.5


def test_totals_use_fpl_gameweek_figures_up_to_the_as_of_gameweek() -> None:
    a = metrics().loc[10]
    assert (a.minutes, a.starts, a.total_points) == (315, 4, 18)   # the gw 4 row is ignored


def completed_m4() -> dict:
    """The tables with m4 complete, so every gameweek-3 appearance has its match row."""
    t = tables()
    fx = t["fact_fixture"].copy()
    fx.loc[fx.match_id == "m4", "stats_complete"] = True
    t["fact_fixture"] = fx
    return t


def test_ppg_counts_a_finished_match_that_is_not_complete_as_an_appearance() -> None:
    # Player 10 played m1, m2, m3 (complete) and m4 (finished, 90 FPL minutes, not complete):
    # 18 points over 4 appearances. The cup match is not an appearance.
    assert metrics().loc[10].ppg == pytest.approx(4.5)


def test_ppg_counts_both_matches_of_a_double_gameweek() -> None:
    # With m4 complete, gameweeks 1-3 hold 1 + 2 + 1 appearances: 18 / 4. Counting
    # gameweeks played alone would give 18 / 3.
    assert metrics(completed_m4()).loc[10].ppg == pytest.approx(4.5)


def test_ppg_leaves_out_a_half_played_double_gameweek_with_the_points() -> None:
    # Gameweek 3 is a double: m4 is finished and complete but m7 is still to play, so
    # player 10's gameweek 3 row is held. Points 16 over the 3 appearances of gameweeks 1-2.
    t = completed_m4()
    t["fact_fixture"] = frame("fact_fixture", [
        *t["fact_fixture"].to_dict("records"), fixture("m7", 3, 2, 1, finished=False)])
    gw = t["fact_player_gw"]
    t["fact_player_gw"] = gw[~((gw.player_id == 10) & (gw.gw == 3))]
    a = metrics(t).loc[10]
    assert a.total_points == 16 and a.ppg == pytest.approx(16 / 3)


def test_ppg_falls_back_to_gameweeks_played_when_match_rows_are_missing() -> None:
    # Player 40 played 10 minutes in gameweek 3 but has no player-match row.
    assert metrics().loc[40].ppg == pytest.approx(1.0)


def test_ppg_ignores_appearances_in_gameweeks_with_no_released_row() -> None:
    # Player 30 has gameweek 1 and 2 rows only; a gameweek 3 match row must not count.
    t = tables()
    t["fact_player_match"] = frame("fact_player_match", [
        *t["fact_player_match"].to_dict("records"), pm_row(30, 2, "m4", 90)])
    fx = t["fact_fixture"].copy()
    fx.loc[fx.match_id == "m4", "stats_complete"] = True
    t["fact_fixture"] = fx
    assert metrics(t).loc[30].ppg == pytest.approx(3.0)      # 3 points, gameweek 1 only


def test_xg90_and_xa90_use_complete_premier_league_matches_and_their_minutes() -> None:
    a = metrics().loc[10]
    assert a.xg90 == pytest.approx(1.0 / 225 * 90)    # 0.5 + 0.3 + 0.2 over 90 + 90 + 45
    assert a.xa90 == pytest.approx(0.5 / 225 * 90)    # the cup (5.0) and m4 (9.0) are left out


def test_dc90_uses_fpl_counts_over_fpl_minutes() -> None:
    assert metrics().loc[10].dc90 == pytest.approx(12 / 315 * 90)


def test_player_with_no_minutes_has_zero_rates_not_nan() -> None:
    b = metrics().loc[20]
    assert (b.minutes, b.starts, b.total_points) == (0, 0, 0)
    assert (b.ppg, b.xg90, b.xa90, b.dc90) == (0.0, 0.0, 0.0, 0.0)


def test_player_with_no_rows_at_all_gets_zeros() -> None:
    t = tables()
    t["fact_player_gw"] = t["fact_player_gw"][t["fact_player_gw"].player_id != 20]
    t["fact_player_match"] = t["fact_player_match"][t["fact_player_match"].player_id != 20]
    b = metrics(t).loc[20]
    assert (b.minutes, b.total_points, b.ppg, b.xg90) == (0, 0, 0.0, 0.0)


def test_pen_taker_is_first_on_the_order_only() -> None:
    m = metrics()
    assert m.loc[10].pen_taker and not m.loc[30].pen_taker and not m.loc[20].pen_taker


def test_transfers_and_price_changes_come_from_dim_player_and_are_never_null() -> None:
    m = metrics()
    assert m.net_transfers_gw.to_dict() == {10: 200, 20: 0, 30: -3, 40: -2}
    assert m.price_change_gw.to_dict() == pytest.approx({10: 0.1, 20: 0.0, 30: -0.1, 40: 0.0})
    assert m.price_change_start.to_dict() == pytest.approx({10: 1.2, 20: 0.0, 30: -0.2, 40: 0.0})
    assert not m[["net_transfers_gw", "price_change_gw", "price_change_start"]].isna().any().any()


def test_a_held_gameweek_row_does_not_null_the_snapshot_columns() -> None:
    # Player 30 has no gameweek 3 row (his club's fixture is unfinished).
    assert metrics().loc[30].net_transfers_gw == -3


def test_one_row_per_player_sorted_with_every_contract_column() -> None:
    out = player_metrics(tables(), AS_OF, PREM)
    assert out.player_id.tolist() == [10, 20, 30, 40]
    assert list(out.columns) == output_columns("players")


def test_a_player_in_a_club_missing_from_dim_team_fails_the_join() -> None:
    t = tables()
    t["dim_team"] = t["dim_team"][t["dim_team"].team_id != 2]
    with pytest.raises(JoinError):
        player_metrics(t, AS_OF, PREM)


def test_duplicate_gameweek_rows_fail_rather_than_double_count() -> None:
    t = tables()
    t["fact_player_gw"] = frame("fact_player_gw", [
        *t["fact_player_gw"].to_dict("records"), gw_row(10, 1, 3, points=2, minutes=90)])
    with pytest.raises(ValidationError, match="duplicate"):
        player_metrics(t, AS_OF, PREM)
