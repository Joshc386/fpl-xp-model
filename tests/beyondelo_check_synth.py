"""A seeded synthetic world for the outside-source Elo check's run tests. All invented.

Two seasons of 10 clubs, 5 matches a gameweek. Results come from an ordered logistic model on
the clubs' true strengths. Our ratings are a function of the truth, and beyondELO's of ours
and the truth.
The windows mirror the real ones in shape: fit S1 GW1-12, scored S1 GW13-18 and S2 GW3-10,
with S2 data running on to GW12 so the pin can be checked.
"""

from __future__ import annotations

import copy
from collections.abc import Callable

import numpy as np
import pandas as pd
from backtest.beyondelo_check import Inputs

from beyondelo_check_frames import PREM

S1, S2 = "2025-2026", "2026-2027"
GWS = {S1: 18, S2: 12}
CLUBS = list(range(1, 11))
NAMES = pd.Series({c: f"Club{c:02d}" for c in CLUBS})
SETTINGS = {
    "mode": "backtest",
    "report_dir": "unused",
    "beyondelo_check": {
        "fit": {"season": S1, "gameweeks": [1, 12]},
        "scored": [{"season": S1, "gameweeks": [13, 18]}, {"season": S2, "gameweeks": [3, 10]}],
        "ratings_file": "outputs/elo_ratings.csv", "meta_file": "outputs/meta.csv",
        "fit_tolerance": 1e-12, "max_iterations": 50, "se_multiple": 2, "compare_decimals": 9,
        "top_disagreements": 5, "report_suffix": "beyondelo",
    },
}
Rating = Callable[[np.ndarray, np.random.Generator], np.ndarray]
Theirs = Callable[[np.ndarray, np.ndarray, np.random.Generator], np.ndarray]


def settings() -> dict:
    """A fresh copy of the synthetic settings."""
    return copy.deepcopy(SETTINGS)


def informative(truth: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Ratings that track the truth with some noise."""
    return truth + rng.normal(0.0, 40.0, len(truth))


def informative_theirs(ours: np.ndarray, truth: np.ndarray,
                       rng: np.random.Generator) -> np.ndarray:
    """beyondELO's default: its own noisy view of the truth, on another scale."""
    return 0.8 * informative(truth, rng) + 200.0


def _fixtures(season: str, rng: np.random.Generator, strength: dict[int, float]) -> pd.DataFrame:
    rows = []
    for gw in range(1, GWS[season] + 1):
        order = rng.permutation(CLUBS)
        for i in range(0, len(order), 2):
            h, a = int(order[i]), int(order[i + 1])
            gap = strength[h] - strength[a] + 60.0
            u = rng.uniform()
            p_away = 1 / (1 + np.exp(-(-0.8 - 0.005 * gap)))
            p_not_home = 1 / (1 + np.exp(-(0.4 - 0.005 * gap)))
            hg, ag = (0, 1) if u < p_away else (1, 1) if u < p_not_home else (2, 0)
            rows.append({"match_id": f"{season[:4]}-{gw:02d}-{h}v{a}", "gw": gw,
                         "kickoff_utc": f"{season[:4]}-{gw:02d}-01T{12 + i:02d}:00:00Z",
                         "home_team_id": h, "away_team_id": a, "home_goals": hg,
                         "away_goals": ag, "finished": True})
    df = pd.DataFrame(rows).assign(season=season, tournament=PREM)
    for c in ("home_team_id", "away_team_id", "home_goals", "away_goals"):
        df[c] = df[c].astype("Int64")
    return df


def _ratings(fx: pd.DataFrame, values: np.ndarray, col: str) -> pd.DataFrame:
    rows = []
    for (r, v) in zip(fx.itertuples(), values.reshape(-1, 2), strict=True):
        for t, home, x in ((int(r.home_team_id), True, v[0]), (int(r.away_team_id), False, v[1])):
            rows.append({"team_id": t, "match_id": r.match_id, "season": r.season,
                         "gw": int(r.gw), "kickoff_utc": r.kickoff_utc, "home": home, col: x})
    return pd.DataFrame(rows)


def world(seed: int = 20261117, ours: Rating = informative, theirs: Theirs = informative_theirs,
          promoted: frozenset[int] = frozenset()) -> Inputs:
    """The synthetic inputs: every match of both seasons with both ratings and its result."""
    rng = np.random.default_rng(seed)
    strength = {c: float(s) for c, s in zip(CLUBS, rng.normal(0.0, 120.0, len(CLUBS)),
                                            strict=True)}
    fixtures, our_rows, be = {}, [], {}
    for season in (S1, S2):
        fx = _fixtures(season, rng, strength)
        truth = np.array([[strength[int(h)], strength[int(a)]]
                          for h, a in zip(fx.home_team_id, fx.away_team_id, strict=True)])
        truth = truth.ravel() + 1500.0
        mine_values = ours(truth, rng)
        mine = _ratings(fx, mine_values, "elo_before")
        our_rows.append(mine.drop(columns="home").assign(elo_after=mine.elo_before))
        b = _ratings(fx, theirs(mine_values, truth, rng), "beyondelo_before")
        be[season] = b.assign(promoted=b.team_id.isin(promoted) & (season == S2))
        fixtures[season] = fx
    return Inputs(ours=pd.concat(our_rows, ignore_index=True), beyondelo=be,
                  fixtures=fixtures, names={S1: NAMES, S2: NAMES}, prem=PREM)
