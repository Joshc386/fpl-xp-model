"""The minutes component v1 (brief section 6.1): start, appearance and 60-minute chances.

For each player, from his last `minutes.windows` Premier League gameweeks with a club fixture
(`features.recent_minutes`; each window weighted per `minutes.window_weights`):
* `p_start` is the weighted start rate, starts / fixtures, so a double gameweek counts as two
  matches;
* the rates given a start (P(60 minutes), minutes) and given no start (a bench appearance, its
  minutes) come from single-fixture gameweeks, where FPL's gameweek minutes are the match's,
  and are shrunk toward the season-to-date position average (`minutes.prior_strength`);
* `p_appear` = p_start + (1 - p_start) * bench rate, `p_60` = p_start * P(60 | start), and
  `exp_minutes` = p_start * minutes given a start + (1 - p_start) * bench rate * minutes given
  a bench appearance.
In a club's second fixture of a double gameweek the start rate is cut by
`minutes.second_fixture_discount`. Last, the availability override: status injured, suspended,
unavailable or not available sets all four to 0 in every gameweek of the horizon, and a chance
of playing below 100 scales them in the next gameweek only, as FPL's chance is for the next
round. The 60-minute line is scoring.yaml's `appearance.long_min_minutes`, on FPL minutes
(brief data rule 2). The per-player rates are in `models/minutes_rates.py`. Why each choice:
docs/decisions.md, "model - minutes v1".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config
from fpl.models.elo import model_config, pipeline_config
from fpl.models.minutes_rates import (
    MinutesError,
    gameweek_counts,
    gameweek_history,
    gameweek_weights,
    player_rates,
    position_priors,
)

log = logging.getLogger(__name__)

SCORING_CONFIG = ROOT / "config" / "scoring.yaml"
OUT_COLUMNS = ["player_id", "team_id", "match_id", "gw", "p_appear", "p_start", "p_60",
               "exp_minutes"]
PROBABILITIES = ["p_appear", "p_start", "p_60"]
# FPL status codes: available, doubtful, and the four that set every output to 0 (injured,
# suspended, unavailable, not available). Every code in both seasons is one of these.
AVAILABLE, DOUBTFUL = "a", "d"
UNAVAILABLE = frozenset({"i", "s", "u", "n"})
STATUSES = UNAVAILABLE | {AVAILABLE, DOUBTFUL}
@dataclass(frozen=True)
class MinutesSettings:
    """The minutes settings (`minutes` and `max_horizon` in config/model.yaml) and the
    60-minute line (`appearance.long_min_minutes` in config/scoring.yaml)."""

    windows: tuple[int, ...]
    weights: tuple[float, ...]
    prior_strength: float
    second_fixture_discount: float
    long_minutes: int
    max_horizon: int

    def __post_init__(self) -> None:
        gameweek_weights(self.windows, self.weights)
        if not self.prior_strength > 0:
            raise MinutesError(f"minutes.prior_strength must be positive, got "
                               f"{self.prior_strength}")
        if not 0 <= self.second_fixture_discount < 1:
            raise MinutesError(f"minutes.second_fixture_discount must be in [0, 1), got "
                               f"{self.second_fixture_discount}")
        if self.long_minutes < 1 or self.max_horizon < 1:
            raise MinutesError(f"long_minutes and max_horizon must be positive, got "
                               f"{self.long_minutes} and {self.max_horizon}")

    @classmethod
    def from_config(cls, model_cfg: dict, scoring_cfg: dict) -> MinutesSettings:
        """The settings in the parsed config/model.yaml and config/scoring.yaml."""
        m = model_cfg["minutes"]
        return cls(tuple(int(n) for n in m["windows"]),
                   tuple(float(w) for w in m["window_weights"]), float(m["prior_strength"]),
                   float(m["second_fixture_discount"]),
                   int(scoring_cfg["appearance"]["long_min_minutes"]),
                   int(model_cfg["max_horizon"]))

    @property
    def gameweek_weights(self) -> np.ndarray:
        """The weight of each recency, most recent first (`gameweek_weights`)."""
        return gameweek_weights(self.windows, self.weights)


def availability(status: pd.Series, chance: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """The availability override's factors per player, from FPL `status` and `chance_next`:
    (every gameweek of the horizon, the next gameweek).

    * Injured, suspended, unavailable or not available (`UNAVAILABLE`): 0 in every gameweek.
    * Otherwise 1 in every gameweek, and in the next gameweek the chance of playing / 100,
      since FPL's chance is for the next round; a null chance reads as 100.
    * Available with a chance of 0 is read as 100: 2025/26's GW2-10 snapshots give 345-565
      available players a chance of 0 with no news, and about half of them played the next
      gameweek, the same share as those at 100 (docs/decisions.md, "model - minutes v1").
    Raises `MinutesError` for a status not in `STATUSES` or a chance outside 0-100.
    """
    unknown = sorted(set(status.dropna()) - STATUSES) + (["null"] if status.isna().any() else [])
    if unknown:
        raise MinutesError(f"unknown status {unknown}; known: {sorted(STATUSES)}")
    pct = chance.astype("Float64").to_numpy(dtype="float64", na_value=np.nan)
    outside = (pct < 0) | (pct > 100)
    if outside.any():
        raise MinutesError(f"chance_next outside 0-100: {sorted(set(pct[outside]))}")
    is_available = status.to_numpy() == AVAILABLE
    every = np.where(status.isin(UNAVAILABLE).to_numpy(), 0.0, 1.0)
    chance_factor = np.where(np.isnan(pct) | (is_available & (pct == 0)), 1.0, pct / 100)
    return every, every * chance_factor


def club_fixtures(fixtures: pd.DataFrame, as_of_gw: int, horizon: int,
                  prem_tag: str) -> pd.DataFrame:
    """One row per club per Premier League fixture with `gw` in (as_of_gw, as_of_gw + horizon].

    The same fixtures as the Elo goals model: chosen by gameweek, never by `finished`. `nth`
    is the fixture's place among the club's fixtures of that gameweek by kickoff (0 first, 1
    the second of a double gameweek). A club with no fixture in a gameweek has no row.
    """
    fx = fixtures[(fixtures.tournament == prem_tag) & (fixtures.gw > as_of_gw)
                  & (fixtures.gw <= as_of_gw + horizon)]
    sides = pd.concat([
        fx[["match_id", "gw", "kickoff_utc", col]].rename(columns={col: "team_id"})
        for col in ("home_team_id", "away_team_id")
    ])
    if sides.team_id.isna().any():
        raise MinutesError("a Premier League fixture in the horizon has no club")
    sides = sides.astype({"team_id": "int64", "gw": "int64"}).sort_values(
        ["team_id", "gw", "kickoff_utc", "match_id"])
    sides["nth"] = sides.groupby(["team_id", "gw"]).cumcount()
    return sides[["team_id", "match_id", "gw", "kickoff_utc", "nth"]].reset_index(drop=True)


def project(players: pd.DataFrame, fixtures: pd.DataFrame, settings: MinutesSettings,
            next_gw: int) -> pd.DataFrame:
    """Per player per fixture of his club: the hand-off columns (`OUT_COLUMNS`).

    `players` holds `player_id`, `team_id`, the `player_rates` columns and the `availability`
    factors `available` (every gameweek) and `available_next` (gameweek `next_gw`, both
    fixtures of a double); `fixtures` is `club_fixtures`. In a club's second fixture of a
    gameweek the start rate is cut by `second_fixture_discount` (rotation), and a player not
    starting can still come off the bench. Then:
        p_appear    = p_start + (1 - p_start) * bench_rate
        p_60        = p_start * p60_given_start
        exp_minutes = p_start * minutes_given_start
                      + (1 - p_start) * bench_rate * minutes_given_bench
    and all four are multiplied by the row's availability factor.
    """
    rows = players.merge(fixtures, on="team_id", how="inner", validate="many_to_many")
    rotation = np.where(rows.nth.to_numpy() > 0, 1 - settings.second_fixture_discount, 1.0)
    start = rows.start_rate.to_numpy() * rotation
    bench = (1 - start) * rows.bench_rate.to_numpy()
    factor = np.where(rows.gw.to_numpy() == next_gw, rows.available_next.to_numpy(),
                      rows.available.to_numpy())
    out = rows.assign(
        p_appear=factor * (start + bench),
        p_start=factor * start,
        p_60=factor * start * rows.p60_given_start.to_numpy(),
        exp_minutes=factor * (start * rows.minutes_given_start.to_numpy()
                              + bench * rows.minutes_given_bench.to_numpy()),
    )
    out = out.sort_values(["gw", "kickoff_utc", "match_id", "team_id", "player_id"])
    return out[OUT_COLUMNS].reset_index(drop=True)


def minutes_from_tables(tables: dict[str, pd.DataFrame], as_of_gw: int,
                        settings: MinutesSettings, prem_tag: str) -> pd.DataFrame:
    """The pure core of `player_minutes`: its rows from one `load_as_of` read.

    Every `dim_player` player gets a row for each fixture of his `dim_player` club in the
    horizon. His rates use his own history whatever the club, and the position priors use
    every gameweek of the season up to `as_of_gw`. The chance of playing scales the next
    gameweek, `as_of_gw` + 1, only.
    """
    players = tables["dim_player"]
    depth = max(as_of_gw, settings.windows[-1])
    counts = gameweek_counts(gameweek_history(tables, as_of_gw, depth, prem_tag),
                             settings.long_minutes)
    positions = players.set_index("player_id").position
    rates = player_rates(counts, positions, settings.gameweek_weights,
                         position_priors(counts, positions), settings.prior_strength)
    every, next_gw = availability(players.status, players.chance_next)
    frame = players[["player_id", "team_id"]].join(rates, on="player_id").assign(
        available=every, available_next=next_gw)
    fixtures = club_fixtures(tables["fact_fixture"], as_of_gw, settings.max_horizon, prem_tag)
    return project(frame, fixtures, settings, as_of_gw + 1)


def player_minutes(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """Minutes for `season`'s next `max_horizon` gameweeks after `as_of_gw` (brief 6.1).

    `mode` goes to `load_as_of`. One row per player per Premier League fixture of his club
    with `gw` in (as_of_gw, as_of_gw + max_horizon]: `player_id`, `team_id`, `match_id`,
    `gw`, `p_appear`, `p_start`, `p_60`, `exp_minutes`. A blank gameweek has no row; a double
    has two. No rows at as-of 0, where `dim_player` is empty, or at the season's last as-of.
    """
    settings = MinutesSettings.from_config(model_config(), load_config(SCORING_CONFIG))
    out = minutes_from_tables(load_as_of(season, as_of_gw, mode), as_of_gw, settings,
                              pipeline_config()["premier_league_tag"])
    log.info("minutes %s as-of %d (%s): %d rows, %d players", season, as_of_gw, mode, len(out),
             out.player_id.nunique())
    return out
