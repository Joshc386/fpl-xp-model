"""Ranking agreement (`CONTEXT.md`): Spearman per gameweek over team-kickoffs, a double
gameweek counting each kickoff, ties ranked by their average, and the biggest disagreements."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from backtest.beyondelo_data import rank_disagreements, ranking_by_gameweek, team_kickoffs

NAMES = pd.Series({1: "Alpha", 2: "Beta", 3: "Gamma", 4: "Delta", 5: "Epsilon"})


def table() -> pd.DataFrame:
    """GW7 is a double for club 1 (home in m1, away in m2), with ties in both sources; GW8 has
    two matches ranked identically by both."""
    rows = [  # match, gw, home, away, ours home/away, beyondELO home/away
        ("m1", 7, 1, 2, 10.0, 20.0, 1.0, 3.0),
        ("m2", 7, 3, 1, 20.0, 30.0, 2.0, 2.0),
        ("m3", 7, 4, 5, 40.0, 50.0, 5.0, 4.0),
        ("m4", 8, 1, 2, 10.0, 20.0, 100.0, 200.0),
        ("m5", 8, 3, 4, 30.0, 40.0, 300.0, 400.0),
    ]
    df = pd.DataFrame(rows, columns=["match_id", "gw", "home_team_id", "away_team_id",
                                     "ours_home", "ours_away", "beyondelo_home",
                                     "beyondelo_away"])
    return df.assign(season="2025-2026", kickoff_utc=[f"2025-10-0{i}T15:00:00Z"
                                                      for i in range(1, 6)])


def test_a_double_gameweek_counts_each_kickoff() -> None:
    k = team_kickoffs(table())
    gw7 = k[k.gw == 7]
    assert len(gw7) == 6 and (gw7.team_id == 1).sum() == 2


def test_spearman_per_gameweek_ranks_ties_by_their_average() -> None:
    # Average ranks: ours 1, 2.5, 2.5, 4, 5, 6 and beyondELO's 1, 4, 2.5, 2.5, 6, 5, so the
    # Pearson correlation of the ranks is 13.75 / 17.
    r = ranking_by_gameweek(table())
    assert list(r.gw) == [7, 8] and list(r.n) == [6, 4]
    assert r.spearman.iloc[0] == pytest.approx(13.75 / 17, abs=1e-12)
    assert r.spearman.iloc[1] == pytest.approx(1.0, abs=1e-12)


def test_a_gameweek_one_source_rates_all_equal_has_no_spearman() -> None:
    t = table()
    t.loc[t.gw == 8, ["beyondelo_home", "beyondelo_away"]] = 5.0
    assert math.isnan(ranking_by_gameweek(t).spearman.iloc[1])


def test_the_biggest_disagreements_rank_highest_first_and_break_ties_by_club() -> None:
    # Ranks with 1 the highest: ours 6, 4.5, 4.5, 3, 2, 1 and beyondELO's 6, 3, 4.5, 4.5, 1, 2.
    d = rank_disagreements(table(), 7, NAMES, 3)
    assert list(d.team) == ["Alpha", "Beta", "Delta"]
    assert list(d.match_id) == ["m2", "m1", "m3"]
    assert list(d.our_rank) == [3.0, 4.5, 2.0]
    assert list(d.beyondelo_rank) == [4.5, 3.0, 1.0]
    assert list(d.rank_gap) == [1.5, 1.5, 1.0]
    assert list(d.elo_before) == [30.0, 20.0, 40.0]
    assert list(d.beyondelo_before) == [2.0, 3.0, 5.0]
