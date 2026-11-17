"""The correction reaches the loader on the real checkout (skipped without it)."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir

CFG = load_config(ROOT / "config" / "pipeline.yaml")
DATA = upstream_data_dir(CFG)
SEASON = "2025-2026"
pytestmark = pytest.mark.skipif(
    not (DATA / SEASON / "By Gameweek" / "GW38").exists(), reason="no upstream checkout"
)


def goals(as_of: int, mode: str) -> tuple:
    entry = next(e for e in CFG["score_corrections"] if e["season"] == SEASON)
    fx = load_as_of(SEASON, as_of, mode)["fact_fixture"]
    row = fx[fx.match_id == entry["match_id"]].iloc[0]
    return row.finished, row.home_goals, row.away_goals


@pytest.mark.parametrize("as_of", [8, 38])
def test_backtest_reads_from_the_match_on_give_the_corrected_score(as_of: int) -> None:
    assert goals(as_of, "backtest") == (True, 1, 2)


def test_a_read_before_the_match_has_no_score() -> None:
    finished, home, away = goals(7, "backtest")
    assert not finished and pd.isna(home) and pd.isna(away)


def test_a_live_read_gives_the_corrected_score() -> None:
    assert goals(20, "live") == (True, 1, 2)
