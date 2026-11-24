"""The xP backtest's inputs: its one read path, the pre-deadline fields, club fixture counts,
the evaluation set's start rule and the baselines.

Every table comes from `read`, which looks `fpl.features.load_as_of` up at each call (so it
holds no reference the loader's test doubles would miss). The status, chance of playing,
price and `ep_next` the harness uses are read in one place, `pre_deadline_view`, so that the
holdout's pre-deadline view (phase 2 task 3) can replace it there.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import yaml

import fpl.features
from backtest.elo_data import HarnessError
from fpl.ingest import ROOT
from fpl.player_metrics import player_metrics

SCORING = ROOT / "config" / "scoring.yaml"
VIEW_COLUMNS = ["player_id", "team_id", "position", "price_tenths", "status", "chance_next",
                "ep_next"]


def long_min_minutes(path: Path = SCORING) -> int:
    """The minutes FPL's full appearance (and the 60-minute line) needs: config/scoring.yaml
    `appearance.long_min_minutes`."""
    return int(yaml.safe_load(path.read_text(encoding="utf-8"))["appearance"]["long_min_minutes"])


def read(season: str, as_of_gw: int, mode: str) -> dict[str, pd.DataFrame]:
    """The processed tables at as-of `as_of_gw`, through the point-in-time loader."""
    return fpl.features.load_as_of(season, as_of_gw, mode)


def pre_deadline_view(season: str, tables: dict[str, pd.DataFrame], s: dict) -> pd.DataFrame:
    """Each player's club, position, price, status, chance of playing and `ep_next` as known
    before the next deadline. The one place the harness reads them.

    `s["player_fields"]` is the switch. Task 3's pre-deadline view (upstream's last commit
    before each deadline) covers 2025/26 and 2026/27 (decided 2026-11-24); until it is wired in
    here, "snapshot" reads the as-of read's `dim_player` (the GW g-1 snapshot, whose late
    versions the timing audit reports) and refuses a holdout season, and "task3" refuses
    every season. Raises `HarnessError`.
    """
    source = s["player_fields"]
    if source == "task3":
        raise HarnessError(f"{season}: player_fields is task3, but task 3's pre-deadline view "
                           "isn't wired in yet")
    if source != "snapshot":
        raise HarnessError(f"player_fields must be snapshot or task3, got {source!r}")
    if season in s["holdout_seasons"]:
        raise HarnessError(f"{season} is a holdout season: its player fields must come from "
                           "the pre-deadline view (phase 2 task 3), which isn't wired in yet")
    return tables["dim_player"][VIEW_COLUMNS].copy()


def _sides(fx: pd.DataFrame) -> pd.DataFrame:
    """One row per club per fixture: team_id, match_id, gw, kickoff_utc."""
    cols = ["match_id", "gw", "kickoff_utc"]
    return pd.concat([fx[[*cols, side]].rename(columns={side: "team_id"})
                      for side in ("home_team_id", "away_team_id")]).dropna(subset=["team_id"])


def _prem(fx: pd.DataFrame, prem: str) -> pd.DataFrame:
    return fx[fx.tournament == prem]


def club_fixtures(fx: pd.DataFrame, gw: int, prem: str) -> pd.Series:
    """Premier League fixtures per club (`team_id`) in gameweek `gw`, from the schedule."""
    sides = _sides(_prem(fx, prem)[lambda d: d.gw == gw])
    return sides.groupby(sides.team_id.astype("int64")).size()


def _started_in(player: int, matches: list[str], window: set[str], starts: int,
                played: dict, complete: set[str]) -> str:
    """'yes', 'no' or 'ambiguous': whether one of a gameweek's `starts` was in `window`.

    With all the gameweek's matches in the window any start counts. Otherwise a start may be
    outside it: the player could have started a match only if he played in it (a match whose
    stats aren't loaded could have been either).
    """
    def could(m: str) -> bool:
        return m not in complete or played.get((player, m), 0) > 0

    outside = [m for m in matches if m not in window]
    if starts == 0:
        return "no"
    if not outside or starts > sum(could(m) for m in outside):
        return "yes"
    return "ambiguous" if any(could(m) for m in window) else "no"


def started_recently(tables: dict[str, pd.DataFrame], as_of_gw: int, prem: str,
                     n: int) -> pd.DataFrame:
    """Whether each `dim_player` player started one of his club's last `n` finished Premier
    League matches up to `as_of_gw` (the evaluation set's second clause, brief section 7).

    His club is his `dim_player` club. Starts come from `fact_player_gw`, in rows where he
    was at that club. A double gameweek cut by the window is resolved from match minutes in
    `fact_player_match`; what stays unresolved (he played both matches and started one) is
    `ambiguous` and counts as started. Returns `player_id`, `started`, `ambiguous`.
    """
    fx = tables["fact_fixture"]
    done = _prem(fx, prem)[lambda d: d.finished & (d.gw <= as_of_gw)]
    sides = _sides(done).sort_values("kickoff_utc", kind="stable")
    sides["team_id"] = sides.team_id.astype("int64")
    per_gw = sides.groupby(["team_id", "gw"]).match_id.apply(list).to_dict()
    window = sides.groupby("team_id").tail(n)
    in_win = window.groupby(["team_id", "gw"]).match_id.apply(set).to_dict()
    gws = tables["fact_player_gw"]
    starts = {(r.player_id, r.gw, r.team_id): r.starts
              for r in gws[gws.gw <= as_of_gw].itertuples()}
    pm = tables["fact_player_match"]
    played = {(r.player_id, r.match_id): r.minutes for r in pm.itertuples()}
    complete = set(fx.match_id[fx.stats_complete])
    rows = []
    for p, club in zip(tables["dim_player"].player_id, tables["dim_player"].team_id,
                       strict=True):
        found = [_started_in(p, per_gw[(c, w)], win, int(starts.get((p, w, c), 0)), played,
                             complete)
                 for (c, w), win in in_win.items() if c == club]
        rows.append({"player_id": p, "started": "yes" in found or "ambiguous" in found,
                     "ambiguous": "ambiguous" in found and "yes" not in found})
    return pd.DataFrame(rows, columns=["player_id", "started", "ambiguous"])


def _recent_gameweeks(tables: dict[str, pd.DataFrame], as_of_gw: int, prem: str,
                      n: int) -> pd.DataFrame:
    """Each player's last `n` gameweeks up to `as_of_gw` in which his club (that row's
    `team_id`) had a Premier League fixture, with the club's `fixtures` that gameweek. A blank
    gameweek is skipped; a double is one gameweek with 2 fixtures."""
    sides = _sides(_prem(tables["fact_fixture"], prem))
    counts = sides.groupby([sides.team_id.astype("int64"), "gw"]).size().rename("fixtures")
    gws = tables["fact_player_gw"]
    gws = gws[(gws.gw <= as_of_gw) & gws.team_id.notna()]
    rows = gws.join(counts, on=[gws.team_id.astype("int64"), "gw"], how="inner")
    rows = rows.sort_values(["player_id", "gw"], ascending=[True, False])
    return rows.groupby("player_id").head(n)


def last5_per_fixture(tables: dict[str, pd.DataFrame], as_of_gw: int, prem: str,
                      n: int) -> pd.Series:
    """Each player's FPL points per club fixture over his last `n` club-fixture gameweeks
    (`_recent_gameweeks`), so a double puts both fixtures in the denominator. Indexed by
    `player_id`; players with no such gameweek are absent."""
    last = _recent_gameweeks(tables, as_of_gw, prem, n).groupby("player_id")[
        ["points", "fixtures"]].sum()
    return (last.points / last.fixtures).rename("last5")


def p60_baseline(tables: dict[str, pd.DataFrame], as_of_gw: int, prem: str, n: int,
                 status: pd.Series, unavailable: Sequence[str], long_minutes: int) -> pd.Series:
    """The simple pre-deadline baseline for `p_60`: the share of a player's last `n`
    club-fixture gameweeks in which his FPL minutes reached `long_minutes` (60, from the
    scoring rules) per club fixture, and 0 if his
    `status` (indexed by `player_id`) is one of `unavailable`. Indexed like `status`; 0 with
    no history."""
    rows = _recent_gameweeks(tables, as_of_gw, prem, n)
    rate = (rows.minutes >= long_minutes * rows.fixtures).groupby(rows.player_id).mean()
    out = status.index.to_series().map(rate).fillna(0.0).astype("float64")
    return out.where(~status.isin(list(unavailable)), 0.0).rename("p60_base")


def baselines(season: str, as_of_gw: int, mode: str, *, s: dict, prem: str) -> pd.DataFrame:
    """Everything the harness takes from the as-of read for gameweek `as_of_gw` + 1.

    One row per player in the pre-deadline view, with `gw`, the view's fields, `fixtures`
    (his club's Premier League fixtures in the target gameweek), the three baselines:

    * `ep_next`: FPL's own figure from the view, as published (a null counts as 0, and
      `ep_next_null` marks it);
    * `last5`: `last5_per_fixture` times `fixtures` (0 with no history, and in a blank);
    * `ppg`: season points per appearance to date (players.csv `ppg`), times `fixtures`;

    and the evaluation set's start rule (`started`, `ambiguous`), FPL minutes over the last
    `weakest.minutes_window` club-fixture gameweeks (`recent_minutes`, for grouping) and the
    `p_60` baseline (`p60_base`). `s` is the `xp_backtest` settings.
    """
    tables = read(season, as_of_gw, mode)
    view = pre_deadline_view(season, tables, s)
    target = as_of_gw + 1
    fixtures = view.team_id.map(club_fixtures(tables["fact_fixture"], target, prem)).fillna(0)
    ppg = player_metrics(tables, as_of_gw, prem).set_index("player_id").ppg
    last5 = last5_per_fixture(tables, as_of_gw, prem, int(s["baselines"]["last_n"]))
    started = started_recently(tables, as_of_gw, prem,
                               int(s["evaluation_set"]["previous_matches"])).set_index("player_id")
    recent = _recent_gameweeks(tables, as_of_gw, prem, int(s["weakest"]["minutes_window"]))
    p60 = s["diagnostics"]["p60_baseline"]
    status = view.set_index("player_id").status
    return view.assign(
        gw=target, fixtures=fixtures.astype("int64"),
        ep_next=view.ep_next.fillna(0.0).astype("float64"),
        last5=view.player_id.map(last5).fillna(0.0) * fixtures,
        ppg=view.player_id.map(ppg).fillna(0.0) * fixtures,
        ep_next_null=view.ep_next.isna(),
        started=view.player_id.map(started.started).fillna(False).astype(bool),
        ambiguous=view.player_id.map(started.ambiguous).fillna(False).astype(bool),
        recent_minutes=view.player_id.map(recent.groupby("player_id").minutes.sum())
        .fillna(0).astype("int64"),
        p60_base=view.player_id.map(p60_baseline(tables, as_of_gw, prem, int(p60["window"]),
                                                 status, p60["unavailable"],
                                                 long_min_minutes())),
    )
