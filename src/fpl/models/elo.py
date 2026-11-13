"""The Elo component: the model's own club ratings over finished Premier League results.

The run starts at GW1 of `elo.start_season` (brief data rule 12). Results are played in
kickoff order, season after season, and clubs are matched across seasons on `team_code`,
never `team_id`. Seeds come only from Premier League kickoff upstream Elo among the finished
matches in the read, and each season's seeds are set before its first match:
* in the first season, each club's first non-null value;
* in a later season, a club with a value at its last match of the previous season is
  re-seeded from it (for 2026/27, ClubElo's end-of-season 2025/26 rating); a club whose
  last-match value is null carries its own rating;
* a club new to the run (a promoted club) from its first non-null value in the new season.
A club that needs a rating and has no seed raises `MissingSeedError`.

The update is standard Elo with a home advantage and a goal-margin factor:
    E = 1 / (1 + 10 ** (-(r_home + home_advantage - r_away) / scale))
    change = k * max(1, |goal difference|) ** margin_power * (result - E)
The home club gains `change` and the away club loses it, so each match is zero-sum.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config

log = logging.getLogger(__name__)

MODEL_CONFIG = ROOT / "config" / "model.yaml"
PIPELINE_CONFIG = ROOT / "config" / "pipeline.yaml"
OUT_COLUMNS = ["team_id", "match_id", "season", "gw", "kickoff_utc", "elo_before", "elo_after"]


class EloError(ValueError):
    """The Elo ratings cannot be computed from the read."""


class MissingSeedError(EloError):
    """A club needs a rating, and the read holds no upstream Elo to seed it from."""


def model_config(path: Path = MODEL_CONFIG) -> dict:
    """config/model.yaml."""
    return load_config(path)


def pipeline_config(path: Path = PIPELINE_CONFIG) -> dict:
    """config/pipeline.yaml (seasons and the Premier League tag; read only)."""
    return load_config(path)


@dataclass(frozen=True)
class EloSettings:
    """The Elo update's settings (`elo` in config/model.yaml)."""

    k: float
    home_advantage: float
    margin_power: float
    scale: float

    @classmethod
    def from_config(cls, cfg: dict) -> EloSettings:
        """The settings in `cfg["elo"]` (the parsed config/model.yaml)."""
        e = cfg["elo"]
        return cls(float(e["k"]), float(e["home_advantage"]), float(e["margin_power"]),
                   float(e["scale"]))


class SeasonRead(NamedTuple):
    """One season's `load_as_of` tables and the as-of gameweek they were read at."""

    season: str
    as_of_gw: int
    tables: dict[str, pd.DataFrame]


Seeds = dict[str, dict[int, float]]  # season -> team_code -> rating set before its first match


class EloRun(NamedTuple):
    """The finished matches of a run with both clubs' ratings, and the current ratings."""

    matches: pd.DataFrame  # one row per match: fixture columns, codes, home/away elo_before/after
    ratings: dict[int, float]  # team_code -> rating after the club's last finished match


def expected_home(r_home: float, r_away: float, s: EloSettings) -> float:
    """The home club's expected score (win 1, draw 1/2), with the home advantage."""
    return 1.0 / (1.0 + 10.0 ** (-(r_home + s.home_advantage - r_away) / s.scale))


def margin_factor(goal_diff: int, power: float) -> float:
    """Weight of a result by its goal margin: 1 for a draw or one goal, |diff| ** power above."""
    return float(max(1, abs(goal_diff))) ** power


def elo_change(r_home: float, r_away: float, home_goals: int, away_goals: int,
               s: EloSettings) -> float:
    """Rating points the home club gains from the result (the away club loses as many)."""
    result = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
    weight = s.k * margin_factor(home_goals - away_goals, s.margin_power)
    return weight * (result - expected_home(r_home, r_away, s))


def prem_fixtures(read: SeasonRead, prem_tag: str) -> pd.DataFrame:
    """The season's Premier League fixtures in kickoff order, with both clubs' team codes."""
    fx = read.tables["fact_fixture"]
    fx = fx[fx.tournament == prem_tag]
    codes = read.tables["dim_team"].set_index("team_id").team_code
    out = fx.assign(home_code=fx.home_team_id.map(codes), away_code=fx.away_team_id.map(codes))
    if out[["home_code", "away_code"]].isna().any().any():
        raise EloError(f"{read.season}: a Premier League fixture's club is not in dim_team")
    out = out.astype({"home_code": "int64", "away_code": "int64"})
    return out.sort_values(["kickoff_utc", "match_id"], ignore_index=True)


def finished_results(fixtures: pd.DataFrame, as_of_gw: int) -> pd.DataFrame:
    """Finished fixtures up to the as-of gameweek. Later rows are never used, even if present."""
    played = fixtures[fixtures.finished & (fixtures.gw <= as_of_gw)]
    if played[["home_goals", "away_goals"]].isna().any().any():
        raise EloError("a finished Premier League fixture has no score")
    return played


def _kickoff_elo(results: pd.DataFrame) -> pd.DataFrame:
    """One row per club per finished match, in kickoff order: kickoff, team_code, upstream Elo."""
    names = ["kickoff_utc", "code", "elo"]
    sides = pd.concat([
        results[["kickoff_utc", f"{side}_code", f"{side}_upstream_elo"]].set_axis(names, axis=1)
        for side in ("home", "away")
    ])
    return sides.sort_values("kickoff_utc", kind="stable")


def _first_upstream(results: pd.DataFrame) -> pd.Series:
    """Each club's first non-null kickoff upstream Elo (team_code -> Elo)."""
    return _kickoff_elo(results).dropna(subset=["elo"]).groupby("code").elo.first()


def _last_upstream(results: pd.DataFrame) -> pd.Series:
    """Each club's kickoff upstream Elo at its last finished match, null if that one is null."""
    return _kickoff_elo(results).drop_duplicates("code", keep="last").set_index("code").elo


def _new_club_seeds(read: SeasonRead, results: pd.DataFrame, new: set[int]) -> dict[int, float]:
    """Seeds for clubs new to the run, from their first value; raise if one has none."""
    first = _first_upstream(results)
    missing = sorted(c for c in new if c not in first.index)
    if missing:
        names = read.tables["dim_team"].set_index("team_code").name
        clubs = ", ".join(f"{names[c]} (team_code {c})" for c in missing)
        raise MissingSeedError(
            f"{read.season} as-of {read.as_of_gw}: no Premier League kickoff upstream Elo among "
            f"the finished matches in the read to seed {clubs}"
        )
    return {c: float(first[c]) for c in sorted(new)}


def season_seeds(read: SeasonRead, fixtures: pd.DataFrame, results: pd.DataFrame,
                 rated: set[int], last: pd.Series) -> dict[int, float]:
    """The ratings set at the start of the season in `read`.

    `rated` holds the clubs of every earlier season; `last` the previous season's last-match
    upstream Elo per club. A continuing club with a last-match value is re-seeded from it,
    one without carries its rating (no entry), and a club new to the run gets its first value.
    """
    clubs = set(fixtures.home_code) | set(fixtures.away_code)
    reseed = {int(c): float(v) for c, v in last.dropna().items() if c in clubs}
    return reseed | _new_club_seeds(read, results, clubs - rated)


def prepare(history: Sequence[SeasonRead], prem_tag: str) -> tuple[pd.DataFrame, Seeds]:
    """Every finished result of the run in kickoff order, and each season's seeds."""
    parts: list[pd.DataFrame] = []
    seeds: Seeds = {}
    rated: set[int] = set()
    last = pd.Series(dtype="float64")
    for read in history:
        fixtures = prem_fixtures(read, prem_tag)
        results = finished_results(fixtures, read.as_of_gw)
        seeds[read.season] = season_seeds(read, fixtures, results, rated, last)
        rated |= set(fixtures.home_code) | set(fixtures.away_code)
        last = _last_upstream(results)
        parts.append(results)
    return pd.concat(parts, ignore_index=True), seeds


def play(results: pd.DataFrame, seeds: Seeds, s: EloSettings) -> EloRun:
    """Play the results season by season, setting each season's seeds before its first match."""
    ratings: dict[int, float] = {}
    rows: list[tuple[float, float, float, float]] = []
    index: list[int] = []
    for season, season_seeds_ in seeds.items():
        ratings |= season_seeds_
        part = results[results.season == season]
        for hc, ac, hg, ag in zip(part.home_code.tolist(), part.away_code.tolist(),
                                  part.home_goals.tolist(), part.away_goals.tolist(), strict=True):
            rh, ra = ratings[hc], ratings[ac]
            change = elo_change(rh, ra, hg, ag, s)
            ratings[hc], ratings[ac] = rh + change, ra - change
            rows.append((rh, ra, rh + change, ra - change))
        index.extend(part.index)
    elo = pd.DataFrame(
        rows, index=index, dtype="float64",
        columns=["home_elo_before", "away_elo_before", "home_elo_after", "away_elo_after"],
    )
    return EloRun(pd.concat([results, elo], axis=1), ratings)


def run_elo(history: Sequence[SeasonRead], s: EloSettings, prem_tag: str) -> EloRun:
    """The pure core: the Elo run over the reads in `history`, oldest season first."""
    results, seeds = prepare(history, prem_tag)
    return play(results, seeds, s)


def team_rows(matches: pd.DataFrame) -> pd.DataFrame:
    """One row per team per match, home first: the `elo_ratings.csv` rows."""
    keys = ["match_id", "season", "gw", "kickoff_utc"]
    sides = [
        matches[keys + [f"{side}_team_id", f"{side}_elo_before", f"{side}_elo_after"]]
        .set_axis(keys + ["team_id", "elo_before", "elo_after"], axis=1).assign(_side=i)
        for i, side in enumerate(("home", "away"))
    ]
    out = pd.concat(sides).sort_values(["kickoff_utc", "match_id", "_side"])
    return out.astype({"team_id": "int64"})[OUT_COLUMNS].reset_index(drop=True)


def load_history(season: str, as_of_gw: int, mode: str) -> list[SeasonRead]:
    """The reads a call needs, oldest first.

    Each earlier season of the run is read in full (its last gameweek) in backtest mode, as
    finished history; `season` is read at `as_of_gw` in `mode`.
    """
    seasons = pipeline_config()["seasons"]
    ids = [s["id"] for s in seasons]
    start = model_config()["elo"]["start_season"]
    if season not in ids or start not in ids or ids.index(season) < ids.index(start):
        raise ValueError(f"season {season!r} is not in the Elo run ({start} onwards of {ids})")
    reads = [
        SeasonRead(s["id"], int(s["gameweeks"]), load_as_of(s["id"], int(s["gameweeks"]),
                                                            "backtest"))
        for s in seasons[ids.index(start):ids.index(season)]
    ]
    return reads + [SeasonRead(season, as_of_gw, load_as_of(season, as_of_gw, mode))]


def elo_ratings(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """Our Elo rating before and after every finished Premier League match.

    Covers `elo.start_season` onwards up to `season` at `as_of_gw`, each season seeded as in
    the module docstring; `mode` goes to
    `load_as_of`. Rows carry each season's own `team_id` (the `elo_ratings.csv` rows).
    Raises `MissingSeedError` if a club of the run has no seed in the read.
    """
    history = load_history(season, as_of_gw, mode)
    run = run_elo(history, EloSettings.from_config(model_config()),
                  pipeline_config()["premier_league_tag"])
    out = team_rows(run.matches)
    log.info("Elo %s as-of %d (%s): %d team-match rows", season, as_of_gw, mode, len(out))
    return out
