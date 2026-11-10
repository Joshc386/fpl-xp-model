"""Cleaning: build the five processed tables from raw frames.

Every function is pure over DataFrames: no file I/O and no reading of master files,
so the point-in-time loader can feed it one gameweek snapshot at a time. Each join is
checked for row counts, and every cleaning rule is logged in docs/decisions.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from fpl.frames import (
    CleanError,
    JoinError,
    checked_merge,
    map_codes,
    normalise_kickoff,
    tenths,
    to_int,
)
from fpl.ingest import RawSeason
from fpl.reconcile import Reconciliation
from fpl.schema import PROCESSED_SCHEMA, fill_sources
from fpl.validate import ValidationError, check_rule15_guards, is_processed

log = logging.getLogger(__name__)



@dataclass
class BuiltSeason:
    """The processed tables of one season, with their reconciliation."""

    season: str
    tables: dict[str, pd.DataFrame]
    reconciliation: pd.DataFrame


def build_dim_team(teams: pd.DataFrame) -> pd.DataFrame:
    """dim_team; ClubElo passes through as upstream_elo, nulls included."""
    return pd.DataFrame({
        "team_id": to_int(teams["id"], "teams.id"),
        "team_code": to_int(teams["code"], "teams.code"),
        "name": teams["name"],
        "short_name": teams["short_name"],
        "upstream_elo": teams["elo"].astype("float64"),
    }).reset_index(drop=True)


def build_fact_fixture(
    matches: pd.DataFrame, teams: pd.DataFrame, season: str, prem_tag: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_fixture: every competition. Returns the table and the rows dropped by reason.

    Matches with no kickoff_time are dropped. Scores are kept for every finished
    match and xG only for processed ones; an unfinished match, even one with a
    part-played score, has them all null.
    """
    has_kickoff = matches.kickoff_time.notna()
    dropped = {"no_kickoff_time": int((~has_kickoff).sum())}
    df = matches[has_kickoff].reset_index(drop=True)
    home = map_codes(df.home_team, teams, "fact_fixture home team")
    away = map_codes(df.away_team, teams, "fact_fixture away team")
    unmapped = (df.tournament == prem_tag) & (home.isna() | away.isna())
    if unmapped.any():
        raise CleanError(f"{int(unmapped.sum())} {prem_tag} matches have a team not in teams")
    finished, done = df.finished.fillna(False).astype(bool), is_processed(df)

    def result(col: str, mask: pd.Series) -> pd.Series:
        return df[col].where(mask)

    out = pd.DataFrame({
        "match_id": df.match_id, "season": season, "gw": to_int(df.gameweek, "gameweek"),
        "kickoff_utc": normalise_kickoff(df.kickoff_time), "tournament": df.tournament,
        "home_team_id": home.astype("Int64"), "away_team_id": away.astype("Int64"),
        "home_upstream_elo": df.home_team_elo, "away_upstream_elo": df.away_team_elo,
        "finished": finished, "processed": done,
        "home_xg": result("home_expected_goals_xg", done),
        "away_xg": result("away_expected_goals_xg", done),
        "home_npxg": result("home_non_penalty_xg", done),
        "away_npxg": result("away_non_penalty_xg", done),
        "home_goals": to_int(result("home_score", finished), "home_score", nullable=True),
        "away_goals": to_int(result("away_score", finished), "away_score", nullable=True),
    })
    return out, dropped


def build_dim_player(
    players: pd.DataFrame, playerstats: pd.DataFrame, teams: pd.DataFrame,
    position_map: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """dim_player from one snapshot of players.csv and playerstats.csv."""
    stats = playerstats.drop(columns="snapshot_gw", errors="ignore").assign(_has_stats=True)
    df = checked_merge(
        players, stats, left_on="player_id", right_on="id", how="left",
        validate="one_to_one", name="players -> playerstats",
    )
    has = df["_has_stats"].notna()
    dropped = {"no_playerstats_row": int((~has).sum())}
    df = df[has].reset_index(drop=True)
    position = df.position.map(position_map)
    if position.isna().any():
        raise CleanError(f"unknown position(s): {sorted(df.position[position.isna()].unique())}")
    team = map_codes(df.team_code, teams, "dim_player team")
    if team.isna().any():
        raise CleanError("dim_player: a player's team_code is not in teams")

    def nint(col: str) -> pd.Series:
        return to_int(df[col], col, nullable=True)

    out = pd.DataFrame({
        "player_id": to_int(df.player_id, "player_id"),
        "player_code": to_int(df.player_code, "player_code"),
        "web_name": df.web_name, "team_id": team.astype("int64"), "position": position,
        "price_tenths": tenths(df.now_cost, "now_cost"), "status": df.status,
        "chance_next": nint("chance_of_playing_next_round"), "news": df.news,
        "selected_pct": df.selected_by_percent,
        "pen_order": nint("penalties_order"), "fk_order": nint("direct_freekicks_order"),
        "corner_order": nint("corners_and_indirect_freekicks_order"), "ep_next": df.ep_next,
    })
    return out, dropped


def build_fact_player_match(
    pms: pd.DataFrame, matches: pd.DataFrame, players: pd.DataFrame, teams: pd.DataFrame,
    tackles_column: str, fill_columns: list[str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_player_match: processed matches only, with blanks filled per rule 15.

    `players` holds one snapshot per gameweek folder; a row's team is the player's
    club in the snapshot of the folder the row came from. Rows are dropped, and
    counted, when their match has no kickoff_time, is not processed, or when the
    player is missing from that snapshot. A row for an unknown match is an error.
    """
    flags = matches[
        ["match_id", "kickoff_time", "finished", "stats_processed", "player_stats_processed"]
    ].assign(_known=True)
    df = checked_merge(pms, flags, on="match_id", how="left", validate="many_to_one",
                       name="playermatchstats -> matches")
    if df["_known"].isna().any():
        raise JoinError("playermatchstats -> matches: rows for unknown match_id")
    no_kickoff = df.kickoff_time.isna()
    not_done = ~is_processed(df) & ~no_kickoff
    df = df[~no_kickoff & ~not_done].reset_index(drop=True)
    problems = check_rule15_guards(df, tackles_column, fill_columns)
    if problems:
        raise ValidationError(problems)
    df = checked_merge(
        df, players[["snapshot_gw", "player_id", "team_code"]],
        on=["snapshot_gw", "player_id"], how="left", validate="many_to_one",
        name="playermatchstats -> players",
    )
    no_player = df.team_code.isna()
    dropped = {
        "match_has_no_kickoff_time": int(no_kickoff.sum()),
        "match_not_processed": int(not_done.sum()),
        "player_not_in_snapshot": int(no_player.sum()),
    }
    df = df[~no_player].reset_index(drop=True)
    return _shape_player_match(df, teams, tackles_column, fill_columns), dropped


def _shape_player_match(
    df: pd.DataFrame, teams: pd.DataFrame, tackles_column: str, fill_columns: list[str]
) -> pd.DataFrame:
    """Rename, fill (rule 15) and type the fact_player_match columns."""
    team = map_codes(df.team_code, teams, "fact_player_match team")
    if team.isna().any():
        raise CleanError("fact_player_match: a player's team_code is not in teams")
    sources = fill_sources(tackles_column)
    out = pd.DataFrame({"player_id": to_int(df.player_id, "player_id"),
                        "team_id": team.astype("int64"), "match_id": df.match_id,
                        "minutes": to_int(df.minutes_played, "minutes_played")})
    for col, src in sources.items():
        out[col] = df[src].fillna(0) if col in fill_columns else df[src]
        if col not in ("xg", "xa"):
            out[col] = to_int(out[col], col)
    return out[[c for c, _, _ in PROCESSED_SCHEMA["fact_player_match"]]]


def _gameweek_holds(
    pgs: pd.DataFrame, players: pd.DataFrame, matches: pd.DataFrame, prem_tag: str
) -> tuple[pd.Series, pd.Series]:
    """Which pgs rows to hold back: (club has an unfinished fixture, player has no club).

    The club is the player's `team_code` in the snapshot of the row's gameweek folder. A club
    with no Premier League fixture that gameweek (a blank gameweek) has nothing unfinished. A
    player missing from the snapshot has no club, so his row is held while *any* Premier League
    fixture in that gameweek is unfinished.
    """
    prem = matches[matches.tournament == prem_tag]
    fin = prem.finished.fillna(False).astype(bool)
    sides = [
        pd.DataFrame({"gw": prem.gameweek, "team_code": prem[side], "open": ~fin})
        for side in ("home_team", "away_team")
    ]
    clubs = pd.concat(sides).groupby(["gw", "team_code"], as_index=False)["open"].any()
    keyed = checked_merge(
        pgs[["snapshot_gw", "id", "gw"]],
        players[["snapshot_gw", "player_id", "team_code"]],
        left_on=["snapshot_gw", "id"], right_on=["snapshot_gw", "player_id"],
        how="left", validate="many_to_one", name="player_gameweek_stats -> players",
    )
    flagged = checked_merge(
        keyed[["gw", "team_code"]].astype("float64"), clubs.astype({"open": "bool"}),
        on=["gw", "team_code"], how="left", validate="many_to_one",
        name="player_gameweek_stats -> club fixtures",
    )
    club_hold = flagged["open"].eq(True).set_axis(pgs.index)
    open_gws = set(clubs.loc[clubs["open"], "gw"])
    no_club = keyed["team_code"].isna().set_axis(pgs.index)
    return club_hold, no_club & pgs["gw"].isin(open_gws)


def build_fact_player_gw(
    pgs: pd.DataFrame, players: pd.DataFrame, matches: pd.DataFrame, season: str, prem_tag: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_player_gw from FPL's own per-gameweek stats; minutes are FPL's, not minutes_played.

    A row is kept only once every Premier League fixture the player's club has in that
    gameweek is finished (`finished`, not `processed`); the others are dropped and counted.
    A player with no club in the snapshot waits for every Premier League fixture of the gameweek.
    """
    club_hold, no_club_hold = _gameweek_holds(pgs, players, matches, prem_tag)
    dropped = {
        "club_fixture_not_finished": int(club_hold.sum()),
        "no_club_gameweek_not_finished": int(no_club_hold.sum()),
    }
    pgs = pgs[~(club_hold | no_club_hold)]
    cols = {
        "points": "event_points", "minutes": "minutes", "starts": "starts", "bonus": "bonus",
        "bps": "bps", "yellow": "yellow_cards", "red": "red_cards", "own_goals": "own_goals",
        "goals_conceded": "goals_conceded", "tackles": "tackles",
        "cbi": "clearances_blocks_interceptions", "recoveries": "recoveries",
        "defensive_contribution": "defensive_contribution",
        "transfers_in": "transfers_in_event", "transfers_out": "transfers_out_event",
    }
    out = pd.DataFrame({
        "player_id": to_int(pgs["id"], "player_id"), "season": season,
        "gw": to_int(pgs["gw"], "gw"),
    })
    for col, src in cols.items():
        out[col] = to_int(pgs[src], col)
    out["price_tenths"] = tenths(pgs.now_cost, "now_cost")
    out["selected_pct"] = pgs.selected_by_percent
    cols_out = [c for c, _, _ in PROCESSED_SCHEMA["fact_player_gw"]]
    return out[cols_out].reset_index(drop=True), dropped


def build_season(raw: RawSeason, cfg: dict) -> BuiltSeason:
    """Build all five processed tables for a season, and reconcile them with upstream."""
    scfg = next(s for s in cfg["seasons"] if s["id"] == raw.season)
    prem, fill = cfg["premier_league_tag"], cfg["fill_zero_columns"]
    snapshot = raw.players[raw.players.snapshot_gw == raw.latest_gw]
    dim_team = build_dim_team(raw.teams)
    fixture, d_fix = build_fact_fixture(raw.matches, raw.teams, raw.season, prem)
    dim_player, d_pl = build_dim_player(snapshot, raw.playerstats, raw.teams, cfg["position_map"])
    pmatch, d_pm = build_fact_player_match(
        raw.playermatchstats, raw.matches, raw.players, raw.teams, scfg["tackles_column"], fill
    )
    pgw, d_gw = build_fact_player_gw(
        raw.player_gameweek_stats, raw.players, raw.matches, raw.season, prem
    )
    info = {
        "unfinished_rows_kept_with_null_results": int((~fixture.finished).sum()),
        "finished_but_not_processed": int((fixture.finished & ~fixture.processed).sum()),
    }
    rec = Reconciliation(raw.season)
    rec.add("dim_team", len(raw.teams), {}, len(dim_team))
    rec.add("dim_player", len(snapshot), d_pl, len(dim_player))
    rec.add("fact_fixture", len(raw.matches), d_fix, len(fixture), info)
    rec.add("fact_player_match", len(raw.playermatchstats), d_pm, len(pmatch))
    rec.add("fact_player_gw", len(raw.player_gameweek_stats), d_gw, len(pgw))
    tables = {"dim_player": dim_player, "dim_team": dim_team, "fact_fixture": fixture,
              "fact_player_match": pmatch, "fact_player_gw": pgw}
    log.info("%s: built %s", raw.season, {k: len(v) for k, v in tables.items()})
    return BuiltSeason(raw.season, tables, rec.frame())
