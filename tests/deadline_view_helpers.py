"""Shared builders for the pre-deadline view's synthetic tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fpl.deadline_view import build_view_rows
from helpers import blank_frame, player_row, teams_frame

POSITIONS = {"Goalkeeper": "GKP", "Defender": "DEF", "Midfielder": "MID", "Forward": "FWD"}
PRICES = [3.0, 20.0]
ROWS = [500, 1000]
TEAMS = teams_frame([(1, 31), (2, 32)])
SHA = "a" * 40
DEADLINE = "2026-08-20T12:00:00Z"
COMMIT_TIME = "2026-08-20T10:00:00Z"


SHA = "a" * 40


def players(ids: list[int], **kw: object) -> pd.DataFrame:
    df = blank_frame("players", [player_row(i, 31 + i % 2, **kw) for i in ids])
    return df.drop(columns="snapshot_gw", errors="ignore")


def stats_row(pid: int, gw: int, **kw: object) -> dict:
    row = {
        "id": pid, "gw": gw, "status": "a", "news": None, "chance_of_playing_next_round": None,
        "now_cost": 5.0 + pid / 10, "selected_by_percent": 1.0, "penalties_order": None,
        "direct_freekicks_order": None, "corners_and_indirect_freekicks_order": None,
        "ep_next": 2.0, "cost_change_start": 0, "cost_change_event": 0,
        "transfers_in_event": 10, "transfers_out_event": 5,
    }
    row.update(kw)
    return row


def stats(rows: list[dict]) -> pd.DataFrame:
    return blank_frame("playerstats", rows)


def build(
    ids: list[int], rows: list[dict], bounds: list[int] | None = None,
    stats_bounds: list[int] | None = None,
) -> tuple:
    return build_view_rows(
        players(ids), stats(rows), TEAMS, POSITIONS, PRICES, bounds or [1, 10],
        stats_bounds or [1, 10],
    )


def history(times: list[str]) -> pd.DataFrame:
    """Commits newest first, as `git log` lists them."""
    t = pd.to_datetime(times, utc=True)
    return pd.DataFrame({"sha": [f"{i:040d}" for i in range(len(t))], "time": t})


def view_frame(gws: list[int], *, price_add: int = 0, flagged: bool = False) -> pd.DataFrame:
    parts = []
    for gw in gws:
        base, _ = build([1, 2], [stats_row(1, gw - 1), stats_row(2, gw - 1)])
        base["price_tenths"] += price_add
        parts.append(base.assign(
            gw=gw, deadline_utc=DEADLINE, upstream_commit=SHA, commit_utc=COMMIT_TIME,
            checkout_ends_early=flagged,
        ))
    return pd.concat(parts, ignore_index=True)


def git_dir(root: Path, head: str) -> Path:
    root.mkdir(exist_ok=True)
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text(head, encoding="utf-8")
    return root
