"""Live overlay: status, news, chance of playing and price from the master playerstats."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.overlay import OVERLAID, overlay_current_state
from fpl.schema import check_table_schema
from fpl.validate import ValidationError

BOUNDS = [3.0, 20.0]


def dim_player() -> pd.DataFrame:
    return pd.DataFrame({
        "player_id": pd.array([1, 2, 3], dtype="int64"),
        "player_code": pd.array([101, 102, 103], dtype="int64"),
        "web_name": ["A", "B", "C"], "team_id": pd.array([1, 1, 2], dtype="int64"),
        "position": ["MID", "DEF", "FWD"],
        "price_tenths": pd.array([50, 60, 70], dtype="int64"),
        "status": ["a", "a", "a"], "chance_next": pd.array([None, 75, None], dtype="Int64"),
        "news": pd.array([None, "Knock", None], dtype="str"),
        "selected_pct": [1.0, 2.0, 3.0], "pen_order": pd.array([1, None, None], dtype="Int64"),
        "fk_order": pd.array([None] * 3, dtype="Int64"),
        "corner_order": pd.array([None] * 3, dtype="Int64"),
        "ep_next": [4.0, 3.0, 2.0],
    })


def master(rows: list[dict]) -> pd.DataFrame:
    base = {"gw": 10.0, "status": "a", "news": np.nan, "chance_of_playing_next_round": np.nan,
            "now_cost": 5.0}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_the_four_fields_are_overlaid_and_nothing_else_changes() -> None:
    dim = dim_player()
    rows = master([
        {"id": 1.0, "status": "i", "news": "Hamstring", "chance_of_playing_next_round": 0.0,
         "now_cost": 5.4},
        {"id": 2.0, "now_cost": 6.0},
        {"id": 3.0, "now_cost": 6.9},
    ])
    out = overlay_current_state(dim, rows, BOUNDS)
    assert out.loc[0, OVERLAID].tolist() == ["i", "Hamstring", 0, 54]
    assert out.price_tenths.tolist() == [54, 60, 69]
    pd.testing.assert_frame_equal(out.drop(columns=OVERLAID), dim.drop(columns=OVERLAID))
    assert check_table_schema(out, "dim_player") == []


def test_a_cleared_concern_in_the_master_clears_the_snapshot_value() -> None:
    out = overlay_current_state(
        dim_player(), master([{"id": 1.0}, {"id": 2.0}, {"id": 3.0}]), BOUNDS
    )
    assert out.chance_next.isna().all() and out.news.isna().all()


def test_the_latest_gameweek_row_wins_whatever_the_row_order() -> None:
    rows = master([
        {"id": 1.0, "gw": 10.0, "now_cost": 5.5}, {"id": 1.0, "gw": 9.0, "now_cost": 5.1},
        {"id": 2.0}, {"id": 3.0},
    ])
    assert overlay_current_state(dim_player(), rows, BOUNDS).price_tenths[0] == 55


def test_a_player_without_a_master_row_keeps_snapshot_values_and_extra_rows_are_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dim = dim_player()
    rows = master([{"id": 1.0, "status": "d"}, {"id": 99.0, "status": "u"}])
    with caplog.at_level("WARNING"):
        out = overlay_current_state(dim, rows, BOUNDS)
    assert out.status.tolist() == ["d", "a", "a"]
    assert out.loc[1, OVERLAID].tolist() == dim.loc[1, OVERLAID].tolist()
    assert len(out) == 3 and out.player_id.tolist() == [1, 2, 3]
    assert any("2 players have no master row" in r.message for r in caplog.records)
    # The dtypes survive, so the overlaid table still passes the schema (price_tenths was
    # float64 when a player was missing).
    assert check_table_schema(out, "dim_player") == []
    assert out.price_tenths.dtype == "int64" and out.chance_next.dtype == "Int64"


def test_inputs_are_not_modified() -> None:
    dim, rows = dim_player(), master([{"id": 1.0, "status": "i"}])
    before = dim.copy()
    overlay_current_state(dim, rows, BOUNDS)
    pd.testing.assert_frame_equal(dim, before)


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"now_cost": 54.0}, "now_cost"),
        ({"now_cost": np.nan}, "now_cost"),
        ({"status": None}, "status"),
    ],
)
def test_a_malformed_master_row_fails(change: dict, text: str) -> None:
    rows = master([{"id": 1.0, **change}])
    with pytest.raises(ValidationError, match=text):
        overlay_current_state(dim_player(), rows, BOUNDS)


def test_duplicate_master_keys_fail() -> None:
    rows = master([{"id": 1.0}, {"id": 1.0}])
    with pytest.raises(ValidationError, match="duplicate"):
        overlay_current_state(dim_player(), rows, BOUNDS)


def test_rows_are_matched_by_player_id_not_by_position() -> None:
    rows = master([
        {"id": 1.0, "status": "i", "now_cost": 5.1, "news": "One"},
        {"id": 2.0, "status": "d", "now_cost": 6.2, "news": "Two"},
        {"id": 3.0, "status": "s", "now_cost": 7.3, "news": "Three"},
    ])
    dim = dim_player().iloc[[2, 0, 1]]  # reordered, with an index that is not 0..n-1
    out = overlay_current_state(dim, rows, BOUNDS)
    assert out.index.tolist() == [2, 0, 1] and out.player_id.tolist() == [3, 1, 2]
    assert out.set_index("player_id").status.to_dict() == {1: "i", 2: "d", 3: "s"}
    assert out.set_index("player_id").price_tenths.to_dict() == {1: 51, 2: 62, 3: 73}
    assert out.set_index("player_id").news.to_dict() == {1: "One", 2: "Two", 3: "Three"}
    assert check_table_schema(out.reset_index(drop=True), "dim_player") == []


def test_a_filtered_dim_player_gets_only_its_own_players_values() -> None:
    rows = master([{"id": 1.0, "now_cost": 5.1}, {"id": 2.0, "now_cost": 6.2},
                   {"id": 3.0, "now_cost": 7.3}])
    dim = dim_player().iloc[[2]]  # just player 3, at index 2
    out = overlay_current_state(dim, rows, BOUNDS)
    assert out.player_id.tolist() == [3] and out.price_tenths.tolist() == [73]


def test_duplicate_player_ids_in_dim_player_are_rejected() -> None:
    dim = pd.concat([dim_player(), dim_player().head(1)])
    with pytest.raises(ValidationError, match="duplicate player_id"):
        overlay_current_state(dim, master([{"id": 1.0}]), BOUNDS)
