"""The xP backtest's inputs on hand-built tables: the evaluation-set start rule, club fixture
counts, the last-5 baseline and the one read point for the pre-deadline fields."""

from __future__ import annotations

import pandas as pd
import pytest
from backtest.elo_data import HarnessError
from backtest.xp_inputs import (
    club_fixtures,
    last5_per_fixture,
    p60_baseline,
    pre_deadline_view,
    started_recently,
)

PREM = "prem"


START = pd.Timestamp("2025-08-01T12:00:00Z")


def fixtures(rows: list[tuple[str, int, int, int, bool]]) -> pd.DataFrame:
    """(match_id, gw, home, away, finished); kickoffs in list order, a day apart."""
    return pd.DataFrame([{
        "match_id": m, "gw": gw, "home_team_id": h, "away_team_id": a, "finished": fin,
        "stats_complete": fin, "tournament": PREM,
        "kickoff_utc": f"{START + pd.Timedelta(days=i):%Y-%m-%dT%H:%M:%SZ}",
    } for i, (m, gw, h, a, fin) in enumerate(rows)])


def gw_rows(rows: list[tuple[int, int, int, int, int, int]]) -> pd.DataFrame:
    """(player_id, team_id, gw, points, minutes, starts)."""
    return pd.DataFrame(rows, columns=["player_id", "team_id", "gw", "points", "minutes",
                                       "starts"])


def players(rows: list[tuple[int, int]]) -> pd.DataFrame:
    return pd.DataFrame([{"player_id": p, "team_id": t, "position": "MID", "price_tenths": 50,
                          "status": "a", "chance_next": None, "ep_next": 1.0}
                         for p, t in rows])


# Club 1: GW1 m1, GW2 m2, GW3 blank, GW4 a double (m4a, m4b); GW5 m5 is the target.
FX = fixtures([("m1", 1, 1, 2, True), ("m2", 2, 1, 3, True), ("m3", 3, 2, 3, True),
               ("m4a", 4, 1, 2, True), ("m4b", 4, 3, 1, True), ("m5", 5, 1, 3, False),
               ("m5b", 5, 2, 3, False)])


def test_club_fixtures_counts_premier_league_fixtures_in_a_gameweek() -> None:
    fx = pd.concat([FX, FX.iloc[[0]].assign(match_id="cup", gw=4, tournament="efl-cup")])
    got = club_fixtures(fx, 4, PREM)
    assert got.to_dict() == {1: 2, 2: 1, 3: 1}
    assert club_fixtures(fx, 3, PREM).get(1, 0) == 0


def test_started_recently_uses_the_clubs_last_three_matches() -> None:
    # Club 1's last three finished matches up to as-of 4: m4b, m4a and m2 (GW3 is a blank).
    tables = {
        "fact_fixture": FX,
        "dim_player": players([(1, 1), (2, 1), (3, 1), (5, 1)]),
        "fact_player_gw": gw_rows([
            (1, 1, 2, 2, 90, 1),            # started m2: in
            (2, 1, 4, 6, 120, 1),           # started one of the GW4 double: in
            (3, 1, 1, 2, 90, 1),            # started m1 only, outside the window: out
            (5, 3, 2, 2, 90, 1),            # started GW2 for club 3 before moving: out
        ]),
        "fact_player_match": pd.DataFrame(columns=["player_id", "match_id", "minutes"]),
    }
    got = started_recently(tables, 4, PREM, 3).set_index("player_id")
    assert got.started.to_dict() == {1: True, 2: True, 3: False, 5: False}
    assert not got.ambiguous.any()


def test_a_double_gameweek_cut_by_the_window_is_resolved_from_match_minutes() -> None:
    # Club 1: GW1, a GW2 double (d1 then d2), GW3, GW4. At as-of 4 the window is m4, m3, d2.
    fx = fixtures([("m1", 1, 1, 2, True), ("d1", 2, 1, 3, True), ("d2", 2, 2, 1, True),
                   ("m3", 3, 1, 3, True), ("m4", 4, 1, 2, True)])
    pm = pd.DataFrame([(1, "d1", 90), (1, "d2", 0),      # played d1 only: started d1, out
                       (2, "d1", 0), (2, "d2", 90),      # played d2 only: started d2, in
                       (3, "d1", 90), (3, "d2", 30)],    # played both, one start: ambiguous
                      columns=["player_id", "match_id", "minutes"])
    tables = {"fact_fixture": fx, "dim_player": players([(1, 1), (2, 1), (3, 1)]),
              "fact_player_gw": gw_rows([(p, 1, 2, 2, 90, 1) for p in (1, 2, 3)]),
              "fact_player_match": pm}
    got = started_recently(tables, 4, PREM, 3).set_index("player_id")
    assert got.started.to_dict() == {1: False, 2: True, 3: True}
    assert got.ambiguous.to_dict() == {1: False, 2: False, 3: True}


def test_last5_is_points_per_club_fixture_over_the_last_five_fixture_gameweeks() -> None:
    rows = [(1, 1, gw, pts, 90, 1) for gw, pts in [(1, 2), (2, 4), (3, 0), (4, 6)]]
    # GW3 is club 1's blank and is skipped; GW4 is a double (2 fixtures).
    rows += [(9, 1, gw, 1, 90, 1) for gw in range(1, 5)]
    tables = {"fact_fixture": FX, "fact_player_gw": gw_rows(rows)}
    got = last5_per_fixture(tables, 4, PREM, 5)
    assert got[1] == pytest.approx((2 + 4 + 6) / 4)
    assert last5_per_fixture(tables, 4, PREM, 1)[1] == pytest.approx(3.0)
    assert last5_per_fixture(tables, 1, PREM, 5)[1] == pytest.approx(2.0)


VIEW_SETTINGS = {"holdout_seasons": ["2026-2027"], "player_fields": "snapshot"}


def test_the_pre_deadline_view_reads_the_snapshot_and_refuses_a_holdout_season() -> None:
    dp = players([(1, 1)]).assign(web_name="x", news=None)
    view = pre_deadline_view("2025-2026", {"dim_player": dp}, VIEW_SETTINGS)
    assert list(view.columns) == ["player_id", "team_id", "position", "price_tenths", "status",
                                  "chance_next", "ep_next"]
    with pytest.raises(HarnessError, match="pre-deadline view"):
        pre_deadline_view("2026-2027", {"dim_player": dp}, VIEW_SETTINGS)


def test_switched_to_task_3s_view_both_seasons_wait_for_it() -> None:
    dp = players([(1, 1)]).assign(web_name="x", news=None)
    s = {**VIEW_SETTINGS, "player_fields": "task3"}
    for season in ("2025-2026", "2026-2027"):
        with pytest.raises(HarnessError, match="task 3"):
            pre_deadline_view(season, {"dim_player": dp}, s)
    with pytest.raises(HarnessError, match="player_fields"):
        pre_deadline_view("2025-2026", {"dim_player": dp}, {**s, "player_fields": "master"})


def test_p60_baseline_is_the_recent_60_minute_rate_with_the_availability_override() -> None:
    # Club 1 has fixtures in GW1, GW2 and a GW4 double; GW3 is its blank.
    rows = [(1, 1, 1, 2, 90, 1), (1, 1, 2, 2, 45, 1), (1, 1, 3, 0, 0, 0), (1, 1, 4, 4, 130, 2),
            (2, 1, 4, 4, 100, 2), (3, 1, 2, 2, 90, 1)]
    tables = {"fact_fixture": FX, "fact_player_gw": gw_rows(rows)}
    status = pd.Series({1: "a", 2: "d", 3: "i"})
    got = p60_baseline(tables, 4, PREM, 5, status, ["i", "s", "u", "n"], 60)
    assert p60_baseline(tables, 4, PREM, 5, status, [], 45)[1] == pytest.approx(1.0)
    # Player 1: GW1 yes, GW2 no (45), GW4 yes (130 >= 2 x 60): 2 of 3.
    assert got[1] == pytest.approx(2 / 3)
    assert got[2] == pytest.approx(0.0)   # 100 in a double is under 60 a fixture
    assert got[3] == 0.0                  # injured: 0 whatever his history
