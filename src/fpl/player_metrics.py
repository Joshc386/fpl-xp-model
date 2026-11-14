"""players.csv: one row per player, season to date through the as-of gameweek (CONTEXT.md).

Pure over the processed tables (from `load_as_of`). Totals come from `fact_player_gw`, which
holds a gameweek row only once the player's club has finished all its fixtures that gameweek.
xG and xA come from complete Premier League matches in `fact_player_match`. The price changes
and transfers come from `dim_player` (never null).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from fpl.frames import checked_merge
from fpl.output_schema import output_columns
from fpl.validate import ValidationError, key_problems

log = logging.getLogger(__name__)

MINUTES_PER_MATCH = 90


def _per90(total: pd.Series, minutes: pd.Series) -> pd.Series:
    """`total` per 90 minutes; 0 where there are no minutes."""
    return (total / minutes.where(minutes > 0) * MINUTES_PER_MATCH).fillna(0.0)


def _gw_totals(gw: pd.DataFrame) -> pd.DataFrame:
    """Season-to-date FPL minutes, starts, points and defensive-contribution counts."""
    return gw.groupby("player_id").agg(
        minutes=("minutes", "sum"), starts=("starts", "sum"), total_points=("points", "sum"),
        dc=("defensive_contribution", "sum"),
    )


def _complete_prem(tables: dict[str, pd.DataFrame], as_of_gw: int, prem_tag: str) -> pd.DataFrame:
    """Complete Premier League matches up to the as-of gameweek: `match_id` and `gw`."""
    fx = tables["fact_fixture"]
    return fx[(fx.tournament == prem_tag) & fx.stats_complete & (fx.gw <= as_of_gw)][
        ["match_id", "gw"]]


def _match_totals(tables: dict[str, pd.DataFrame], as_of_gw: int, prem_tag: str) -> pd.DataFrame:
    """Per player over complete Premier League matches: minutes, xG and xA."""
    ok = _complete_prem(tables, as_of_gw, prem_tag)
    pm = tables["fact_player_match"]
    return pm[pm.match_id.isin(ok.match_id)].groupby("player_id").agg(
        match_minutes=("minutes", "sum"), xg=("xg", "sum"), xa=("xa", "sum"),
    )


def _appearances(tables: dict[str, pd.DataFrame], gw: pd.DataFrame, as_of_gw: int,
                 prem_tag: str) -> pd.Series:
    """Appearances per player, over the gameweeks in which he has a released `gw` row.

    One window for points and appearances: a gameweek counts only once his club has finished
    all its fixtures (the row exists). In each, the larger of his appearances in complete
    Premier League matches (a double gameweek can give two) and 1 if FPL credits him minutes.
    The 1 covers a single finished match that is not complete, or a dropped player-match row.
    It undercounts a double gameweek with both matches finished but only one complete: the
    gameweek counts once, so a player who played both gets 4.5 where the definition gives
    3.6, until the second match's stats load. Accepted as transient.
    """
    ok = _complete_prem(tables, as_of_gw, prem_tag)
    pm = tables["fact_player_match"]
    pm = pm[pm.match_id.isin(ok.match_id) & (pm.minutes > 0)]
    pm = checked_merge(
        pm[["player_id", "match_id"]], ok, on="match_id", how="inner",
        validate="many_to_one", name="fact_player_match -> fact_fixture",
    )
    matches = pm.groupby(["player_id", "gw"]).size().rename("matches")
    rows = gw[["player_id", "gw", "minutes"]].join(matches, on=["player_id", "gw"])
    credited = np.maximum(rows.matches.fillna(0), (rows.minutes > 0).astype("int64"))
    return credited.groupby(rows.player_id).sum().astype("int64")


def player_metrics(tables: dict[str, pd.DataFrame], as_of_gw: int, prem_tag: str) -> pd.DataFrame:
    """The players.csv rows (every contract column), by player_id.

    Raises `ValidationError` on duplicate gameweek rows and `JoinError` if a player's club is
    not in `dim_team`.
    """
    gw = tables["fact_player_gw"]
    gw = gw[gw.gw <= as_of_gw]
    problems = key_problems(gw, ["player_id", "gw"], "fact_player_gw")
    if problems:
        raise ValidationError(problems)
    dp = checked_merge(
        tables["dim_player"], tables["dim_team"][["team_id", "short_name"]], on="team_id",
        how="inner", validate="many_to_one", name="dim_player -> dim_team",
    ).set_index("player_id").sort_index()
    totals = _gw_totals(gw).reindex(dp.index, fill_value=0)
    matches = _match_totals(tables, as_of_gw, prem_tag).reindex(dp.index, fill_value=0)
    apps = _appearances(tables, gw, as_of_gw, prem_tag).reindex(dp.index, fill_value=0)
    out = pd.DataFrame({
        "web_name": dp.web_name, "team": dp.short_name, "position": dp.position,
        "price_m": (dp.price_tenths / 10).round(1), "status": dp.status,
        "chance_next": dp.chance_next, "news": dp.news, "selected_pct": dp.selected_pct,
        "minutes": totals.minutes, "starts": totals.starts, "total_points": totals.total_points,
        "ppg": (totals.total_points / apps.where(apps > 0)).fillna(0.0),
        "xg90": _per90(matches.xg, matches.match_minutes),
        "xa90": _per90(matches.xa, matches.match_minutes),
        "dc90": _per90(totals.dc, totals.minutes),
        "pen_taker": (dp.pen_order == 1).fillna(False).astype(bool),
        "net_transfers_gw": dp.transfers_in_gw - dp.transfers_out_gw,
        "price_change_gw": (dp.price_change_gw_tenths / 10).round(1),
        "price_change_start": (dp.price_change_start_tenths / 10).round(1),
    })
    out = out.astype({"minutes": "int64", "starts": "int64", "total_points": "int64"})
    return out.reset_index()[output_columns("players")]
