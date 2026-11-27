"""A small git repo shaped like the upstream checkout, for the pre-deadline view's builder.

It holds the synthetic season (`synth`) under `data/`, with commits at chosen gameweeks. For a
gameweek g in `STATES` there are two commits, each holding a state (each player's rows for
GW1..state, so prices are `50 + player + state` tenths):

* a **before** commit of state g, two hours before the GW g+1 deadline, and
* an **after** commit of state g+1, one hour after it: upstream rewriting master files for the
  next gameweek.

A builder that took the newest commit instead of the last one before a deadline would read the
after commit's state. Player 9 exists from state 6 on. The folders under `By Gameweek` are
the synthetic season's final ones, committed once at the start (they are not what the builder
reads player figures from).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import synth

STATES = (1, 2, 5, 20, 36)
NEW_PLAYER, NEW_PLAYER_FROM = 9, 6


@dataclass(frozen=True)
class Commit:
    sha: str
    time: pd.Timestamp
    state: int  # the master files hold GW1..state


def deadline(gw: int) -> pd.Timestamp:
    """The synthetic season's deadline of `gw`: first Premier League kickoff minus 90 minutes."""
    kicks = [m["kick"] for m in synth.schedule() if m["gw"] == gw and m["tournament"] == "prem"]
    return min(kicks) - pd.Timedelta(minutes=90)


def git(repo: Path, *args: str, when: pd.Timestamp | None = None) -> str:
    env = dict(os.environ)
    if when is not None:
        stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        env |= {"GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return res.stdout.strip()


def master_files(state: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The master `players.csv` and `playerstats.csv` of the state after GW `state`."""
    ids = list(synth.PLAYER_CLUB) + ([NEW_PLAYER] if state >= NEW_PLAYER_FROM else [])
    players = pd.DataFrame([{
        "player_code": 1000 + p, "player_id": p, "web_name": f"P{p}", "position": "Midfielder",
        "team_code": synth.TEAM_CODE[synth.club(min(p, 8), state)],
    } for p in ids])
    rows = []
    for g in range(1, state + 1):
        for row in synth._state_rows(g):
            rows.append(row)
            if row["id"] == 8 and state >= NEW_PLAYER_FROM:
                rows.append({**row, "id": NEW_PLAYER})
    return players, pd.DataFrame(rows)


def write_state(repo: Path, state: int) -> None:
    base = repo / "data" / synth.SEASON
    players, stats = master_files(state)
    players.to_csv(base / "players.csv", index=False)
    stats.to_csv(base / "playerstats.csv", index=False)


def make_repo(root: Path, states: tuple[int, ...] = STATES) -> tuple[Path, list[Commit]]:
    """Create the repo at `root / "repo"`; return it and its commits, oldest first."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    synth.write_upstream(repo / "data")
    shutil.rmtree(repo / "pre_deadline")  # the synthetic view isn't part of the upstream repo
    start = deadline(2) - pd.Timedelta(days=30)
    commits: list[Commit] = []

    def commit(state: int, when: pd.Timestamp) -> None:
        if state:
            write_state(repo, state)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--allow-empty", "-m", f"state {state}", when=when)
        commits.append(Commit(git(repo, "rev-parse", "HEAD"), when, state))

    commit(0, start)  # the folders (and poisoned master files); no gameweek played
    for g in states:
        commit(g, deadline(g + 1) - pd.Timedelta(hours=2))
        commit(g + 1, deadline(g + 1) + pd.Timedelta(hours=1))
    return repo, commits


def clone_edit(repo: Path, dest: Path, edit: Callable[[Path], None]) -> Path:
    """A full clone of `repo` at `dest` with one more commit (made now, so the newest) holding
    `edit(dest)`'s changes to the files under `dest/data`."""
    subprocess.run(["git", "clone", "-q", str(repo), str(dest)], check=True, capture_output=True)
    git(dest, "config", "user.name", "test")
    git(dest, "config", "user.email", "test@example.com")
    git(dest, "config", "commit.gpgsign", "false")
    edit(dest)
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "edit")
    return dest


def expected_commit(commits: list[Commit], gw: int) -> Commit:
    """The last commit strictly before GW `gw`'s deadline, from the test's own list."""
    return [c for c in commits if c.time < deadline(gw)][-1]
