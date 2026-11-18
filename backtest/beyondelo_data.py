"""The outside-source Elo check's data layer: one row per match of a window, with each source's
before-match gap and the result, and ranking agreement per gameweek. Pure: every input is a
frame (our `elo_ratings.csv`, `ext_beyondelo` and `fact_fixture` from `load_as_of`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from backtest.beyondelo_fit import AWAY, DRAW, HOME
from backtest.elo_metrics import spearman

PARTNERS = ("finished_result", "our_rating", "beyondelo_rating")
OURS, THEIRS = "elo_before", "beyondelo_before"


class CheckError(RuntimeError):
    """The check can't be run as defined: it stops with this plain message and no report."""


@dataclass(frozen=True)
class Window:
    """A season's inclusive gameweek range: the fit window or a scored window."""

    name: str
    season: str
    first: int
    last: int

    @property
    def label(self) -> str:
        """For example "2025-2026 GW27-38"."""
        return f"{self.season} GW{self.first}-{self.last}"

    def holds(self, df: pd.DataFrame) -> pd.Series:
        """Which rows of `df` (with `season` and `gw`) fall in the window."""
        return (df.season == self.season) & df.gw.between(self.first, self.last)


def _pair(rows: pd.DataFrame | None, col: str,
          teams: tuple[int, int] | None) -> tuple[float, float] | None:
    """(home, away) rating of one match from its rows, or None unless there are exactly two,
    one per club of the fixture, both rated. Without a fixture, two rated rows of two clubs
    count as present, with unknown sides."""
    if rows is None or len(rows) != 2 or rows[col].isna().any():
        return None
    ids = [int(t) for t in rows.team_id]
    if len(set(ids)) != 2:
        return None
    if teams is None:
        return (math.nan, math.nan)
    if set(ids) != set(teams):
        return None
    r = dict(zip(ids, rows[col], strict=True))
    return float(r[teams[0]]), float(r[teams[1]])


def _result(home: int, away: int) -> int:
    return HOME if home > away else DRAW if home == away else AWAY


def window_table(w: Window, ours: pd.DataFrame, theirs: pd.DataFrame, fx: pd.DataFrame,
                 prem: str) -> tuple[pd.DataFrame, dict[str, int], dict[str, list[str]]]:
    """Window `w`'s matches, each with a finished result and both sources' ratings.

    A match is in the window if any source places it there: a Premier League fixture, our
    rating rows or beyondELO's, by each one's own `season` and `gw`. Returns the complete
    matches (sorted by kickoff), the counts per partner, and the matches lacking each partner
    (only kinds with any). `gap_ours` and `gap_beyondelo` are home minus away; `promoted` is
    true when beyondELO flags either club.
    """
    league = fx[(fx.tournament == prem) & w.holds(fx)]
    if league.match_id.duplicated().any():
        raise CheckError(f"{w.label}: a fixture appears twice in fact_fixture")
    fix = league.set_index("match_id")
    o, b = ours[w.holds(ours)], theirs[w.holds(theirs)]
    og, bg = dict(tuple(o.groupby("match_id"))), dict(tuple(b.groupby("match_id")))
    ids = sorted(set(fix.index) | set(og) | set(bg))
    rows, missing = [], {k: [] for k in PARTNERS}
    for m in ids:
        f = fix.loc[m] if m in fix.index else None
        teams = None if f is None else (int(f.home_team_id), int(f.away_team_id))
        done = (f is not None and bool(f.finished) and pd.notna(f.home_goals)
                and pd.notna(f.away_goals))
        po, pb = _pair(og.get(m), OURS, teams), _pair(bg.get(m), THEIRS, teams)
        for kind, ok in zip(PARTNERS, (done, po is not None, pb is not None), strict=True):
            if not ok:
                missing[kind].append(m)
        if done and po is not None and pb is not None:
            rows.append({"season": w.season, "gw": int(f.gw), "match_id": m,
                         "kickoff_utc": f.kickoff_utc, "home_team_id": teams[0],
                         "away_team_id": teams[1],
                         "result": _result(int(f.home_goals), int(f.away_goals)),
                         "ours_home": po[0], "ours_away": po[1],
                         "beyondelo_home": pb[0], "beyondelo_away": pb[1],
                         "gap_ours": po[0] - po[1], "gap_beyondelo": pb[0] - pb[1],
                         "promoted": bool(bg[m].promoted.any())})
    counts = {"matches": len(ids)} | {k: len(ids) - len(missing[k]) for k in PARTNERS}
    counts["complete"] = len(rows)
    cols = ["season", "gw", "match_id", "kickoff_utc", "home_team_id", "away_team_id",
            "result", "ours_home", "ours_away", "beyondelo_home", "beyondelo_away", "gap_ours",
            "gap_beyondelo", "promoted"]
    table = pd.DataFrame(rows, columns=cols).sort_values(["kickoff_utc", "match_id"],
                                                         kind="stable", ignore_index=True)
    return table, counts, {k: v for k, v in missing.items() if v}


def team_kickoffs(table: pd.DataFrame) -> pd.DataFrame:
    """A window table as one row per club per match: a double gameweek gives a club two."""
    keys = ["season", "gw", "match_id", "kickoff_utc"]
    sides = [table[keys].assign(team_id=table[f"{s}_team_id"], elo_before=table[f"ours_{s}"],
                                beyondelo_before=table[f"beyondelo_{s}"])
             for s in ("home", "away")]
    return pd.concat(sides, ignore_index=True).sort_values(["kickoff_utc", "match_id"],
                                                           kind="stable", ignore_index=True)


def ranking_by_gameweek(table: pd.DataFrame) -> pd.DataFrame:
    """Spearman's rank correlation of our `elo_before` with `beyondelo_before` over each
    gameweek's team-kickoffs (ties take their average rank; NaN if a source rates all equal)."""
    k = team_kickoffs(table)
    rows = [{"gw": int(g), "n": len(x), "spearman": spearman(x.elo_before, x.beyondelo_before)}
            for g, x in k.groupby("gw")]
    return pd.DataFrame(rows, columns=["gw", "n", "spearman"])


def rank_disagreements(table: pd.DataFrame, gw: int, names: pd.Series,
                       top_n: int) -> pd.DataFrame:
    """GW `gw`'s `top_n` team-kickoffs whose ranks differ most between the sources.

    Rank 1 is the highest rating; ties take their average rank. Equal gaps are ordered by
    club name, then kickoff.
    """
    k = team_kickoffs(table[table.gw == gw])
    k = k.assign(team=k.team_id.map(names),
                 our_rank=k.elo_before.rank(ascending=False),
                 beyondelo_rank=k.beyondelo_before.rank(ascending=False))
    k["rank_gap"] = (k.our_rank - k.beyondelo_rank).abs()
    k = k.sort_values(["rank_gap", "team", "kickoff_utc"], ascending=[False, True, True],
                      kind="stable")
    cols = ["team", "match_id", "elo_before", "our_rank", "beyondelo_before",
            "beyondelo_rank", "rank_gap"]
    return k[cols].head(top_n).reset_index(drop=True)
