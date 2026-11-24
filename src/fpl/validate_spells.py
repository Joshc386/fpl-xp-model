"""Checks on fact_shot and fact_player_spell that run on every read (docs/data_contract.md).

They use only the shot, spell, player-match, player-gameweek and fixture tables, so nothing in
them depends on the result and xG columns of matches.csv. That keeps them valid on the
validator's perturbation copy, which corrupts those columns. The comparisons with matches.csv
are in `fpl.matchcheck`, which only the pipeline build runs.

Hard checks return a problem whatever the count. Counted checks return their count by reason,
and a problem only when it is over its cap (`spells.max_*` in config/pipeline.yaml: a share of
the rows compared, but never less than `always_allowed`).
"""

from __future__ import annotations

import pandas as pd

from fpl.frames import checked_merge
from fpl.spells import minutes_inside_90, on_pitch

STARTERS = 11


def _cap(rule: dict, n: int) -> float:
    return max(rule["share"] * n, rule["always_allowed"])


def _over(label: str, count: int, n: int, rule: dict) -> list[str]:
    cap = _cap(rule, n)
    if count > cap:
        return [f"{label}: {count} of {n} over the cap of {cap:.1f}"]
    return []


def _shot_problems(shot: pd.DataFrame, fixture: pd.DataFrame, cfg: dict) -> list[str]:
    """Hard checks on fact_shot: ranges, known values, and shots for every complete match."""
    out = []
    bad_xg = int((~shot.xg.between(0, 1)).sum())
    if bad_xg:
        out.append(f"fact_shot.xg: {bad_xg} values outside [0, 1]")
    lo, hi = cfg["shots"]["minute_range"]
    bad_minute = int((~shot.minute.between(lo, hi)).sum())
    if bad_minute:
        out.append(f"fact_shot.minute: {bad_minute} values outside [{lo}, {hi}]")
    for col, known in (("situation", cfg["shots"]["situations"]),
                       ("outcome", cfg["shots"]["outcomes"])):
        new = sorted(set(shot[col]) - set(known))
        if new:
            out.append(f"fact_shot.{col}: unknown value(s) {new}; a new upstream value needs "
                       "a decision before it is built")
    prem = fixture[(fixture.tournament == cfg["premier_league_tag"]) & fixture.stats_complete]
    lacking = sorted(set(prem.match_id) - set(shot.match_id))
    if lacking:
        out.append(f"fact_shot: {len(lacking)} complete matches have no shot rows: {lacking[:5]}")
    return out


def _club_gameweeks(fixture: pd.DataFrame, prem_tag: str) -> pd.DataFrame:
    """(team_id, gw, club_complete): True where every Premier League fixture of the club in the
    gameweek is complete."""
    prem = fixture[fixture.tournament == prem_tag]
    sides = pd.concat([
        pd.DataFrame({"team_id": prem[f"{side}_team_id"], "gw": prem.gw,
                      "club_complete": prem.stats_complete})
        for side in ("home", "away")
    ])
    return sides.groupby(["team_id", "gw"], as_index=False).club_complete.all()


def _spell_gameweeks(spell: pd.DataFrame, fixture: pd.DataFrame) -> pd.DataFrame:
    """One row per player-gameweek with a spell: the spells' minutes inside 90, summed."""
    df = checked_merge(spell, fixture[["match_id", "gw"]], on="match_id", how="left",
                       validate="many_to_one", name="spells -> fact_fixture")
    df = df.assign(reg=minutes_inside_90(df.spell_start, df.spell_end))
    return df.groupby(["player_id", "gw"], as_index=False).reg.sum().assign(_spell=True)


def _spell_problems(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Hard checks: no spell for an unused substitute, or for a player with no FPL minutes."""
    spell, pmatch, gw = tables["fact_player_spell"], tables["fact_player_match"], tables[
        "fact_player_gw"]
    out = []
    played = pmatch[["player_id", "match_id", "minutes"]]
    df = checked_merge(spell, played, on=["player_id", "match_id"], how="left",
                       validate="one_to_one", name="spells -> fact_player_match")
    unused = int((df.minutes.fillna(0) <= 0).sum())
    if unused:
        out.append(f"fact_player_spell: {unused} spells for an unused substitute (no minutes)")
    per = _spell_gameweeks(spell, tables["fact_fixture"])
    fpl = checked_merge(
        gw[["player_id", "gw", "minutes"]], per, on=["player_id", "gw"], how="left",
        validate="one_to_one", name="fact_player_gw -> spells")
    none = int((fpl["_spell"].notna() & (fpl.minutes == 0)).sum())
    if none:
        out.append(f"fact_player_spell: {none} player-gameweeks with a spell but FPL minutes 0")
    return out


def _fpl_minutes(
    tables: dict[str, pd.DataFrame], cfg: dict
) -> tuple[dict[str, int], dict[str, int]]:
    """FPL gameweek minutes against the spells, where every fixture of the club is complete.

    Returns the counts (`fpl_minutes_mismatch`, `fpl_minutes_without_spell`) and the number
    of rows each is counted among.
    """
    fixture, gw = tables["fact_fixture"], tables["fact_player_gw"]
    clubs = _club_gameweeks(fixture, cfg["premier_league_tag"])
    fpl = checked_merge(
        gw[["player_id", "team_id", "gw", "minutes"]].astype({"team_id": "float64"}),
        clubs.astype({"team_id": "float64"}), on=["team_id", "gw"], how="left",
        validate="many_to_one", name="fact_player_gw -> club gameweeks")
    fpl = checked_merge(
        fpl[fpl.club_complete.fillna(False).astype(bool)], _spell_gameweeks(
            tables["fact_player_spell"], fixture), on=["player_id", "gw"], how="left",
        validate="one_to_one", name="fact_player_gw -> spells")
    has = fpl["_spell"].notna()
    tol = cfg["spells"]["gw_minutes_tolerance"]
    mismatch = has & ((fpl.reg - fpl.minutes).abs() > tol)
    without = ~has & (fpl.minutes > 0)
    counts = {"fpl_minutes_mismatch": int(mismatch.sum()),
              "fpl_minutes_without_spell": int(without.sum())}
    rows = {"fpl_minutes_mismatch": int(has.sum()),
            "fpl_minutes_without_spell": int((fpl.minutes > 0).sum())}
    return counts, rows


def _starters(tables: dict[str, pd.DataFrame], prem_tag: str) -> tuple[int, int, int]:
    """Clubs with more than 11 and fewer than 11 starters, and the clubs counted."""
    fixture = tables["fact_fixture"]
    done = fixture[(fixture.tournament == prem_tag) & fixture.stats_complete]
    sides = pd.concat([
        pd.DataFrame({"match_id": done.match_id, "team_id": done[f"{side}_team_id"]})
        for side in ("home", "away")
    ])
    spell = tables["fact_player_spell"]
    n = spell[spell.spell_start == 0].groupby(["match_id", "team_id"]).size().rename("n")
    got = checked_merge(sides, n.reset_index(), on=["match_id", "team_id"], how="left",
                        validate="one_to_one", name="club sides -> spells").n.fillna(0)
    return int((got > STARTERS).sum()), int((got < STARTERS).sum()), len(sides)


def _shooters_off_pitch(shot: pd.DataFrame, spell: pd.DataFrame) -> int:
    """Shots whose shooter has a spell in the match that does not cover the shot's clock."""
    named = shot[shot.player_id.notna()][["player_id", "match_id", "clock"]]
    df = checked_merge(
        named.astype({"player_id": "int64"}), spell[["player_id", "match_id", "spell_start",
                                                      "spell_end"]],
        on=["player_id", "match_id"], how="left", validate="many_to_one",
        name="fact_shot -> spells")
    has = df.spell_start.notna()
    return int((has & ~on_pitch(df.spell_start, df.spell_end, df.clock)).sum())


def _shooters_without_minutes(shot: pd.DataFrame, pmatch: pd.DataFrame) -> int:
    """Shots whose shooter has a player-match row in the match with 0 minutes."""
    named = shot[shot.player_id.notna()][["player_id", "match_id"]]
    df = checked_merge(
        named.astype({"player_id": "int64"}), pmatch[["player_id", "match_id", "minutes"]],
        on=["player_id", "match_id"], how="left", validate="many_to_one",
        name="fact_shot -> fact_player_match")
    return int((df.minutes == 0).sum())


def check_shots_and_spells(
    tables: dict[str, pd.DataFrame], cfg: dict
) -> tuple[list[str], dict[str, int]]:
    """Run the per-read checks; return the problems and every counted reason's count."""
    rules, prem = cfg["spells"], cfg["premier_league_tag"]
    shot, spell = tables["fact_shot"], tables["fact_player_spell"]
    problems = _shot_problems(shot, tables["fact_fixture"], cfg) + _spell_problems(tables)
    minutes, rows = _fpl_minutes(tables, cfg)
    over, under, sides = _starters(tables, prem)
    counts = {
        "spell_repaired": int(spell.spell_repaired.sum()), **minutes,
        "starters_over_11": over, "starters_under_11": under,
        "shooter_off_pitch": _shooters_off_pitch(shot, spell),
        "shooter_no_minutes": _shooters_without_minutes(shot, tables["fact_player_match"]),
    }
    problems += _over("fact_player_spell: spell_repaired", counts["spell_repaired"], len(spell),
                      rules["max_repaired"])
    for reason, rule in (("fpl_minutes_mismatch", "max_fpl_minutes_mismatch"),
                         ("fpl_minutes_without_spell", "max_fpl_minutes_without_spell")):
        problems += _over(f"player-gameweeks: {reason}", counts[reason], rows[reason],
                          rules[rule])
    problems += _over("clubs per match: starters_over_11 + starters_under_11", over + under,
                      sides, rules["max_starters_not_11"])
    for reason in ("shooter_off_pitch", "shooter_no_minutes"):  # one cap for both
        problems += _over(f"fact_shot: {reason}", counts[reason], len(shot),
                          rules["max_shooter_off_pitch"])
    return problems, counts
