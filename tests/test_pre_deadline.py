"""`fpl.pre_deadline`, the builder of the pre-deadline view, on a small synthetic git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import pytest

import synth
import view_repo
from fpl.deadline_view import VIEW_COLUMNS, ViewError, read_view
from fpl.ingest import IngestError
from fpl.pre_deadline import build_season_view, build_views, main
from view_repo import Commit, deadline, expected_commit

pytest_plugins = ["pre_deadline_fixtures"]
SEASON = synth.SEASON
N = synth.N_GW


@pytest.fixture(scope="module")
def built(repo: tuple[Path, list[Commit]], git_cfg: dict) -> tuple[pd.DataFrame, dict]:
    return build_season_view(repo[0], git_cfg, git_cfg["seasons"][0])


def test_every_gameweek_from_2_to_the_last_has_its_players(
    built: tuple[pd.DataFrame, dict], repo: tuple[Path, list[Commit]]
) -> None:
    view, report = built
    assert list(view.columns) == VIEW_COLUMNS
    assert sorted(view.gw.unique()) == list(range(2, N + 1))
    assert report["gameweeks"] == N - 1
    per_gw = view.groupby("gw").size()
    assert per_gw[2:5].eq(8).all() and per_gw[6:].eq(9).all()  # player 9 from state 6


def test_each_gameweek_takes_the_last_commit_before_its_deadline(
    built: tuple[pd.DataFrame, dict], repo: tuple[Path, list[Commit]]
) -> None:
    view, _ = built
    for gw, rows in view.groupby("gw"):
        want = expected_commit(repo[1], gw)
        assert set(rows.upstream_commit) == {want.sha}, gw
        assert set(rows.commit_utc) == {want.time.strftime("%Y-%m-%dT%H:%M:%SZ")}, gw


def test_no_record_comes_from_a_commit_after_its_deadline(built: tuple[pd.DataFrame, dict]) -> None:
    view, _ = built
    for gw, rows in view.groupby("gw"):
        assert (pd.to_datetime(rows.commit_utc, utc=True) < deadline(gw)).all(), gw


def test_the_values_are_the_picked_commits_not_the_newest(
    built: tuple[pd.DataFrame, dict], repo: tuple[Path, list[Commit]]
) -> None:
    view, _ = built
    for gw, rows in view.groupby("gw"):
        state = expected_commit(repo[1], gw).state
        assert (rows.price_tenths == 50 + rows.player_id.clip(upper=8) + state).all(), gw
        assert (rows.ep_next == state + rows.player_id.clip(upper=8) / 10).all(), gw


def test_clubs_come_from_the_commits_master_players_file(
    built: tuple[pd.DataFrame, dict], repo: tuple[Path, list[Commit]]
) -> None:
    view, _ = built
    for gw, rows in view.groupby("gw"):
        state = expected_commit(repo[1], gw).state
        mover = rows[rows.player_id == synth.MOVER].team_id.item()
        assert mover == (3 if state >= synth.MOVE_GW else 1), gw


def test_a_gameweek_after_the_newest_commit_is_flagged_and_uses_that_commit(
    built: tuple[pd.DataFrame, dict], repo: tuple[Path, list[Commit]]
) -> None:
    view, report = built
    newest = repo[1][-1]
    assert deadline(N) > newest.time
    flagged = sorted(view.loc[view.checkout_ends_early, "gw"].unique())
    assert flagged == [N] == report["checkout_ends_early"]
    assert set(view[view.gw == N].upstream_commit) == {newest.sha}


def test_the_report_counts_players_without_a_playerstats_row(
    built: tuple[pd.DataFrame, dict]
) -> None:
    assert built[1]["no_playerstats_row"] == {}


def test_the_deadline_is_stored_per_row_and_equals_the_derived_one_when_fpls_agrees(
    built: tuple[pd.DataFrame, dict]
) -> None:
    view, report = built
    assert report["deadline_gaps"] == []
    for gw, rows in view.groupby("gw"):
        assert set(rows.deadline_utc) == {deadline(gw).strftime("%Y-%m-%dT%H:%M:%SZ")}, gw


def test_a_checkout_that_is_not_the_root_of_a_git_repo_fails(
    tmp_path: Path, git_cfg: dict
) -> None:
    with pytest.raises(IngestError, match="git checkout"):
        build_season_view(tmp_path, git_cfg, git_cfg["seasons"][0])


def test_a_shallow_clone_fails_for_lack_of_history(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo[0].as_uri(), str(shallow)],
                   check=True, capture_output=True)
    with pytest.raises(ViewError, match="full clone"):
        build_season_view(shallow, git_cfg, git_cfg["seasons"][0])


def test_a_broken_cleaning_rule_in_an_old_commit_fails_the_build(
    tmp_path: Path, git_cfg: dict
) -> None:
    # A price in tenths in one commit's master file: it is reported, never converted.
    repo, commits = view_repo.make_repo(tmp_path, states=(1,))
    bad = commits[1]  # the first before-commit
    view_repo.git(repo, "checkout", "-q", bad.sha)
    path = repo / "data" / SEASON / "playerstats.csv"
    stats = pd.read_csv(path)
    stats.loc[0, "now_cost"] = 58.0
    stats.to_csv(path, index=False)
    view_repo.git(repo, "commit", "-q", "-am", "tenths", when=bad.time + pd.Timedelta(minutes=1))
    rest = commits[2:]
    # Re-apply the later commits on top of the broken one so the history stays linear.
    for c in rest:
        view_repo.write_state(repo, c.state)
        view_repo.git(repo, "add", "-A")
        view_repo.git(repo, "commit", "-q", "--allow-empty", "-m", "again", when=c.time)
    with pytest.raises(ViewError, match=r"GW2.*now_cost"):
        build_season_view(repo, git_cfg, git_cfg["seasons"][0])


def test_the_command_writes_each_season_and_records_the_checkout_commit(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    reports = build_views(repo[0], git_cfg, tmp_path / "out")
    head = view_repo.git(repo[0], "rev-parse", "HEAD")
    assert list(reports) == [SEASON]
    got = read_view(tmp_path / "out", SEASON, 5, head)
    assert len(got) == 8
    with pytest.raises(ViewError, match="stale"):
        read_view(tmp_path / "out", SEASON, 5, "0" * 40)


def test_a_failed_build_writes_nothing(repo: tuple[Path, list[Commit]], git_cfg: dict,
                                       tmp_path: Path) -> None:
    out = tmp_path / "out"
    tight = {**git_cfg, "validation": {**git_cfg["validation"], "now_cost_m": [0.0, 1.0]}}
    with pytest.raises(ViewError):
        build_views(repo[0], tight, out)
    assert not out.exists()


def test_main_exits_non_zero_with_a_message_on_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--checkout", str(tmp_path), "--out-dir", str(tmp_path / "out")])
    assert code == 1
    assert "git checkout" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()



def test_the_report_names_the_head_the_history_was_read_at(
    repo: tuple[Path, list[Commit]], built: tuple[pd.DataFrame, dict]
) -> None:
    assert built[1]["checkout_commit"] == view_repo.git(repo[0], "rev-parse", "HEAD")
