"""Cut the real-match samples in tests/fixtures/spells/ (shots, spells, red cards).

Run by hand, not part of the test run:

    python tests/fixtures/build_spell_fixtures.py

It reads the local upstream checkout named in config/pipeline.yaml (cut at upstream
`ac8be9c`) and keeps whole rows of each raw file, so the samples keep the real columns. Two
matches, each holding a sent-off player whose `playermatchstats` timeline reads full time or
whose first-half stoppage minutes sit beyond 45:

* 2026-2027 GW1 Brighton v Aston Villa: player 54 is sent off after 40 minutes (FPL minutes 39,
  `minutes_played` 40) but his `finish_min` is 95.
* 2025-2026 GW5 Man Utd v Chelsea: player 457 is sent off in first-half stoppage (`minutes_played`
  49); its substitutions come from `incidents.csv`.

`<season>_<match>_players.csv` joins each `playermatchstats` row with the player's club
(`team_id`, from that gameweek's `players.csv` and `teams.csv`) and the fact_player_match
minutes, so a test can feed the spell builder without the whole pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "spells"
CASES = [
    ("2026-2027", 1, "26-27-prem-brighton-hove-albion-vs-aston-villa", "2627"),
    ("2025-2026", 5, "25-26-prem-manchester-united-vs-chelsea", "2526"),
]


def cut(data: Path, season: str, gw: int, match_id: str, tag: str) -> None:
    """Write the sample files of one match."""
    folder = data / season / "By Gameweek" / f"GW{gw}"

    def read(name: str) -> pd.DataFrame:
        return pd.read_csv(folder / f"{name}.csv", low_memory=False)

    pms = read("playermatchstats")
    pms = pms[pms.match_id == match_id]
    players, teams = read("players"), read("teams")
    club = players.merge(teams[["code", "id"]], left_on="team_code", right_on="code")
    rows = pms.merge(club[["player_id", "id"]].rename(columns={"id": "team_id"}), on="player_id")
    keep = ["player_id", "team_id", "match_id", "minutes_played", "start_min", "finish_min"]
    rows[keep].to_csv(OUT / f"{tag}_players.csv", index=False)
    read("shots").query("match_id == @match_id").to_csv(OUT / f"{tag}_shots.csv", index=False)
    if season == "2025-2026":
        inc = read("incidents").query("match_id == @match_id")
        inc.to_csv(OUT / f"{tag}_incidents.csv", index=False)
    matches = read("matches").query("match_id == @match_id")
    keep_m = ["match_id", "home_team", "away_team", "home_expected_goals_xg",
              "away_expected_goals_xg", "home_non_penalty_xg", "away_non_penalty_xg",
              "home_score", "away_score", "home_total_shots", "away_total_shots"]
    matches[keep_m].to_csv(OUT / f"{tag}_match.csv", index=False)
    teams[["id", "code"]].to_csv(OUT / f"{tag}_teams.csv", index=False)


def main() -> None:
    """Rebuild the samples."""
    cfg = yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))
    data = ROOT / cfg["upstream"]["checkout_path"] / cfg["upstream"]["data_dir"]
    OUT.mkdir(exist_ok=True)
    for case in CASES:
        cut(data, *case)


if __name__ == "__main__":
    main()
