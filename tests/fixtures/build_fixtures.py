"""Cut the small upstream samples in tests/fixtures/upstream/ from the real files.

Run by hand when the samples need refreshing (not part of the test run):

    python tests/fixtures/build_fixtures.py

It reads the local upstream checkout named in config/pipeline.yaml and keeps
whole rows and all columns, so the samples have the real schema. Only rows are
selected. The future-gameweek folder of 2026-2027 (GW3) is the real GW11 folder
renumbered to GW3, so the sample shows what upstream holds for gameweeks that
have not been played: scheduled matches, a players list, and header-only
player files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import yaml

from fpl.complete import complete_matches

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "upstream" / "data"
FILES = [
    "fixtures", "matches", "players", "teams", "playerstats",
    "playermatchstats", "player_gameweek_stats",
]
EXTRA_PLAYERS = 12  # players kept besides those in the selected matches


def pick_matches(
    matches: pd.DataFrame, pms: pd.DataFrame, players: pd.DataFrame, teams: pd.DataFrame
) -> pd.DataFrame:
    """Choose a few matches that show each case: complete, not complete, cup.

    Completeness is judged on the data (finished, team xG, club rows), not on upstream flags.
    """
    needed = ["match_id", "tournament", "finished", "home_team", "away_team",
              "home_expected_goals_xg", "away_expected_goals_xg"]
    done = complete_matches(
        matches[needed], pms.assign(snapshot_gw=1), players.assign(snapshot_gw=1), teams
    )
    prem = matches.tournament == "prem"
    parts = [
        matches[prem & done].head(2),
        matches[prem & ~done].head(1),
        matches[~prem & done].head(1),
        matches[~prem & ~done].head(1),
    ]
    return pd.concat(parts).drop_duplicates("match_id")


def read(base: Path, gw: int, name: str) -> pd.DataFrame:
    """Read one file of a gameweek folder."""
    return pd.read_csv(base / "By Gameweek" / f"GW{gw}" / f"{name}.csv", low_memory=False)


def write(df: pd.DataFrame, season: str, gw: int, name: str) -> None:
    """Write one sample file."""
    folder = OUT / season / "By Gameweek" / f"GW{gw}"
    folder.mkdir(parents=True, exist_ok=True)
    df.to_csv(folder / f"{name}.csv", index=False)


def cut_played(base: Path, season: str, gw: int, ids: set[int] | None) -> set[int]:
    """Cut one played gameweek; return the player ids kept."""
    pms = read(base, gw, "playermatchstats")
    matches = pick_matches(
        read(base, gw, "matches"), pms, read(base, gw, "players"), read(base, gw, "teams")
    )
    pms = pms[pms.match_id.isin(matches.match_id)]
    keep = set(pms.player_id) | set(read(base, gw, "players").player_id[:EXTRA_PLAYERS])
    keep |= ids or set()
    write(matches, season, gw, "matches")
    write(matches, season, gw, "fixtures")
    write(pms, season, gw, "playermatchstats")
    write(read(base, gw, "teams"), season, gw, "teams")
    write(read(base, gw, "players").query("player_id in @keep"), season, gw, "players")
    for name in ("playerstats", "player_gameweek_stats"):
        df = read(base, gw, name)
        write(df[df.id.isin(keep)], season, gw, name)
    return keep


def cut_future(base: Path, season: str, real_gw: int, as_gw: int, keep: set[int]) -> None:
    """Cut a not-yet-played gameweek, renumbered to `as_gw`."""
    matches = read(base, real_gw, "matches").head(3).assign(gameweek=as_gw)
    write(matches, season, as_gw, "matches")
    write(matches, season, as_gw, "fixtures")
    write(read(base, real_gw, "teams"), season, as_gw, "teams")
    players = read(base, real_gw, "players")
    write(players[players.player_id.isin(keep)], season, as_gw, "players")
    for name in ("playerstats", "playermatchstats", "player_gameweek_stats"):
        write(read(base, real_gw, name).head(0), season, as_gw, name)


def main() -> None:
    """Rebuild the samples."""
    cfg = yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))
    data = ROOT / cfg["upstream"]["checkout_path"] / cfg["upstream"]["data_dir"]
    shutil.rmtree(OUT, ignore_errors=True)
    for season in ("2025-2026", "2026-2027"):
        base = data / season
        keep = cut_played(base, season, 1, None)
        keep = cut_played(base, season, 2, keep)
        if season == "2026-2027":
            cut_future(base, season, 11, 3, keep)


if __name__ == "__main__":
    main()
