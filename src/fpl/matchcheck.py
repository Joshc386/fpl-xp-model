"""Checks of fact_shot against matches.csv: penalty xG, shot counts, goals and team xG.

These run only from `run_pipeline` on the real checkout, never inside `load_as_of`: the
validator's perturbation test corrupts the scores, xG and `finished` of matches.csv, and a
comparison with the shots (which it leaves alone) would fail on that copy. The shots file and
matches.csv carry two xG measures from the same provider, so the team xG checks are loose; the
tight ones are penalty xG and the shot counts (docs/data_contract.md, config/pipeline.yaml).
"""

from __future__ import annotations

import pandas as pd

from fpl.frames import checked_merge

GOAL_OUTCOMES = ("goal", "ownGoal")


def _sides(fixture: pd.DataFrame, matches: pd.DataFrame, prem_tag: str) -> pd.DataFrame:
    """One row per club of each Premier League complete match, with what matches.csv says."""
    done = fixture[(fixture.tournament == prem_tag) & fixture.stats_complete]
    raw = checked_merge(
        done[["match_id"]], matches[["match_id", "home_total_shots", "away_total_shots"]],
        on="match_id", how="left", validate="one_to_one", name="complete matches -> matches.csv")
    rows = []
    for side, other in (("home", "away"), ("away", "home")):
        rows.append(pd.DataFrame({
            "match_id": done.match_id.to_numpy(), "gw": done.gw.to_numpy(),
            "team_id": done[f"{side}_team_id"].to_numpy(),
            "opp_id": done[f"{other}_team_id"].to_numpy(),
            "team_xg": done[f"{side}_xg"].to_numpy(), "team_npxg": done[f"{side}_npxg"].to_numpy(),
            "goals": done[f"{side}_goals"].to_numpy(),
            "total_shots": raw[f"{side}_total_shots"].to_numpy(),
        }))
    return pd.concat(rows, ignore_index=True)


def _shot_totals(shot: pd.DataFrame) -> pd.DataFrame:
    """Per club and match: shot rows, shot xG, penalty xG and goal-type shots."""
    df = shot.assign(
        pen=shot.xg.where(shot.is_penalty, 0.0),
        goal=shot.outcome.isin(GOAL_OUTCOMES).astype("int64"),
    )
    return df.groupby(["match_id", "team_id"], as_index=False).agg(
        n=("xg", "size"), xg=("xg", "sum"), pen=("pen", "sum"), g=("goal", "sum"))


def check_against_matches(
    tables: dict[str, pd.DataFrame], matches: pd.DataFrame, cfg: dict
) -> tuple[list[str], dict[str, float]]:
    """Compare fact_shot with the complete Premier League matches of fact_fixture and matches.csv.

    `matches` is the raw matches frame (for `home_total_shots` and `away_total_shots`). Every
    failure is counted by reason; each count over zero is a problem. The season ratio and mean
    absolute difference of shot xG against team xG are returned beside the counts.
    """
    tol, prem = cfg["shot_reconciliation"], cfg["premier_league_tag"]
    sides = _sides(tables["fact_fixture"], matches, prem)
    totals = _shot_totals(tables["fact_shot"])
    df = checked_merge(sides, totals, on=["match_id", "team_id"], how="left",
                       validate="one_to_one", name="club sides -> shot totals")
    df[["n", "xg", "pen", "g"]] = df[["n", "xg", "pen", "g"]].fillna(0)
    own = tables["fact_player_gw"].groupby(["team_id", "gw"], as_index=False).own_goals.sum()
    df = _with_own_goals(df, own)
    diff = df.xg - df.team_xg
    gap = df.goals - df.g
    count_gap = (df.n - df.total_shots).abs()
    counts: dict[str, float] = {
        "penalty_xg_mismatch": int(((df.pen - (df.team_xg - df.team_npxg)).abs()
                                    > tol["penalty_xg_tolerance"]).sum()),
        "shot_count_mismatch": int((~(count_gap <= tol["shot_count_tolerance"])).sum()),
        "goals_mismatch": int(((gap < 0) | (gap > df.opp_own_goals)).sum()),
        "team_xg_mismatch": int((diff.abs() > tol["team_xg_tolerance"]).sum()),
        "sides": len(df),
    }
    ratio = float(df.xg.sum() / df.team_xg.sum()) if len(df) else 1.0
    mean_abs = float(diff.abs().mean()) if len(df) else 0.0
    counts |= {"team_xg_ratio": ratio, "team_xg_mean_abs": mean_abs}
    problems = [f"fact_shot against matches.csv: {counts[k]} of {len(df)} club sides: {k}"
                for k in ("penalty_xg_mismatch", "shot_count_mismatch", "goals_mismatch",
                          "team_xg_mismatch") if counts[k]]
    lo, hi = tol["team_xg_season_ratio"]
    if not lo <= ratio <= hi:
        problems.append(f"fact_shot: season ratio of shot xG to team xG is {ratio:.3f}, outside "
                        f"[{lo}, {hi}]")
    if mean_abs > tol["team_xg_mean_abs"]:
        problems.append(f"fact_shot: mean absolute shot xG minus team xG is {mean_abs:.3f}, over "
                        f"{tol['team_xg_mean_abs']}")
    return problems, counts


def _with_own_goals(df: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    """Add `opp_own_goals`: the own goals the opponent's players scored that gameweek."""
    right = own.rename(columns={"team_id": "opp_id", "own_goals": "opp_own_goals"})
    right = right.astype({"opp_id": "float64"})
    out = checked_merge(df.astype({"opp_id": "float64"}), right, on=["opp_id", "gw"], how="left",
                        validate="many_to_one", name="club sides -> opponent own goals")
    return out.fillna({"opp_own_goals": 0})

