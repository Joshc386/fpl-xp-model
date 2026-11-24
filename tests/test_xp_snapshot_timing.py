"""Snapshot timing on a small git repository with controlled commit times: whether each
GW g-1 snapshot's player fields are as they stood before the GW g deadline, and which
gameweek a late snapshot's ep_next refers to."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest
from backtest.snapshot_timing import deadlines, snapshot_timing

SEASON = "2025-2026"
FIELDS = ["ep_next", "now_cost", "status", "chance_of_playing_next_round"]
DL = pd.Series({2: pd.Timestamp("2025-08-22T17:30Z"), 3: pd.Timestamp("2025-08-29T17:30Z"),
                4: pd.Timestamp("2025-09-12T17:30Z"), 5: pd.Timestamp("2025-09-19T17:30Z")})


def stats(ep: list[float], cost: list[str], chance: list[str] | None = None) -> str:
    chance = chance or ["" for _ in ep]
    rows = [f"{i + 1},a,{c},{p},{e}" for i, (e, p, c) in enumerate(zip(ep, cost, chance,
                                                                        strict=True))]
    return "id,status,chance_of_playing_next_round,now_cost,ep_next\n" + "\n".join(rows) + "\n"


def commit(repo: Path, when: str, files: dict[int, str]) -> None:
    for s, text in files.items():
        path = repo / "data" / SEASON / "By Gameweek" / f"GW{s}" / "playerstats.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "-A"], check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", when], check=True, env=env)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("upstream")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    commit(r, "2025-08-20T10:00:00Z", {1: stats([1.0, 2.0], ["5.0", "6.0"])})
    commit(r, "2025-08-27T10:00:00Z", {2: stats([1.5, 2.5], ["5.0", "6.0"])})
    commit(r, "2025-09-10T10:00:00Z", {3: stats([4.0, 0.5], ["5.1", "6.0"])})
    # After the GW3 deadline: GW1 is rewritten with GW3's state (its ep_next is for GW4), and
    # GW2 only changes format (prices in tenths, a blank chance written as 100).
    commit(r, "2025-11-19T23:00:00Z", {1: stats([4.0, 0.5], ["5.1", "6.0"]),
                                       2: stats([1.5, 2.5], ["50", "60"], ["100", ""])})
    # GW4 is first written after the GW5 deadline.
    commit(r, "2025-09-20T08:00:00Z", {4: stats([3.0, 3.0], ["5.1", "6.0"])})
    return r


def test_each_snapshot_is_compared_with_its_last_version_before_the_deadline(repo: Path
                                                                             ) -> None:
    got = snapshot_timing(repo, "data", SEASON, DL, range(1, 5), FIELDS, 0.01).set_index(
        "snapshot")
    assert got.target.to_dict() == {1: 2, 2: 3, 3: 4, 4: 5}
    assert got.late.to_dict() == {1: True, 2: False, 3: False, 4: True}
    assert got.loc[1, "changed_ep_next"] == pytest.approx(1.0)
    assert got.loc[1, "changed_now_cost"] == pytest.approx(0.5)
    assert got.loc[2, "changed_now_cost"] == 0.0
    assert got.loc[1, "refers_to"] == 4 and got.loc[1, "refers_share"] == pytest.approx(1.0)
    assert got.loc[2, "refers_to"] == 3
    assert got.loc[1, "last_write"] == pd.Timestamp("2025-11-19T23:00:00Z")
    assert got.loc[4, "note"] == "no version before the deadline"


def test_deadlines_are_the_first_league_kickoff_minus_the_offset() -> None:
    fx = pd.DataFrame({"gw": [1, 1, 2, 2], "tournament": ["prem", "prem", "efl-cup", "prem"],
                       "kickoff_utc": ["2025-08-15T19:00:00Z", "2025-08-16T11:30:00Z",
                                       "2025-08-20T10:00:00Z", "2025-08-22T19:00:00Z"]})
    got = deadlines(fx, "prem", 90)
    assert got[1] == pd.Timestamp("2025-08-15T17:30:00Z")
    assert got[2] == pd.Timestamp("2025-08-22T17:30:00Z")


def test_commits_in_the_same_second_resolve_by_history_order(
        tmp_path_factory: pytest.TempPathFactory) -> None:
    r = tmp_path_factory.mktemp("same_second")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    commit(r, "2025-08-20T10:00:00Z", {1: stats([1.0, 2.0], ["5.0", "6.0"])})
    # Same second, one more player: the later commit in history is the version read.
    commit(r, "2025-08-20T10:00:00Z", {1: stats([3.0, 4.0, 1.0], ["5.0", "6.0", "4.5"])})
    commit(r, "2025-08-27T10:00:00Z", {2: stats([3.0, 4.0], ["5.0", "6.0"])})
    got = snapshot_timing(r, "data", SEASON, DL, [1, 2], FIELDS, 0.01).set_index("snapshot")
    assert got.loc[1, "players"] == 3
    # ...and the last version before the deadline is that same commit, so nothing changed.
    assert not got.loc[1, "late"] and got.loc[1, "changed_ep_next"] == 0.0


def test_a_snapshot_that_doesnt_exist_is_reported_not_raised(repo: Path) -> None:
    dl = pd.concat([pd.Series({1: pd.Timestamp("2025-08-15T17:30Z")}), DL])
    got = snapshot_timing(repo, "data", SEASON, dl, [0, 1], FIELDS, 0.01).set_index("snapshot")
    assert got.loc[0, "late"] and got.loc[0, "note"] == "no snapshot in the history"
    assert pd.isna(got.loc[0, "refers_to"]) and got.loc[0, "target"] == 1
    assert got.loc[1, "late"]  # its GW3-state rewrite, as in the main fixture test
