"""The Elo check's data layer on small hand-built tables: skips, joins, pairs, pool, stability."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from backtest.elo_data import (
    HarnessError,
    SkipLog,
    UnexpectedReadError,
    baseline_pool,
    implied_coefficients,
    match_results,
    rating_pairs,
    read_stability,
    score_gameweek,
    team_results,
)

PREM = "prem"


class SeedError(ValueError):
    pass


class SampleError(ValueError):
    pass


def fixture(match_id: str, gw: int, home: int, away: int, hg: int | None, ag: int | None,
            kick: str = "2025-08-16T14:00:00Z", tournament: str = PREM,
            elo: tuple[float, float] = (1500.0, 1500.0), season: str = "S1") -> dict:
    done = hg is not None
    return {"match_id": match_id, "season": season, "gw": gw, "kickoff_utc": kick,
            "tournament": tournament, "home_team_id": home, "away_team_id": away,
            "home_upstream_elo": elo[0], "away_upstream_elo": elo[1], "finished": done,
            "home_goals": hg, "away_goals": ag}


def fixtures(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.astype({"home_team_id": "Int64", "away_team_id": "Int64", "home_goals": "Int64",
                      "away_goals": "Int64"})


FX = fixtures([
    fixture("a", 1, 1, 2, 2, 0, kick="2025-08-16T14:00:00Z"),
    fixture("b", 1, 3, 4, 1, 1, kick="2025-08-16T16:30:00Z"),
    fixture("c", 2, 1, 3, 0, 3, kick="2025-08-23T14:00:00Z", elo=(1510.0, 1490.0)),
    fixture("d", 2, 2, 1, 1, 2, kick="2025-08-26T19:00:00Z", elo=(1495.0, 1505.0)),  # double
    fixture("cup", 2, 1, None, 5, 0, tournament="efl-cup", elo=(9000.0, 9000.0)),
    fixture("e", 3, 4, 2, None, None, kick="2025-08-30T14:00:00Z"),
])


def preds(rows: list[tuple]) -> pd.DataFrame:
    cols = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for", "lambda_against"]
    df = pd.DataFrame(rows, columns=cols)
    return df.assign(p_cs=np.exp(-df.lambda_against))


# --- skips -------------------------------------------------------------------------------

def test_an_expected_error_is_skipped_and_counted() -> None:
    log = SkipLog({"elo_goals": {"S1": {0: SeedError, 1: SampleError}}})

    def fn(season: str, as_of: int, mode: str) -> pd.DataFrame:
        raise (SeedError if as_of == 0 else SampleError)("no")

    assert log.call("elo_goals", fn, "S1", 0, "backtest") is None
    assert log.call("elo_goals", fn, "S1", 1, "backtest") is None
    assert [(s.function, s.as_of, s.error) for s in log.skips] == [
        ("elo_goals", 0, "SeedError"), ("elo_goals", 1, "SampleError")]


def test_an_expected_error_at_another_as_of_stops_the_run() -> None:
    log = SkipLog({"elo_ratings": {"S1": {0: SeedError}}})

    def fn(season: str, as_of: int, mode: str) -> pd.DataFrame:
        raise SeedError("no seed")

    with pytest.raises(UnexpectedReadError, match="S1 as-of 4.*SeedError"):
        log.call("elo_ratings", fn, "S1", 4, "backtest")


def test_the_wrong_error_at_an_expected_as_of_stops_the_run() -> None:
    log = SkipLog({"elo_goals": {"S1": {1: SampleError}}})

    def fn(season: str, as_of: int, mode: str) -> pd.DataFrame:
        raise SeedError("no seed")

    with pytest.raises(UnexpectedReadError):
        log.call("elo_goals", fn, "S1", 1, "backtest")


def test_any_other_exception_stops_the_run() -> None:
    def fn(season: str, as_of: int, mode: str) -> pd.DataFrame:
        raise KeyError("boom")

    with pytest.raises(UnexpectedReadError, match="KeyError"):
        SkipLog({}).call("elo_goals", fn, "S1", 5, "backtest")


def test_an_expected_skip_that_does_not_raise_is_recorded() -> None:
    log = SkipLog({"elo_goals": {"S1": {0: SeedError}}})
    out = log.call("elo_goals", lambda s, g, m: pd.DataFrame({"x": [1]}), "S1", 0, "backtest")
    assert out is not None and log.unraised == [("elo_goals", "S1", 0)]


def test_an_expectation_for_one_function_does_not_cover_another() -> None:
    log = SkipLog({"elo_goals": {"S1": {1: SampleError}}})
    out = log.call("elo_ratings", lambda s, g, m: pd.DataFrame({"x": [1]}), "S1", 1, "backtest")
    assert out is not None and log.unraised == []

    def fn(season: str, as_of: int, mode: str) -> pd.DataFrame:
        raise SampleError("too few")

    with pytest.raises(UnexpectedReadError):
        log.call("elo_ratings", fn, "S1", 1, "backtest")


# --- results and goals -------------------------------------------------------------------

def test_team_results_are_finished_league_fixtures_twice_each() -> None:
    out = team_results(FX, PREM)
    assert len(out) == 8 and set(out.match_id) == {"a", "b", "c", "d"}  # no cup, no unplayed
    row = out[(out.match_id == "c") & ~out.home].iloc[0]
    assert (row.team_id, row.opponent_id, row.goals_for, row.goals_against) == (3, 1, 3, 0)


def test_match_results_keep_finished_league_fixtures_only() -> None:
    assert match_results(FX, PREM).match_id.tolist() == ["a", "b", "c", "d"]


def test_score_gameweek_joins_actual_goals_and_keeps_only_that_gameweek() -> None:
    p = preds([(1, "c", 2, 3, True, 1.2, 1.0), (3, "c", 2, 1, False, 1.0, 1.2),
               (2, "d", 2, 1, True, 1.1, 1.3), (1, "d", 2, 2, False, 1.3, 1.1),
               (4, "e", 3, 2, True, 1.5, 0.9), (2, "e", 3, 4, False, 0.9, 1.5)])
    out = score_gameweek(p, team_results(FX, PREM), FX, 2, PREM)
    assert len(out) == 4 and set(out.gw) == {2}  # the double gives club 1 two rows
    club1 = out[out.team_id == 1].sort_values("match_id")
    assert club1.goals_for.tolist() == [0, 2] and club1.goals_against.tolist() == [3, 1]
    assert club1.clean_sheet.tolist() == [False, False]


def test_score_gameweek_raises_if_a_fixture_has_no_prediction() -> None:
    p = preds([(1, "c", 2, 3, True, 1.2, 1.0), (3, "c", 2, 1, False, 1.0, 1.2)])
    with pytest.raises(HarnessError, match="GW2"):
        score_gameweek(p, team_results(FX, PREM), FX, 2, PREM)


def test_score_gameweek_raises_if_a_column_is_missing() -> None:
    p = preds([(1, "c", 2, 3, True, 1.2, 1.0)]).drop(columns="p_cs")
    with pytest.raises(HarnessError, match="p_cs"):
        score_gameweek(p, team_results(FX, PREM), FX, 2, PREM)


def test_score_gameweek_of_a_blank_club_has_no_row_for_it() -> None:
    # GW1: clubs 1-4 all play; build a GW with one fixture to leave two clubs blank.
    fx = fixtures([fixture("x", 5, 1, 2, 1, 0)])
    p = preds([(1, "x", 5, 2, True, 1.4, 0.8), (2, "x", 5, 1, False, 0.8, 1.4)])
    out = score_gameweek(p, team_results(fx, PREM), fx, 5, PREM)
    assert sorted(out.team_id) == [1, 2]


# --- rating pairs ------------------------------------------------------------------------

def ratings(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["team_id", "match_id", "season", "gw", "kickoff_utc",
                                       "elo_before", "elo_after"])


def test_rating_pairs_use_each_sides_upstream_elo_and_count_a_double_twice() -> None:
    r = ratings([(1, "c", "S1", 2, "t", 1520.0, 1510.0), (3, "c", "S1", 2, "t", 1480.0, 1490.0),
                 (2, "d", "S1", 2, "t", 1490.0, 1480.0), (1, "d", "S1", 2, "t", 1510.0, 1520.0),
                 (1, "a", "S1", 1, "t", 1500.0, 1520.0)])
    out = rating_pairs(r, FX, 2, PREM).sort_values(["match_id", "team_id"])
    assert len(out) == 4
    assert out.upstream_elo.tolist() == [1510.0, 1490.0, 1505.0, 1495.0]


def test_rating_pairs_raise_if_a_kickoff_is_missing() -> None:
    r = ratings([(1, "c", "S1", 2, "t", 1520.0, 1510.0)])
    with pytest.raises(HarnessError, match="GW2"):
        rating_pairs(r, FX, 2, PREM)


# --- baseline pool -----------------------------------------------------------------------

def test_baseline_pool_is_last_season_in_full_and_this_season_up_to_g_minus_1() -> None:
    s0 = fixtures([fixture("p", 38, 1, 2, 4, 4, season="S0")])
    s1 = FX
    by_season = {"S0": match_results(s0, PREM), "S1": match_results(s1, PREM)}
    pool = baseline_pool(by_season, ["S0", "S1"], "S1", 2, pool_seasons=2)
    assert sorted(pool.match_id) == ["a", "b", "p"]  # GW2 itself is not in the pool
    first = baseline_pool(by_season, ["S0", "S1"], "S0", 39, pool_seasons=2)
    assert first.match_id.tolist() == ["p"]  # no season before S0 is loaded
    one = baseline_pool(by_season, ["S0", "S1"], "S1", 3, pool_seasons=1)
    assert sorted(one.match_id) == ["a", "b", "c", "d"]


# --- stability ---------------------------------------------------------------------------

def test_reads_that_agree_with_the_last_read_are_stable() -> None:
    full = ratings([(1, "a", "S1", 1, "t1", 1500.0, 1510.0), (2, "a", "S1", 1, "t1", 1.0, 2.0),
                    (1, "c", "S1", 2, "t2", 1510.0, 1505.0), (3, "c", "S1", 2, "t2", 3.0, 4.0)])
    reads = {1: full[full.gw <= 1], 2: full}
    out = read_stability(reads, "S1")
    assert out == {"reads": 2, "rows": 6, "changed": 0, "missing": 0, "extra": 0,
                   "max_abs_diff": 0.0}


def test_a_read_whose_elo_before_changes_later_is_flagged() -> None:
    full = ratings([(1, "a", "S1", 1, "t1", 1500.0, 1510.0), (1, "c", "S1", 2, "t2", 1510.0, 1.0)])
    early = full[full.gw <= 1].assign(elo_before=1499.0)
    gone = full.iloc[[1]]
    out = read_stability({1: early, 2: full, 3: full}, "S1")
    assert out["changed"] == 1 and out["max_abs_diff"] == pytest.approx(1.0)
    wrong = read_stability({1: gone, 2: full}, "S1")  # read 1 holds a GW2 row, not its own
    assert (wrong["missing"], wrong["extra"]) == (1, 1)


# --- section 6.2 claims ------------------------------------------------------------------

def test_implied_coefficients_recover_a_log_linear_model_exactly() -> None:
    r = ratings([(1, "a", "S1", 1, "t1", 1500.0, 1560.0), (2, "a", "S1", 1, "t1", 1500.0, 1440.0),
                 (3, "b", "S1", 1, "t2", 1500.0, 1530.0), (4, "b", "S1", 1, "t2", 1500.0, 1480.0)])
    a, b, h = 0.1, 0.002, 0.25
    cur = {1: 1560.0, 2: 1440.0, 3: 1530.0, 4: 1480.0}  # gaps 30 and 40
    rows = []
    for mid, home, away in [("e", 1, 3), ("f", 4, 2)]:
        gap = cur[home] - cur[away]
        lh, la = math.exp(a + b * gap + h), math.exp(a - b * gap)
        rows += [(home, mid, 2, away, True, lh, la), (away, mid, 2, home, False, la, lh)]
    out = implied_coefficients(preds(rows), r, "S1")
    assert out["intercept"] == pytest.approx(a) and out["gap"] == pytest.approx(b)
    assert out["home"] == pytest.approx(h) and out["max_resid"] < 1e-9
    assert out["p_cs_err"] < 1e-12 and out["mirror_err"] < 1e-12 and out["unrated"] == 0
