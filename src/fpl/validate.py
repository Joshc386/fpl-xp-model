"""Validation: input checks (brief section 11, step 4) and processed-table checks.

Every check returns a list of problems; the public functions gather them all and
raise `ValidationError` if there is any. A failed check never logs and carries on.
"""

from __future__ import annotations

import logging

import pandas as pd

from fpl.ingest import RawSeason, required_columns_missing
from fpl.schema import TABLE_KEYS, check_table_schema, fill_sources

log = logging.getLogger(__name__)


class ValidationError(RuntimeError):
    """One or more checks failed; `problems` lists them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def is_processed(matches: pd.DataFrame) -> pd.Series:
    """True for a processed match: finished, stats_processed and player_stats_processed."""
    flags = matches.finished & matches.stats_processed & matches.player_stats_processed
    return flags.fillna(False).astype(bool)


def _outside(value: float, bounds: list[float]) -> bool:
    return not bounds[0] <= value <= bounds[1]


def _key_problems(df: pd.DataFrame, cols: list[str], label: str) -> list[str]:
    out = [
        f"{label}.{c}: {int(df[c].isna().sum())} null values" for c in cols if df[c].isna().any()
    ]
    dups = int(df.duplicated(cols).sum())
    if dups:
        out.append(f"{label} ({', '.join(cols)}): {dups} duplicate keys")
    return out


def check_files(raw: RawSeason) -> list[str]:
    """Expected files exist and carry the required columns."""
    out = [f"missing file: {f}" for f in raw.missing_files]
    return out + [f"missing required column {x}" for x in required_columns_missing(raw)]


def check_keys(raw: RawSeason) -> list[str]:
    """Keys are non-null and unique."""
    out: list[str] = []
    for df, cols, label in (
        (raw.matches, ["match_id"], "matches"),
        (raw.teams, ["id"], "teams"),
        (raw.teams, ["code"], "teams"),
        (raw.players, ["snapshot_gw", "player_id"], "players"),
        (raw.players, ["snapshot_gw", "player_code"], "players"),
        (raw.playerstats, ["id"], "playerstats"),
        (raw.playermatchstats, ["player_id", "match_id"], "playermatchstats"),
        (raw.player_gameweek_stats, ["id", "gw"], "player_gameweek_stats"),
    ):
        out += _key_problems(df, cols, label)
    return out


def _bounded(label: str, counts: pd.Series, bounds: list[float]) -> list[str]:
    bad = counts[(counts < bounds[0]) | (counts > bounds[1])]
    return [f"{label}: {k} has {v} rows, outside {bounds}" for k, v in bad.items()]


def check_row_counts(raw: RawSeason, bounds: dict, prem_tag: str) -> list[str]:
    """Row counts are within the configured bounds."""
    in_play = raw.matches.snapshot_gw <= raw.latest_gw
    done_ids = raw.matches.match_id[is_processed(raw.matches) & in_play]
    per_match = raw.playermatchstats.groupby("match_id").size().reindex(done_ids, fill_value=0)
    pgs = pd.Series(raw.gw_rows["player_gameweek_stats"])
    pgs = pgs[(pgs.index >= 1) & (pgs.index <= raw.latest_gw) & (pgs > 0)]
    out = _bounded("playermatchstats", per_match, bounds["playermatchstats_rows_per_match"])
    out += _bounded("player_gameweek_stats", pgs, bounds["player_gameweek_stats_rows_per_gw"])
    out += _bounded("players", raw.players.groupby("snapshot_gw").size(),
                    bounds["players_rows_per_snapshot"])
    scalars = (
        ("teams", len(raw.teams), "teams_rows"),
        ("playerstats", len(raw.playerstats), "playerstats_rows_snapshot"),
        ("matches", len(raw.matches), "matches_rows"),
        ("prem matches", int((raw.matches.tournament == prem_tag).sum()), "prem_matches_rows"),
    )
    for label, n, key in scalars:
        if _outside(n, bounds[key]):
            out.append(f"{label}: {n} rows, outside {bounds[key]}")
    n_prem = scalars[-1][1]
    if bounds["prem_matches_rows"][0] <= n_prem < bounds["prem_matches_rows"][1]:
        log.warning(
            "%s: %d prem matches, below %d; postponed matches have no gameweek folder",
            raw.season, n_prem, bounds["prem_matches_rows"][1],
        )
    return out


def check_prices(raw: RawSeason, bounds: dict) -> list[str]:
    """now_cost is in GBP m (not tenths) and within bounds."""
    lo, hi = bounds["now_cost_m"]
    out = []
    for df, label in (
        (raw.playerstats, "playerstats"),
        (raw.player_gameweek_stats, "player_gameweek_stats"),
    ):
        bad = int((~df.now_cost.between(lo, hi)).sum())
        if bad:
            out.append(f"{label}.now_cost: {bad} values null or outside [{lo}, {hi}] GBP m")
    return out


def check_latest_gw(raw: RawSeason) -> list[str]:
    """The latest gameweek folder is present, with no gap before it and no data after it."""
    if raw.latest_gw < 1:
        return ["latest gameweek: no folder holds player_gameweek_stats rows"]
    out = []
    pgs = raw.gw_rows["player_gameweek_stats"]
    gaps = [g for g in range(1, raw.latest_gw + 1) if pgs.get(g, 0) == 0]
    if gaps:
        out.append(f"gap: gameweeks {gaps} have no player_gameweek_stats rows")
    later = {g: n for g, n in raw.gw_rows["playermatchstats"].items() if g > raw.latest_gw and n}
    if later:
        out.append(f"playermatchstats rows after the latest gameweek {raw.latest_gw}: {later}")
    future_done = raw.matches[is_processed(raw.matches) & (raw.matches.snapshot_gw > raw.latest_gw)]
    if len(future_done):
        out.append(f"{len(future_done)} processed match(es) in folders after the latest gameweek")
    have = set(raw.matches.snapshot_gw)
    missing = [g for g in range(1, raw.n_gw + 1) if g not in have]
    if missing:
        out.append(f"gameweek folder(s) {missing} have no matches")
    return out


def check_references(raw: RawSeason, prem_tag: str) -> list[str]:
    """Foreign keys resolve and the two match files agree."""
    m = raw.matches
    out = []
    unknown = int((~raw.playermatchstats.match_id.isin(m.match_id)).sum())
    if unknown:
        out.append(f"playermatchstats: {unknown} rows for unknown match_id")
    prem = m[m.tournament == prem_tag]
    no_kickoff = int(prem.kickoff_time.isna().sum())
    if no_kickoff:
        out.append(f"{no_kickoff} {prem_tag} matches have no kickoff_time")
    bad = int((~prem.home_team.isin(raw.teams.code) | ~prem.away_team.isin(raw.teams.code)).sum())
    if bad:
        out.append(f"{bad} {prem_tag} matches have a team code not in teams.csv")
    if int((~raw.players.team_code.isin(raw.teams.code)).sum()):
        out.append("players: team_code not in teams.csv")
    wrong_gw = int((m.gameweek != m.snapshot_gw).sum())
    if wrong_gw:
        out.append(f"matches.gameweek differs from its folder in {wrong_gw} rows")
    left = set(zip(raw.fixture_ids.snapshot_gw, raw.fixture_ids.match_id, strict=True))
    right = set(zip(m.snapshot_gw, m.match_id, strict=True))
    if left != right:
        out.append(f"fixtures.csv and matches.csv list different matches ({len(left ^ right)})")
    return out


def check_rule15_guards(
    pms: pd.DataFrame, tackles_column: str, fill_columns: list[str]
) -> list[str]:
    """Brief data rule 15 guards, on playermatchstats rows of processed matches.

    Fails if a listed column's *source* column (tackles map to `tackles_column`) is
    empty for the whole season, or if an xG is blank beside `total_shots` > 0.
    """
    if pms.empty:
        return []
    sources = fill_sources(tackles_column)
    out = [
        f"rule 15: {col} (source column {sources[col]}) is empty for the whole season"
        for col in fill_columns
        if pms[sources[col]].isna().all()
    ]
    blank = int((pms.xg.isna() & (pms.total_shots > 0)).sum())
    if blank:
        out.append(f"rule 15: xg is blank in {blank} rows where total_shots > 0")
    return out


def validate_inputs(raw: RawSeason, cfg: dict, season_cfg: dict) -> None:
    """Run every input check for one season; raise `ValidationError` on any problem."""
    bounds = cfg["validation"]
    problems = check_files(raw) + check_keys(raw) + check_latest_gw(raw)
    prem = cfg["premier_league_tag"]
    problems += check_row_counts(raw, bounds, prem) + check_prices(raw, bounds)
    problems += check_references(raw, prem)
    done = raw.matches.match_id[is_processed(raw.matches)]
    pms = raw.playermatchstats[raw.playermatchstats.match_id.isin(done)]
    problems += check_rule15_guards(pms, season_cfg["tackles_column"], cfg["fill_zero_columns"])
    if problems:
        raise ValidationError([f"{raw.season}: {p}" for p in problems])


def check_match_ids_disjoint(raws: list[RawSeason]) -> None:
    """A match_id must belong to one season only."""
    seen: dict[str, str] = {}
    clash: list[str] = []
    for raw in raws:
        for mid in raw.matches.match_id:
            if mid in seen and seen[mid] != raw.season:
                clash.append(mid)
            seen.setdefault(mid, raw.season)
    if clash:
        raise ValidationError([f"match_id appears in more than one season: {clash[:5]}"])


# Fact tables may hold players who have since left the league, so player_id is not
# required to be in dim_player (a snapshot of the current players).
_FOREIGN_KEYS = (
    ("fact_fixture", "home_team_id", "dim_team", "team_id"),
    ("fact_fixture", "away_team_id", "dim_team", "team_id"),
    ("dim_player", "team_id", "dim_team", "team_id"),
    ("fact_player_match", "match_id", "fact_fixture", "match_id"),
    ("fact_player_match", "team_id", "dim_team", "team_id"),
)


def _fixture_result_problems(fx: pd.DataFrame) -> list[str]:
    """Scores only on finished matches, xG only on processed ones."""
    goals, xg = ["home_goals", "away_goals"], ["home_xg", "away_xg", "home_npxg", "away_npxg"]
    out = []
    if fx.loc[~fx.finished, goals].notna().any().any():
        out.append("fact_fixture: scores present on unfinished matches")
    if fx.loc[fx.finished, goals].isna().any().any():
        out.append("fact_fixture: finished matches without a score")
    if fx.loc[~fx.processed, xg].notna().any().any():
        out.append("fact_fixture: xG present on unprocessed matches")
    if (fx.processed & ~fx.finished).any():
        out.append("fact_fixture: processed matches that are not finished")
    return out


def validate_tables(tables: dict[str, pd.DataFrame]) -> None:
    """Check processed tables: schema, unique keys, foreign keys, results only when finished."""
    problems: list[str] = []
    for name, df in tables.items():
        problems += check_table_schema(df, name)
        if not problems:
            problems += _key_problems(df, TABLE_KEYS[name], name)
    if not problems:
        for table, col, ref, ref_col in _FOREIGN_KEYS:
            orphans = int((~tables[table][col].dropna().isin(tables[ref][ref_col])).sum())
            if orphans:
                problems.append(f"{table}.{col}: {orphans} values not in {ref}.{ref_col}")
        problems += _fixture_result_problems(tables["fact_fixture"])
    if problems:
        raise ValidationError(problems)
