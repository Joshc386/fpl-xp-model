"""The loader and the shot and spell tables: nothing from a match outside the read."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

import synth
from conftest import read_sample
from fpl.clean import build_season
from fpl.features import load_as_of
from fpl.schema import PROCESSED_SCHEMA
from fpl.validate import ValidationError
from leakage import assert_no_leakage
from test_loader import SCFG
from test_loader_master import opened  # noqa: F401  (the spy fixture)

SEASON = synth.SEASON
NEW = ("fact_shot", "fact_player_spell")


@pytest.fixture(scope="module")
def full(synth_upstream: tuple[Path, dict]) -> dict[str, pd.DataFrame]:
    """The whole season built at once: what every read's rows must be a subset of."""
    root, cfg = synth_upstream
    return build_season(read_sample(root / "data", SCFG), cfg).tables


def folder_of(path: Path) -> int:
    return int(re.search(r"GW(\d+)", str(path)).group(1))


@pytest.mark.parametrize("as_of", [0, 1, 7, 20])
def test_backtest_mode_never_opens_a_later_folders_shots_or_incidents(
    synth_upstream: tuple[Path, dict], opened: list[Path], as_of: int  # noqa: F811
) -> None:
    load_as_of(SEASON, as_of, "backtest", cfg=synth_upstream[1])
    late = [p for p in opened if p.name in ("shots.csv", "incidents.csv") and folder_of(p) > as_of]
    assert late == []
    if as_of >= 1:  # the spy does see the files it must see
        assert {p.name for p in opened} >= {"shots.csv", "incidents.csv"}


def test_the_spy_catches_a_shots_read_from_the_read_folders(
    synth_upstream: tuple[Path, dict], opened: list[Path]  # noqa: F811
) -> None:
    load_as_of(SEASON, 7, "backtest", cfg=synth_upstream[1])
    got = {folder_of(p) for p in opened if p.name == "shots.csv"}
    assert got == set(range(1, 8))


@pytest.mark.parametrize("as_of", [0, 1, 5, 7, 20, 37, 38])
def test_no_shot_or_spell_from_a_match_outside_the_read(
    synth_load: Callable, full: dict[str, pd.DataFrame], as_of: int
) -> None:
    tables = synth_load(as_of, "backtest")
    assert_no_leakage(tables, as_of, full["fact_fixture"])
    fx = full["fact_fixture"].set_index("match_id")
    for name in NEW:
        got = tables[name]
        assert (fx.gw[got.match_id.unique()] <= as_of).all(), name
        rows = full[name][full[name].match_id.isin(fx.index[fx.gw <= as_of])]
        pd.testing.assert_frame_equal(got.reset_index(drop=True), rows.reset_index(drop=True))
        assert as_of == 0 or len(got) > 0


def test_the_full_season_has_shots_and_spells_after_every_as_of_so_the_checks_are_not_vacuous(
    full: dict[str, pd.DataFrame],
) -> None:
    fx = full["fact_fixture"]
    for name in NEW:
        gws = fx.set_index("match_id").gw[full[name].match_id.unique()]
        assert gws.min() == 1 and gws.max() == synth.N_GW


@pytest.mark.parametrize("mode", ["backtest", "live"])
def test_both_new_tables_are_empty_at_as_of_0_with_the_contract_columns(
    synth_load: Callable, mode: str
) -> None:
    tables = synth_load(0, mode)
    for name in NEW:
        assert tables[name].empty
        assert list(tables[name].columns) == [c for c, _, _ in PROCESSED_SCHEMA[name]]


@pytest.mark.parametrize("as_of", [1, 7, 38])
def test_backtest_and_live_return_the_same_shots_and_spells(
    synth_load: Callable, as_of: int
) -> None:
    back, live = synth_load(as_of, "backtest"), synth_load(as_of, "live")
    assert set(back) == set(live) == set(PROCESSED_SCHEMA)
    for name in NEW:
        pd.testing.assert_frame_equal(back[name], live[name])


def test_a_later_folders_shots_and_incidents_can_be_poisoned_or_deleted_without_a_change(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    root, cfg = synth_upstream
    copy = tmp_path / "up"
    shutil.copytree(root / "data", copy / "data")
    for gw in range(13, synth.N_GW + 1):
        folder = copy / "data" / SEASON / "By Gameweek" / f"GW{gw}"
        (folder / "shots.csv").write_text("garbage,not,a,shots,file\n1,2\n", encoding="utf-8")
        (folder / "incidents.csv").unlink()
    cfg2 = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(copy)}}
    before = load_as_of(SEASON, 12, "backtest", cfg=cfg)
    after = load_as_of(SEASON, 12, "backtest", cfg=cfg2)
    for name in before:
        pd.testing.assert_frame_equal(before[name], after[name])


def test_a_missing_shots_file_in_a_read_folder_fails_the_read(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    root, cfg = synth_upstream
    copy = tmp_path / "up"
    shutil.copytree(root / "data", copy / "data")
    (copy / "data" / SEASON / "By Gameweek" / "GW3" / "shots.csv").unlink()
    cfg2 = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(copy)}}
    with pytest.raises(ValidationError, match="shots.csv"):
        load_as_of(SEASON, 5, "backtest", cfg=cfg2)
    load_as_of(SEASON, 2, "backtest", cfg=cfg2)  # GW3 is not in a read that stops at GW2


def test_a_failing_every_read_check_fails_the_read_that_holds_the_fault(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    """A new `situation` in GW3's shots fails a read that includes GW3, and no earlier one."""
    root, cfg = synth_upstream
    copy = tmp_path / "up"
    shutil.copytree(root / "data", copy / "data")
    path = copy / "data" / SEASON / "By Gameweek" / "GW3" / "shots.csv"
    shots = pd.read_csv(path)
    shots.loc[0, "situation"] = "volley"
    shots.to_csv(path, index=False)
    cfg2 = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(copy)}}
    with pytest.raises(ValidationError, match="volley"):
        load_as_of(SEASON, 5, "backtest", cfg=cfg2)
    load_as_of(SEASON, 2, "backtest", cfg=cfg2)


def test_a_capped_count_over_its_cap_also_fails_the_read(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    """The cap problems reach the loader too (the term `+ spell_problems` in `build_season`)."""
    root, cfg = synth_upstream
    strict = {**cfg, "spells": {**cfg["spells"], "max_shooter_off_pitch":
                                {"share": 0.0, "always_allowed": 0}}}
    copy = tmp_path / "up"
    shutil.copytree(root / "data", copy / "data")
    path = copy / "data" / SEASON / "By Gameweek" / "GW3" / "shots.csv"
    shots = pd.read_csv(path)
    shots["minute"] = 90  # past the substitution at 61 or 76 of any shooter who has one
    shots["added_time"] = 5
    shots.to_csv(path, index=False)
    cfg2 = {**strict, "upstream": {**cfg["upstream"], "checkout_path": str(copy)}}
    load_as_of(SEASON, 2, "backtest", cfg=cfg2)
    with pytest.raises(ValidationError, match="shooter_off_pitch"):
        load_as_of(SEASON, 5, "backtest", cfg=cfg2)


def test_shots_of_a_late_cup_tie_filed_in_an_earlier_folder_are_left_out_of_the_read(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    """cup-10 is played in GW9, so a read at 5 leaves it out; its shots rows in GW3's file must be
    dropped with it, not reported as shots of an unknown match."""
    root, cfg = synth_upstream
    copy = tmp_path / "up"
    shutil.copytree(root / "data", copy / "data")
    path = copy / "data" / SEASON / "By Gameweek" / "GW3" / "shots.csv"
    shots = pd.read_csv(path)
    pd.concat([shots, shots.head(2).assign(match_id="cup-10")]).to_csv(path, index=False)
    cfg2 = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(copy)}}
    before = load_as_of(SEASON, 5, "backtest", cfg=cfg)
    after = load_as_of(SEASON, 5, "backtest", cfg=cfg2)  # no ValidationError
    for name in before:
        pd.testing.assert_frame_equal(before[name], after[name])
    assert "cup-10" not in set(after["fact_shot"].match_id)
