"""fact_player_spell: when each player who played was on the pitch.

Pure over DataFrames. A spell is [`spell_start`, `spell_end`] on the `fpl.shots.shot_clock`
scale, both ends included; a null end is on until the final whistle. A player's minutes
inside 90 are checked against `minutes_played`, and a spell that contradicts them is repaired
(docs/data_contract.md, `fact_player_spell`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from fpl.frames import JoinError, checked_merge
from fpl.schema import column_names
from fpl.shots import shot_clock

if TYPE_CHECKING:
    from fpl.ingest import RawSeason

SOURCES = ("incidents", "playermatchstats")
# Incident card types that end a player's match.
DISMISSALS = ("red", "yellowRed")


def on_pitch(start: pd.Series, end: pd.Series, clock: float | pd.Series) -> pd.Series:
    """True where `start` <= `clock` <= `end`, with a null `end` meaning the whistle."""
    return (start <= clock) & (end.isna() | (clock <= end))


def minutes_inside_90(start: pd.Series, end: pd.Series) -> pd.Series:
    """Minutes on the pitch inside 90, the scale of FPL's minutes (a null end is the whistle)."""
    return (end.fillna(90.0).clip(upper=90.0) - start.clip(upper=90.0)).clip(lower=0.0)


def _unique(df: pd.DataFrame, name: str) -> pd.DataFrame:
    if df.duplicated(["match_id", "player_id"]).any():
        raise JoinError(f"{name}: more than one row for a player in a match")
    return df


def _from_playermatchstats(base: pd.DataFrame, pms: pd.DataFrame) -> pd.DataFrame:
    """Start from `start_min`; the end is `finish_min` below 90, else the whistle."""
    cols = pms[["player_id", "match_id", "start_min", "finish_min"]].assign(_has=True)
    df = checked_merge(base, cols, on=["player_id", "match_id"], how="left",
                       validate="one_to_one", name="spells: fact_player_match -> playermatchstats")
    if df["_has"].isna().any():
        raise JoinError("spells: a fact_player_match row has no playermatchstats row")
    return df.assign(
        spell_start=df.start_min.fillna(0.0),
        spell_end=df.finish_min.where(df.finish_min < 90),
    )


def _from_incidents(
    base: pd.DataFrame, incidents: pd.DataFrame, pms: pd.DataFrame | None
) -> pd.DataFrame:
    """Start at the substitution that brought him on; end at the one that took him off, or a
    red or second yellow card.

    `end_given` marks an end an incident gave, which is never repaired. `start_min` (from `pms`,
    null if there is none) is kept for a substitute with no "on" incident.
    """
    inc = incidents[incidents.match_id.isin(base.match_id)]
    inc = inc.assign(clock=shot_clock(inc.minute, inc.added_time))
    sub = inc[inc.incident_type == "substitution"]
    on = _unique(sub.dropna(subset=["secondary_player_id"]).drop(columns="player_id").rename(
        columns={"secondary_player_id": "player_id", "clock": "on"})[
        ["match_id", "player_id", "on"]], "incidents (substitutions on)")
    off = _unique(sub.dropna(subset=["player_id"]).rename(columns={"clock": "off"})[
        ["match_id", "player_id", "off"]], "incidents (substitutions off)")
    sent = inc[(inc.incident_type == "card") & inc.card_type.isin(DISMISSALS)]
    sent = _unique(sent.dropna(subset=["player_id"]).rename(columns={"clock": "sent_off"})[
        ["match_id", "player_id", "sent_off"]], "incidents (dismissals)")
    df = base
    for part in (on, off, sent):
        df = checked_merge(df, part, on=["player_id", "match_id"], how="left",
                           validate="one_to_one", name="spells: fact_player_match -> incidents")
    starts = pms[["player_id", "match_id", "start_min"]] if pms is not None else pd.DataFrame({
        "player_id": pd.Series(dtype="float64"), "match_id": pd.Series(dtype="str"),
        "start_min": pd.Series(dtype="float64")})
    df = checked_merge(df, starts.astype({"player_id": "int64"}), on=["player_id", "match_id"],
                       how="left", validate="one_to_one",
                       name="spells: fact_player_match -> playermatchstats")
    end = df[["off", "sent_off"]].min(axis=1)
    return df.assign(spell_start=df.on.fillna(0.0), spell_end=end, end_given=end.notna(),
                     has_on=df.on.notna())


def _substitutes_without_a_start(df: pd.DataFrame, tolerance: float) -> tuple[pd.DataFrame, int]:
    """Give a substitute with no "on" incident his `start_min`, or drop him; return the count.

    Such a player has no "on" incident and a spell from kickoff that contradicts his minutes.
    If his `start_min` gives a spell that fits his minutes within `tolerance`, it is his start.
    Otherwise, with no incident end, his start is unknown, so his spell is dropped, never
    guessed and never repaired; with an incident end (a starter sent off, say) he keeps his
    start of 0.
    """
    gap = (minutes_inside_90(df.spell_start, df.spell_end) - df.minutes).abs()
    lost = ~df.has_on & (gap > tolerance)
    # A `start_min` of 0 or null never fits: it gives the same gap that made him lost.
    fits = (minutes_inside_90(df.start_min, df.spell_end) - df.minutes).abs() <= tolerance
    known = lost & fits
    df = df.assign(spell_start=df.spell_start.where(~known, df.start_min))
    unknown = lost & ~known & ~df.end_given
    return df[~unknown], int(unknown.sum())


def build_fact_player_spell(
    pmatch: pd.DataFrame, pms: pd.DataFrame | None, incidents: pd.DataFrame | None,
    source: str, tolerance: float,
) -> tuple[pd.DataFrame, int]:
    """One spell per `pmatch` row with minutes > 0, so an unused substitute has none.

    `pmatch` is the fact_player_match rows of the Premier League complete matches; `source`
    is the season's `spell_source`. Where the spell's minutes inside 90 differ from `minutes`
    by more than `tolerance`, the end becomes start + `minutes` and `spell_repaired` is true,
    except where an incident gave the end (then the mismatch is only counted, by the checks).
    A substitute of an `incidents` season with no "on" incident takes his start from
    `start_min` where it fits his minutes; otherwise his spell is dropped, unless an incident
    gave his end, when his start stays 0. Returns the table and the number of spells dropped
    for that reason (`spell_start_unknown`).
    """
    if source not in SOURCES:
        raise ValueError(f"spell_source must be one of {SOURCES}, got {source!r}")
    base = pmatch.loc[pmatch.minutes > 0, ["player_id", "team_id", "match_id", "minutes"]]
    base = base.reset_index(drop=True)
    unknown = 0
    if source == "incidents":
        if incidents is None:
            raise ValueError("spell_source incidents needs the incidents frame")
        df, unknown = _substitutes_without_a_start(
            _from_incidents(base, incidents, pms), tolerance)
    else:
        if pms is None:
            raise ValueError("spell_source playermatchstats needs the playermatchstats frame")
        df = _from_playermatchstats(base, pms).assign(end_given=False)
    gap = (minutes_inside_90(df.spell_start, df.spell_end) - df.minutes).abs()
    repaired = (gap > tolerance) & ~df.end_given
    end = df.spell_end.where(~repaired, df.spell_start + df.minutes)
    out = df.assign(spell_end=end.astype("float64"), spell_repaired=repaired.to_numpy())
    out["spell_start"] = out.spell_start.astype("float64")
    return out[column_names("fact_player_spell")].reset_index(drop=True), unknown


def build_spells(
    pmatch: pd.DataFrame, fixture: pd.DataFrame, raw: RawSeason, scfg: dict, cfg: dict
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_player_spell from the Premier League rows of `pmatch`; the rows dropped by reason.

    Rows from cup and European matches, rows with no minutes (unused substitutes) and
    substitutes whose start is unknown (`spell_start_unknown`) are dropped and counted.
    """
    tour = checked_merge(
        pmatch, fixture[["match_id", "tournament"]], on="match_id", how="left",
        validate="many_to_one", name="fact_player_match -> fact_fixture",
    )
    prem = tour.tournament == cfg["premier_league_tag"]
    dropped = {"match_not_premier_league": int((~prem).sum()),
               "no_minutes": int((prem & (tour.minutes <= 0)).sum())}
    spells, unknown = build_fact_player_spell(
        tour[prem].drop(columns="tournament"), raw.playermatchstats, raw.incidents,
        scfg["spell_source"], cfg["spells"]["minutes_tolerance"],
    )
    dropped["spell_start_unknown"] = unknown
    return spells, dropped
