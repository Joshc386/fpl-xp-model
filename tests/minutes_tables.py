"""Minimal processed tables for the minutes component's tests."""

from __future__ import annotations

import pandas as pd

PREM = "prem"


def tables(pgw: list[tuple], fixtures: list[tuple], players: list[tuple] = ()) -> dict:
    """Minimal processed tables.

    `pgw` rows are (player, team, gw, minutes, starts); `fixtures` rows are (gw, home, away)
    or (gw, home, away, tournament), each kicking off three hours after the one before;
    `players` rows are (player, team, position, status, chance). Players in `pgw` but not in
    `players` join dim_player as available midfielders at their last club.
    """
    gw = pd.DataFrame(pgw, columns=["player_id", "team_id", "gw", "minutes", "starts"])
    gw = gw.astype({"player_id": "int64", "team_id": "Int64", "gw": "int64",
                    "minutes": "int64", "starts": "int64"})
    fx = pd.DataFrame([
        {"match_id": f"m{i}", "gw": g, "home_team_id": h, "away_team_id": a,
         "tournament": t[0] if t else PREM,
         "kickoff_utc": (pd.Timestamp("2025-08-16T12:00:00Z") + pd.Timedelta(hours=3 * i))
         .strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i, (g, h, a, *t) in enumerate(fixtures)
    ], columns=["match_id", "gw", "home_team_id", "away_team_id", "tournament", "kickoff_utc"])
    fx = fx.astype({"gw": "int64", "home_team_id": "Int64", "away_team_id": "Int64"})
    named = {p for p, *_ in players}
    last_club = gw.dropna(subset=["team_id"]).sort_values("gw").groupby("player_id").team_id.last()
    rows = list(players) + [(p, int(t), "MID", "a", None) for p, t in last_club.items()
                            if p not in named]
    dp = pd.DataFrame(rows, columns=["player_id", "team_id", "position", "status", "chance_next"])
    dp = dp.astype({"player_id": "int64", "team_id": "int64", "chance_next": "Int64"})
    return {"fact_player_gw": gw, "fact_fixture": fx, "dim_player": dp}
