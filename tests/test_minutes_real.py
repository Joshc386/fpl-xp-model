"""The minutes component on the real upstream checkout (skipped when it is not there).

Internal consistency only: keys, ranges and expected starters. Nothing here compares a
prediction with an outcome; 2026/27 is the holdout.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest

from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models import elo, minutes
from fpl.models.minutes import OUT_COLUMNS, PROBABILITIES, player_minutes
from fpl.models.team_goals import elo_goals

CFG = load_config(ROOT / "config" / "pipeline.yaml")
pytestmark = pytest.mark.skipif(
    not (upstream_data_dir(CFG) / "2026-2027" / "By Gameweek" / "GW10").exists(),
    reason="no upstream checkout",
)
READS = [("2025-2026", 32, "backtest"), ("2026-2027", 10, "live")]   # GW33 has six doubles


@pytest.fixture(scope="module")
def real() -> Iterator[dict]:
    """player_minutes for each of `READS`, with a memoised loader patched in for the module."""
    cache: dict[tuple[str, int, str], dict] = {}

    def load(season: str, as_of: int, mode: str) -> dict:
        if (season, as_of, mode) not in cache:
            cache[(season, as_of, mode)] = load_as_of(season, as_of, mode)
        return cache[(season, as_of, mode)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(minutes, "load_as_of", load)
        mp.setattr(elo, "load_as_of", load)
        yield {read: (player_minutes(*read), load(*read)) for read in READS}


@pytest.mark.parametrize("read", READS)
def test_keys_are_unique_and_nothing_is_missing(real: dict, read: tuple) -> None:
    out, tables = real[read]
    assert list(out.columns) == OUT_COLUMNS
    assert not out.duplicated(["player_id", "match_id"]).any()
    assert out.notna().all().all()
    assert set(out.player_id) == set(tables["dim_player"].player_id)


@pytest.mark.parametrize("read", READS)
def test_probabilities_are_ordered_and_minutes_fit_a_match(real: dict, read: tuple) -> None:
    out, _ = real[read]
    assert out[PROBABILITIES].stack().between(0, 1).all()
    assert (out.p_60 <= out.p_start + 1e-12).all()
    assert (out.p_start <= out.p_appear + 1e-12).all()
    assert out.exp_minutes.between(0, 90).all()


@pytest.mark.parametrize("read", READS)
def test_expected_starters_per_club_fixture_are_about_eleven(real: dict, read: tuple) -> None:
    # Below 11 because v1 zeroes injured and suspended starters without handing their starts
    # to anyone, and cuts the second fixture of a double gameweek.
    out, _ = real[read]
    starters = out.groupby(["team_id", "match_id"]).p_start.sum()
    assert starters.max() <= 11 + 1e-9
    assert 9.5 <= starters.mean() <= 11 and starters.min() >= 8


@pytest.mark.parametrize("read", READS)
def test_the_fixtures_are_the_ones_the_elo_goals_model_chooses(real: dict, read: tuple) -> None:
    out, _ = real[read]
    theirs = elo_goals(*read)[["team_id", "match_id", "gw"]]
    mine = out[["team_id", "match_id", "gw"]].drop_duplicates()
    assert set(mine.itertuples(index=False)) == set(theirs.itertuples(index=False))


def test_a_double_gameweek_has_two_rows_for_each_player_of_its_clubs(real: dict) -> None:
    out, _ = real[READS[0]]
    per = out[out.gw == 33].groupby(["team_id", "player_id"]).size()
    assert set(per) == {1, 2} and (per == 2).groupby(level=0).all().sum() == 6
    assert pd.Series(per).index.get_level_values(0).nunique() == 20
