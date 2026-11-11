"""Ingestion: read one season of the upstream checkout into raw frames.

File I/O lives here (and in the export step). It reads each CSV with explicit dtypes,
tags rows with the gameweek folder they came from (`snapshot_gw`), and records what
was missing so that validation can fail the run. On an as-of read it also decides which
matches the read holds (`asof.select_matches`). `read_season` never reads a master file;
the readers of master files are in `master.py`, and only live mode calls them.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from fpl.asof import select_matches
from fpl.schema import raw_columns, raw_dtypes

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# The files read from the folders after the as-of gameweek: the schedule.
SCHEDULE_FILES = ("fixtures", "matches")

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
    `player_gameweek_stats` stops at `latest_gw`, and so do the `playermatchstats` rows of
    Premier League matches (`gw_rows["playermatchstats"]` counts the Premier League rows of
    the folders read). Rows of cup and European matches are kept from any folder that holds
    a match the read holds; their `snapshot_gw` is the snapshot their clubs come from (the
    match's gameweek, at least 1), not the folder, and `players` has those snapshots. `matches` and
    `fixture_ids` cover every folder of the season (future folders hold the scheduled
    matches); on an as-of read, Premier League matches after `as_of_gw` are blanked and
    later cup and European matches are absent. `teams` and `playerstats` are the
    `latest_gw` snapshot (`teams` from GW1 when `latest_gw` is 0).
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
    as_of_gw: int | None = None


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
    """Read one upstream CSV with the explicit dtypes for `file`, keeping only the columns used."""
    if not Path(path).exists():
        raise IngestError(f"{path} does not exist")
    need = set(raw_columns(file))
    return pd.read_csv(
        path, dtype=raw_dtypes(file), low_memory=False, usecols=lambda c: c in need
    )


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


def _read_folders(
    base: Path, gws: Iterable[int], files: tuple[str, ...]
) -> tuple[dict, dict, list[str]]:
    """Read `files` of every folder in `gws`; return frames, columns seen, missing."""
    frames: dict[str, list[pd.DataFrame]] = {f: [] for f in GW_FILES}
    columns: dict[str, list[str]] = {}
    missing: list[str] = []
    for gw in gws:
        for file in files:
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


def _merge_reads(into: tuple[dict, dict, list[str]], more: tuple[dict, dict, list[str]]) -> None:
    for file, parts in more[0].items():
        into[0][file] += parts
    into[1].update(more[1])
    into[2].extend(more[2])


def read_season(
    data_dir: Path, season_cfg: dict, commit: str, as_of_gw: int | None = None, *,
    prem_tag: str, offset_minutes: int,
) -> RawSeason:
    """Read one season from `data_dir/{season}/By Gameweek/GW{n}/`.

    With `as_of_gw`, only folders up to it are read in full; this is how the point-in-time
    loader builds a backtest view without seeing the future. Every folder's `fixtures` and
    `matches` are read for the schedule, and then (`asof.select_matches`, which needs the
    deadline offset) Premier League matches after `as_of_gw` are blanked to schedule only,
    and cup and European matches played after it are left out. A held cup match's
    `gameweek` is the gameweek it was played in. Its player rows are read from the folder
    that files it, and its clubs come from the `players` snapshot of that gameweek (GW1's
    for a match before the GW1 deadline), so those rows get that `snapshot_gw`. Premier
    League player rows stop at the latest played gameweek.
    """
    season = season_cfg["id"]
    n_gw = int(season_cfg["gameweeks"])
    if as_of_gw is not None and as_of_gw < 0:
        raise ValueError(f"as_of_gw must be 0 or more, got {as_of_gw}")
    max_gw = n_gw if as_of_gw is None else min(n_gw, as_of_gw)
    base = data_dir / season / "By Gameweek"
    reads = _read_folders(base, range(1, max_gw + 1), GW_FILES)
    if max_gw < n_gw:
        _merge_reads(reads, _read_folders(base, range(max_gw + 1, n_gw + 1), SCHEDULE_FILES))
        if max_gw == 0:
            _merge_reads(reads, _read_folders(base, [1], ("teams",)))
    matches = _concat(reads[0]["matches"], "matches")
    held, left_out = select_matches(matches, max_gw, n_gw, prem_tag, offset_minutes)
    cups = held[held.tournament != prem_tag]
    club_gw = cups.set_index("match_id").gameweek.clip(lower=1).astype("int64")
    have = set(range(1, max_gw + 1))
    filing = sorted(set(cups.snapshot_gw) - have)
    _merge_reads(reads, _read_folders(base, filing, ("playermatchstats",)))
    _merge_reads(reads, _read_folders(base, sorted(set(club_gw) - have), ("players",)))
    cat = {f: _concat(reads[0][f], f) for f in GW_FILES}
    cat["matches"] = held
    cat["fixtures"] = _without(cat["fixtures"], left_out)
    cat["playermatchstats"] = _at_club_snapshot(cat["playermatchstats"], club_gw)
    return _assemble(season, commit, (n_gw, as_of_gw, max_gw), cat, left_out, reads, prem_tag)


def _at_club_snapshot(pms: pd.DataFrame, club_gw: pd.Series) -> pd.DataFrame:
    """Give each cup or European row the `snapshot_gw` its clubs are read from."""
    snap = pms.match_id.map(club_gw)
    return pms.assign(snapshot_gw=snap.fillna(pms.snapshot_gw).astype("int64"))


def _without(fixtures: pd.DataFrame, left_out: pd.DataFrame) -> pd.DataFrame:
    """Fixture list rows without those of the matches an as-of read leaves out."""
    gone = set(zip(left_out.snapshot_gw, left_out.match_id, strict=True))
    keep = [k not in gone for k in zip(fixtures.snapshot_gw, fixtures.match_id, strict=True)]
    return fixtures[keep].reset_index(drop=True)


def _assemble(
    season: str, commit: str, gws: tuple[int, int | None, int], cat: dict[str, pd.DataFrame],
    left_out: pd.DataFrame, reads: tuple[dict, dict, list[str]], prem_tag: str,
) -> RawSeason:
    """Trim the frames to what the read holds and record the per-folder row counts."""
    n_gw, as_of_gw, max_gw = gws
    _, columns, missing = reads
    held = cat["matches"]
    pgs_rows = cat["player_gameweek_stats"].groupby("snapshot_gw").size().to_dict()
    latest = max((gw for gw, n in pgs_rows.items() if n > 0), default=0)
    pms = cat["playermatchstats"]
    pms = pms[~pms.match_id.isin(left_out.match_id)]
    is_prem = pms.match_id.isin(held.match_id[held.tournament == prem_tag])
    prem_rows = pms[is_prem & (pms.snapshot_gw <= max_gw)].groupby("snapshot_gw").size()
    pms = pms[~is_prem | (pms.snapshot_gw <= latest)].reset_index(drop=True)
    players = cat["players"]
    keep = set(range(latest + 1)) | set(pms.snapshot_gw)
    players = players[players.snapshot_gw.isin(keep)].reset_index(drop=True)
    log.info("%s: latest played gameweek %s, %d files missing", season, latest, len(missing))
    return RawSeason(
        season=season, upstream_commit=commit, latest_gw=latest, n_gw=n_gw,
        teams=_at(cat["teams"], latest or 1), playerstats=_at(cat["playerstats"], latest),
        players=players, matches=held, fixture_ids=cat["fixtures"][["snapshot_gw", "match_id"]],
        playermatchstats=pms, player_gameweek_stats=_upto(cat["player_gameweek_stats"], latest),
        gw_rows={"player_gameweek_stats": pgs_rows, "playermatchstats": prem_rows.to_dict()},
        file_columns=columns, missing_files=missing, as_of_gw=as_of_gw,
    )


def upstream_data_dir(cfg: dict, root: Path = ROOT) -> Path:
    """The folder of the upstream checkout that holds the season folders."""
    return root / cfg["upstream"]["checkout_path"] / cfg["upstream"]["data_dir"]


def required_columns_missing(raw: RawSeason) -> list[str]:
    """Required upstream columns absent from any file read, as 'GWn/file.csv: col'."""
    out = []
    for rel, cols in raw.file_columns.items():
        need = raw_columns(rel.split("/")[1].removesuffix(".csv"))
        out += [f"{rel}: {c}" for c in need if c not in cols]
    return out
