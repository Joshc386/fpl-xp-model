"""Ingestion on an as-of read: played folders in full, later folders as schedule only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from conftest import SAMPLE_DATA, SAMPLE_SEASONS, read_sample
from fpl.clean import build_season
from fpl.ingest import IngestError, RawSeason
from fpl.master import read_deadlines, read_master_state
from fpl.schema import RESULT_COLUMNS

SEASON_2526 = SAMPLE_SEASONS["2025-2026"]  # GW1 and GW2, both played and with results
SEASON_2627 = SAMPLE_SEASONS["2026-2027"]  # GW1-GW3, GW3 scheduled only


def read(season: dict, as_of: int | None) -> RawSeason:
    return read_sample(SAMPLE_DATA, season, commit="x", as_of_gw=as_of)


def test_premier_league_player_files_stop_at_the_as_of_gameweek() -> None:
    raw = read(SEASON_2627, 1)
    assert raw.latest_gw == 1 and raw.as_of_gw == 1
    assert raw.player_gameweek_stats.snapshot_gw.max() == 1
    prem = raw.matches.match_id[raw.matches.tournament == "prem"]
    assert raw.playermatchstats[raw.playermatchstats.match_id.isin(prem)].snapshot_gw.max() == 1
    assert (raw.teams.snapshot_gw == 1).all() and (raw.playerstats.snapshot_gw == 1).all()


def test_a_cup_match_played_up_to_as_of_is_held_with_its_played_gameweek_and_clubs() -> None:
    # The GW2 folder files an EFL Cup tie played on 25 Aug: after the GW1 deadline (21 Aug
    # 17:30) and before GW2's (30 Aug 11:30). It was played in GW1.
    raw = read(SEASON_2627, 1)
    cup = raw.matches[raw.matches.tournament != "prem"]
    assert cup.snapshot_gw.tolist() == [2] and cup.gameweek.tolist() == [1] and cup.finished.all()
    rows = raw.playermatchstats[raw.playermatchstats.match_id.isin(cup.match_id)]
    # The rows are read from the GW2 folder but their clubs come from the GW1 snapshot.
    assert len(rows) > 0 and set(rows.snapshot_gw) == {1}
    assert raw.file_columns["GW2/playermatchstats.csv"]
    assert "GW2/players.csv" not in raw.file_columns  # the GW1 snapshot is enough


def test_later_premier_league_matches_are_blanked_and_later_cup_matches_are_left_out() -> None:
    full, early = read(SEASON_2526, None), read(SEASON_2526, 1)
    real = full.matches[full.matches.snapshot_gw == 2]
    later = early.matches[early.matches.snapshot_gw == 2]
    assert real.finished.any() and real[RESULT_COLUMNS].notna().any().any()  # it has results
    assert (real.tournament != "prem").any()
    # The EFL Cup tie (27 Aug) kicks off after GW2's cutoff (23 Aug 12:30): left out entirely.
    assert (later.tournament == "prem").all()
    prem = real[real.tournament == "prem"]
    assert later.match_id.tolist() == prem.match_id.tolist()
    assert later.kickoff_time.tolist() == prem.kickoff_time.tolist()
    assert not later.finished.any() and later[RESULT_COLUMNS].isna().all().all()
    assert early.matches[early.matches.snapshot_gw == 1].finished.any()  # as-of folder untouched
    assert not early.fixture_ids.match_id.str.contains("efl-cup").any()
    assert early.playermatchstats.snapshot_gw.max() == 1


def test_a_cup_match_in_a_folder_up_to_as_of_but_after_the_cutoff_is_left_out() -> None:
    raw = read(SEASON_2526, 1)  # no cup match, though the sample folder 1 has none
    full = read(SEASON_2526, None)
    cup = full.matches[full.matches.tournament != "prem"].iloc[0]
    assert cup.match_id not in set(raw.matches.match_id)
    assert cup.match_id not in set(raw.playermatchstats.match_id)


def test_the_schedule_covers_the_whole_premier_league_season() -> None:
    early, full = read(SEASON_2627, 1), read(SEASON_2627, None)
    pl = lambda r: r.matches[r.matches.tournament == "prem"].match_id.tolist()  # noqa: E731
    assert pl(early) == pl(full)
    assert early.missing_files == []
    assert "GW3/matches.csv" in early.file_columns
    assert "GW3/playermatchstats.csv" not in early.file_columns


def test_at_the_last_gameweek_every_match_counts() -> None:
    assert len(read(SEASON_2526, 2).matches) == len(read(SEASON_2526, None).matches) == 5
    assert len(read(SEASON_2526, 99).matches) == 5


def test_as_of_zero_has_the_premier_league_schedule_and_the_clubs_only() -> None:
    raw = read(SEASON_2526, 0)
    assert raw.latest_gw == 0
    assert raw.players.empty and raw.playermatchstats.empty and raw.player_gameweek_stats.empty
    assert raw.playerstats.empty
    assert raw.matches.tournament.eq("prem").all() and len(raw.matches) == 4
    assert not raw.matches.finished.any()
    assert len(raw.teams) == 20
    assert "GW1/teams.csv" in raw.file_columns


def test_as_of_one_before_gw1_is_written_has_no_playerstats_but_the_clubs(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    folder = data / "2026-2027" / "By Gameweek" / "GW1"
    for name in ("playerstats", "playermatchstats", "player_gameweek_stats"):
        pd.read_csv(folder / f"{name}.csv").iloc[0:0].to_csv(folder / f"{name}.csv", index=False)
    raw = read_sample(data, SEASON_2627, as_of_gw=1)
    assert raw.latest_gw == 0 and len(raw.teams) == 20 and raw.playerstats.empty
    assert set(raw.players.snapshot_gw) <= {1}  # only the snapshot the held cup rows need


def test_a_missing_schedule_file_is_recorded(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    (data / "2026-2027" / "By Gameweek" / "GW3" / "fixtures.csv").unlink()
    raw = read_sample(data, SEASON_2627, commit="x", as_of_gw=1)
    assert raw.missing_files == ["GW3/fixtures.csv"]


def test_as_of_past_the_last_gameweek_reads_the_whole_season() -> None:
    raw = read(SEASON_2627, 99)
    full = read(SEASON_2627, None)
    assert raw.latest_gw == 2 and raw.matches.finished.sum() == full.matches.finished.sum()


def test_a_negative_as_of_gameweek_is_rejected() -> None:
    with pytest.raises(ValueError, match="as_of_gw"):
        read(SEASON_2627, -1)


def test_master_readers_return_the_required_columns(tmp_path: Path) -> None:
    (tmp_path / "gameweek_summaries.csv").write_text(
        "id,name,deadline_time\n1,Gameweek 1,2026-08-21T17:30:00+00:00\n", encoding="utf-8"
    )
    (tmp_path / "playerstats.csv").write_text(
        "id,gw,status,news,now_cost,chance_of_playing_next_round,selected_by_percent,"
        "penalties_order,direct_freekicks_order,corners_and_indirect_freekicks_order,ep_next\n"
        "5,3,a,,5.5,,1.0,,,,2.0\n", encoding="utf-8",
    )
    assert read_deadlines(tmp_path).to_dict("records") == [
        {"deadline_time": "2026-08-21T17:30:00+00:00", "id": 1.0}
    ]
    state = read_master_state(tmp_path)
    assert state.loc[0, ["id", "gw", "now_cost"]].tolist() == [5.0, 3.0, 5.5]


def test_a_master_file_missing_a_column_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "gameweek_summaries.csv").write_text("id,name\n1,x\n", encoding="utf-8")
    with pytest.raises(IngestError, match="deadline_time"):
        read_deadlines(tmp_path)


def test_a_gameweek_0_cup_match_is_held_at_as_of_0_with_clubs_from_the_gw1_snapshot(
    tmp_path: Path, cfg: dict
) -> None:
    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    path = data / "2026-2027" / "By Gameweek" / "GW2" / "matches.csv"
    m = pd.read_csv(path)
    cup = m.tournament != "prem"
    m.loc[cup, "kickoff_time"] = "2026-08-15T18:45:00"  # before the GW1 deadline (21 Aug 17:30)
    m.to_csv(path, index=False)
    raw = read_sample(data, SEASON_2627, as_of_gw=0)
    held = raw.matches[raw.matches.tournament != "prem"]
    assert held.gameweek.tolist() == [0] and held.snapshot_gw.tolist() == [2]
    rows = raw.playermatchstats
    assert len(rows) > 0 and set(rows.snapshot_gw) == {1}  # GW0 uses the GW1 snapshot
    assert set(raw.players.snapshot_gw) == {1}
    tables = build_season(raw, {**cfg, "seasons": [SEASON_2627 | {"id": "2026-2027"}]}).tables
    assert len(tables["fact_player_match"]) > 0 and tables["fact_fixture"].gw.min() == 0
