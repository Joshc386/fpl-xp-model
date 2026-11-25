"""SeasonReads with team xG, for the team-penalty tests: `elo_tables`' fixtures made complete.

Penalties are given per (fixture position in the list, side). With `PENS_A` on season A
(`FIXTURES_A`, codes 31-34, three matches each): code 31 has 0.79 + 0.78 = 1.57 penalty xG,
code 32 has 0.79, codes 33 and 34 none; 2.36 over 12 team-matches. `PENS_B` gives season B's
first fixture's home club (id 1, code 33) 0.79.
"""

from __future__ import annotations

from elo_tables import PREM
from fpl.models.elo import SeasonRead

XG = 1.5  # each club's team xG in a complete match; its npxG is XG minus its penalty xG
PENS_A = {(0, "home"): 0.79, (3, "away"): 0.78, (5, "home"): 0.79}
PENS_B = {(0, "home"): 0.79}


def complete(read: SeasonRead, pens: dict[tuple[int, str], float] | None = None,
             upto: int | None = None) -> SeasonRead:
    """`read` with its finished Premier League fixtures complete (those up to gameweek `upto`,
    or all): team xG `XG` and npxG `XG` minus the side's penalty xG in `pens` (0 if absent)."""
    fx = read.tables["fact_fixture"].copy()
    pens = pens or {}
    done = fx.finished & (fx.tournament == PREM)
    if upto is not None:
        done &= fx.gw <= upto
    for i in fx.index[done]:
        fx.loc[i, "stats_complete"] = True
        for side in ("home", "away"):
            fx.loc[i, f"{side}_xg"] = XG
            fx.loc[i, f"{side}_npxg"] = XG - pens.get((i, side), 0.0)
    return SeasonRead(read.season, read.as_of_gw, {**read.tables, "fact_fixture": fx})
