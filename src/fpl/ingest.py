"""Ingestion: read one season of the upstream checkout into raw frames.

File I/O lives here (and in the export step). Nothing in this module changes a
value: it reads each CSV with explicit dtypes, tags rows with the gameweek folder
they came from (`snapshot_gw`), and records what was missing so that validation can
fail the run. Master files are never read.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from fpl.schema import raw_columns, raw_dtypes

log = logging.getLogger(__name__)

# The files expected in every gameweek folder.
GW_FILES = (
    "fixtures", "matches", "players", "teams", "playerstats",
    "playermatchstats", "player_gameweek_stats",
)


class IngestError(RuntimeError):
    """Upstream data could not be read at all."""


@dataclass
class RawSeason:
    """One season of upstream data, as read.

    Frames carry `snapshot_gw`, the gameweek folder each row came from.
    `players`, `playermatchstats` and `player_gameweek_stats` stop at `latest_gw`;
    `matches` and `fixture_ids` cover every folder read (future folders hold the
    scheduled matches). `teams` and `playerstats` are the `latest_gw` snapshot.
    """

    season: str
    upstream_commit: str
    latest_gw: int
    n_gw: int
    teams: pd.DataFrame
    playerstats: pd.DataFrame
    players: pd.DataFrame
    matches: pd.DataFrame
    fixture_ids: pd.DataFrame
    playermatchstats: pd.DataFrame
    player_gameweek_stats: pd.DataFrame
    gw_rows: dict[str, dict[int, int]]
    file_columns: dict[str, list[str]]
    missing_files: list[str]


def load_config(path: Path) -> dict:
    """Load config/pipeline.yaml."""
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def read_upstream_commit(checkout: Path) -> str:
    """The full SHA of the upstream checkout's HEAD."""
    try:
        res = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise IngestError(f"cannot run git to read the upstream commit: {exc}") from exc
    if res.returncode != 0:
        raise IngestError(f"{checkout} is not a git checkout: {res.stderr.strip()}")
    return res.stdout.strip()


def read_table(path: Path, file: str) -> pd.DataFrame:
    """Read one upstream CSV with the explicit dtypes for `file`."""
    if not Path(path).exists():
        raise IngestError(f"{path} does not exist")
    return pd.read_csv(path, dtype=raw_dtypes(file), low_memory=False)


def _empty(file: str) -> pd.DataFrame:
    """An empty frame with the required columns, for a file that was not found."""
    df = pd.DataFrame({c: pd.Series(dtype=t) for c, t in raw_dtypes(file).items()})
    df["snapshot_gw"] = pd.Series(dtype="int64")
    return df


def _concat(frames: list[pd.DataFrame], file: str) -> pd.DataFrame:
    """Concatenate gameweek frames, tolerating none."""
    if not frames:
        return _empty(file)
    return pd.concat(frames, ignore_index=True)


def _upto(df: pd.DataFrame, gw: int) -> pd.DataFrame:
    return df[df.snapshot_gw <= gw].reset_index(drop=True)


def _at(df: pd.DataFrame, gw: int) -> pd.DataFrame:
    return df[df.snapshot_gw == gw].reset_index(drop=True)


def _read_folders(base: Path, max_gw: int) -> tuple[dict, dict, list[str]]:
    """Read every expected file of GW1..max_gw; return frames, columns seen, missing."""
    frames: dict[str, list[pd.DataFrame]] = {f: [] for f in GW_FILES}
    columns: dict[str, list[str]] = {}
    missing: list[str] = []
    for gw in range(1, max_gw + 1):
        for file in GW_FILES:
            rel = f"GW{gw}/{file}.csv"
            path = base / f"GW{gw}" / f"{file}.csv"
            if not path.exists():
                missing.append(rel)
                continue
            df = read_table(path, file)
            columns[rel] = list(df.columns)
            df = df[[c for c in raw_columns(file) if c in df.columns]].copy()
            df["snapshot_gw"] = gw
            frames[file].append(df)
    return frames, columns, missing


def read_season(
    data_dir: Path, season_cfg: dict, commit: str, as_of_gw: int | None = None
) -> RawSeason:
    """Read one season from `data_dir/{season}/By Gameweek/GW{n}/`.

    With `as_of_gw`, folders after it are not read at all, which is how the
    point-in-time loader builds a backtest view without seeing the future.
    """
    season = season_cfg["id"]
    n_gw = int(season_cfg["gameweeks"])
    max_gw = n_gw if as_of_gw is None else min(n_gw, as_of_gw)
    frames, columns, missing = _read_folders(data_dir / season / "By Gameweek", max_gw)
    cat = {f: _concat(frames[f], f) for f in GW_FILES}
    gw_rows = {
        f: cat[f].groupby("snapshot_gw").size().to_dict()
        for f in ("player_gameweek_stats", "playermatchstats")
    }
    played = [gw for gw, n in gw_rows["player_gameweek_stats"].items() if n > 0]
    latest = max(played, default=0)
    log.info("%s: latest played gameweek %s, %d files missing", season, latest, len(missing))
    return RawSeason(
        season=season, upstream_commit=commit, latest_gw=latest, n_gw=n_gw,
        teams=_at(cat["teams"], latest), playerstats=_at(cat["playerstats"], latest),
        players=_upto(cat["players"], latest), matches=cat["matches"],
        fixture_ids=cat["fixtures"][["snapshot_gw", "match_id"]],
        playermatchstats=_upto(cat["playermatchstats"], latest),
        player_gameweek_stats=_upto(cat["player_gameweek_stats"], latest),
        gw_rows=gw_rows, file_columns=columns, missing_files=missing,
    )


def required_columns_missing(raw: RawSeason) -> list[str]:
    """Required upstream columns absent from any file read, as 'GWn/file.csv: col'."""
    out = []
    for rel, cols in raw.file_columns.items():
        need = raw_columns(rel.split("/")[1].removesuffix(".csv"))
        out += [f"{rel}: {c}" for c in need if c not in cols]
    return out
