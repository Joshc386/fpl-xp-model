"""`use_data_copy` on a real copy of the upstream data (skipped when there is no checkout).

The copy changes one finished Premier League result in 2026/27 GW10, so the Elo ratings show
which data the model's public function read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from fpl.features import use_data_copy
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models.elo import elo_ratings

CFG = load_config(ROOT / "config" / "pipeline.yaml")
DATA = upstream_data_dir(CFG)
SEASON = "2026-2027"
pytestmark = pytest.mark.skipif(not (DATA / SEASON / "By Gameweek" / "GW10").exists(),
                                reason="no upstream checkout")


@pytest.fixture(scope="module")
def copy(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A copy of the data (without By Tournament) with one GW10 score set to 9-0, and its id."""
    dest = tmp_path_factory.mktemp("copy") / "data"
    shutil.copytree(DATA, dest, ignore=shutil.ignore_patterns("By Tournament"))
    path = dest / SEASON / "By Gameweek" / "GW10" / "matches.csv"
    matches = pd.read_csv(path)
    row = matches[(matches.tournament == CFG["premier_league_tag"]) & matches.finished].index[0]
    matches.loc[row, ["home_score", "away_score"]] = [9, 0]
    matches.to_csv(path, index=False)
    return dest, str(matches.loc[row, "match_id"])


def home_change(ratings: pd.DataFrame, match_id: str) -> float:
    """The home club's rating change in a match (its first row)."""
    row = ratings[ratings.match_id == match_id].iloc[0]
    return float(row.elo_after - row.elo_before)


def test_elo_ratings_read_the_copy_inside_the_block_and_the_checkout_outside(
    copy: tuple[Path, str],
) -> None:
    dest, match_id = copy
    before = elo_ratings(SEASON, 10, "backtest")
    with use_data_copy(dest):
        inside = elo_ratings(SEASON, 10, "backtest")
    after = elo_ratings(SEASON, 10, "backtest")
    pd.testing.assert_frame_equal(before, after)
    assert not before.equals(inside)
    assert home_change(inside, match_id) > home_change(before, match_id)
