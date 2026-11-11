"""A run between a deadline and upstream's first write, on a sample cut from real upstream.

The sample (tests/fixtures/upstream_gap, see build_gap_fixture.py) is upstream 92a90c26 of
2026-11-06 15:16 UTC, renumbered to three gameweeks: GW1 is the played GW9, GW2 the GW10
folder (cup and European matches finished, with player rows, but no player figures yet) and
GW3 the scheduled GW11. Before the fix a run after the GW10 deadline raised "playermatchstats
rows after the latest gameweek" and "finished match(es) in folders after the latest gameweek".
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl.features import live_gameweeks, load_as_of
from leakage import assert_no_leakage

GAP = Path(__file__).parent / "fixtures" / "upstream_gap"
SEASON = "2026-2027"


@pytest.fixture(scope="module")
def gap_cfg(cfg: dict) -> dict:
    out = copy.deepcopy(cfg)
    out["upstream"].update(checkout_path=str(GAP), data_dir="data")
    out["seasons"] = [{"id": SEASON, "gameweeks": 3, "tackles_column": "tackles_won"}]
    out["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    return out


def at(hour: int, cfg: dict) -> tuple[int, int]:
    return live_gameweeks(SEASON, datetime(2026, 11, 6, hour, 0, tzinfo=UTC), cfg=cfg)


def test_the_two_runs_of_the_real_repro_have_as_of_one_and_two(gap_cfg: dict) -> None:
    assert at(18, gap_cfg) == (2, 1)  # before the 18:30 deadline
    assert at(19, gap_cfg) == (3, 2)  # after it, upstream's GW2 folder not yet written


@pytest.mark.parametrize("mode", ["backtest", "live"])
def test_a_run_after_the_deadline_returns_what_exists(gap_cfg: dict, mode: str) -> None:
    t = load_as_of(SEASON, 2, mode, cfg=gap_cfg)
    assert t["fact_player_gw"].gw.max() == 1
    fx = t["fact_fixture"]
    cup = fx[fx.tournament != "prem"]
    assert len(cup) == 9 and cup.finished.all() and cup.stats_complete.all()
    assert (cup.gw == 1).all()  # played after the GW1 (real GW9) deadline; filed in the GW2 folder
    prem2 = fx[(fx.tournament == "prem") & (fx.gw == 2)]
    assert len(prem2) == 10 and not prem2.finished.any()
    assert t["fact_player_match"].match_id.isin(cup.match_id).sum() > 150
    assert_no_leakage(t, 2)


def test_the_run_before_the_deadline_gives_the_same_cup_matches_and_player_figures(
    gap_cfg: dict,
) -> None:
    before, after = load_as_of(SEASON, 1, "backtest", cfg=gap_cfg), load_as_of(
        SEASON, 2, "backtest", cfg=gap_cfg
    )
    assert before["fact_player_gw"].equals(after["fact_player_gw"])
    # The cup ties were played before the GW2 deadline, so as-of 1 holds them as well.
    assert len(before["fact_fixture"].query("tournament != 'prem'")) == 9
    assert_no_leakage(before, 1)
