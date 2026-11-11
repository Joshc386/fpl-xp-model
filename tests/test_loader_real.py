"""The loader on the real upstream checkout (skipped when data/raw/upstream is not there).

By default a spread of as-of gameweeks is checked; set FPL_FULL_SWEEP=1 for every one.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from fpl.asof import deadlines
from fpl.clean import build_season
from fpl.features import load_as_of
from fpl.ingest import ROOT, RawSeason, load_config, read_season, upstream_data_dir
from fpl.master import read_deadlines
from fpl.overlay import OVERLAID
from fpl.validate import validate_inputs
from leakage import PREM, assert_no_leakage

CFG = load_config(ROOT / "config" / "pipeline.yaml")
DATA = upstream_data_dir(CFG)
OFFSET = CFG["loader"]["deadline_offset_minutes"]
FULL = bool(os.environ.get("FPL_FULL_SWEEP"))
pytestmark = pytest.mark.skipif(
    not (DATA / "2025-2026" / "By Gameweek" / "GW38").exists(), reason="no upstream checkout"
)


def scfg(season: str) -> dict:
    return next(s for s in CFG["seasons"] if s["id"] == season)


def read(season: str, as_of: int | None = None) -> RawSeason:
    return read_season(
        DATA, scfg(season), "x", as_of, prem_tag=CFG["premier_league_tag"], offset_minutes=OFFSET
    )


@pytest.fixture(scope="module")
def full_2526() -> dict[str, pd.DataFrame]:
    return build_season(read("2025-2026"), CFG).tables


@pytest.mark.parametrize("as_of", range(39) if FULL else [0, 1, 2, 5, 9, 10, 25, 37, 38])
def test_real_2025_26_backtest_leaks_nothing_and_matches_the_full_build(
    full_2526: dict, as_of: int
) -> None:
    # load_as_of validates with the real full-season bounds, so a part-season read passing
    # also proves the validation of part-seasons works on real data.
    tables = load_as_of("2025-2026", as_of, "backtest")
    full_fx = full_2526["fact_fixture"]
    assert_no_leakage(tables, as_of, full_fx)
    fx = tables["fact_fixture"]
    shown = fx[~((fx.tournament == PREM) & (fx.gw > as_of))]
    pd.testing.assert_frame_equal(
        shown.reset_index(drop=True),
        full_fx[full_fx.match_id.isin(shown.match_id)].reset_index(drop=True),
    )
    pm, full_pm = tables["fact_player_match"], full_2526["fact_player_match"]
    pd.testing.assert_frame_equal(
        pm.reset_index(drop=True),
        full_pm[full_pm.match_id.isin(shown.match_id)].reset_index(drop=True),
    )
    full = full_2526["fact_player_gw"]
    pd.testing.assert_frame_equal(
        tables["fact_player_gw"].reset_index(drop=True),
        full[full.gw <= as_of].reset_index(drop=True),
    )


@pytest.fixture(scope="module")
def full_2627_fixture() -> pd.DataFrame:
    return build_season(read("2026-2027"), CFG).tables["fact_fixture"]


@pytest.mark.parametrize("as_of", range(11) if FULL else [0, 1, 5, 9, 10])
def test_real_2026_27_backtest_leaks_nothing(full_2627_fixture: pd.DataFrame, as_of: int) -> None:
    assert_no_leakage(load_as_of("2026-2027", as_of, "backtest"), as_of, full_2627_fixture)


def test_real_2026_27_as_of_9_holds_the_cup_matches_played_up_to_gw9() -> None:
    t = load_as_of("2026-2027", 9, "backtest")
    fx, pm = t["fact_fixture"], t["fact_player_match"]
    cup = fx[fx.tournament != PREM]
    assert len(cup) == 65 and cup.stats_complete.all() and (cup.gw <= 9).all()
    assert pm.match_id.isin(cup.match_id).sum() == 1532  # 6 wrong-club and 5 no-snapshot rows go
    # As-of 10 holds the same cup matches: the GW11 folder has none before the GW11 deadline.
    cup10 = load_as_of("2026-2027", 10, "backtest")["fact_fixture"].query("tournament != 'prem'")
    assert len(cup10) == 65 and cup10.finished.all()


def test_real_2025_26_team_elo_is_the_latest_kickoff_value_not_teams_csv() -> None:
    first = load_as_of("2025-2026", 1, "backtest")["dim_team"].set_index("name").upstream_elo
    # teams.csv says 2065 for Arsenal in the GW1 folder; the GW1 kickoff rating is 1993.
    assert first["Arsenal"] != 2065 and first.notna().sum() == 20


def test_real_deadlines_derived_from_the_schedule_match_the_master_file() -> None:
    raw = read("2026-2027")
    master = read_deadlines(DATA / "2026-2027").set_index("id").deadline_time
    derived = deadlines(raw.matches, 38, PREM, OFFSET)
    for gw in range(1, 39):
        assert derived[gw] == pd.Timestamp(master[float(gw)]), gw


def test_real_2025_26_later_folders_really_hold_results() -> None:
    raw = read("2025-2026")  # a full read: nothing blanked
    later = raw.matches[raw.matches.snapshot_gw > 5]
    assert later.finished.sum() > 300 and later.home_score.notna().sum() > 300


@pytest.mark.parametrize("season", ["2025-2026", "2026-2027"])
def test_real_part_season_inputs_validate_at_the_real_bounds(season: str) -> None:
    validate_inputs(read(season, 5), CFG, scfg(season))


@pytest.mark.parametrize("mode", ["backtest", "live"])
def test_real_2026_27_as_of_ahead_of_the_newest_folder(mode: str) -> None:
    ahead = min(read("2026-2027").latest_gw + 3, 38)
    tables = load_as_of("2026-2027", ahead, mode)
    assert_no_leakage(tables, ahead)
    assert tables["fact_player_gw"].gw.max() <= read("2026-2027").latest_gw
    assert tables["fact_player_gw"].team_id.isna().sum() < len(tables["fact_player_gw"]) * 0.01


def test_real_live_mode_overlays_from_the_master_playerstats() -> None:
    back, live = load_as_of("2026-2027", 5, "backtest"), load_as_of("2026-2027", 5, "live")
    other = [c for c in back["dim_player"].columns if c not in OVERLAID]
    pd.testing.assert_frame_equal(back["dim_player"][other], live["dim_player"][other])
    master = pd.read_csv(DATA / "2026-2027" / "playerstats.csv", usecols=["id", "gw", "now_cost"])
    now = master.sort_values("gw").drop_duplicates("id", keep="last").set_index("id").now_cost
    expect = (now.reindex(live["dim_player"].player_id) * 10).round().astype("int64")
    assert live["dim_player"].price_tenths.tolist() == expect.tolist()


def test_real_2025_26_guehi_is_at_palace_for_the_larnaca_tie_at_as_of_8() -> None:
    # The tie is filed in the GW30 folder, whose snapshot has Guehi at Man City after his
    # January move; the snapshot of the gameweek it was played in (8) has him at Palace.
    t = load_as_of("2025-2026", 8, "backtest")
    teams = t["dim_team"].set_index("team_id").name
    pm = t["fact_player_match"]
    row = pm[(pm.match_id == "25-26-conference-league-aek-larnaca-vs-crystal-palace")
             & (pm.player_id == 260)].iloc[0]
    assert teams[row.team_id] == "Crystal Palace" and row.minutes == 90


def test_real_2025_26_as_of_2_team_elo_is_a_league_kickoff_value_not_a_cup_tie() -> None:
    elo = load_as_of("2025-2026", 2, "backtest")["dim_team"].set_index("name").upstream_elo
    assert elo["Bournemouth"] == 1804.01  # its GW2 kickoff; the 26 Aug EFL Cup row said 1871.97
