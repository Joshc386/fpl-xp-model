"""The loader fails, with every problem listed, on bad inputs in the folders it reads."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

import synth
from conftest import SAMPLE_DATA, SAMPLE_SEASONS, read_sample
from fpl.features import load_as_of
from fpl.schema import RESULT_COLUMNS
from fpl.validate import ValidationError, validate_inputs

SEASON = synth.SEASON


def copy_cfg(upstream: tuple[Path, dict], tmp_path: Path) -> tuple[Path, dict]:
    root, cfg = upstream
    shutil.copytree(root / "data", tmp_path / "up" / "data")
    folder = tmp_path / "up" / "data" / SEASON / "By Gameweek"
    return folder, {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(tmp_path / "up")}}


def header_only(path: Path) -> None:
    pd.read_csv(path).iloc[0:0].to_csv(path, index=False)


@pytest.mark.parametrize("as_of", [20, 38])
def test_a_header_only_players_file_in_a_folder_read_fails(
    synth_upstream: tuple[Path, dict], tmp_path: Path, as_of: int
) -> None:
    folder, cfg = copy_cfg(synth_upstream, tmp_path)
    header_only(folder / "GW20" / "players.csv")
    with pytest.raises(ValidationError, match=r"players: 20 has 0 rows"):
        load_as_of(SEASON, as_of, "backtest", cfg=cfg)


def test_a_header_only_players_file_that_a_cup_ties_clubs_come_from_fails(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    # cup-late was played in GW2 but is filed in the GW25 folder; its clubs come from GW2's
    # snapshot. The GW25 file is not used for them, but the GW2 one is.
    folder, cfg = copy_cfg(synth_upstream, tmp_path)
    header_only(folder / "GW2" / "players.csv")
    with pytest.raises(ValidationError, match=r"players: 2 has 0 rows"):
        load_as_of(SEASON, 2, "backtest", cfg=cfg)


def test_a_header_only_snapshot_needed_by_a_match_before_any_player_data_fails(
    cfg: dict, tmp_path: Path
) -> None:
    # As-of 1 before upstream writes GW1: no player figures, but the EFL Cup tie played in GW1
    # needs the GW1 players snapshot for its clubs.
    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    folder = data / "2026-2027" / "By Gameweek" / "GW1"
    for name in ("playerstats", "playermatchstats", "player_gameweek_stats", "players"):
        header_only(folder / f"{name}.csv")
    matches = pd.read_csv(folder / "matches.csv")
    matches[RESULT_COLUMNS] = float("nan")
    matches["finished"] = False
    matches.to_csv(folder / "matches.csv", index=False)
    scfg = SAMPLE_SEASONS["2026-2027"]
    small = {**cfg, "validation": {**cfg["validation"], "players_rows_per_snapshot": [1, 1000],
                                   "prem_matches_rows": [1, 380], "matches_rows": [1, 700]}}
    with pytest.raises(ValidationError, match=r"players: 1 has 0 rows"):
        validate_inputs(read_sample(data, scfg, "x", as_of_gw=1), small, scfg)


def test_a_missing_next_gameweek_matches_file_is_a_validation_problem_with_the_others(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    folder, cfg = copy_cfg(synth_upstream, tmp_path)
    (folder / "GW21" / "matches.csv").unlink()
    (folder / "GW5" / "players.csv").unlink()
    with pytest.raises(ValidationError) as exc:
        load_as_of(SEASON, 20, "backtest", cfg=cfg)
    text = "; ".join(exc.value.problems)
    assert "missing file: GW21/matches.csv" in text and "missing file: GW5/players.csv" in text
