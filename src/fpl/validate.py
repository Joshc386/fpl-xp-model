"""Validation: input checks (brief section 11, step 4). Table checks are in validate_tables.

Every check returns a list of problems; the public functions gather them all and
raise `ValidationError` if there is any. A failed check never logs and carries on.
"""

from __future__ import annotations

import logging

import pandas as pd

from fpl.complete import complete_matches
from fpl.frames import JoinError
from fpl.ingest import RawSeason, required_columns_missing
from fpl.schema import fill_sources

log = logging.getLogger(__name__)


class ValidationError(RuntimeError):
    """One or more checks failed; `problems` lists them all."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _outside(value: float, bounds: list[float]) -> bool:
    return not bounds[0] <= value <= bounds[1]


def key_problems(df: pd.DataFrame, cols: list[str], label: str) -> list[str]:
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
        out += key_problems(df, cols, label)
    return out


def _bounded(label: str, counts: pd.Series, bounds: list[float]) -> list[str]:
    bad = counts[(counts < bounds[0]) | (counts > bounds[1])]
    return [f"{label}: {k} has {v} rows, outside {bounds}" for k, v in bad.items()]


def _complete(raw: RawSeason) -> pd.Series:
    return complete_matches(raw.matches, raw.playermatchstats, raw.players, raw.teams)


def check_row_counts(
    raw: RawSeason, bounds: dict, prem_tag: str, complete: pd.Series | None
) -> list[str]:
    """Row counts are within the configured bounds.

    `complete` is the completeness of each match; None when it could not be computed
    (already reported), which skips the per-match player row bound.
    """
    pgs = pd.Series(raw.gw_rows["player_gameweek_stats"])
    pgs = pgs[(pgs.index >= 1) & (pgs.index <= raw.latest_gw) & (pgs > 0)]
    out = []
    if complete is not None:
        done_ids = raw.matches.match_id[complete]
        per_match = raw.playermatchstats.groupby("match_id").size().reindex(done_ids, fill_value=0)
        out += _bounded("playermatchstats", per_match, bounds["playermatchstats_rows_per_match"])
    out += _bounded("player_gameweek_stats", pgs, bounds["player_gameweek_stats_rows_per_gw"])
    # Every snapshot the read needs counts, so a header-only players.csv fails the bound.
    needed = sorted(set(range(1, raw.latest_gw + 1)) | set(raw.playermatchstats.snapshot_gw))
    players = raw.players.groupby("snapshot_gw").size().reindex(needed, fill_value=0)
    out += _bounded("players", players, bounds["players_rows_per_snapshot"])
    n_prem = int((raw.matches.tournament == prem_tag).sum())
    matches_bounds = bounds["matches_rows"]
    if raw.as_of_gw is not None and raw.as_of_gw < raw.n_gw:
        # An as-of read leaves out later cup and European matches, so only the Premier
        # League schedule is whole: it must still reach the full-season Premier League bound.
        matches_bounds = [bounds["prem_matches_rows"][0], matches_bounds[1]]
    scalars = [
        ("teams", len(raw.teams), bounds["teams_rows"]),
        ("playerstats", len(raw.playerstats), bounds["playerstats_rows_snapshot"]),
        ("matches", len(raw.matches), matches_bounds),
        ("prem matches", n_prem, bounds["prem_matches_rows"]),
    ]
    if raw.latest_gw == 0:  # nothing played yet, so no playerstats snapshot
        del scalars[1]
    for label, n, limits in scalars:
        if _outside(n, limits):
            out.append(f"{label}: {n} rows, outside {limits}")
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


def check_latest_gw(raw: RawSeason, prem_tag: str) -> list[str]:
    """The latest gameweek folder is present, with no gap before it and no data after it.

    "Data after" means Premier League data: player rows or finished matches in a later
    folder. Finished cup and European matches there are normal (upstream files a midweek
    tie under the next gameweek), and so are their player rows. On an as-of read the
    Premier League matches after `as_of_gw` are blanked, so they can only fail if the
    blanking is removed. Nothing is played yet at as-of 0, or at 1 before upstream writes GW1.
    """
    if raw.latest_gw < 1 and raw.as_of_gw not in (0, 1):
        return ["latest gameweek: no folder holds player_gameweek_stats rows"]
    out = []
    pgs = raw.gw_rows["player_gameweek_stats"]
    gaps = [g for g in range(1, raw.latest_gw + 1) if pgs.get(g, 0) == 0]
    if gaps:
        out.append(f"gap: gameweeks {gaps} have no player_gameweek_stats rows")
    later = {g: n for g, n in raw.gw_rows["playermatchstats"].items() if g > raw.latest_gw and n}
    if later:
        out.append(f"playermatchstats rows after the latest gameweek {raw.latest_gw}: {later}")
    future_done = (
        raw.matches.finished.fillna(False)
        & (raw.matches.snapshot_gw > raw.latest_gw)
        & (raw.matches.tournament == prem_tag)
    )
    if future_done.any():
        out.append(
            f"{int(future_done.sum())} finished match(es) of {prem_tag} in folders after the "
            "latest gameweek"
        )
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
    # A cup or European match's gameweek is derived (the gameweek it was played in), so only
    # the Premier League ones must agree with the folder.
    wrong_gw = int((prem.gameweek != prem.snapshot_gw).sum())
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
    """Brief data rule 15 guards, on playermatchstats rows of complete matches.

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
    prem = cfg["premier_league_tag"]
    problems = check_files(raw) + check_keys(raw) + check_latest_gw(raw, prem)
    try:
        complete: pd.Series | None = _complete(raw)
    except JoinError as exc:
        problems.append(f"complete matches could not be worked out: {exc}")
        complete = None
    problems += check_row_counts(raw, bounds, prem, complete) + check_prices(raw, bounds)
    problems += check_references(raw, prem)
    if complete is not None:
        done = raw.matches.match_id[complete]
        pms = raw.playermatchstats[raw.playermatchstats.match_id.isin(done)]
        fill = cfg["fill_zero_columns"]
        problems += check_rule15_guards(pms, season_cfg["tackles_column"], fill)
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
