"""A small synthetic upstream season (2025-2026, 38 gameweeks) written as CSV folders.

It has the shape of the real final folders: every `GW{n}` folder is complete, so the
folders after an as-of gameweek hold full results (the leakage risk). Every value is a
formula of the player, club and gameweek, so a test can say what a table should hold.

* 4 clubs (id 1-4, code 31-34) and 8 players, two per club.
* GW5 is blank for clubs 2 and 4, GW7 is a double for clubs 1 and 2.
* Player 2 moves from club 1 to club 3 from GW20 (the snapshot shows it).
* Two EFL Cup matches against a club outside the league, with a poisoned upstream Elo (9000+):
  cup-10 is played in GW9 and filed in the GW10 folder; cup-late is played in GW2 but filed
  in the GW25 folder, after player 2 has moved clubs. Its players are club 1's at GW2.
* Team Elo, price, ep_next and the transfer counts change with the gameweek.
* The master files are poisoned (injured, price 9.9) to show up any read of them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from helpers import blank_frame

SEASON = "2025-2026"
N_GW = 38
TEAM_CODE = {1: 31, 2: 32, 3: 33, 4: 34}
PLAYER_CLUB = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4}
MOVER, MOVE_GW = 2, 20
BLANK_GW, DOUBLE_GW = 5, 7
# Cup matches: (id, folder, club, days after the first kickoff, gameweek played in). cup-10 is
# filed in the next gameweek's folder, as upstream does (played 3 days before GW10); cup-late
# sits in folder 25 although it was played 3 days before GW3, in GW2.
CUPS = [("cup-10", 10, 1, 7 * 10 - 3, 9), ("cup-late", 25, 1, 7 * 3 - 3, 2)]
OUTSIDE_CODE = 999
ROUNDS = [((1, 2), (3, 4)), ((1, 3), (2, 4)), ((1, 4), (2, 3))]
FIRST_KICKOFF = pd.Timestamp("2025-08-16T14:00:00Z")
POISON = {"status": "i", "news": "Poison", "chance": 0.0, "now_cost": 9.9}


def club(player: int, gw: int) -> int:
    """The player's club (team id) in the snapshot of gameweek `gw`."""
    return 3 if player == MOVER and gw >= MOVE_GW else PLAYER_CLUB[player]


def minutes(player: int, gw: int) -> int:
    return [90, 60, 0, 75][(player + gw) % 4]


def schedule() -> list[dict]:
    """Every match: id, gameweek, kickoff, home and away team id (None outside the league)."""
    out = []
    for gw in range(1, N_GW + 1):
        pairs = list(ROUNDS[(gw - 1) % 3])
        if gw == BLANK_GW:
            pairs = pairs[:1]
        if gw == DOUBLE_GW:
            pairs.append((2, 1))
        for i, (home, away) in enumerate(pairs):
            kick = FIRST_KICKOFF + pd.Timedelta(days=7 * gw, hours=3 * i)
            out.append({"id": f"m{gw:02d}-{home}-{away}", "gw": gw, "kick": kick, "home": home,
                        "away": away, "tournament": "prem"})
    for cup_id, gw, home, day, played in CUPS:
        out.append({"id": cup_id, "gw": gw, "kick": FIRST_KICKOFF + pd.Timedelta(days=day),
                    "home": home, "away": None, "tournament": "efl-cup", "played": played})
    return out


def _match_rows(gw: int) -> list[dict]:
    rows = []
    for m in (m for m in schedule() if m["gw"] == gw):
        home, away = m["home"], m["away"]
        hs, as_ = (gw + home) % 4, (gw + (away or 0)) % 3
        cup = m["tournament"] != "prem"
        rows.append({
            "match_id": m["id"], "gameweek": gw, "tournament": m["tournament"],
            "kickoff_time": f"{m['kick']:%Y-%m-%dT%H:%M:%S}+00:00",
            "home_team": TEAM_CODE[home], "away_team": OUTSIDE_CODE if cup else TEAM_CODE[away],
            "home_team_elo": 9000.0 + gw if cup else 1500.0 + 10 * home + gw,
            "away_team_elo": 1500.0 + 10 * (away or 5) + gw,
            "home_score": float(hs), "away_score": float(as_), "finished": True,
            "home_expected_goals_xg": 0.5 + 0.25 * hs, "away_expected_goals_xg": 0.4 + 0.25 * as_,
            "home_non_penalty_xg": np.nan if cup else 0.4 + 0.25 * hs,
            "away_non_penalty_xg": np.nan if cup else 0.3 + 0.25 * as_,
        })
    return rows


def _pms_rows(gw: int) -> list[dict]:
    rows = []
    for m in (m for m in schedule() if m["gw"] == gw):
        for team in (m["home"], m["away"]):
            at = m.get("played", gw)  # a cup match's players are the clubs' when it was played
            for p in (p for p in PLAYER_CLUB if team and club(p, at) == team):
                rows.append({
                    "player_id": p, "match_id": m["id"], "minutes_played": float(minutes(p, at)),
                    "goals": 0.0, "assists": 0.0, "total_shots": 1.0, "xg": 0.1, "xa": 0.05,
                    "tackles": 2.0, "tackles_won": 2.0, "interceptions": 1.0, "clearances": 1.0,
                    "blocks": 0.0, "recoveries": 3.0, "saves": 0.0, "penalties_scored": 0.0,
                    "penalties_missed": 0.0,
                })
    return rows


def _pgs_rows(gw: int) -> list[dict]:
    rows = []
    prem = [m for m in schedule() if m["gw"] == gw and m["tournament"] == "prem"]
    for p in PLAYER_CLUB:
        played = [minutes(p, gw) for m in prem if club(p, gw) in (m["home"], m["away"])]
        rows.append({
            "id": p, "gw": gw, "event_points": sum(played) // 30 + gw % 3,
            "minutes": sum(played), "starts": sum(x >= 60 for x in played), "bonus": 0,
            "bps": 10, "yellow_cards": 0, "red_cards": 0, "own_goals": 0, "goals_conceded": 1,
            "tackles": 1, "clearances_blocks_interceptions": 1, "recoveries": 1,
            "defensive_contribution": 1, "now_cost": (50 + p + gw) / 10,
            "selected_by_percent": 1.5 + p / 10, "transfers_in_event": 10 * gw + p,
            "transfers_out_event": p,
        })
    return rows


def _state_rows(gw: int) -> list[dict]:
    return [{
        "id": p, "gw": gw, "status": "a", "news": "Knock" if p == 3 else np.nan,
        "chance_of_playing_next_round": 50.0 if p == 3 else np.nan,
        "now_cost": (50 + p + gw) / 10, "selected_by_percent": 1.5 + p / 10,
        "penalties_order": 1.0 if p == 1 else np.nan, "direct_freekicks_order": np.nan,
        "corners_and_indirect_freekicks_order": np.nan, "ep_next": gw + p / 10,
    } for p in PLAYER_CLUB]


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _write_folder(base: Path, gw: int) -> None:
    folder = base / "By Gameweek" / f"GW{gw}"
    matches = _match_rows(gw)
    players = [{"player_code": 1000 + p, "player_id": p, "web_name": f"P{p}",
                "position": "Midfielder", "team_code": TEAM_CODE[club(p, gw)]}
               for p in PLAYER_CLUB]
    teams = [{"id": t, "code": c, "name": f"Team{t}", "short_name": f"T{t:02d}",
              "elo": 1500.0 + 10 * t + gw} for t, c in TEAM_CODE.items()]
    files = {
        "matches": matches,
        "fixtures": [{"match_id": m["match_id"], "gameweek": gw} for m in matches],
        "players": players, "teams": teams, "playerstats": _state_rows(gw),
        "playermatchstats": _pms_rows(gw), "player_gameweek_stats": _pgs_rows(gw),
    }
    for name, rows in files.items():
        _write(blank_frame(name, rows), folder / f"{name}.csv")


def _write_master(base: Path) -> None:
    prem = [m for m in schedule() if m["tournament"] == "prem"]
    first = {g: min(m["kick"] for m in prem if m["gw"] == g) for g in range(1, N_GW + 1)}
    summaries = [{"id": g, "name": f"Gameweek {g}",
                  "deadline_time": f"{k - pd.Timedelta(minutes=90):%Y-%m-%dT%H:%M:%S}+00:00"}
                 for g, k in first.items()]
    _write(pd.DataFrame(summaries), base / "gameweek_summaries.csv")
    poisoned = pd.DataFrame(_state_rows(N_GW)).assign(
        status=POISON["status"], news=POISON["news"],
        chance_of_playing_next_round=POISON["chance"], now_cost=POISON["now_cost"],
    )
    _write(pd.concat([pd.DataFrame(_state_rows(N_GW - 1)), poisoned]), base / "playerstats.csv")
    _write(pd.DataFrame([{"player_id": p} for p in PLAYER_CLUB]), base / "players.csv")
    _write(pd.DataFrame([{"id": t, "code": c} for t, c in TEAM_CODE.items()]), base / "teams.csv")


def write_upstream(data_dir: Path) -> Path:
    """Write the season under `data_dir/2025-2026/`; return the season folder."""
    base = data_dir / SEASON
    for gw in range(1, N_GW + 1):
        _write_folder(base, gw)
    _write_master(base)
    return base


def synth_cfg(cfg: dict, checkout: Path) -> dict:
    """The pipeline config pointed at a synthetic checkout, with bounds sized to it."""
    upstream = {**cfg["upstream"], "checkout_path": str(checkout), "data_dir": "data"}
    out = {**cfg, "upstream": upstream}
    out["validation"] = {
        **cfg["validation"], "teams_rows": [4, 4], "prem_matches_rows": [76, 76],
        "matches_rows": [78, 78], "players_rows_per_snapshot": [8, 8],
        "playerstats_rows_snapshot": [8, 8], "player_gameweek_stats_rows_per_gw": [8, 8],
        "playermatchstats_rows_per_match": [2, 8],
    }
    return out
