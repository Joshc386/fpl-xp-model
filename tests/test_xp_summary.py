"""The xP backtest's summaries on a hand-built scored set: windows, the gate dry run and the
weakest groups."""

from __future__ import annotations

import pandas as pd
import pytest
from backtest.xp_summary import gate_dry_run, headline, weakest_groups, windows

GATE = {"beat_share": 0.6, "calibration_tolerance": 0.3, "calibration_min_count": 2,
        "compare_decimals": 9}
WEAK = {"top_n": 2, "min_rows": 2, "price_edges_tenths": [0, 50, 80],
        "minutes_window": 3, "minutes_edges": [0, 1, 181]}


def scored() -> pd.DataFrame:
    # Three gameweeks of four players. `good` is exact except in GW3; `ep_next` is off by 1.
    rows = []
    for gw in (2, 3, 6):
        for p, pos, price, mins, pts in [(1, "MID", 45, 0, 0), (2, "MID", 90, 270, 6),
                                         (3, "DEF", 55, 200, 2), (4, "FWD", 85, 100, 1)]:
            good = pts + (2 if gw == 3 else 0)
            rows.append({"season": "s", "gw": gw, "player_id": p, "position": pos,
                         "price_tenths": price, "recent_minutes": mins, "points": pts,
                         "ep_next": pts + 1.0, "good": float(good)})
    return pd.DataFrame(rows)


def test_windows_split_early_season_and_late_snapshots() -> None:
    got = windows(scored(), early=(1, 5), late_gws={("s", 3)})
    assert {k: sorted(v.gw.unique()) for k, v in got.items()} == {
        "all": [2, 3, 6], "GW1-5": [2, 3], "GW6+": [6], "pre-deadline snapshots": [2, 6],
        "late snapshots": [3]}


def test_headline_gives_errors_and_the_share_of_gameweeks_beating_ep_next() -> None:
    got = headline(scored(), ["ep_next", "good"]).set_index("predictor")
    assert got.loc["ep_next", "mae"] == pytest.approx(1.0)
    assert got.loc["good", "mae"] == pytest.approx(2 / 3)
    assert got.loc["good", "beats_ep_next"] == pytest.approx(2 / 3)
    assert pd.isna(got.loc["ep_next", "beats_ep_next"])
    assert got.loc["good", "gameweeks"] == 3


def test_gate_dry_run_checks_mae_share_calibration_and_leakage() -> None:
    df = scored()
    got = gate_dry_run(df, "good", GATE, [0, 1, 2, 3, 4, 5, 6, 7, 8], leakage_ok=True)
    assert got["mae_below_ep_next"] and got["beats_share"] == pytest.approx(2 / 3)
    assert got["share_ok"]
    # GW3 puts every bin off by 2/3 on average (counts of 3, over the minimum of 2).
    assert not got["calibration_ok"] and got["calibration_failed_bins"]
    assert not got["passed"]
    assert not gate_dry_run(df.assign(good=df.points.astype(float)), "good", GATE,
                            [0, 8], leakage_ok=False)["passed"]
    assert gate_dry_run(df.assign(good=df.points.astype(float)), "good", GATE, [0, 8],
                        leakage_ok=True)["passed"]


def test_weakest_groups_rank_position_price_and_minutes_bands_by_mae() -> None:
    df = scored().assign(bad=lambda d: d.points + (d.player_id == 2) * 5.0)
    got = weakest_groups(df, "bad", WEAK)
    assert got.iloc[0][["dimension", "group"]].tolist() in (
        ["position", "MID"], ["price band", "£8.0m+"], ["minutes band", "181+"])
    assert len(got) == 2
    assert got.mae.iloc[0] == pytest.approx(2.5)
    assert set(got.columns) >= {"dimension", "group", "n", "mae", "mae_ep_next"}


def test_a_bin_with_exactly_the_minimum_count_carries_the_tolerance() -> None:
    # Two rows in the 0-1 bin (the minimum is 2), each 0.5 under its actual: outside 0.3.
    df = pd.DataFrame({"season": "s", "gw": [1, 1], "player_id": [1, 2], "points": [1, 1],
                       "ep_next": [3.0, 3.0], "good": [0.5, 0.5]})
    got = gate_dry_run(df, "good", GATE, [0, 1], leakage_ok=True)
    assert got["calibration_failed_bins"] == ["0-1"] and not got["calibration_ok"]
    assert gate_dry_run(df, "good", {**GATE, "calibration_min_count": 3}, [0, 1],
                        leakage_ok=True)["calibration_ok"]


def test_a_gap_of_exactly_the_tolerance_passes() -> None:
    df = pd.DataFrame({"season": "s", "gw": [1, 1], "player_id": [1, 2], "points": [1, 1],
                       "ep_next": [3.0, 3.0], "good": [0.7, 0.7]})
    assert gate_dry_run(df, "good", GATE, [0, 1], leakage_ok=True)["calibration_ok"]
