"""Tiny processed tables (fact_fixture and dim_team) for the Elo and goals-model tests.

A fixture is a tuple `(gw, home_id, away_id, home_goals, away_goals, home_elo, away_elo)`;
goals of None make it schedule only (not finished). Kickoffs follow the list order, a day
apart from the gameweek's Saturday, so list order is kickoff order.
"""

from __future__ import annotations

import pandas as pd

from fpl.models.elo import EloSettings, SeasonRead
from fpl.schema import column_names

PREM = "prem"
SETTINGS = EloSettings(k=20.0, home_advantage=50.0, margin_power=0.5, scale=400.0)
START = {"2024-2025": pd.Timestamp("2024-08-17T14:00:00Z"),
         "2025-2026": pd.Timestamp("2025-08-16T14:00:00Z"),
         "2026-2027": pd.Timestamp("2026-08-22T14:00:00Z"),
         "2027-2028": pd.Timestamp("2027-08-21T14:00:00Z")}

Fixture = tuple[int, int, int, int | None, int | None, float | None, float | None]


def fixture_frame(season: str, fixtures: list[Fixture], tournament: str = PREM) -> pd.DataFrame:
    """fact_fixture rows (contract columns and dtypes) for the given fixtures."""
    rows = []
    for i, (gw, home, away, hg, ag, he, ae) in enumerate(fixtures):
        kick = START[season] + pd.Timedelta(days=7 * (gw - 1), hours=i)
        rows.append({
            "match_id": f"{season[:4]}-{tournament}-{i:03d}-{home}-{away}", "season": season,
            "gw": gw, "kickoff_utc": f"{kick:%Y-%m-%dT%H:%M:%SZ}", "tournament": tournament,
            "home_team_id": home, "away_team_id": away, "home_upstream_elo": he,
            "away_upstream_elo": ae, "finished": hg is not None, "stats_complete": False,
            "home_goals": hg, "away_goals": ag,
        })
    df = pd.DataFrame(rows, columns=column_names("fact_fixture"))
    types = {"home_team_id": "Int64", "away_team_id": "Int64", "home_goals": "Int64",
             "away_goals": "Int64", "gw": "int64", "finished": "bool", "stats_complete": "bool"}
    floats = ["home_upstream_elo", "away_upstream_elo", "home_xg", "away_xg", "home_npxg",
              "away_npxg"]
    return df.astype(types | dict.fromkeys(floats, "float64"))


def team_frame(codes: dict[int, int], upstream_elo: float = 9999.0) -> pd.DataFrame:
    """dim_team from team_id -> team_code; `upstream_elo` is poisoned to catch any use of it."""
    return pd.DataFrame({
        "team_id": list(codes), "team_code": list(codes.values()),
        "name": [f"Club{c}" for c in codes.values()],
        "short_name": [f"C{c:02d}" for c in codes.values()], "upstream_elo": upstream_elo,
    })


def season_read(season: str, as_of: int, codes: dict[int, int], fixtures: list[Fixture],
                cups: list[Fixture] | None = None) -> SeasonRead:
    """A SeasonRead holding the two tables the Elo component uses."""
    fx = fixture_frame(season, fixtures)
    if cups:
        fx = pd.concat([fx, fixture_frame(season, cups, tournament="efl-cup")], ignore_index=True)
    return SeasonRead(season, as_of, {"fact_fixture": fx, "dim_team": team_frame(codes)})


# Season A: clubs 1-4 (codes 31-34); each club's last-match upstream Elo (GW3) differs from
# its first. Season B: club ids reshuffled, code 34 relegated and code 35 promoted. Season B's
# own upstream Elo for continuing clubs is poisoned (7777): they are re-seeded from season A.
CODES_A = {1: 31, 2: 32, 3: 33, 4: 34}
CODES_B = {1: 33, 2: 35, 3: 31, 4: 32}
FIXTURES_A: list[Fixture] = [
    (1, 1, 2, 2, 0, 1600.0, 1500.0), (1, 3, 4, 1, 1, 1550.0, 1450.0),
    (2, 2, 3, 0, 0, 1510.0, 1560.0), (2, 4, 1, 1, 3, 1440.0, 1610.0),
    (3, 1, 3, 1, 2, 1620.0, 1570.0), (3, 2, 4, 4, 1, 1520.0, 1430.0),
]
FIXTURES_B: list[Fixture] = [
    (1, 1, 2, 2, 1, 7777.0, 1480.0), (1, 3, 4, 0, 1, 7777.0, 7777.0),
    (2, 2, 3, 1, 1, None, 7777.0), (2, 4, 1, 2, 2, 7777.0, 7777.0),
    (3, 1, 4, None, None, None, None), (3, 3, 2, None, None, None, None),
]


def two_seasons(as_of_b: int = 2) -> list[SeasonRead]:
    """Season A in full, then season B at as-of `as_of_b`."""
    return [season_read("2025-2026", 3, CODES_A, FIXTURES_A),
            season_read("2026-2027", as_of_b, CODES_B, FIXTURES_B)]
