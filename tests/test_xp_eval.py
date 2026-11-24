"""The scored rows of one target gameweek: the evaluation set, actual points and the model's
hand-off check, on hand-built frames."""

from __future__ import annotations

import pandas as pd
import pytest
from backtest.elo_data import HarnessError
from backtest.xp_eval import actuals, evaluation_rows, model_column


def view(rows: list[tuple[int, int, bool]]) -> pd.DataFrame:
    """(player_id, fixtures, started) rows of the baselines frame for GW5."""
    return pd.DataFrame([{"player_id": p, "gw": 5, "fixtures": f, "started": s,
                          "ep_next": 1.0, "last5": 2.0, "ppg": 3.0} for p, f, s in rows])


def test_actuals_are_the_target_gameweeks_fpl_points_and_minutes() -> None:
    gw = pd.DataFrame({"player_id": [1, 1, 2], "gw": [4, 5, 5], "points": [9, 2, 0],
                       "minutes": [90, 60, 0], "goals_conceded": [0, 3, 0]})
    got = actuals({"fact_player_gw": gw}, 5).set_index("player_id")
    assert got.points.to_dict() == {1: 2, 2: 0}
    assert got.goals_conceded.to_dict() == {1: 3, 2: 0}
    assert got.minutes.to_dict() == {1: 60, 2: 0}


def test_the_evaluation_set_is_minutes_in_g_or_a_recent_start() -> None:
    frame = view([(1, 1, False), (2, 1, True), (3, 1, False), (4, 0, True), (5, 1, True)])
    actual = pd.DataFrame({"player_id": [1, 2, 3, 4, 9], "points": [2, 0, 0, 0, 5],
                           "minutes": [30, 0, 0, 0, 90]})
    rows, counts = evaluation_rows(frame, actual)
    # 1 played; 2 started recently; 3 neither; 4 started recently (blank, 0 points);
    # 5 started recently but has no row for GW5; 9 played but isn't in the GW4 snapshot.
    assert rows.player_id.tolist() == [1, 2, 4]
    assert counts == {"in_set": 5, "scored": 3, "not_in_snapshot": 1, "no_actual_row": 1}


def xp_rows(rows: list[tuple[int, str, int, float]]) -> pd.DataFrame:
    """The contract's Combine rows, one per player per fixture: (player_id, match_id, gw,
    xp_total)."""
    return pd.DataFrame([{"player_id": p, "team_id": 1, "match_id": m, "gw": gw,
                          "xp_appear": 1.0, "xp_cards": -0.1, "xp_total": x}
                         for p, m, gw, x in rows])


def test_model_column_sums_a_players_fixtures_and_zero_fills_only_blanks() -> None:
    frame = view([(1, 2, True), (2, 1, True), (3, 0, True)])
    out = xp_rows([(1, "a", 5, 1.5), (1, "b", 5, 2.0), (2, "c", 5, 4.0), (2, "d", 6, 9.0)])
    got = model_column(out, frame, "xp_total")
    assert got.tolist() == [3.5, 4.0, 0.0]


def test_model_column_stops_on_a_missing_player() -> None:
    frame = view([(1, 1, True), (2, 1, True)])
    with pytest.raises(HarnessError, match="no prediction for 1 player"):
        model_column(xp_rows([(1, "a", 5, 1.0)]), frame, "xp_total")


@pytest.mark.parametrize("column", ["player_id", "match_id", "gw", "team_id", "xp_appear",
                                    "xp_cards", "xp_total"])
def test_model_column_requires_the_contracts_combine_columns(column: str) -> None:
    frame = view([(1, 1, True)])
    with pytest.raises(HarnessError, match=column):
        model_column(xp_rows([(1, "a", 5, 1.0)]).drop(columns=column), frame, "xp_total")
