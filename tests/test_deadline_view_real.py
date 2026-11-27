"""The pre-deadline view on the real upstream checkout (skipped when there is none).

The view is built once into a scratch folder and checked against an independent reading of the
history: `git rev-list`, `git show`, FPL's `deadline_time` and the contract's rules by hand.
Counts that depend on upstream's history are those at the pinned checkout `ac8be9c`.
"""

from __future__ import annotations

import functools
import io
import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from backtest.xp_reads import forbid_reads

from fpl.deadline_view import ViewError
from fpl.features import load_as_of, use_data_copy
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.pre_deadline import build_views
from fpl.view_checkout import copy_view, head_commit

CFG = load_config(ROOT / "config" / "pipeline.yaml")
CHECKOUT = ROOT / CFG["upstream"]["checkout_path"]
DATA = upstream_data_dir(CFG)
PINNED = "ac8be9caa3bce7aa6c2b73d5a33a9f5c0b2f0e41"
SEASONS = ("2025-2026", "2026-2027")
POSITION = {"Goalkeeper": "GKP", "Defender": "DEF", "Midfielder": "MID", "Forward": "FWD"}
pytestmark = pytest.mark.skipif(
    not (DATA / "2025-2026" / "By Gameweek" / "GW38").exists(), reason="no upstream checkout"
)


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(CHECKOUT), *args], capture_output=True,
                          check=True).stdout


def show(commit: str, rel: str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(git("show", f"{commit}:{rel}")), low_memory=False)


def head() -> str:
    return git("rev-parse", "HEAD").decode().strip()


@pytest.fixture(scope="module")
def view_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pre_deadline")
    build_views(CHECKOUT, CFG, out)
    return out


@pytest.fixture(scope="module")
def cfg(view_dir: Path) -> dict:
    """The real config reading the scratch view."""
    return {**CFG, "paths": {**CFG["paths"], "pre_deadline_dir": str(view_dir)}}


def view_of(view_dir: Path, season: str) -> pd.DataFrame:
    return pd.read_parquet(view_dir / f"{season}.parquet")


@functools.cache
def fpl_summaries(season: str) -> pd.DataFrame:
    return show(head(), f"data/{season}/gameweek_summaries.csv").set_index("id")


def fpl_deadline(season: str, gw: int) -> pd.Timestamp:
    """FPL's own deadline for `gw`, from the master gameweek_summaries.csv (an independent
    source: the builder derives deadlines from the schedule)."""
    return pd.Timestamp(fpl_summaries(season).deadline_time[gw]).tz_convert("UTC")


def last_commit_before(deadline: pd.Timestamp) -> str:
    """The newest commit on the first-parent line strictly before `deadline` (git's own
    `--before` is inclusive, so the cutoff is a second earlier)."""
    cutoff = (deadline - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return git("rev-list", "--first-parent", "-n", "1", f"--before={cutoff}",
               "HEAD").decode().strip()


@functools.cache
def expected_rows(season: str, commit: str) -> pd.DataFrame:
    """The cleaning rules of the contract applied by hand to the commit's master files."""
    players = show(commit, f"data/{season}/players.csv")
    stats = show(commit, f"data/{season}/playerstats.csv")
    stats = stats.sort_values("gw").groupby("id").tail(1)[[
        "id", "status", "chance_of_playing_next_round", "now_cost", "selected_by_percent",
        "penalties_order", "direct_freekicks_order", "corners_and_indirect_freekicks_order",
        "ep_next", "cost_change_start", "cost_change_event", "transfers_in_event",
        "transfers_out_event", "news"]]
    teams = show(head(), f"data/{season}/By Gameweek/GW1/teams.csv")
    df = players.merge(stats, left_on="player_id", right_on="id", how="inner")
    team = df.team_code.map(dict(zip(teams.code, teams.id, strict=True)))  # code, never id
    out = pd.DataFrame({
        "player_id": df.player_id, "player_code": df.player_code, "web_name": df.web_name,
        "team_id": team, "position": df.position.map(POSITION),
        "price_tenths": (df.now_cost * 10).round(), "status": df.status,
        "chance_next": df.chance_of_playing_next_round, "news": df.news,
        "selected_pct": df.selected_by_percent, "pen_order": df.penalties_order,
        "fk_order": df.direct_freekicks_order,
        "corner_order": df.corners_and_indirect_freekicks_order, "ep_next": df.ep_next,
        "price_change_start_tenths": df.cost_change_start,
        "price_change_gw_tenths": df.cost_change_event, "transfers_in_gw": df.transfers_in_event,
        "transfers_out_gw": df.transfers_out_event,
    })
    return out.sort_values("player_id").reset_index(drop=True)


def assert_same(got: pd.DataFrame, want: pd.DataFrame) -> None:
    got = got.sort_values("player_id").reset_index(drop=True)
    assert list(got.player_id) == list(want.player_id)
    for col in want.columns:
        pd.testing.assert_series_equal(
            got[col].astype(object).where(got[col].notna(), np.nan).astype("float64")
            if want[col].dtype.kind in "fi" else got[col].astype(object),
            want[col].astype("float64") if want[col].dtype.kind in "fi" else want[col],
            check_dtype=False, check_names=False, obj=col,
        )


ALL = [(season, gw) for season in SEASONS for gw in range(2, 39)]


@pytest.mark.parametrize(("season", "gw"), ALL)
def test_each_record_equals_the_cleaning_rules_applied_to_its_commits_master_files(
    view_dir: Path, season: str, gw: int
) -> None:
    """Every gameweek of both seasons: the commit is the one a first-parent `git rev-list`
    finds from FPL's own deadline, and the rows are the contract's rules over its `git show`."""
    rows = view_of(view_dir, season)
    rows = rows[rows.gw == gw]
    commit = last_commit_before(fpl_deadline(season, gw))
    assert set(rows.upstream_commit) == {commit}
    assert set(rows.deadline_utc) == {fpl_deadline(season, gw).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert_same(rows, expected_rows(season, commit))


@pytest.mark.parametrize("season", SEASONS)
def test_no_record_comes_from_a_commit_after_its_deadline(view_dir: Path, season: str) -> None:
    view = view_of(view_dir, season)
    assert sorted(view.gw.unique()) == list(range(2, 39))
    for gw, rows in view.groupby("gw"):
        deadline = fpl_deadline(season, gw)
        assert (pd.to_datetime(rows.commit_utc, utc=True) < deadline).all(), (season, gw)
        assert (pd.to_datetime(rows.deadline_utc, utc=True) <= deadline).all(), (season, gw)


def test_every_commit_used_is_on_the_first_parent_line(view_dir: Path) -> None:
    line = set(git("rev-list", "--first-parent", "HEAD").decode().split())
    for season in SEASONS:
        assert set(view_of(view_dir, season).upstream_commit) <= line


def test_the_commit_time_recorded_is_the_commits_own(view_dir: Path) -> None:
    one = view_of(view_dir, "2025-2026").query("gw == 3").iloc[0]
    stamp = pd.Timestamp(git("log", "-1", "--format=%cI", one.upstream_commit).decode().strip())
    assert stamp.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") == one.commit_utc


@pytest.mark.parametrize(("season", "gw"), [("2025-2026", 3), ("2025-2026", 4)])
def test_the_master_files_differ_from_the_gameweek_folder_where_upstream_rewrote_it(
    view_dir: Path, season: str, gw: int
) -> None:
    # Without a difference the equality tests above wouldn't show the view isn't the snapshot.
    rows = view_of(view_dir, season)
    rows = rows[rows.gw == gw].set_index("player_id")
    folder = pd.read_csv(DATA / season / "By Gameweek" / f"GW{gw - 1}" / "playerstats.csv",
                         usecols=["id", "status", "now_cost", "ep_next"]).set_index("id")
    both = rows.index.intersection(folder.index)
    assert (rows.loc[both, "status"] != folder.loc[both, "status"]).sum() > 0
    assert (rows.loc[both, "ep_next"] != folder.loc[both, "ep_next"]).sum() > 0


@pytest.mark.skipif(head() != PINNED, reason="counts are those at upstream ac8be9c")
def test_gameweeks_after_the_checkouts_last_commit_are_flagged_at_the_pinned_checkout(
    view_dir: Path
) -> None:
    flagged = {s: sorted(view_of(view_dir, s).query("checkout_ends_early").gw.unique())
               for s in SEASONS}
    assert flagged["2025-2026"] == []
    assert flagged["2026-2027"] == list(range(11, 39))
    newest = pd.Timestamp(git("log", "-1", "--format=%cI").decode().strip())
    rows = view_of(view_dir, "2026-2027")
    assert set(rows[rows.checkout_ends_early].upstream_commit) == {PINNED}
    assert fpl_deadline("2026-2027", 11) > newest
    assert not rows[rows.gw == 10].checkout_ends_early.any()


@pytest.mark.skipif(head() != PINNED, reason="counts are those at upstream ac8be9c")
def test_the_row_counts_at_the_pinned_checkout(view_dir: Path) -> None:
    sizes = {s: view_of(view_dir, s).groupby("gw").size() for s in SEASONS}
    assert sizes["2025-2026"][2] == 699 and sizes["2025-2026"][38] == 840
    assert sizes["2026-2027"][2] == 616 and sizes["2026-2027"][38] == 672


def test_the_record_names_the_checkout_commit_the_view_was_built_from(view_dir: Path) -> None:
    for season in SEASONS:
        info = json.loads((view_dir / f"{season}.json").read_text(encoding="utf-8"))
        assert info["checkout_commit"] == head()


# ---- the loader on real data ---------------------------------------------------------------


# 2025/26 players the as-of read holds that the view lacks (decisions.md, 2026-11-25).
DROPPED_2526 = {1: 60, 2: 43, 5: 11, 10: 4, 15: 0, 20: 0}


@pytest.mark.parametrize(("as_of", "dropped"), DROPPED_2526.items())
def test_players_the_view_lacks_are_dropped_and_counted_as_decided(
    cfg: dict, as_of: int, dropped: int, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="fpl.features"):
        tables = load_as_of("2025-2026", as_of, "backtest", cfg=cfg)
    snap = pd.read_csv(DATA / "2025-2026" / "By Gameweek" / f"GW{as_of}" / "players.csv",
                       usecols=["player_id"]).player_id
    stats = pd.read_csv(DATA / "2025-2026" / "By Gameweek" / f"GW{as_of}" / "playerstats.csv",
                        usecols=["id"]).id
    ids = set(snap) & set(stats)  # the snapshot's dim_player
    view = view_of(Path(cfg["paths"]["pre_deadline_dir"]), "2025-2026")
    in_view = set(view[view.gw == as_of + 1].player_id)
    assert len(ids - in_view) == dropped
    assert set(tables["dim_player"].player_id) == in_view
    assert any(f"{dropped} players dropped" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("season", "as_of"), [("2025-2026", 2), ("2025-2026", 3),
                                               ("2026-2027", 5), ("2026-2027", 10)])
def test_a_real_backtest_read_holds_the_views_players(cfg: dict, season: str, as_of: int) -> None:
    got = load_as_of(season, as_of, "backtest", cfg=cfg)["dim_player"]
    commit = last_commit_before(fpl_deadline(season, as_of + 1))
    assert_same(got, expected_rows(season, commit))


def test_as_of_0_is_empty_and_as_of_38_keeps_the_snapshots_players(cfg: dict) -> None:
    assert load_as_of("2025-2026", 0, "backtest", cfg=cfg)["dim_player"].empty
    last = load_as_of("2025-2026", 38, "backtest", cfg=cfg)["dim_player"]
    folder = pd.read_csv(DATA / "2025-2026" / "By Gameweek" / "GW38" / "players.csv")
    assert set(last.player_id) <= set(folder.player_id) and len(last) > 800


def test_a_real_view_built_from_another_checkout_commit_refuses(
    cfg: dict, view_dir: Path, tmp_path: Path
) -> None:
    shutil.copytree(view_dir, tmp_path / "v")
    record = tmp_path / "v" / "2026-2027.json"
    info = json.loads(record.read_text(encoding="utf-8"))
    record.write_text(json.dumps({**info, "checkout_commit": "0" * 40}), encoding="utf-8")
    stale = {**cfg, "paths": {**cfg["paths"], "pre_deadline_dir": str(tmp_path / "v")}}
    with pytest.raises(ViewError, match="stale"):
        load_as_of("2026-2027", 5, "backtest", cfg=stale)


def test_head_commit_reads_the_checkouts_head_without_git() -> None:
    assert head_commit(CHECKOUT) == head()
    assert head_commit(CHECKOUT.parent) is None  # a folder that isn't a git checkout


def test_a_read_through_a_data_copy_takes_the_copys_own_view(
    cfg: dict, view_dir: Path, tmp_path: Path
) -> None:
    """The copy replaces the upstream data folder, and `copy_view` gives it the view. A read
    there opens nothing under the real data, starts no process, and still reads the view's
    players, whatever the copy's snapshot files hold."""
    season = "2026-2027"
    dest = tmp_path / "data"
    shutil.copytree(DATA, dest, ignore=shutil.ignore_patterns("By Tournament", "2024-2025",
                                                              "2025-2026"))
    copy_view(view_dir, CHECKOUT, dest, [season])
    path = dest / season / "By Gameweek" / "GW5" / "playerstats.csv"
    stats = pd.read_csv(path)
    stats["status"] = "scrambled"
    stats.to_csv(path, index=False)
    direct = load_as_of(season, 5, "backtest", cfg=cfg)["dim_player"]
    with forbid_reads([DATA, ROOT / "data"]) as hits, use_data_copy(dest):
        copied = load_as_of(season, 5, "backtest")["dim_player"]
    assert hits == []
    pd.testing.assert_frame_equal(copied, direct)
    assert not (copied.status == "scrambled").any()


def test_a_copy_of_a_stale_view_is_refused_when_the_copy_is_made(
    view_dir: Path, tmp_path: Path
) -> None:
    shutil.copytree(view_dir, tmp_path / "v")
    record = tmp_path / "v" / "2026-2027.json"
    info = json.loads(record.read_text(encoding="utf-8"))
    record.write_text(json.dumps({**info, "checkout_commit": "0" * 40}), encoding="utf-8")
    with pytest.raises(ViewError, match="stale"):
        copy_view(tmp_path / "v", CHECKOUT, tmp_path / "data", ["2026-2027"])
    assert not (tmp_path / "data").exists()
