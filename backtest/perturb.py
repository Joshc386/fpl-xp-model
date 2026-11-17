"""Scratch copies of the upstream checkout, corrupted after a point in time, and a redirect.

The real checkout under data/ is only ever read. `copy_upstream` copies the gameweek folders'
files to a scratch directory; `corrupt_after` and `corrupt_within` rewrite that copy's
`matches.csv` and `fixtures.csv` files (both carry result columns upstream); `redirect`
points every `load_as_of` call at the copy through the loader's `use_data_copy`. Files are read
and written as text, so every cell that isn't corrupted is kept exactly. No corruption touches
a match in `Corruption.keep` (the score-corrected matches, brief data rule 16).
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fpl.features import use_data_copy

log = logging.getLogger(__name__)

GAMEWEEKS = "By Gameweek"
SCORES = ["home_score", "away_score"]
ELO = ["home_team_elo", "away_team_elo"]
XG = [("home_expected_goals_xg", "home_non_penalty_xg"),
      ("away_expected_goals_xg", "away_non_penalty_xg")]
RESULT_FILES = ("matches", "fixtures")
Selector = Callable[[int, pd.DataFrame], pd.Series]  # (folder gameweek, matches) -> rows


@dataclass(frozen=True)
class Corruption:
    """How values are corrupted, and the schedule settings needed to date a cup tie.

    `keep`: match ids no corruption ever touches. These are the matches listed in
    `score_corrections` (brief data rule 16), because the cleaning step fails a read whose
    upstream score for one of them isn't the listed one. The trade-off: a leak of only those
    matches' results would go unseen, while every other match is still corrupted.
    """

    score: tuple[int, int]
    elo: tuple[float, float]
    xg: tuple[float, float]
    prem_tag: str
    offset_minutes: int
    keep: frozenset[str] = frozenset()


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
    """Copy every `matches.csv` and `fixtures.csv` of `season` back from `src`."""
    for gw, folder in _folders(src / season).items():
        for name in RESULT_FILES:
            path = folder / f"{name}.csv"
            if path.exists():
                shutil.copy2(path, dst / season / GAMEWEEKS / f"GW{gw}" / path.name)


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
    """Corrupt scores, upstream Elo and xG (and `finished`, unless kept) on `rows`.

    Only the columns present are touched; returns the number of cells rewritten.
    """
    n = int(rows.sum())
    if n == 0:
        return 0
    have = set(df.columns)
    cells = 0
    for col in (x for x in SCORES if x in have):
        df.loc[rows, col] = _new_scores(df.loc[rows, col], rng, c)
        cells += n
    for col in (x for x in ELO if x in have):
        df.loc[rows, col] = [f"{v:.2f}" for v in rng.uniform(*c.elo, n)]
        cells += n
    for xg, npxg in XG:
        total = rng.uniform(*c.xg, n)
        for col, vals in ((xg, total), (npxg, total * rng.uniform(0.0, 1.0, n))):
            if col in have:
                df.loc[rows, col] = [f"{v:.2f}" for v in vals]
                cells += n
    if not keep_finished and "finished" in have:
        df.loc[rows, "finished"] = np.where(rng.random(n) < 0.5, "True", "False")
        cells += n
    return cells


def _rewrite(folders: dict[int, Path], select: Selector, rng: np.random.Generator,
             c: Corruption, keep_finished: bool) -> int:
    """Corrupt the selected matches in each folder's `matches.csv`, and the same match ids in
    its `fixtures.csv`, except the ids in `c.keep`; returns the number of cells rewritten."""
    total = 0
    for gw, folder in sorted(folders.items()):
        matches = _read(folder / "matches.csv")
        rows = select(gw, matches) & ~matches.match_id.isin(c.keep)
        if not rows.any():
            continue
        ids = set(matches.match_id[rows])
        total += _corrupt_rows(matches, rows, rng, c, keep_finished)
        matches.to_csv(folder / "matches.csv", index=False)
        path = folder / "fixtures.csv"
        if path.exists():
            fixtures = _read(path)
            total += _corrupt_rows(fixtures, fixtures.match_id.isin(ids), rng, c, keep_finished)
            fixtures.to_csv(path, index=False)
    return total


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

    def select(gw: int, df: pd.DataFrame) -> pd.Series:
        prem = df.tournament == c.prem_tag
        kick = _kick(df)
        late_cup = ~prem & (kick >= deadline if deadline is not None else False)
        undated_cup = ~prem & kick.isna() & (gw > as_of)
        return (prem & (gw > as_of)) | late_cup | undated_cup

    total = _rewrite(folders, select, rng, c, keep_finished=False)
    log.info("%s: corrupted %d cells after as-of %d", season, total, as_of)
    return total


def corrupt_up_to(data_dir: Path, season: str, as_of: int, rng: np.random.Generator,
                  c: Corruption) -> int:
    """Corrupt every Premier League result up to as-of gameweek `as_of`, with `finished` kept.

    The control: a function that reads the copy must change its output.
    """
    folders = {g: f for g, f in _folders(data_dir / season).items() if g <= as_of}
    return _rewrite(folders, lambda gw, df: df.tournament == c.prem_tag, rng, c,
                    keep_finished=True)


def corrupt_within(data_dir: Path, season: str, gw: int, split: pd.Timestamp,
                   rng: np.random.Generator, c: Corruption) -> int:
    """Corrupt GW `gw`'s Premier League results kicking off at or after `split`.

    `finished` is kept, so the matches stay in the read with wrong scores.
    """
    folders = {gw: data_dir / season / GAMEWEEKS / f"GW{gw}"}
    return _rewrite(folders, lambda g, df: (df.tournament == c.prem_tag) & (_kick(df) >= split),
                    rng, c, keep_finished=True)


Redirect = Callable[[Path], AbstractContextManager[None]]


def redirect(data_dir: Path) -> AbstractContextManager[None]:
    """Point every `load_as_of` call that names no `root` or `cfg` at the data copy `data_dir`.

    This is the loader's supported override, `fpl.features.use_data_copy`, so it reaches the
    model's public functions without patching anything. It doesn't reach worker threads.
    """
    return use_data_copy(data_dir)
