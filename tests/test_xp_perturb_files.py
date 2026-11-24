"""The extended perturbation: every file the loader reads is corrupted after the as-of
gameweek (and, for the control, up to it), on a copy of the synthetic upstream."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from backtest.elo_check import load_settings
from backtest.perturb import Corruption, copy_upstream, restore_season
from backtest.perturb_files import (
    FileRule,
    corrupt_files_after,
    corrupt_files_up_to,
    file_rules,
)

import synth

SEASON = synth.SEASON
# The harness's own file list and corruption rules (backtest/config.yaml), so the tests check
# the rules a real run uses, and a new upstream file needs no edit here.
PERTURBATION = load_settings()["xp_backtest"]["perturbation"]
FILES = list(PERTURBATION["files"])
RULES = file_rules(PERTURBATION["files"])
C = Corruption((0, 9), (1200.0, 2200.0), (0.0, 4.0), "prem", 90)
BASE = "By Gameweek"


def _shots(match_ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"match_id": match_ids, "shot_index": range(len(match_ids)),
                         "minute": [10 + i for i in range(len(match_ids))],
                         "player_id": [1 + i % 8 for i in range(len(match_ids))],
                         "xg": [0.1 * (1 + i) for i in range(len(match_ids))]})


@pytest.fixture
def copy(synth_upstream: tuple[Path, dict], tmp_path: Path) -> tuple[Path, Path]:
    """The synthetic season copied to `tmp_path`, with shots files added in GW3 and GW25
    (GW25 also files cup-late, played in GW2, so its shot rows are dated before every
    as-of from 2)."""
    src = synth_upstream[0] / "data"
    dst = tmp_path / "data"
    copy_upstream(src, dst, [SEASON], FILES)
    for gw, ids in SHOTS.items():
        _shots(ids).to_csv(dst / SEASON / BASE / f"GW{gw}" / "shots.csv", index=False)
    return src, dst


def read(dst: Path, gw: int, name: str) -> pd.DataFrame:
    return pd.read_csv(dst / SEASON / BASE / f"GW{gw}" / f"{name}.csv", dtype=str,
                       keep_default_na=False)


SHOTS = {3: ["m03-1-3", "m03-1-3"], 25: ["m25-1-2", "cup-late"]}


@pytest.fixture
def original(copy: tuple[Path, Path]) -> Callable[[int, str], pd.DataFrame]:
    """A file as the synthetic upstream (and the added shots) has it."""
    def read_original(gw: int, name: str) -> pd.DataFrame:
        if name == "shots":
            return _shots(SHOTS[gw]).astype(str)
        return read(copy[0], gw, name)

    return read_original


def changed(a: pd.DataFrame, b: pd.DataFrame, cols: list[str]) -> int:
    return int((a[cols].astype(str).to_numpy() != b[cols].astype(str).to_numpy()).sum())


def values(df: pd.DataFrame, rule: FileRule) -> list[str]:
    return [c for c in df.columns if c not in rule.keys and df[c].nunique() > 1]


def test_after_corrupts_every_later_folder_and_keeps_keys(
        copy: tuple[Path, Path], original: Callable[[int, str], pd.DataFrame]) -> None:
    _, dst = copy
    cells = corrupt_files_after(dst, SEASON, 12, np.random.default_rng(1), C, RULES)
    assert cells["player_gameweek_stats"] > 0 and cells["players"] > 0
    # The synthetic season files incidents in every folder: a later one must be corrupted.
    assert cells["incidents"] > 0
    inc_new, inc_old = read(dst, 20, "incidents"), original(20, "incidents")
    keys = [k for k in RULES["incidents"].keys if k in inc_old.columns]  # no index in synth
    assert keys and changed(inc_new, inc_old, keys) == 0
    assert changed(inc_new, inc_old, values(inc_old, RULES["incidents"])) > 0
    assert read(dst, 12, "incidents").equals(original(12, "incidents"))
    # The synthetic teams.csv has key columns only, so it can't change; its keys mustn't.
    for name in ("players", "playerstats", "player_gameweek_stats", "teams"):
        for gw in (13, 20, 38):
            new, old = read(dst, gw, name), original(gw, name)
            rule = RULES[name]
            assert changed(new, old, list(rule.keys)) == 0, (name, gw)
            assert name == "teams" or changed(new, old, values(old, rule)) > 0, (name, gw)
        for gw in (1, 12):
            assert read(dst, gw, name).equals(original(gw, name)), (name, gw)
    assert (read(dst, 13, "players").team_code != original(13, "players").team_code).any()


def test_after_keeps_rows_of_matches_played_before_the_deadline(
        copy: tuple[Path, Path], original: Callable[[int, str], pd.DataFrame]) -> None:
    _, dst = copy
    corrupt_files_after(dst, SEASON, 12, np.random.default_rng(2), C, RULES)
    pms_new, pms_old = read(dst, 25, "playermatchstats"), original(25, "playermatchstats")
    cup = pms_old.match_id == "cup-late"
    assert pms_new[cup].equals(pms_old[cup])
    assert changed(pms_new[~cup], pms_old[~cup], ["minutes_played"]) > 0
    shots, before = read(dst, 25, "shots"), original(25, "shots")
    held = shots.match_id == "cup-late"
    assert shots[held].equals(before[held])
    assert changed(shots[~held], before[~held], ["minute", "xg"]) > 0
    assert read(dst, 3, "shots").equals(original(3, "shots"))


def test_after_corrupts_a_cup_tie_filed_late_but_played_after_the_deadline(
        copy: tuple[Path, Path], original: Callable[[int, str], pd.DataFrame]) -> None:
    # cup-10 is played in GW9 and filed in GW10: at as-of 5 its rows are dated after.
    _, dst = copy
    corrupt_files_after(dst, SEASON, 5, np.random.default_rng(3), C, RULES)
    new, old = read(dst, 10, "playermatchstats"), original(10, "playermatchstats")
    cup = old.match_id == "cup-10"
    assert changed(new[cup], old[cup], ["minutes_played"]) > 0


def test_up_to_corrupts_earlier_folders_but_never_clubs_and_restore_undoes_it(
        copy: tuple[Path, Path], original: Callable[[int, str], pd.DataFrame]) -> None:
    src, dst = copy
    corrupt_files_up_to(dst, SEASON, 12, np.random.default_rng(4), C, RULES)
    for gw in (1, 12):
        new, old = read(dst, gw, "player_gameweek_stats"), original(gw, "player_gameweek_stats")
        assert changed(new, old, ["event_points", "minutes"]) > 0
        assert read(dst, gw, "players").team_code.equals(original(gw, "players").team_code)
    assert read(dst, 3, "shots").minute.tolist() != original(3, "shots").minute.tolist()
    for name in ("player_gameweek_stats", "matches", "playermatchstats"):
        assert read(dst, 13, name).equals(original(13, name))
    restore_season(src, dst, SEASON, FILES)
    assert read(dst, 12, "player_gameweek_stats").equals(original(12, "player_gameweek_stats"))


def test_a_file_without_a_rule_stops_the_corruption(copy: tuple[Path, Path]) -> None:
    _, dst = copy
    with pytest.raises(ValueError, match="no corruption rule for players"):
        corrupt_files_after(dst, SEASON, 12, np.random.default_rng(5), C,
                            {k: v for k, v in RULES.items() if k != "players"})
