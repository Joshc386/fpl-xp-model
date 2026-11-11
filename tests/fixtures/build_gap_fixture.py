"""Cut tests/fixtures/upstream_gap/ from upstream commit 92a90c26 (2026-11-06 15:16 UTC).

Run by hand, not part of the test run:

    python tests/fixtures/build_gap_fixture.py PATH_TO_CHECKOUT_AT_92a90c26/data

That commit is what a run sees after the GW10 deadline (18:30) and before upstream's first
write of GW10's player figures (20:59): the GW10 folder already holds the cup and European
matches played on 3-5 November, finished, with their player rows, but its
`player_gameweek_stats` is header-only. The sample is a three-gameweek season of 2026-2027:

* GW1 is the real GW9 (played), cut to three Premier League matches;
* GW2 is the real GW10 folder as it stood at 92a90c26 (the gap folder);
* GW3 is the real GW11 (scheduled only), copied from the main sample.

Rows are whole and columns are untouched; only the gameweek numbers are renumbered.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "upstream_gap" / "data" / "2026-2027"
MAIN_SAMPLE = HERE / "upstream" / "data" / "2026-2027" / "By Gameweek" / "GW3"
EXTRA_PLAYERS = 12


def folder(src: Path, real_gw: int) -> Path:
    return src / "2026-2027" / "By Gameweek" / f"GW{real_gw}"


def write(df: pd.DataFrame, gw: int, name: str) -> None:
    path = OUT / "By Gameweek" / f"GW{gw}" / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def cut(src: Path) -> None:
    g9, g10 = folder(src, 9), folder(src, 10)
    m9 = pd.read_csv(g9 / "matches.csv")
    m9 = m9[(m9.tournament == "prem") & m9.finished].head(3)
    pms9 = pd.read_csv(g9 / "playermatchstats.csv")
    pms9 = pms9[pms9.match_id.isin(m9.match_id)]
    pms10 = pd.read_csv(g10 / "playermatchstats.csv")
    players9 = pd.read_csv(g9 / "players.csv")
    keep = set(pms9.player_id) | set(pms10.player_id) | set(players9.player_id[:EXTRA_PLAYERS])
    for real, gw, matches, pms in ((9, 1, m9, pms9), (10, 2, None, pms10)):
        f = folder(src, real)
        m = pd.read_csv(f / "matches.csv") if matches is None else matches
        m = m.assign(gameweek=gw)
        write(m, gw, "matches")
        fixtures = pd.read_csv(f / "fixtures.csv")
        write(fixtures[fixtures.match_id.isin(m.match_id)].assign(gameweek=gw), gw, "fixtures")
        write(pms, gw, "playermatchstats")
        players = pd.read_csv(f / "players.csv")
        write(players[players.player_id.isin(keep)], gw, "players")
        write(pd.read_csv(f / "teams.csv"), gw, "teams")
        for name in ("playerstats", "player_gameweek_stats"):
            d = pd.read_csv(f / f"{name}.csv")
            d = d[d["id"].isin(keep)] if len(d) else d
            write(d.assign(gw=gw) if len(d) else d, gw, name)
    for path in MAIN_SAMPLE.glob("*.csv"):
        dest = OUT / "By Gameweek" / "GW3" / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
    summaries = pd.read_csv(src / "2026-2027" / "gameweek_summaries.csv")
    rows = summaries[summaries.id.isin([9, 10, 11])].sort_values("id")
    OUT.joinpath("gameweek_summaries.csv").write_text(
        rows.assign(id=[1, 2, 3]).to_csv(index=False), encoding="utf-8"
    )
    master = pd.read_csv(src / "2026-2027" / "playerstats.csv")
    master = master[(master.gw == 9) & master["id"].isin(keep)].assign(gw=1)
    master.to_csv(OUT / "playerstats.csv", index=False)


if __name__ == "__main__":
    cut(Path(sys.argv[1]))
