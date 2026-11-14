"""Output checks for the two model-built files: fixture_difficulty.csv and elo_ratings.csv.

Each function returns a list of problems rather than raising, except on input malformed
beyond the schema (see `output_checks`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FIXTURE_KEY = ["team_id", "match_id"]


def _expected_fixtures(
    fixtures: pd.DataFrame, prem_tag: str, first: int, last: int
) -> pd.DataFrame:
    """The team rows the horizon should hold: every Premier League fixture in gameweeks
    `first`..`last`, once per side."""
    fx = fixtures[(fixtures.tournament == prem_tag) & fixtures.gw.between(first, last)]
    sides = [
        pd.DataFrame({
            "team_id": fx[team].astype("int64"), "match_id": fx.match_id, "gw": fx.gw,
            "opponent_id": fx[opp].astype("int64"), "home": home,
        })
        for team, opp, home in (("home_team_id", "away_team_id", True),
                                ("away_team_id", "home_team_id", False))
    ]
    return pd.concat(sides, ignore_index=True)


def _lambda_problems(fd: pd.DataFrame, tol: float, lambda_max: float) -> list[str]:
    """Both lambdas strictly inside (0, `lambda_max`); `p_cs` in [0, 1] and exp(-lambda_against)."""
    out = []
    for col in ("lambda_for", "lambda_against"):
        bad = int((~fd[col].between(0, lambda_max, inclusive="neither")).sum())
        if bad:
            out.append(f"fixture_difficulty.{col}: {bad} values not in (0, {lambda_max})")
    if not fd.p_cs.between(0, 1).all():
        out.append("fixture_difficulty.p_cs: values outside [0, 1]")
    if ((fd.p_cs - np.exp(-fd.lambda_against)).abs() > tol).any():
        out.append("fixture_difficulty.p_cs: not exp(-lambda_against)")
    return out


def _gameweek_problems(fd: pd.DataFrame, deadlines: pd.Series, run: pd.Timestamp,
                       next_gw: int, max_horizon: int) -> list[str]:
    """Gameweeks inside the horizon, each with a deadline strictly after the run."""
    out = []
    last = next_gw + max_horizon - 1
    if not fd.gw.between(next_gw, last).all():
        out.append(f"fixture_difficulty.gw: values outside the horizon {next_gw}..{last}")
    due = deadlines.reindex(fd.gw.unique())
    missing = sorted(due.index[due.isna()])
    passed = sorted(due.index[due <= run])
    if missing:
        out.append(f"fixture_difficulty: gameweeks {missing} have no deadline")
    if passed:
        out.append(f"fixture_difficulty: gameweeks {passed} have a deadline at or before the run")
    return out


def _mirror_problems(fd: pd.DataFrame) -> list[str]:
    """Each row's lambda_against is the opponent's lambda_for in the same match."""
    own = fd.set_index(FIXTURE_KEY).lambda_for
    partner = own.reindex(pd.MultiIndex.from_arrays([fd.opponent_id, fd.match_id]))
    same = np.isclose(partner.to_numpy(), fd.lambda_against.to_numpy(), atol=0, rtol=1e-12)
    bad = int((~same).sum())
    return [f"fixture_difficulty: {bad} rows whose lambda_against does not mirror the opponent's "
            "lambda_for"] if bad else []


def _fixture_set_problems(fd: pd.DataFrame, expected: pd.DataFrame) -> list[str]:
    """The (team, match) rows equal the expected fixtures, with matching gw, opponent and home."""
    got, want = set(zip(fd.team_id, fd.match_id, strict=True)), set(
        zip(expected.team_id, expected.match_id, strict=True))
    out = []
    if got != want:
        out.append(f"fixture_difficulty: {len(want - got)} fixtures missing and "
                   f"{len(got - want)} unexpected against fact_fixture")
    both = fd.merge(expected, on=FIXTURE_KEY, suffixes=("", "_fx"), validate="one_to_one")
    differ = int(((both.gw != both.gw_fx) | (both.opponent_id != both.opponent_id_fx)
                  | (both.home != both.home_fx)).sum())
    if differ:
        out.append(f"fixture_difficulty: {differ} rows differ from fact_fixture in gw, "
                   "opponent_id or home")
    return out


def _name_problems(fd: pd.DataFrame, short_names: dict[int, str]) -> list[str]:
    """`team` and `opponent` are the short names of `team_id` and `opponent_id`."""
    out = []
    for name, key in (("team", "team_id"), ("opponent", "opponent_id")):
        bad = int((fd[name] != fd[key].map(short_names)).sum())
        if bad:
            out.append(f"fixture_difficulty.{name}: {bad} values differ from dim_team.short_name")
    return out


def fixture_difficulty_problems(
    fd: pd.DataFrame, *, fixtures: pd.DataFrame, short_names: dict[int, str], deadlines: pd.Series,
    run: pd.Timestamp, next_gw: int, max_horizon: int, prem_tag: str, tol: float,
    lambda_max: float,
) -> list[str]:
    """Problems with fixture_difficulty.csv: values, gameweeks, teams, names and fixture set.

    Assumes a valid schema and unique keys (checked first). Raises only if `fixtures` is
    malformed (a Premier League fixture with no club).
    """
    out = _lambda_problems(fd, tol, lambda_max)
    out += _gameweek_problems(fd, deadlines, run, next_gw, max_horizon)
    unknown = sorted((set(fd.team_id) | set(fd.opponent_id)) - set(short_names))
    if unknown:
        out.append(f"fixture_difficulty: team ids {unknown} not in dim_team")
    else:
        out += _name_problems(fd, short_names)
    if out:
        return out
    expected = _expected_fixtures(fixtures, prem_tag, next_gw, next_gw + max_horizon - 1)
    return _fixture_set_problems(fd, expected) + _mirror_problems(fd)


def _elo_match_problems(elo: pd.DataFrame, finished: dict[str, set[str]], tol: float) -> list[str]:
    """Two rows per match, zero-sum rating changes, and exactly each season's finished matches."""
    out = []
    per_match = elo.groupby(["season", "match_id"]).agg(
        rows=("team_id", "size"), moved=("elo_after", "sum"), before=("elo_before", "sum"))
    if (per_match.rows != 2).any():
        out.append(f"elo_ratings: {int((per_match.rows != 2).sum())} matches without two rows")
    if ((per_match.moved - per_match.before).abs() > tol).any():
        out.append("elo_ratings: matches whose rating changes are not zero-sum")
    for season, want in finished.items():
        got = set(elo.loc[elo.season == season, "match_id"])
        if got != want:
            out.append(f"elo_ratings {season}: {len(want - got)} finished Premier League matches "
                       f"missing and {len(got - want)} unexpected")
    return out


def elo_problems(
    elo: pd.DataFrame, *, team_ids: dict[str, set[int]], finished: dict[str, set[str]],
    season: str, as_of_gw: int, run: pd.Timestamp, rating_range: list[float], tol: float,
) -> list[str]:
    """Problems with elo_ratings.csv: per-match integrity, teams, range, and leakage.

    Assumes a valid schema and unique keys (checked first). Raises `ValueError` if
    `kickoff_utc` cannot be parsed.
    """
    out = _elo_match_problems(elo, finished, tol)
    for s, ids in team_ids.items():
        unknown = sorted(set(elo.loc[elo.season == s, "team_id"]) - ids)
        if unknown:
            out.append(f"elo_ratings {s}: team ids {unknown} not in dim_team")
    if (elo[elo.season == season].gw > as_of_gw).any():
        out.append(f"elo_ratings: {season} rows after the as-of gameweek {as_of_gw}")
    lo, hi = rating_range
    for col in ("elo_before", "elo_after"):
        if not elo[col].between(lo, hi).all():
            out.append(f"elo_ratings.{col}: values outside the range [{lo}, {hi}]")
    kickoff = pd.to_datetime(elo.kickoff_utc, utc=True, format="ISO8601")
    if (kickoff > run).any():
        out.append("elo_ratings: kickoff_utc after run_utc")
    return out
