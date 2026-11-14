"""Scratch copies of the upstream checkout, corrupted after a point in time, and a redirect.

The real checkout under data/ is only ever read. `copy_upstream` copies the gameweek folders'
files to a scratch directory; `corrupt_after` and `corrupt_within` rewrite that copy's
`matches.csv` files; `redirect` points every `load_as_of` call at the copy. Files are read
and written as text, so every cell that isn't corrupted is kept exactly.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import fpl.features

log = logging.getLogger(__name__)

GAMEWEEKS = "By Gameweek"
SCORES = ["home_score", "away_score"]
ELO = ["home_team_elo", "away_team_elo"]
XG = [("home_expected_goals_xg", "home_non_penalty_xg"),
      ("away_expected_goals_xg", "away_non_penalty_xg")]


@dataclass(frozen=True)
class Corruption:
    """How values are corrupted, and the schedule settings needed to date a cup tie."""

    score: tuple[int, int]
    elo: tuple[float, float]
    xg: tuple[float, float]
    prem_tag: str
    offset_minutes: int


def _folders(season_dir: Path) -> dict[int, Path]:
    base = season_dir / GAMEWEEKS
    return {int(p.name[2:]): p for p in base.iterdir() if p.is_dir() and p.name.startswith("GW")}


def copy_upstream(src: Path, dst: Path, seasons: list[str], files: list[str]) -> None:
    """Copy `files` of every gameweek folder of `seasons` from data dir `src` to `dst`."""
    for season in seasons:
        for gw, folder in sorted(_folders(src / season).items()):
            out = dst / season / GAMEWEEKS / f"GW{gw}"
            out.mkdir(parents=True, exist_ok=True)
            for name in files:
                path = folder / f"{name}.csv"
                if path.exists():
                    shutil.copy2(path, out / path.name)


def restore_season(src: Path, dst: Path, season: str) -> None:
    """Copy every `matches.csv` of `season` back from `src`, undoing a corruption."""
    for gw, folder in _folders(src / season).items():
        shutil.copy2(folder / "matches.csv", dst / season / GAMEWEEKS / f"GW{gw}" / "matches.csv")


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _kick(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df.kickoff_time.replace("", None), utc=True, format="ISO8601")


def _new_scores(old: pd.Series, rng: np.random.Generator, c: Corruption) -> list[str]:
    """A score for each row, drawn from `c.score` and never equal to the old one."""
    lo, hi = c.score
    out = []
    for v in old:
        new = int(rng.integers(lo, hi)) if v else int(rng.integers(lo, hi + 1))
        if v and new >= int(float(v)):
            new += 1
        out.append(f"{float(new)}")
    return out


def _corrupt_rows(df: pd.DataFrame, rows: pd.Series, rng: np.random.Generator, c: Corruption,
                  keep_finished: bool) -> int:
    """Corrupt scores, upstream Elo and xG (and `finished`, unless kept) on `rows`."""
    n = int(rows.sum())
    if n == 0:
        return 0
    for col in SCORES:
        df.loc[rows, col] = _new_scores(df.loc[rows, col], rng, c)
    for col in ELO:
        df.loc[rows, col] = [f"{v:.2f}" for v in rng.uniform(*c.elo, n)]
    for xg, npxg in XG:
        total = rng.uniform(*c.xg, n)
        df.loc[rows, xg] = [f"{v:.2f}" for v in total]
        df.loc[rows, npxg] = [f"{v:.2f}" for v in total * rng.uniform(0.0, 1.0, n)]
    cols = SCORES + ELO + [c for pair in XG for c in pair]
    if not keep_finished:
        df.loc[rows, "finished"] = np.where(rng.random(n) < 0.5, "True", "False")
        cols.append("finished")
    return n * len(cols)


def _deadline_after(folders: dict[int, Path], as_of: int, c: Corruption) -> pd.Timestamp | None:
    """The GW as_of+1 deadline: its first Premier League kickoff minus the offset."""
    if as_of + 1 not in folders:
        return None
    df = _read(folders[as_of + 1] / "matches.csv")
    first = _kick(df[df.tournament == c.prem_tag]).min()
    return first - pd.Timedelta(minutes=c.offset_minutes)


def corrupt_after(data_dir: Path, season: str, as_of: int, rng: np.random.Generator,
                  c: Corruption) -> int:
    """Corrupt every result after as-of gameweek `as_of` in the copy; keep the schedule.

    That is every Premier League match in a folder after `as_of`, and every cup or European
    match kicked off at or after the GW as_of+1 deadline (or with no kickoff time, in a
    later folder). Match ids, gameweeks, kickoffs, clubs and tournaments are kept. Returns the
    number of cells rewritten.
    """
    folders = _folders(data_dir / season)
    deadline = _deadline_after(folders, as_of, c)
    total = 0
    for gw, folder in sorted(folders.items()):
        path = folder / "matches.csv"
        df = _read(path)
        prem = df.tournament == c.prem_tag
        kick = _kick(df)
        late_cup = ~prem & (kick >= deadline if deadline is not None else False)
        undated_cup = ~prem & kick.isna() & (gw > as_of)
        rows = (prem & (gw > as_of)) | late_cup | undated_cup
        if rows.any():
            total += _corrupt_rows(df, rows, rng, c, keep_finished=False)
            df.to_csv(path, index=False)
    log.info("%s: corrupted %d cells after as-of %d", season, total, as_of)
    return total


def corrupt_within(data_dir: Path, season: str, gw: int, split: pd.Timestamp,
                   rng: np.random.Generator, c: Corruption) -> int:
    """Corrupt GW `gw`'s Premier League results kicking off at or after `split`.

    `finished` is kept, so the matches stay in the read with wrong scores.
    """
    path = data_dir / season / GAMEWEEKS / f"GW{gw}" / "matches.csv"
    df = _read(path)
    rows = (df.tournament == c.prem_tag) & (_kick(df) >= split)
    n = _corrupt_rows(df, rows, rng, c, keep_finished=True)
    df.to_csv(path, index=False)
    return n


@contextmanager
def redirect(cfg: dict) -> Iterator[None]:
    """Make every `load_as_of` call that passes no config use `cfg` (a scratch checkout).

    Patches the loader's config lookup, so it reaches the model's calls whatever name they
    imported `load_as_of` under. The model's own `config/pipeline.yaml` reads are untouched.
    """
    real = fpl.features._config

    def pointed(given: dict | None, root: Path) -> dict:
        return given if given is not None else cfg

    with mock.patch.object(fpl.features, "_config", pointed):
        yield
    assert fpl.features._config is real
