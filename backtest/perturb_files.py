"""The extended perturbation: every file the loader reads, not only the result columns.

`perturb.corrupt_after` rewrites the results of matches dated after an as-of gameweek. The
xP model also reads player files (`players`, `playerstats`, `player_gameweek_stats`,
`playermatchstats`) and, from phase 2 task 1, `shots` and `incidents`. This module corrupts
every column of those files except each file's keys, in every row dated after the as-of:

* a file with a `match_id` column: the rows of matches dated after it (`perturb.
  after_selector`, over every folder), so a cup tie filed in a later folder but played
  before the deadline keeps its rows;
* any other file: every row of every folder after the as-of gameweek.

The control (`corrupt_files_up_to`) corrupts the rows dated up to the as-of instead, except
each rule's `club` columns, so the copy's clubs stay valid. An honest read of the copy must
then change: by value, or by failing. On the real data it fails: the loader's checks on every
read (spells against minutes, starters per club, one incident row per player and match) reject
shuffled player files. A failure only on the corrupted copy still shows the function read the
copy, and the report says which way each control changed.

A column is corrupted by shuffling its values among the selected rows; a cell the shuffle
leaves unchanged takes another value seen in that column of the file. A column with a single
value in the file can't change and is left as it is. Files are read and written as
text, so untouched cells are kept exactly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.perturb import (
    Corruption,
    after_selector,
    gameweek_folders,
    read_text_csv,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileRule:
    """Columns of one upstream file that are never corrupted (`keys`), and those corrupted
    only after the as-of gameweek (`club`)."""

    keys: frozenset[str]
    club: frozenset[str] = frozenset()


def file_rules(cfg: dict[str, dict]) -> dict[str, FileRule]:
    """`{file: {keys: [...], club: [...]}}` from backtest/config.yaml as `FileRule`s."""
    return {name: FileRule(frozenset(r.get("keys", [])), frozenset(r.get("club", [])))
            for name, r in cfg.items()}


def _scramble(df: pd.DataFrame, rows: np.ndarray, cols: list[str],
              rng: np.random.Generator) -> int:
    """Shuffle each column among `rows`, then give every unchanged cell another value from
    the column; returns the number of cells changed."""
    if len(rows) == 0:
        return 0
    cells = 0
    for col in cols:
        old = df[col].to_numpy(dtype=object)[rows]
        pool = np.array(sorted(set(df[col])), dtype=object)
        if len(pool) < 2:
            continue
        new = rng.permutation(old)
        for i in np.flatnonzero(new == old):
            others = pool[pool != old[i]]
            new[i] = others[rng.integers(len(others))]
        df.loc[df.index[rows], col] = new
        cells += int((new != old).sum())
    return cells


def _after_ids(folders: dict[int, Path], as_of: int, c: Corruption) -> set[str]:
    select = after_selector(folders, as_of, c)
    ids: set[str] = set()
    for gw, folder in folders.items():
        df = read_text_csv(folder / "matches.csv")
        ids |= set(df.match_id[select(gw, df)])
    return ids


RowPick = Callable[[int, pd.DataFrame], np.ndarray]


def _corrupt(data_dir: Path, season: str, files: list[str], rules: dict[str, FileRule],
             pick: RowPick, skip_club: bool, rng: np.random.Generator) -> dict[str, int]:
    """Corrupt the rows `pick(folder gameweek, frame)` of each file; cells changed per file."""
    missing = [f for f in files if f not in rules]
    if missing:
        raise ValueError(f"no corruption rule for {', '.join(missing)}")
    cells = dict.fromkeys(files, 0)
    for gw, folder in sorted(gameweek_folders(data_dir / season).items()):
        for name in files:
            path = folder / f"{name}.csv"
            if not path.exists():
                continue
            df = read_text_csv(path)
            rows = pick(gw, df)
            if len(rows) == 0:
                continue
            rule = rules[name]
            keep = rule.keys | (rule.club if skip_club else frozenset())
            cells[name] += _scramble(df, rows, [c for c in df.columns if c not in keep], rng)
            df.to_csv(path, index=False)
    return cells


def _present(data_dir: Path, season: str) -> list[str]:
    """Every file in the copy's gameweek folders, by name: each must have a rule."""
    names = {p.stem for f in gameweek_folders(data_dir / season).values() for p in f.glob("*.csv")}
    return sorted(names)


def corrupt_files_after(data_dir: Path, season: str, as_of: int, rng: np.random.Generator,
                        c: Corruption, rules: dict[str, FileRule]) -> dict[str, int]:
    """Corrupt every row dated after as-of gameweek `as_of`, in every file of the copy
    (module docstring). Matches in `c.keep` keep their `matches` and `fixtures` rows, as in
    `perturb`. Raises `ValueError` for a file in the copy with no rule."""
    folders = gameweek_folders(data_dir / season)
    after = _after_ids(folders, as_of, c)

    def pick(gw: int, df: pd.DataFrame) -> np.ndarray:
        if "match_id" not in df.columns:
            return np.arange(len(df)) if gw > as_of else np.array([], dtype=int)
        hit = df.match_id.isin(after) & ~df.match_id.isin(c.keep)
        return np.flatnonzero(hit.to_numpy())

    cells = _corrupt(data_dir, season, _present(data_dir, season), rules, pick, False, rng)
    log.info("%s: corrupted %s cells in files after as-of %d", season, cells, as_of)
    return cells


def corrupt_files_up_to(data_dir: Path, season: str, as_of: int, rng: np.random.Generator,
                        c: Corruption, rules: dict[str, FileRule]) -> dict[str, int]:
    """The control: corrupt every row dated up to `as_of` (folders up to it, without the
    matches dated after it), except the rules' `club` columns and the `c.keep` matches."""
    folders = gameweek_folders(data_dir / season)
    after = _after_ids(folders, as_of, c)

    def pick(gw: int, df: pd.DataFrame) -> np.ndarray:
        if gw > as_of:
            return np.array([], dtype=int)
        if "match_id" not in df.columns:
            return np.arange(len(df))
        hit = ~df.match_id.isin(after) & ~df.match_id.isin(c.keep)
        return np.flatnonzero(hit.to_numpy())

    return _corrupt(data_dir, season, _present(data_dir, season), rules, pick, True, rng)
