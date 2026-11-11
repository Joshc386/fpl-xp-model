"""Input validation on a part-season read (code review finding 3 of task 1)."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pandas as pd
import pytest

from conftest import SAMPLE_DATA, SAMPLE_SEASONS, read_sample
from fpl.schema import RESULT_COLUMNS
from fpl.validate import ValidationError, validate_inputs


@pytest.fixture
def small_cfg(cfg: dict) -> dict:
    """Config with the player-file bounds relaxed to suit the samples; match bounds stay."""
    out = copy.deepcopy(cfg)
    out["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    return out


def check(season: str, as_of: int | None, small_cfg: dict, **mutate: object) -> str:
    scfg = SAMPLE_SEASONS[season]
    raw = read_sample(SAMPLE_DATA, scfg, commit="x", as_of_gw=as_of)
    for name, value in mutate.items():
        setattr(raw, name, value)
    try:
        validate_inputs(raw, small_cfg, scfg)
    except ValidationError as exc:
        return "; ".join(exc.problems)
    return ""


@pytest.mark.parametrize("season", ["2025-2026", "2026-2027"])
@pytest.mark.parametrize("as_of", [0, 1, 2, 3, None])
def test_every_as_of_read_of_the_samples_passes(season: str, as_of: int | None, small_cfg: dict):
    # Before the fix: the folders after as_of were "missing", and matches counted short.
    assert check(season, as_of, small_cfg) == ""


def test_folders_after_as_of_are_still_required_for_the_schedule(small_cfg: dict) -> None:
    raw = read_sample(SAMPLE_DATA, SAMPLE_SEASONS["2026-2027"], "x", as_of_gw=1)
    raw.matches = raw.matches[raw.matches.snapshot_gw != 3]
    raw.fixture_ids = raw.fixture_ids[raw.fixture_ids.snapshot_gw != 3]
    with pytest.raises(ValidationError, match=r"folder\(s\) \[3\] have no matches"):
        validate_inputs(raw, small_cfg, SAMPLE_SEASONS["2026-2027"])


def test_the_premier_league_schedule_must_still_be_whole_on_an_as_of_read(small_cfg: dict) -> None:
    small_cfg["validation"]["prem_matches_rows"] = [100, 380]  # the samples hold 7
    text = check("2026-2027", 1, small_cfg)
    assert "prem matches: 7 rows" in text
    assert "matches: 8 rows" in text  # later cup matches are left out, so only the floor moves


def test_the_all_competition_upper_bound_still_applies_on_an_as_of_read(small_cfg: dict) -> None:
    small_cfg["validation"]["matches_rows"] = [1, 5]
    assert "matches: 8 rows" in check("2026-2027", 3, small_cfg)
    assert "matches: 8 rows" in check("2026-2027", 1, small_cfg)


def test_a_result_that_reaches_a_later_folder_fails_the_run(small_cfg: dict) -> None:
    scfg = SAMPLE_SEASONS["2025-2026"]
    raw = read_sample(SAMPLE_DATA, scfg, "x", as_of_gw=1)
    later = raw.matches.snapshot_gw == 2
    raw.matches.loc[later, "finished"] = True  # what an un-blanked schedule would look like
    with pytest.raises(ValidationError, match="finished match"):
        validate_inputs(raw, small_cfg, scfg)


def test_gameweek_zero_and_one_before_gw1_is_written_need_no_player_data(
    small_cfg: dict, tmp_path: Path
) -> None:
    assert check("2026-2027", 0, small_cfg) == ""
    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    folder = data / "2026-2027" / "By Gameweek" / "GW1"
    for name in ("playerstats", "playermatchstats", "player_gameweek_stats"):
        pd.read_csv(folder / f"{name}.csv").iloc[0:0].to_csv(folder / f"{name}.csv", index=False)
    matches = pd.read_csv(folder / "matches.csv")
    matches[RESULT_COLUMNS] = float("nan")
    matches["finished"] = False
    matches.to_csv(folder / "matches.csv", index=False)
    scfg = SAMPLE_SEASONS["2026-2027"]
    validate_inputs(read_sample(data, scfg, "x", as_of_gw=1), small_cfg, scfg)  # as-of 1: passes
    with pytest.raises(ValidationError, match="gap"):  # GW1 empty but GW2 played
        validate_inputs(read_sample(data, scfg, "x", as_of_gw=2), small_cfg, scfg)
    with pytest.raises(ValidationError, match="gap"):
        validate_inputs(read_sample(data, scfg, "x"), small_cfg, scfg)
    raw = read_sample(data, scfg, "x", as_of_gw=1)
    raw.as_of_gw = 3  # three folders with no player figures at all is not the first-write gap
    with pytest.raises(ValidationError, match="latest gameweek"):
        validate_inputs(raw, small_cfg, scfg)


def test_finished_cup_matches_and_their_rows_after_the_latest_gameweek_are_normal(
    small_cfg: dict,
) -> None:
    scfg = SAMPLE_SEASONS["2026-2027"]
    raw = read_sample(SAMPLE_DATA, scfg, "x", as_of_gw=1)  # holds the cup tie filed in GW2
    cup = raw.matches[raw.matches.tournament != "prem"]
    assert cup.snapshot_gw.max() > raw.latest_gw and cup.finished.all()
    validate_inputs(raw, small_cfg, scfg)
    raw.gw_rows["playermatchstats"][2] = 40  # but Premier League rows there would not be
    with pytest.raises(ValidationError, match="after the latest"):
        validate_inputs(raw, small_cfg, scfg)


def test_player_bounds_still_apply_to_the_folders_read(small_cfg: dict) -> None:
    small_cfg["validation"]["players_rows_per_snapshot"] = [10_000, 20_000]
    assert "players" in check("2026-2027", 2, small_cfg)
