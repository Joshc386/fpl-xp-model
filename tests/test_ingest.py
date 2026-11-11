"""Ingestion tests on the real-upstream samples in tests/fixtures/."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import SAMPLE_DATA, SAMPLE_SEASONS, read_sample
from fpl.ingest import (
    IngestError,
    RawSeason,
    read_table,
    read_upstream_commit,
)


def test_load_config_has_both_seasons_and_the_source(cfg: dict) -> None:
    assert [s["id"] for s in cfg["seasons"]] == ["2025-2026", "2026-2027"]
    assert cfg["upstream"]["repo_url"].endswith("FPL-Core-Insights")


def test_read_season_finds_the_latest_played_gameweek(raw_2627: RawSeason) -> None:
    assert raw_2627.latest_gw == 2
    assert raw_2627.season == "2026-2027"
    assert raw_2627.upstream_commit == "sample"


def test_matches_cover_all_folders_but_player_files_stop_at_the_latest_gameweek(
    raw_2627: RawSeason,
) -> None:
    assert sorted(raw_2627.matches.snapshot_gw.unique()) == [1, 2, 3]
    assert sorted(raw_2627.playermatchstats.snapshot_gw.unique()) == [1, 2]
    assert sorted(raw_2627.player_gameweek_stats.snapshot_gw.unique()) == [1, 2]
    assert sorted(raw_2627.players.snapshot_gw.unique()) == [1, 2]


def test_future_folder_matches_are_unplayed_placeholders(raw_2627: RawSeason) -> None:
    future = raw_2627.matches[raw_2627.matches.snapshot_gw == 3]
    assert len(future) == 3
    assert not future.finished.any()
    assert future.home_score.isna().all()


def test_snapshot_tables_come_from_the_latest_folder(raw_2627: RawSeason) -> None:
    assert len(raw_2627.teams) == 20
    assert set(raw_2627.playerstats.id) == set(
        raw_2627.players.query("snapshot_gw == 2").player_id
    )


@pytest.mark.parametrize("season", ["2025-2026", "2026-2027"])
def test_numeric_columns_load_as_float_not_object(season: str) -> None:
    raw = read_sample(SAMPLE_DATA, SAMPLE_SEASONS[season], commit="x")
    for col in ("xg", "xa", "goals", "minutes_played", "saves"):
        assert raw.playermatchstats[col].dtype == "float64", col
    assert raw.matches.finished.dtype == "boolean"


def test_an_empty_future_file_still_loads_with_numeric_dtypes() -> None:
    path = SAMPLE_DATA / "2026-2027" / "By Gameweek" / "GW3" / "playermatchstats.csv"
    df = read_table(path, "playermatchstats")
    assert len(df) == 0
    assert df.xg.dtype == "float64"
    assert df.goals.dtype == "float64"


def test_a_missing_file_is_recorded_not_hidden(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    (data / "2025-2026" / "By Gameweek" / "GW2" / "matches.csv").unlink()
    raw = read_sample(data, SAMPLE_SEASONS["2025-2026"], commit="x")
    assert any("GW2" in f and "matches.csv" in f for f in raw.missing_files)


def test_file_columns_are_recorded_for_the_schema_check(raw_2627: RawSeason) -> None:
    cols = raw_2627.file_columns["GW1/matches.csv"]
    assert "home_team" in cols and "kickoff_time" in cols


def test_read_table_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IngestError):
        read_table(tmp_path / "nope.csv", "matches")


def test_read_upstream_commit_returns_the_head_sha(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    sha = read_upstream_commit(tmp_path)
    assert len(sha) == 40
    assert set(sha) <= set("0123456789abcdef")


def test_read_upstream_commit_fails_outside_a_repo(tmp_path: Path) -> None:
    with pytest.raises(IngestError):
        read_upstream_commit(tmp_path)
