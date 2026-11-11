"""End-to-end build on the real samples: tables, reconciliation, files on disk."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest
import yaml

from conftest import SAMPLE_DATA
from fpl import run_pipeline
from fpl.clean import build_season
from fpl.ingest import RawSeason
from fpl.reconcile import Reconciliation, ReconciliationError
from fpl.run_pipeline import run, write_season
from fpl.schema import PROCESSED_SCHEMA, check_table_schema
from fpl.validate import ValidationError


def test_every_table_matches_its_schema_in_both_seasons(
    raw_2526: RawSeason, raw_2627: RawSeason, cfg: dict
) -> None:
    for raw in (raw_2526, raw_2627):
        built = build_season(raw, cfg)
        assert set(built.tables) == set(PROCESSED_SCHEMA)
        for name, df in built.tables.items():
            assert check_table_schema(df, name) == [], (raw.season, name)


def test_reconciliation_adds_up_for_every_table_and_season(
    raw_2526: RawSeason, raw_2627: RawSeason, cfg: dict
) -> None:
    for raw in (raw_2526, raw_2627):
        built = build_season(raw, cfg)
        rec = built.reconciliation
        assert set(rec.table) == set(PROCESSED_SCHEMA)
        for table, grp in rec.groupby("table"):
            rows_in = grp.loc[grp.line == "rows_in", "rows"].sum()
            dropped = grp.loc[grp.line == "dropped", "rows"].sum()
            rows_out = grp.loc[grp.line == "rows_out", "rows"].sum()
            assert rows_in - dropped == rows_out, table
            assert rows_out == len(built.tables[table]), table


def test_sample_counts_for_2026_27(raw_2627: RawSeason, cfg: dict) -> None:
    built = build_season(raw_2627, cfg)
    rec = built.reconciliation.set_index(["table", "line", "reason"]).rows
    # 8 matches in the samples (2, 3 and 3 per folder); the 5 finished ones are all complete.
    assert rec[("fact_fixture", "rows_in", "")] == 8
    assert built.tables["fact_fixture"].finished.sum() == 5
    assert built.tables["fact_fixture"].stats_complete.sum() == 5
    # GW1: 80 rows and GW2: 100 rows, all from complete matches.
    assert rec[("fact_player_match", "rows_in", "")] == 180
    assert rec[("fact_player_match", "dropped", "match_not_complete")] == 0
    missing = rec[("fact_player_match", "dropped", "player_not_in_snapshot")]
    assert rec[("fact_player_match", "rows_out", "")] == 180 - missing
    # Player-gameweek rows are all kept: 85 for GW1 and 157 for GW2.
    assert len(built.tables["fact_player_gw"]) == 242


def test_fact_player_gw_team_id_is_the_snapshot_club_and_null_only_without_a_snapshot_row(
    raw_2627: RawSeason, cfg: dict
) -> None:
    built = build_season(raw_2627, cfg).tables
    pgw = built["fact_player_gw"]
    in_snapshot = pgw.merge(
        raw_2627.players.rename(columns={"snapshot_gw": "gw", "player_id": "player_id"}),
        on=["player_id", "gw"], how="left",
    ).team_code.notna()
    assert (pgw.team_id.notna() == in_snapshot.to_numpy()).all()
    assert pgw.team_id.dropna().isin(built["dim_team"].team_id).all()


def test_future_gameweek_matches_are_kept_as_unfinished_with_no_results(
    raw_2627: RawSeason, cfg: dict
) -> None:
    fx = build_season(raw_2627, cfg).tables["fact_fixture"]
    future = fx[fx.gw == 3]
    assert len(future) == 3
    assert not future.finished.any()
    assert future[["home_goals", "away_goals", "home_xg", "away_xg"]].isna().all().all()
    assert future.home_team_id.notna().all()


def test_no_future_stats_reach_the_player_tables(raw_2627: RawSeason, cfg: dict) -> None:
    tables = build_season(raw_2627, cfg).tables
    assert tables["fact_player_gw"].gw.max() == 2
    played = set(tables["fact_fixture"].query("gw <= 2").match_id)
    assert set(tables["fact_player_match"].match_id) <= played


def test_a_failed_guard_stops_the_build(raw_2627: RawSeason, cfg: dict) -> None:
    raw_2627.playermatchstats["tackles_won"] = float("nan")
    with pytest.raises(ValidationError, match="tackles"):
        build_season(raw_2627, cfg)


def test_write_season_writes_parquet_reconciliation_and_manifest(
    raw_2627: RawSeason, cfg: dict, tmp_path: Path
) -> None:
    built = build_season(raw_2627, cfg)
    out = write_season(raw_2627, built, tmp_path)
    assert out == tmp_path / "2026-2027"
    for name in PROCESSED_SCHEMA:
        back = pd.read_parquet(out / f"{name}.parquet")
        assert check_table_schema(back, name) == [], name
        assert len(back) == len(built.tables[name])
    rec = pd.read_csv(out / "reconciliation.csv")
    assert list(rec.columns) == ["season", "table", "line", "reason", "rows"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["upstream_commit"] == "sample"
    assert manifest["latest_gw"] == 2
    assert manifest["rows"]["fact_fixture"] == 8


def make_checkout(tmp_path: Path) -> Path:
    """A git repo holding the real samples, standing in for the upstream checkout."""
    repo = tmp_path / "upstream"
    shutil.copytree(SAMPLE_DATA, repo / "data")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "samples")
    return repo


def test_run_builds_both_seasons_from_a_checkout(cfg: dict, tmp_path: Path) -> None:
    cfg = copy.deepcopy(cfg)
    cfg["upstream"]["checkout_path"] = str(make_checkout(tmp_path))
    cfg["paths"]["processed_dir"] = str(tmp_path / "processed")
    cfg["seasons"][0]["gameweeks"] = 2
    cfg["seasons"][1]["gameweeks"] = 3
    cfg["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    run(cfg, root=tmp_path)
    for season in ("2025-2026", "2026-2027"):
        assert (tmp_path / "processed" / season / "fact_fixture.parquet").exists()
    commit = json.loads(
        (tmp_path / "processed" / "2026-2027" / "manifest.json").read_text(encoding="utf-8")
    )["upstream_commit"]
    assert len(commit) == 40


def test_run_writes_nothing_when_validation_fails(cfg: dict, tmp_path: Path) -> None:
    cfg = copy.deepcopy(cfg)
    cfg["upstream"]["checkout_path"] = str(make_checkout(tmp_path))
    cfg["paths"]["processed_dir"] = str(tmp_path / "processed")
    cfg["seasons"][0]["gameweeks"] = 2
    cfg["seasons"][1]["gameweeks"] = 3
    # The sample is not a full season, so the real bounds (380 Premier League matches) fail.
    with pytest.raises(ValidationError):
        run(cfg, root=tmp_path)
    assert not (tmp_path / "processed").exists()


def test_main_runs_from_a_config_file(
    cfg: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = copy.deepcopy(cfg)
    cfg["upstream"]["checkout_path"] = str(make_checkout(tmp_path))
    cfg["paths"]["processed_dir"] = str(tmp_path / "processed")
    cfg["seasons"][0]["gameweeks"] = 2
    cfg["seasons"][1]["gameweeks"] = 3
    cfg["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    run_pipeline.main(["--config", str(path)])
    assert (tmp_path / "processed" / "2025-2026" / "manifest.json").exists()


def test_a_table_whose_counts_do_not_add_up_is_rejected() -> None:
    rec = Reconciliation("2026-2027")
    rec.add("t", 10, {"a": 3}, 7)
    with pytest.raises(ReconciliationError):
        rec.add("t", 10, {"a": 3}, 8)
    assert set(rec.frame().line) == {"rows_in", "dropped", "rows_out"}


def test_nothing_is_written_when_the_second_season_fails(cfg: dict, tmp_path: Path) -> None:
    cfg = copy.deepcopy(cfg)
    repo = make_checkout(tmp_path)
    cfg["upstream"]["checkout_path"] = str(repo)
    cfg["paths"]["processed_dir"] = str(tmp_path / "processed")
    cfg["seasons"][0]["gameweeks"] = 2
    cfg["seasons"][1]["gameweeks"] = 3
    cfg["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    # 2025-2026 is untouched and passes; 2026-2027 loses a file and fails.
    (repo / "data" / "2026-2027" / "By Gameweek" / "GW2" / "matches.csv").unlink()
    with pytest.raises(ValidationError, match="2026-2027"):
        run(cfg, root=tmp_path)
    assert not (tmp_path / "processed").exists()
