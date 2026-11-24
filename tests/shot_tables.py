"""A tiny consistent league for the shot and spell checks: two clubs, two Premier League matches.

Match m1 (GW1, club 1 at home to club 2) and m2 (GW2, club 2 at home). Each club has 11
starters, a substitute who replaces its last starter at 60, and an unused substitute. Players
are 100 + n for club 1 and 200 + n for club 2, with n = 1..11 starting, 12 on at 60, 13 unused.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fpl.schema import PROCESSED_SCHEMA

MATCHES = {"m1": (1, 1, 2), "m2": (2, 2, 1)}  # match -> (gw, home, away)


def frame(table: str, rows: list[dict]) -> pd.DataFrame:
    """A processed table with the contract's columns and dtypes."""
    df = pd.DataFrame(rows, columns=[c for c, _, _ in PROCESSED_SCHEMA[table]])
    for col, kind, nullable in PROCESSED_SCHEMA[table]:
        if kind == "int":
            vals = df[col] if nullable else df[col].fillna(0)  # columns a test leaves out are 0
            df[col] = pd.array(vals, dtype="Int64" if nullable else "int64")
        elif kind == "float":
            df[col] = df[col].astype("float64")
        elif kind == "bool":
            df[col] = df[col].fillna(False).astype("bool")
    return df


def raw_matches() -> pd.DataFrame:
    """The matches.csv columns the match checks read, consistent with `mini`: two shots a side."""
    return pd.DataFrame({"match_id": list(MATCHES), "home_total_shots": [2.0, 2.0],
                         "away_total_shots": [2.0, 2.0]})


def mini() -> dict[str, pd.DataFrame]:
    """The tables, consistent: every check passes on them."""
    fixture, pmatch, gw, spell, shot = [], [], [], [], []
    for mid, (g, home, away) in MATCHES.items():
        fixture.append({
            "match_id": mid, "season": "s", "gw": g, "kickoff_utc": "x", "tournament": "prem",
            "home_team_id": home, "away_team_id": away, "finished": True,
            "stats_complete": True, "home_xg": 0.8884, "away_xg": 0.8884, "home_npxg": 0.1,
            "away_npxg": 0.1, "home_goals": 1, "away_goals": 1,
        })
        for team in (home, away):
            base = 100 * team
            for n in range(1, 14):
                minutes = {11: 60, 12: 30, 13: 0}.get(n, 90)
                pmatch.append({"player_id": base + n, "team_id": team, "match_id": mid,
                               "minutes": minutes})
                if minutes:
                    start = 60.0 if n == 12 else 0.0
                    end = 60.0 if n == 11 else np.nan
                    spell.append({"player_id": base + n, "team_id": team, "match_id": mid,
                                  "spell_start": start, "spell_end": end,
                                  "spell_repaired": False})
            shot.append({"match_id": mid, "shot_index": team * 10 + 1, "team_id": team,
                         "player_id": base + 1, "minute": 10, "added_time": None,
                         "clock": 10.0, "situation": "regular", "outcome": "miss", "xg": 0.1,
                         "is_penalty": False, "is_own_goal": False})
            shot.append({"match_id": mid, "shot_index": team * 10 + 2, "team_id": team,
                         "player_id": base + 12, "minute": 70, "added_time": None,
                         "clock": 70.0, "situation": "penalty", "outcome": "goal", "xg": 0.7884,
                         "is_penalty": True, "is_own_goal": False})
    for p in sorted({r["player_id"] for r in pmatch}):
        team = p // 100
        for g in (1, 2):
            minutes = next(r["minutes"] for r in pmatch
                           if r["player_id"] == p and MATCHES[r["match_id"]][0] == g)
            gw.append({"player_id": p, "team_id": team, "season": "s", "gw": g, "points": 0,
                       "minutes": minutes, "starts": 0, "bonus": 0, "bps": 0, "fpl_goals": 0,
                       "fpl_assists": 0, "yellow": 0, "red": 0, "own_goals": 0,
                       "goals_conceded": 0, "tackles": 0, "cbi": 0, "recoveries": 0,
                       "defensive_contribution": 0, "price_tenths": 50, "selected_pct": 1.0,
                       "transfers_in": 0, "transfers_out": 0})
    return {
        "fact_fixture": frame("fact_fixture", fixture),
        "fact_player_match": frame("fact_player_match", pmatch),
        "fact_player_gw": frame("fact_player_gw", gw),
        "fact_shot": frame("fact_shot", shot),
        "fact_player_spell": frame("fact_player_spell", spell),
    }
