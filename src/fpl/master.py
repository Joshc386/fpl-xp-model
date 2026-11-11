"""Readers of the master files (`data/{season}/*.csv`). Only live mode calls these.

Backtest mode never reads a master file, and `ingest.read_season` reads only the
`By Gameweek` folders. Keeping the master readers in one module makes that checkable.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fpl.ingest import IngestError, read_table
from fpl.schema import raw_columns


def _read_master(path: Path, file: str) -> pd.DataFrame:
    """Read a master file, keeping the required columns; raise if any is absent."""
    df = read_table(path, file)
    absent = [c for c in raw_columns(file) if c not in df.columns]
    if absent:
        raise IngestError(f"{path.name} lacks columns {absent}")
    return df[raw_columns(file)]


def read_deadlines(season_dir: Path) -> pd.DataFrame:
    """The master gameweek_summaries.csv: `deadline_time` and `id`."""
    return _read_master(season_dir / "gameweek_summaries.csv", "gameweek_summaries")


def read_master_state(season_dir: Path) -> pd.DataFrame:
    """The master playerstats.csv, one row per player per gameweek."""
    return _read_master(season_dir / "playerstats.csv", "playerstats")
