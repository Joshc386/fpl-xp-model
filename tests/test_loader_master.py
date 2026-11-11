"""The loader and the master files: never opened in backtest mode, overlaid in live mode."""

from __future__ import annotations

import builtins
import io
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import synth
from fpl.clock import DeadlineError
from fpl.features import live_gameweeks, load_as_of
from fpl.ingest import IngestError
from fpl.schema import RESULT_COLUMNS
from fpl.validate import ValidationError
from leakage import assert_no_leakage

SEASON = synth.SEASON


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Spy on every file the loader opens: pandas readers, `open` and `io.open`."""
    seen: list[Path] = []
    real_csv, real_parquet = pd.read_csv, pd.read_parquet
    real_open, real_io_open = builtins.open, io.open

    def csv(path: object, *a: object, **k: object) -> pd.DataFrame:
        seen.append(Path(str(path)))
        return real_csv(path, *a, **k)

    def parquet(path: object, *a: object, **k: object) -> pd.DataFrame:
        seen.append(Path(str(path)))
        return real_parquet(path, *a, **k)

    def opener(real: object) -> object:
        def wrapped(file: object, *a: object, **k: object) -> object:
            if isinstance(file, str | Path):
                seen.append(Path(file))
            return real(file, *a, **k)
        return wrapped

    monkeypatch.setattr(pd, "read_csv", csv)
    monkeypatch.setattr(pd, "read_parquet", parquet)
    monkeypatch.setattr(builtins, "open", opener(real_open))
    monkeypatch.setattr(io, "open", opener(real_io_open))
    return seen


def master_reads(seen: list[Path], root: Path) -> list[Path]:
    """Opened files that sit directly in a season folder (data/{season}/*.csv)."""
    season_dir = (root / "data" / SEASON).resolve()
    return [p for p in seen if p.suffix == ".csv" and p.resolve().parent == season_dir]


@pytest.mark.parametrize("as_of", [0, 1, 20, 38])
def test_backtest_mode_never_opens_a_master_file(
    synth_upstream: tuple[Path, dict], opened: list[Path], as_of: int
) -> None:
    root, cfg = synth_upstream
    load_as_of(SEASON, as_of, "backtest", cfg=cfg)
    assert any("By Gameweek" in str(p) for p in opened)  # the spy sees the folder reads
    assert master_reads(opened, root) == []


def test_the_spy_does_catch_a_master_read_in_live_mode(
    synth_upstream: tuple[Path, dict], opened: list[Path]
) -> None:
    root, cfg = synth_upstream
    load_as_of(SEASON, 20, "live", cfg=cfg)
    assert {p.name for p in master_reads(opened, root)} == {"playerstats.csv"}


def test_the_spy_catches_the_deadline_file_in_the_clock(
    synth_upstream: tuple[Path, dict], opened: list[Path]
) -> None:
    root, cfg = synth_upstream
    live_gameweeks(SEASON, datetime(2026, 1, 1, tzinfo=UTC), cfg=cfg)
    assert {p.name for p in master_reads(opened, root)} == {"gameweek_summaries.csv"}


def test_backtest_mode_works_with_every_master_file_deleted(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    root, cfg = synth_upstream
    copy = tmp_path / "up"
    shutil.copytree(root / "data", copy / "data")
    for f in (copy / "data" / SEASON).glob("*.csv"):
        f.unlink()
    cfg = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(copy)}}
    with_master = load_as_of(SEASON, 12, "backtest", cfg=synth_upstream[1])
    without = load_as_of(SEASON, 12, "backtest", cfg=cfg)
    for name in with_master:
        pd.testing.assert_frame_equal(with_master[name], without[name])
    with pytest.raises(IngestError, match="playerstats.csv"):
        load_as_of(SEASON, 12, "live", cfg=cfg)


def truncate_after(season_dir: Path, last_played: int) -> None:
    """Make the folders after `last_played` look as upstream's do before its first write.

    Player figures and Premier League results are not there yet, but cup and European
    matches that were already played are: finished, with their player rows.
    """
    for gw in range(last_played + 1, synth.N_GW + 1):
        folder = season_dir / "By Gameweek" / f"GW{gw}"
        for name in ("playerstats", "player_gameweek_stats"):
            path = folder / f"{name}.csv"
            pd.read_csv(path).iloc[0:0].to_csv(path, index=False)
        pms = pd.read_csv(folder / "playermatchstats.csv")
        pms[pms.match_id.str.startswith("cup")].to_csv(folder / "playermatchstats.csv", index=False)
        matches = pd.read_csv(folder / "matches.csv")
        prem = matches.tournament == "prem"
        matches.loc[prem, RESULT_COLUMNS] = float("nan")
        matches.loc[prem, "finished"] = False
        matches.to_csv(folder / "matches.csv", index=False)


def truncated_cfg(upstream: tuple[Path, dict], tmp_path: Path, last_played: int) -> dict:
    root, cfg = upstream
    shutil.copytree(root / "data", tmp_path / "up" / "data")
    truncate_after(tmp_path / "up" / "data" / SEASON, last_played)
    return {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(tmp_path / "up")}}


@pytest.mark.parametrize("mode", ["backtest", "live"])
def test_as_of_ahead_of_the_newest_folder_with_data_returns_what_exists(
    synth_upstream: tuple[Path, dict], tmp_path: Path, mode: str
) -> None:
    cfg = truncated_cfg(synth_upstream, tmp_path, 20)
    ahead = load_as_of(SEASON, 25, mode, cfg=cfg)
    assert ahead["fact_player_gw"].gw.max() == 20
    assert_no_leakage(ahead, 25)
    fx = ahead["fact_fixture"]
    assert fx[fx.tournament == "prem"].finished[fx.gw > 20].sum() == 0
    assert len(fx) == 78  # 76 Premier League fixtures and both cup matches
    assert ahead["dim_player"].price_tenths.tolist() == (
        [99] * 8 if mode == "live" else [50 + p + 20 for p in synth.PLAYER_CLUB]
    )
    at20 = load_as_of(SEASON, 20, mode, cfg=cfg)
    for name in ("fact_player_gw", "dim_player"):
        pd.testing.assert_frame_equal(ahead[name], at20[name])


@pytest.mark.parametrize("mode", ["backtest", "live"])
def test_between_a_deadline_and_the_first_write_finished_cup_matches_are_normal(
    synth_upstream: tuple[Path, dict], tmp_path: Path, mode: str
) -> None:
    # cup-10 was played before the GW10 deadline and sits in the GW10 folder, which has no
    # player figures yet: a run just after that deadline has as-of 10 and the newest folder 9.
    cfg = truncated_cfg(synth_upstream, tmp_path, 9)
    t = load_as_of(SEASON, 10, mode, cfg=cfg)
    assert t["fact_player_gw"].gw.max() == 9
    fx = t["fact_fixture"].set_index("match_id")
    assert fx.loc["cup-10", ["finished", "stats_complete"]].tolist() == [True, True]
    assert (t["fact_player_match"].match_id == "cup-10").sum() == 2
    gw10 = fx[(fx.tournament == "prem") & (fx.gw == 10)]
    assert len(gw10) == 2 and not gw10.finished.any()
    assert_no_leakage(t, 10)


@pytest.mark.parametrize("mode", ["backtest", "live"])
def test_as_of_one_before_upstream_writes_gw1_returns_the_as_of_zero_tables(
    synth_upstream: tuple[Path, dict], tmp_path: Path, mode: str
) -> None:
    cfg = truncated_cfg(synth_upstream, tmp_path, 0)
    one, zero = load_as_of(SEASON, 1, mode, cfg=cfg), load_as_of(SEASON, 0, mode, cfg=cfg)
    assert one.keys() == zero.keys()
    for name in zero:
        pd.testing.assert_frame_equal(one[name], zero[name])
    assert one["dim_player"].empty and len(one["dim_team"]) == 4


def test_a_finished_premier_league_match_in_the_gap_folder_still_fails_the_run(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    cfg = truncated_cfg(synth_upstream, tmp_path, 9)
    path = tmp_path / "up" / "data" / SEASON / "By Gameweek" / "GW10" / "matches.csv"
    matches = pd.read_csv(path)
    matches.loc[matches.tournament == "prem", "finished"] = True
    matches.to_csv(path, index=False)
    with pytest.raises(ValidationError, match="finished match"):
        load_as_of(SEASON, 10, "backtest", cfg=cfg)


def test_a_failed_check_raises_and_nothing_is_returned(
    synth_upstream: tuple[Path, dict], tmp_path: Path
) -> None:
    root, cfg = synth_upstream
    shutil.copytree(root / "data", tmp_path / "up" / "data")
    (tmp_path / "up" / "data" / SEASON / "By Gameweek" / "GW30" / "fixtures.csv").unlink()
    cfg = {**cfg, "upstream": {**cfg["upstream"], "checkout_path": str(tmp_path / "up")}}
    with pytest.raises(ValidationError, match=r"GW30/fixtures.csv"):
        load_as_of(SEASON, 5, "backtest", cfg=cfg)


def test_live_gameweeks_come_from_the_master_deadlines(synth_upstream: tuple[Path, dict]) -> None:
    _, cfg = synth_upstream
    deadline_12 = synth.FIRST_KICKOFF + pd.Timedelta(days=7 * 12, minutes=-90)
    run = deadline_12.to_pydatetime()
    assert live_gameweeks(SEASON, run - timedelta(seconds=1), cfg=cfg) == (12, 11)
    assert live_gameweeks(SEASON, run, cfg=cfg) == (13, 12)
    assert live_gameweeks(SEASON, datetime(2025, 1, 1, tzinfo=UTC), cfg=cfg) == (1, 0)
    with pytest.raises(DeadlineError):
        live_gameweeks(SEASON, datetime(2026, 6, 1, tzinfo=UTC), cfg=cfg)
