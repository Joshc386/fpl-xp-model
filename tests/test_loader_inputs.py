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


def postpone_gw12(folder: Path, with_cup: bool) -> None:
    """Move every GW12 league fixture (and its player rows) to GW13, a week later.

    With `with_cup`, GW12's folder keeps one finished cup tie played a day after the original
    first kickoff, as the European ties were in 2022/23's wholly postponed gameweek.
    """
    src, dst = folder / "GW12", folder / "GW13"
    names = ("matches", "fixtures", "playermatchstats")
    m12, f12, p12 = (pd.read_csv(src / f"{n}.csv") for n in names)
    later = (pd.to_datetime(m12.kickoff_time, utc=True) + pd.Timedelta(days=7))
    moved = m12.assign(gameweek=13, kickoff_time=later.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
    for name, extra in (("matches", moved), ("fixtures", f12.assign(gameweek=13)),
                        ("playermatchstats", p12)):
        both = pd.concat([pd.read_csv(dst / f"{name}.csv"), extra])
        both.to_csv(dst / f"{name}.csv", index=False)
    cup = pd.read_csv(folder / "GW10" / "matches.csv").query("match_id == 'cup-10'")
    first = pd.to_datetime(m12.kickoff_time, utc=True).min() + pd.Timedelta(days=1)
    cup = cup.assign(match_id="cup-12", gameweek=12,
                     kickoff_time=first.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
    keep = cup if with_cup else cup.iloc[0:0]
    keep.to_csv(src / "matches.csv", index=False)
    keep[["match_id", "gameweek"]].to_csv(src / "fixtures.csv", index=False)
    header_only(src / "playermatchstats.csv")


def wide_bounds(cfg: dict) -> dict:
    return {**cfg, "validation": {**cfg["validation"], "matches_rows": [76, 90]}}


def test_a_wholly_postponed_gameweek_dates_its_cup_tie_to_it_and_hides_it_before(
    synth_upstream: tuple[Path, dict], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder, cfg = copy_cfg(synth_upstream, tmp_path)
    postpone_gw12(folder, with_cup=True)
    cfg = wide_bounds(cfg)
    with caplog.at_level("WARNING"):
        at12 = load_as_of(SEASON, 12, "backtest", cfg=cfg)["fact_fixture"].set_index("match_id")
        at11 = load_as_of(SEASON, 11, "backtest", cfg=cfg)["fact_fixture"]
    assert at12.loc["cup-12", "gw"] == 12 and at12.loc["cup-12", "finished"]
    assert "cup-12" not in set(at11.match_id)  # not dated a gameweek early, so no result at 11
    assert any("[12]" in r.message and "no Premier League fixture" in r.message
               for r in caplog.records)


def test_a_wholly_postponed_gameweek_with_an_empty_folder_still_loads(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    folder, cfg = copy_cfg(synth_upstream, tmp_path)
    postpone_gw12(folder, with_cup=False)
    cfg = wide_bounds(cfg)
    for as_of in (11, 12, 13):
        fx = load_as_of(SEASON, as_of, "backtest", cfg=cfg)["fact_fixture"]
        assert len(fx[fx.tournament == "prem"]) == 76


def test_one_mis_dated_kickoff_fails_the_read_instead_of_moving_cup_ties(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    folder, cfg = copy_cfg(synth_upstream, tmp_path)
    path = folder / "GW30" / "matches.csv"
    m = pd.read_csv(path)
    m.loc[0, "kickoff_time"] = "2025-09-01T12:00:00+00:00"  # a GW30 fixture dated in September
    m.to_csv(path, index=False)
    for as_of in (9, 29, 30):
        with pytest.raises(ValidationError, match="derived deadline of GW30"):
            load_as_of(SEASON, as_of, "backtest", cfg=cfg)
