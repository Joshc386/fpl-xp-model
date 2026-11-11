"""Cleaning: build the five processed tables from raw frames.

Every function is pure over DataFrames: no file I/O and no reading of master files,
so the point-in-time loader can feed it one gameweek snapshot at a time. Each join is
checked for row counts, and every cleaning rule is logged in docs/decisions.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from fpl.complete import complete_matches
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
from fpl.playergw import build_fact_player_gw
from fpl.reconcile import Reconciliation
from fpl.schema import PROCESSED_SCHEMA, fill_sources
from fpl.validate import ValidationError, check_rule15_guards

log = logging.getLogger(__name__)


@dataclass
class BuiltSeason:
    """The processed tables of one season, with their reconciliation."""

    season: str
    tables: dict[str, pd.DataFrame]
    reconciliation: pd.DataFrame


def latest_kickoff_elo(fixture: pd.DataFrame) -> pd.Series:
    """Each club's most recent non-null kickoff Elo among the finished matches, by team_id."""
    done = fixture[fixture.finished]
    sides = pd.concat([
        done[["kickoff_utc", f"{side}_team_id", f"{side}_upstream_elo"]].set_axis(
            ["kickoff_utc", "team_id", "elo"], axis=1
        )
        for side in ("home", "away")
    ]).dropna(subset=["team_id", "elo"])
    latest = sides.sort_values("kickoff_utc", kind="stable").groupby("team_id")["elo"].last()
    return latest.set_axis(latest.index.astype("int64"))


def build_dim_team(teams: pd.DataFrame, fixture: pd.DataFrame) -> pd.DataFrame:
    """dim_team. `upstream_elo` is the club's latest kickoff Elo in the read (null if none).

    `teams.elo` is not used: in 2025/26 it is a later rating than the folder it sits in.
    """
    team_id = to_int(teams["id"], "teams.id")
    return pd.DataFrame({
        "team_id": team_id,
        "team_code": to_int(teams["code"], "teams.code"),
        "name": teams["name"],
        "short_name": teams["short_name"],
        "upstream_elo": team_id.map(latest_kickoff_elo(fixture)).astype("float64"),
    }).reset_index(drop=True)


def build_fact_fixture(
    matches: pd.DataFrame, teams: pd.DataFrame, season: str, prem_tag: str, complete: pd.Series
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_fixture: every competition. Returns the table and the rows dropped by reason.

    `complete` flags complete matches, indexed like `matches`. Matches with no kickoff_time
    are dropped. Scores are kept for every finished match and xG only for complete ones; an
    unfinished match, even one with a part-played score, has them all null. Upstream Elo is
    kept for Premier League matches only: in 2025/26 a cup row's Elo is a much later rating.
    """
    has_kickoff = matches.kickoff_time.notna()
    dropped = {"no_kickoff_time": int((~has_kickoff).sum())}
    df = matches[has_kickoff].reset_index(drop=True)
    home = map_codes(df.home_team, teams, "fact_fixture home team")
    away = map_codes(df.away_team, teams, "fact_fixture away team")
    unmapped = (df.tournament == prem_tag) & (home.isna() | away.isna())
    if unmapped.any():
        raise CleanError(f"{int(unmapped.sum())} {prem_tag} matches have a team not in teams")
    finished = df.finished.fillna(False).astype(bool)
    done = complete[has_kickoff].reset_index(drop=True)

    def result(col: str, mask: pd.Series) -> pd.Series:
        return df[col].where(mask)

    out = pd.DataFrame({
        "match_id": df.match_id, "season": season, "gw": to_int(df.gameweek, "gameweek"),
        "kickoff_utc": normalise_kickoff(df.kickoff_time), "tournament": df.tournament,
        "home_team_id": home.astype("Int64"), "away_team_id": away.astype("Int64"),
        "home_upstream_elo": df.home_team_elo.where(df.tournament == prem_tag),
        "away_upstream_elo": df.away_team_elo.where(df.tournament == prem_tag),
        "finished": finished, "stats_complete": done,
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
    tackles_column: str, fill_columns: list[str], complete: pd.Series,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_player_match: complete matches only, with blanks filled per rule 15.

    `complete` flags complete matches, indexed like `matches`; pass the same Series given to
    `build_fact_fixture`. `players` holds one snapshot per gameweek folder; a row's team is
    the player's club in the snapshot of the folder the row came from. Rows are dropped, and
    counted, when their match has no kickoff_time, is not finished, or is finished but not
    complete, or when the player is missing from that snapshot. A row for an unknown
    match is an error.
    """
    flags = matches[["match_id", "kickoff_time", "finished", "home_team", "away_team"]].assign(
        _complete=complete, _known=True
    )
    df = checked_merge(pms, flags, on="match_id", how="left", validate="many_to_one",
                       name="playermatchstats -> matches")
    if df["_known"].isna().any():
        raise JoinError("playermatchstats -> matches: rows for unknown match_id")
    no_kickoff = df.kickoff_time.isna()
    not_finished = ~df.finished.fillna(False).astype(bool) & ~no_kickoff
    not_complete = ~df["_complete"].astype(bool) & ~no_kickoff & ~not_finished
    df = df[~no_kickoff & ~not_finished & ~not_complete].reset_index(drop=True)
    problems = check_rule15_guards(df, tackles_column, fill_columns)
    if problems:
        raise ValidationError(problems)
    df = checked_merge(
        df, players[["snapshot_gw", "player_id", "team_code"]],
        on=["snapshot_gw", "player_id"], how="left", validate="many_to_one",
        name="playermatchstats -> players",
    )
    no_player = df.team_code.isna()
    wrong_club = ~no_player & (df.team_code != df.home_team) & (df.team_code != df.away_team)
    dropped = {
        "match_has_no_kickoff_time": int(no_kickoff.sum()),
        "match_not_finished": int(not_finished.sum()),
        "match_not_complete": int(not_complete.sum()),
        "player_not_in_snapshot": int(no_player.sum()),
        "club_not_in_match": int(wrong_club.sum()),
    }
    if wrong_club.any():
        rows = df[wrong_club][["player_id", "match_id"]].to_dict("records")
        log.warning("%d player-match rows dropped, club not in the match: %s", len(rows), rows)
    df = df[~no_player & ~wrong_club].reset_index(drop=True)
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


def build_season(raw: RawSeason, cfg: dict) -> BuiltSeason:
    """Build all five processed tables for a season, and reconcile them with upstream."""
    scfg = next(s for s in cfg["seasons"] if s["id"] == raw.season)
    prem, fill = cfg["premier_league_tag"], cfg["fill_zero_columns"]
    snapshot = raw.players[raw.players.snapshot_gw == raw.latest_gw]
    complete = complete_matches(raw.matches, raw.playermatchstats, raw.players, raw.teams)
    fixture, d_fix = build_fact_fixture(raw.matches, raw.teams, raw.season, prem, complete)
    dim_team = build_dim_team(raw.teams, fixture)
    dim_player, d_pl = build_dim_player(snapshot, raw.playerstats, raw.teams, cfg["position_map"])
    pmatch, d_pm = build_fact_player_match(
        raw.playermatchstats, raw.matches, raw.players, raw.teams, scfg["tackles_column"], fill,
        complete,
    )
    pgw, d_gw = build_fact_player_gw(
        raw.player_gameweek_stats, raw.players, raw.matches, raw.teams, raw.season, prem
    )
    info = {
        "unfinished_rows_kept_with_null_results": int((~fixture.finished).sum()),
        "finished_but_not_complete": int((fixture.finished & ~fixture.stats_complete).sum()),
        "finished_prem_but_not_complete": int(
            (fixture.finished & ~fixture.stats_complete & (fixture.tournament == prem)).sum()
        ),
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
