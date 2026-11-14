"""A valid set of the four outputs and its check context, built on export_tables.tables().

Run time 2026-09-03 20:00Z: gameweek 3's deadline (12:00 that day) has passed, so the next
gameweek is 4 and the as-of gameweek 3. Gameweek 4 holds one fixture, m6, club 1 at home to
club 2.
"""

from __future__ import annotations

import math

import pandas as pd

from export_tables import AS_OF, PREM, SEASON, tables
from fpl.ingest import ROOT, load_config
from fpl.output_checks import CheckContext
from fpl.output_schema import OUTPUT_SCHEMA
from fpl.player_metrics import player_metrics
from fpl.schema import expected_dtype

MODEL_VERSION = load_config(ROOT / "config" / "model.yaml")["model_version"]
RUN = pd.Timestamp("2026-09-03T20:00:00Z")
BOUNDS = {
    "now_cost_m": [3.0, 20.0], "positions": ["GKP", "DEF", "MID", "FWD"],
    "elo_rating_range": [1000, 2500], "lambda_max": 10, "tolerance": 1.0e-9,
}


def typed(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """`df` with the dtypes of a published file's schema."""
    kinds = {c: expected_dtype(k, n) for c, k, n in OUTPUT_SCHEMA[name]}
    return df.astype(kinds)


def fixture_difficulty() -> pd.DataFrame:
    rows = [(1, "ALP", "m6", 4, 2, "BET", True, 1.5, 1.0),
            (2, "BET", "m6", 4, 1, "ALP", False, 1.0, 1.5)]
    df = pd.DataFrame(rows, columns=["team_id", "team", "match_id", "gw", "opponent_id",
                                     "opponent", "home", "lambda_for", "lambda_against"])
    return typed("fixture_difficulty", df.assign(p_cs=[math.exp(-1.0), math.exp(-1.5)]))


def elo_ratings() -> pd.DataFrame:
    rows = []
    for gw, mid in ((1, "m1"), (2, "m2"), (2, "m3"), (3, "m4")):
        kick = f"2026-09-{gw:02d}T14:00:00Z"
        rows += [(1, mid, SEASON, gw, kick, 1500.0, 1510.0), (2, mid, SEASON, gw, kick,
                                                               1500.0, 1490.0)]
    cols = ["team_id", "match_id", "season", "gw", "kickoff_utc", "elo_before", "elo_after"]
    return typed("elo_ratings", pd.DataFrame(rows, columns=cols))


def meta() -> pd.DataFrame:
    row = {
        "run_utc": "2026-09-03T20:00:00Z",
        "upstream_commit": "ac8be9caa3bce7aa6c2b73d5a33a9f5c0b2f0e41",
        "current_gw": 3, "next_gw": 4, "next_deadline_utc": "2026-09-04T12:00:00Z",
        "model_version": MODEL_VERSION, "max_horizon": 5, "backtest_mae_model": None,
        "backtest_mae_ep_next": None, "status": "ok",
    }
    return typed("meta", pd.DataFrame([row]))


def outputs() -> dict[str, pd.DataFrame]:
    players = typed("players", player_metrics(tables(), AS_OF, PREM))
    return {"players": players, "fixture_difficulty": fixture_difficulty(),
            "elo_ratings": elo_ratings(), "meta": meta()}


def context() -> CheckContext:
    t = tables()
    fx = t["fact_fixture"]
    done = fx[(fx.tournament == PREM) & fx.finished & (fx.gw <= AS_OF)]
    deadlines = pd.Series(
        pd.date_range("2026-09-01T12:00:00Z", periods=8, freq="D"), index=range(1, 9))
    return CheckContext(
        run_utc=RUN, season=SEASON, as_of_gw=AS_OF, next_gw=4, max_horizon=5, deadlines=deadlines,
        tables=t, team_ids={SEASON: {1, 2}}, finished_prem={SEASON: set(done.match_id)},
        prem_tag=PREM, bounds=BOUNDS,
    )
