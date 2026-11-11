"""Live mode: overlay current-state fields from the master playerstats onto dim_player.

Pure over DataFrames; the master file is read by `master.read_master_state`. Only status,
news, chance of playing and price are overlaid; every other column stays as the gameweek
snapshot has it.
"""

from __future__ import annotations

import logging

import pandas as pd

from fpl.frames import tenths, to_int
from fpl.validate import ValidationError

log = logging.getLogger(__name__)

OVERLAID = ["status", "news", "chance_next", "price_tenths"]


def _check_master(master: pd.DataFrame, price_bounds: list[float]) -> list[str]:
    """Problems with the master playerstats rows: duplicate keys, bad status or price."""
    out = []
    dups = int(master.duplicated(["id", "gw"]).sum())
    if dups:
        out.append(f"master playerstats: {dups} duplicate (id, gw) keys")
    if master[["id", "gw"]].isna().any().any():
        out.append("master playerstats: null id or gw")
    if master.status.isna().any():
        out.append(f"master playerstats.status: {int(master.status.isna().sum())} null values")
    lo, hi = price_bounds
    bad = int((~master.now_cost.between(lo, hi)).sum())
    if bad:
        out.append(f"master playerstats.now_cost: {bad} values null or outside [{lo}, {hi}] GBP m")
    return out


def overlay_current_state(
    dim_player: pd.DataFrame, master: pd.DataFrame, price_bounds: list[float]
) -> pd.DataFrame:
    """dim_player with status, news, chance_next and price_tenths from each player's latest
    master row (highest `gw`).

    A player with no master row keeps his snapshot values (logged). Master rows for players
    not in dim_player are ignored. Raises `ValidationError` on a malformed master file.
    """
    problems = _check_master(master, price_bounds)
    if problems:
        raise ValidationError(problems)
    ids = dim_player["player_id"]
    if ids.duplicated().any():
        raise ValidationError(["dim_player: duplicate player_id before the overlay"])
    latest = master.sort_values("gw").drop_duplicates("id", keep="last")
    state = pd.DataFrame({
        "status": latest.status, "news": latest.news,
        "chance_next": to_int(latest.chance_of_playing_next_round, "chance", nullable=True),
        "price_tenths": tenths(latest.now_cost, "now_cost"),
    }).set_axis(to_int(latest.id, "id"))
    seen = ids.isin(state.index)
    if not seen.all():
        log.warning("live overlay: %d players have no master row; snapshot values kept",
                    int((~seen).sum()))
    out = dim_player.copy()
    for col in OVERLAID:
        out.loc[seen, col] = state[col].loc[ids[seen]].astype(out[col].dtype).array
    return out
