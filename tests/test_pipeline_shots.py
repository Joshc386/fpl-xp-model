"""The shot checks against matches.csv: `run_pipeline` runs them, `load_as_of` never does."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pandas as pd
import pytest

import synth
from fpl.clean import build_season, build_spells
from fpl.features import load_as_of
from fpl.ingest import RawSeason
from fpl.matchcheck import check_against_matches
from fpl.run_pipeline import run
from fpl.validate import ValidationError
from test_pipeline import make_checkout

NEW = ("fact_shot", "fact_player_spell")


def sample_cfg(cfg: dict, tmp_path: Path) -> dict:
    """The config pointed at a checkout of the real samples, with bounds sized to them."""
    out = copy.deepcopy(cfg)
    out["upstream"]["checkout_path"] = str(make_checkout(tmp_path))
    out["paths"]["processed_dir"] = str(tmp_path / "processed")
    out["seasons"][0]["gameweeks"] = 2
    out["seasons"][1]["gameweeks"] = 3
    out["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    # The samples hold a handful of matches, so the season ratio of shot xG to team xG is noisy.
    out["shot_reconciliation"]["team_xg_season_ratio"] = [0.5, 1.5]
    return out


def test_run_writes_the_shot_and_spell_tables_and_logs_the_build_checks(
    cfg: dict, tmp_path: Path
) -> None:
    out = run(sample_cfg(cfg, tmp_path), root=tmp_path)
    for season, path in out.items():
        for name in NEW:
            assert len(pd.read_parquet(path / f"{name}.parquet")) > 0, (season, name)
        rec = pd.read_csv(path / "reconciliation.csv")
        info = rec[(rec.table == "fact_shot") & (rec.line == "info")]
        for reason in ("penalty_xg_mismatch", "shot_count_mismatch", "goals_mismatch",
                       "team_xg_mismatch"):
            assert int(info[info.reason == f"match_check_{reason}"].rows.iloc[0]) == 0
        # every drop and count reason is listed, zeros included
        lines = rec[rec.table.isin(NEW)]
        assert {"match_not_premier_league", "match_not_complete", "no_minutes",
                "match_has_no_kickoff_time"} <= set(lines.reason)
        assert {"player_blank", "own_goal", "spell_repaired", "starters_over_11"} <= set(
            lines.reason)


@pytest.mark.parametrize(("column", "reason"), [
    ("home_total_shots", "shot_count_mismatch"),
    ("home_expected_goals_xg", "team_xg_mismatch"),
    ("home_score", "goals_mismatch"),
])
def test_run_fails_and_writes_nothing_when_matches_csv_disagrees_with_the_shots(
    cfg: dict, tmp_path: Path, column: str, reason: str
) -> None:
    config = sample_cfg(cfg, tmp_path)
    path = tmp_path / "upstream" / "data" / "2026-2027" / "By Gameweek" / "GW1" / "matches.csv"
    df = pd.read_csv(path)
    prem = df[df.tournament == "prem"].index[0]
    df.loc[prem, column] = df.loc[prem, column] + 30  # far beyond any tolerance
    if column == "home_expected_goals_xg":
        df.loc[prem, "home_non_penalty_xg"] += 30
    df.to_csv(path, index=False)
    with pytest.raises(ValidationError, match=reason):
        run(config, root=tmp_path)
    assert not (tmp_path / "processed").exists()


def test_load_as_of_does_not_run_the_matches_csv_checks(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    """The perturbation test's corrupted copy: wrong scores, xG and shot counts in the read."""
    root, cfg = synth_upstream
    copy_root = tmp_path / "up"
    shutil.copytree(root / "data", copy_root / "data")
    for gw in range(1, 4):
        path = copy_root / "data" / synth.SEASON / "By Gameweek" / f"GW{gw}" / "matches.csv"
        df = pd.read_csv(path)
        for col in ("home_score", "away_score", "home_expected_goals_xg",
                    "away_expected_goals_xg", "home_total_shots"):
            df[col] = df[col] + 40
        df.to_csv(path, index=False)
    cfg2 = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(copy_root)}}
    tables = load_as_of(synth.SEASON, 3, "backtest", cfg=cfg2)  # reads fine
    assert len(tables["fact_shot"]) > 0
    # ... and the build-only checks would have failed on it, which is why they stay out.
    raw = pd.concat([pd.read_csv(copy_root / "data" / synth.SEASON / "By Gameweek" / f"GW{g}" /
                                 "matches.csv") for g in (1, 2, 3)])
    problems, counts = check_against_matches(tables, raw, cfg2)
    assert problems and counts["shot_count_mismatch"] > 0 and counts["goals_mismatch"] > 0


def test_the_repair_tolerance_is_read_from_the_config(raw_2627: RawSeason, cfg: dict) -> None:
    """With a tolerance of 0 every one-minute gap is repaired; with 1,000 none is."""
    tables = build_season(raw_2627, cfg).tables
    scfg = next(s for s in cfg["seasons"] if s["id"] == raw_2627.season)

    def repaired(tolerance: float) -> int:
        c = copy.deepcopy(cfg)
        c["spells"]["minutes_tolerance"] = tolerance
        spells, _ = build_spells(
            tables["fact_player_match"], tables["fact_fixture"], raw_2627, scfg, c)
        return int(spells.spell_repaired.sum())

    assert repaired(1000) == 0
    assert repaired(0) > repaired(2) >= 0


def test_the_approved_tolerances_are_pinned(cfg: dict) -> None:
    """Two minutes per row and per player-gameweek (decided 2026-11-23); a change is a decision."""
    assert cfg["spells"]["minutes_tolerance"] == 2
    assert cfg["spells"]["gw_minutes_tolerance"] == 2
