"""Component diagnostics (phase 2 plan point 1: reported, no pass mark).

Each component is called like the live pipeline calls it, through its hand-off function
`(season, as_of_gw, mode)`, at as-of g-1, and its rows for gameweek g are scored against what
happened. Player components (minutes `p_60`, defence `p_cs`, attack `xg`) are scored on the
evaluation set's players; team goals (`lambda_for`) on every club fixture of g.

Outcomes per player per fixture, from the season's final read:

* `p60`: 60+ minutes (`long_minutes`, the scoring rules' `long_min_minutes`). A club's only
  fixture of the gameweek uses FPL's minutes (which set the threshold); a fixture in a double
  uses that match's minutes in `fact_player_match` (FPL gives only the gameweek total), 0
  with no row.
* `cs`: a clean sheet. Single fixture: 60+ FPL minutes and 0 FPL goals conceded on the
  pitch. In a double: 60+ match minutes and the club conceding 0 in the match.
* `goals`: the player's goals in the match, from complete matches only (others dropped).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

import numpy as np
import pandas as pd

from backtest.elo_data import HarnessError
from backtest.xp_metrics import brier

KEYS = {"player": ["player_id", "match_id", "gw"], "team": ["team_id", "match_id", "gw"]}


def resolve(path: str | None) -> Callable | None:
    """The object named `module:attribute`, or None if it isn't built yet: `path` is None (not
    named in the contract yet) or the module doesn't exist. A module that exists but lacks the
    attribute raises `HarnessError` (the name is wrong, so its checks would silently vanish);
    one that fails to import raises its own error."""
    if path is None:
        return None
    if ":" not in path:
        raise HarnessError(f"a callable must be named module:function, got {path!r}")
    module, name = path.split(":", 1)
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and (module == exc.name or module.startswith(exc.name + ".")):
            return None
        raise
    if not hasattr(mod, name):
        raise HarnessError(f"{module} has no attribute {name!r}: is it named differently? "
                           "(backtest/config.yaml)")
    return getattr(mod, name)


def _rows_for(out: pd.DataFrame, gw: int, column: str, kind: str) -> pd.DataFrame:
    missing = [c for c in [*KEYS[kind], column] if c not in out.columns]
    if missing:
        raise HarnessError(f"component output lacks columns {missing}")
    return out.loc[out.gw == gw, [*KEYS[kind], column]].rename(columns={column: "pred"})


def _goals_against(fx: pd.DataFrame) -> pd.DataFrame:
    """Per club per finished match: goals for and against."""
    done = fx[fx.finished]
    home = done.assign(team_id=done.home_team_id, gf=done.home_goals, ga=done.away_goals)
    away = done.assign(team_id=done.away_team_id, gf=done.away_goals, ga=done.home_goals)
    out = pd.concat([home, away])[["team_id", "match_id", "gf", "ga"]].dropna()
    return out.astype({"team_id": "int64"})


def player_rows(out: pd.DataFrame, gw: int, scored: pd.DataFrame, final: dict, column: str,
                outcome: str, europe: set[int], long_minutes: int) -> pd.DataFrame:
    """The component's rows for gameweek `gw` for the evaluation set's players (`scored`, the
    gameweek's scored rows), with `pred`, the `outcome` (module docstring), `p60_base`,
    `team_id` (the GW g-1 club) and `europe`."""
    rows = _rows_for(out, gw, column, "player").merge(
        scored[["player_id", "team_id", "fixtures", "minutes", "goals_conceded", "p60_base"]],
        on="player_id", how="inner")
    pm = final["fact_player_match"][["player_id", "match_id", "minutes", "goals"]]
    rows = rows.merge(pm.rename(columns={"minutes": "match_minutes"}),
                      on=["player_id", "match_id"], how="left")
    single = rows.fixtures == 1
    mins = np.where(single, rows.minutes, rows.match_minutes.fillna(0))
    if outcome == "p60":
        y = mins >= long_minutes
    elif outcome == "cs":
        ga = rows.merge(_goals_against(final["fact_fixture"]), on=["team_id", "match_id"],
                        how="left").ga
        y = (mins >= long_minutes) & np.where(single, rows.goals_conceded == 0, ga.to_numpy() == 0)
    else:
        complete = set(final["fact_fixture"].match_id[final["fact_fixture"].stats_complete])
        rows = rows[rows.match_id.isin(complete)]
        y = rows.goals.fillna(0)
    rows = rows.assign(outcome=np.asarray(y, dtype="int64"), europe=rows.team_id.isin(europe))
    return rows[["player_id", "match_id", "gw", "team_id", "pred", "outcome", "p60_base",
                 "europe"]].reset_index(drop=True)


def team_rows(out: pd.DataFrame, gw: int, final: dict, column: str,
              europe: set[int]) -> pd.DataFrame:
    """A team component's rows for gameweek `gw` with the club's goals in the fixture."""
    rows = _rows_for(out, gw, column, "team").astype({"team_id": "int64"}).merge(
        _goals_against(final["fact_fixture"]), on=["team_id", "match_id"], how="inner")
    return rows.assign(outcome=rows.gf.astype("int64"), europe=rows.team_id.isin(europe))[
        ["team_id", "match_id", "gw", "pred", "outcome", "europe"]]


def minutes_summary(rows: pd.DataFrame) -> pd.DataFrame:
    """Brier score of `p_60` and of the baseline, mean prediction and observed 60-minute rate,
    for all rows, clubs in Europe that season and the rest."""
    out = []
    for name, part in (("all", rows), ("Europe", rows[rows.europe]),
                       ("rest", rows[~rows.europe])):
        out.append({"group": name, "n": len(part), "brier": brier(part.pred, part.outcome),
                    "brier_baseline": brier(part.p60_base, part.outcome),
                    "mean_pred": float(part.pred.mean()) if len(part) else np.nan,
                    "observed": float(part.outcome.mean()) if len(part) else np.nan})
    return pd.DataFrame(out)
