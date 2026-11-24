"""The scored rows of one target gameweek (brief section 7, "Evaluation set").

The evaluation set: players with actual FPL minutes > 0 in the target gameweek g, or who
started one of their club's previous 3 Premier League matches (`xp_inputs.started_recently`).
It uses no model's output, so every predictor is scored on the identical rows. Two kinds of
member can't be scored and are counted instead: players missing from the GW g-1 snapshot
(nobody, ep_next included, had a prediction for them) and players with no `fact_player_gw`
row for g.
"""

from __future__ import annotations

import pandas as pd

from backtest.elo_data import HarnessError

# The Combine row of docs/data_contract.md ("Component hand-offs", decided 2026-11-24): keys
# and columns every `xp` row carries, besides the scored column.
MODEL_COLUMNS = ["player_id", "team_id", "match_id", "gw", "xp_appear", "xp_cards"]


def actuals(final: dict[str, pd.DataFrame], gw: int) -> pd.DataFrame:
    """FPL points, minutes and goals conceded on the pitch in gameweek `gw` (a double
    already summed by FPL), per player, from a read that holds the gameweek (the season's
    last target gameweek)."""
    rows = final["fact_player_gw"]
    cols = ["player_id", "points", "minutes", "goals_conceded"]
    return rows.loc[rows.gw == gw, cols].reset_index(drop=True)


def evaluation_rows(frame: pd.DataFrame,
                    actual: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """The scored rows: `frame` (one row per snapshot player, with `started`) joined to the
    actual points, kept where the player is in the evaluation set; and the counts."""
    played = set(actual.player_id[actual.minutes > 0])
    m = frame.merge(actual, on="player_id", how="left", validate="one_to_one")
    in_set = m.player_id.isin(played) | m.started.astype(bool)
    rows = m[in_set & m.points.notna()].astype({"points": "int64", "minutes": "int64"})
    counts = {"in_set": int(in_set.sum()) + len(played - set(frame.player_id)),
              "scored": len(rows), "not_in_snapshot": len(played - set(frame.player_id)),
              "no_actual_row": int((in_set & m.points.isna()).sum())}
    return rows.reset_index(drop=True), counts


def model_column(out: pd.DataFrame, frame: pd.DataFrame, column: str) -> pd.Series:
    """The model's prediction for each `frame` player in `frame`'s target gameweek: `column`
    summed over his rows for that gameweek, one per fixture (the contract's Combine row).

    A player with no row scores 0 only if his club has no fixture (a blank). Raises
    `HarnessError` if a contract column or `column` is missing, or a player with a fixture has
    no row.
    """
    missing = [c for c in [*MODEL_COLUMNS, column] if c not in out.columns]
    if missing:
        raise HarnessError(f"model output lacks columns {missing}")
    gw = int(frame.gw.iloc[0])
    total = out[out.gw == gw].groupby("player_id")[column].sum()
    got = frame.player_id.map(total)
    gap = got.isna() & (frame.fixtures > 0)
    if gap.any():
        some = frame.player_id[gap].head(5).tolist()
        raise HarnessError(f"model output has no prediction for {int(gap.sum())} player(s) "
                           f"with a fixture in GW{gw}, e.g. {some}")
    return got.fillna(0.0).astype("float64").rename("model")
