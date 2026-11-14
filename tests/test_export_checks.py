"""Output checks (brief section 11, step 8): a valid set passes, and each fault is caught.

Each fault asserts the exact problem message, so one check cannot pass on another's message.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from export_outputs import context, outputs, typed
from export_tables import fixture, frame
from fpl.output_checks import check_outputs, output_problems
from fpl.validate import ValidationError

FD = "fixture_difficulty"


def problems(mutate: Callable[[dict[str, pd.DataFrame]], None]) -> list[str]:
    out = outputs()
    mutate(out)
    return output_problems(out, context())


def set_col(name: str, col: str, value: object) -> Callable[[dict[str, pd.DataFrame]], None]:
    """A mutation that sets a whole column of one output file."""
    return lambda o: o[name].__setitem__(col, value)


def test_a_valid_set_passes_and_check_outputs_returns_quietly() -> None:
    assert output_problems(outputs(), context()) == []
    check_outputs(outputs(), context())


def test_check_outputs_raises_with_every_problem() -> None:
    out = outputs()
    out["meta"].loc[0, "next_gw"] = 9
    out["players"].loc[0, "ppg"] = np.nan
    with pytest.raises(ValidationError) as err:
        check_outputs(out, context())
    assert len(err.value.problems) >= 2


def test_columns_must_match_the_contract_in_order() -> None:
    assert any("columns" in p for p in problems(lambda o: o.update(
        players=o["players"].iloc[:, ::-1])))
    assert any("columns" in p for p in problems(lambda o: o.update(
        meta=o["meta"].drop(columns="status"))))


def test_wrong_dtype_is_caught() -> None:
    found = problems(lambda o: o["players"].__setitem__(
        "minutes", o["players"].minutes.astype("float64")))
    assert "players.minutes: dtype float64, expected int64" in found


def test_duplicate_keys_are_caught() -> None:
    found = problems(lambda o: o.update(players=pd.concat([o["players"], o["players"].iloc[:1]])))
    assert "players (player_id): 1 duplicate keys" in found
    found = problems(lambda o: o.update(
        elo_ratings=pd.concat([o["elo_ratings"], o["elo_ratings"].iloc[:1]])))
    assert "elo_ratings (season, team_id, match_id): 1 duplicate keys" in found


def test_nan_is_caught_in_every_column_that_is_not_null_by_design() -> None:
    assert "players.xg90: 4 null values" in problems(set_col("players", "xg90", np.nan))
    assert "players.status: 4 null values" in problems(set_col("players", "status", None))
    assert "players.price_change_start: 4 null values" in problems(
        set_col("players", "price_change_start", np.nan))
    assert "players.net_transfers_gw: dtype Int64, expected int64" in problems(
        set_col("players", "net_transfers_gw", pd.array([pd.NA] * 4, dtype="Int64")))
    assert f"{FD}.lambda_for: 2 null values" in problems(set_col(FD, "lambda_for", np.nan))


def test_nulls_are_allowed_only_where_the_contract_says() -> None:
    assert problems(set_col("players", "news", None)) == []
    assert problems(set_col("players", "chance_next", pd.array([pd.NA] * 4, dtype="Int64"))) == []
    assert problems(set_col("meta", "backtest_mae_model", np.nan)) == []
    assert problems(set_col("meta", "backtest_mae_ep_next", np.nan)) == []


def test_infinity_is_caught() -> None:
    assert "players.dc90: 4 infinite values" in problems(set_col("players", "dc90", np.inf))


def test_lambda_bounds_are_exclusive_at_zero_and_at_the_maximum() -> None:
    bad = "fixture_difficulty.lambda_for: 1 values not in (0, 10)"
    for value in (0.0, -0.5, 10.0, 11.0):
        assert bad in problems(lambda o, v=value: o[FD].loc.__setitem__((0, "lambda_for"), v))
    for value in (1e-9, 9.999):
        assert bad not in problems(lambda o, v=value: o[FD].loc.__setitem__((0, "lambda_for"), v))
    assert "fixture_difficulty.lambda_against: 2 values not in (0, 10)" in problems(
        set_col(FD, "lambda_against", 10.0))
    assert "fixture_difficulty.lambda_against: 2 values not in (0, 10)" in problems(
        set_col(FD, "lambda_against", 0.0))


def test_p_cs_must_be_exp_of_minus_lambda_against() -> None:
    assert "fixture_difficulty.p_cs: not exp(-lambda_against)" in problems(
        set_col(FD, "p_cs", 0.5))


def test_p_cs_outside_zero_one_is_caught_even_if_it_matches() -> None:
    def bad(o: dict) -> None:
        o[FD]["lambda_against"] = -0.1
        o[FD]["p_cs"] = math.exp(0.1)
    assert "fixture_difficulty.p_cs: values outside [0, 1]" in problems(bad)


def test_fixture_difficulty_gameweeks_must_have_a_deadline_after_the_run() -> None:
    found = problems(set_col(FD, "gw", 3))
    assert "fixture_difficulty: gameweeks [3] have a deadline at or before the run" in found


def test_a_gameweek_whose_deadline_is_exactly_the_run_time_counts_as_passed() -> None:
    ctx = dataclasses.replace(context(), run_utc=context().deadlines[4])
    found = output_problems(outputs(), ctx)
    assert "fixture_difficulty: gameweeks [4] have a deadline at or before the run" in found
    before = dataclasses.replace(context(), run_utc=context().deadlines[4] - pd.Timedelta("1s"))
    assert not any("deadline at or before" in p for p in output_problems(outputs(), before))


def test_fixture_difficulty_gameweeks_must_be_inside_the_horizon() -> None:
    found = problems(set_col(FD, "gw", 9))
    assert "fixture_difficulty.gw: values outside the horizon 4..8" in found
    assert "fixture_difficulty: gameweeks [9] have no deadline" in found


def test_fixture_difficulty_teams_must_be_in_dim_team() -> None:
    assert "fixture_difficulty: team ids [99] not in dim_team" in problems(
        set_col(FD, "team_id", [1, 99]))
    assert "fixture_difficulty: team ids [98] not in dim_team" in problems(
        set_col(FD, "opponent_id", [2, 98]))


def test_team_and_opponent_names_must_be_the_short_names() -> None:
    assert "fixture_difficulty.team: 1 values differ from dim_team.short_name" in problems(
        lambda o: o[FD].loc.__setitem__((0, "team"), "XXX"))
    assert "fixture_difficulty.opponent: 2 values differ from dim_team.short_name" in problems(
        set_col(FD, "opponent", "Alpha"))


def test_fixture_difficulty_must_hold_exactly_the_horizon_fixtures() -> None:
    missing = "fixture_difficulty: 1 fixtures missing and 0 unexpected against fact_fixture"
    assert missing in problems(lambda o: o.update(fixture_difficulty=o[FD].iloc[:1]))
    assert "fixture_difficulty: 2 fixtures missing and 2 unexpected against fact_fixture" in (
        problems(set_col(FD, "match_id", "m3")))


def test_fixture_difficulty_rows_must_agree_with_fact_fixture() -> None:
    differ = "fixture_difficulty: {} rows differ from fact_fixture in gw, opponent_id or home"
    assert differ.format(1) in problems(set_col(FD, "home", True))

    def swapped(o: dict) -> None:
        o[FD]["opponent_id"] = [1, 2]
        o[FD]["opponent"] = ["ALP", "BET"]
    assert differ.format(2) in problems(swapped)


def test_fixture_difficulty_pairs_must_mirror_each_other() -> None:
    mirror = ("fixture_difficulty: 1 rows whose lambda_against does not mirror the opponent's "
              "lambda_for")
    assert mirror in problems(set_col(FD, "lambda_for", [1.5, 0.7]))


def test_elo_ratings_must_be_zero_sum_per_match() -> None:
    assert "elo_ratings: matches whose rating changes are not zero-sum" in problems(
        set_col("elo_ratings", "elo_after", 1600.0))


def test_elo_ratings_teams_must_be_in_that_seasons_dim_team() -> None:
    def unknown_club(o: dict) -> None:
        o["elo_ratings"].loc[o["elo_ratings"].team_id == 1, "team_id"] = 7
    assert "elo_ratings 2026-2027: team ids [7] not in dim_team" in problems(unknown_club)


def test_elo_ratings_must_not_reach_past_the_as_of_gameweek() -> None:
    assert "elo_ratings: 2026-2027 rows after the as-of gameweek 3" in problems(
        set_col("elo_ratings", "gw", 4))


def test_elo_ratings_must_cover_every_finished_premier_league_match() -> None:
    found = problems(lambda o: o.update(elo_ratings=o["elo_ratings"].iloc[2:]))
    assert ("elo_ratings 2026-2027: 1 finished Premier League matches missing and 0 unexpected"
            in found)

    def cup_match(o: dict) -> None:
        o["elo_ratings"].loc[o["elo_ratings"].match_id == "m4", "match_id"] = "m5"
    assert ("elo_ratings 2026-2027: 1 finished Premier League matches missing and 1 unexpected"
            in problems(cup_match))


def test_elo_ratings_must_be_in_range_and_not_after_the_run() -> None:
    assert "elo_ratings.elo_before: values outside the range [1000, 2500]" in problems(
        set_col("elo_ratings", "elo_before", 5000.0))
    assert "elo_ratings: kickoff_utc after run_utc" in problems(
        set_col("elo_ratings", "kickoff_utc", "2026-09-30T14:00:00Z"))


def test_players_must_match_dim_player_and_dim_team() -> None:
    assert "players: player_id set differs from dim_player" in problems(
        lambda o: o.update(players=o["players"].iloc[1:]))
    assert "players.team: 4 values differ from dim_team.short_name" in problems(
        set_col("players", "team", "Nowhere"))
    assert "players.position: 4 values not in ['GKP', 'DEF', 'MID', 'FWD']" in problems(
        set_col("players", "position", "XXX"))


def test_a_players_team_must_be_his_own_club_not_just_any_club() -> None:
    assert "players.team: 4 values differ from dim_team.short_name" in problems(
        lambda o: o["players"].__setitem__("team", np.where(o["players"].team == "ALP", "BET",
                                                           "ALP")))


def test_players_value_bounds() -> None:
    assert "players.price_m: values outside [3.0, 20.0]" in problems(
        set_col("players", "price_m", 99.0))
    assert "players.selected_pct: values outside [0, 100]" in problems(
        set_col("players", "selected_pct", 120.0))
    assert "players.chance_next: values outside [0, 100]" in problems(
        set_col("players", "chance_next", pd.array([150, 150, 150, 150], dtype="Int64")))


@pytest.mark.parametrize("col", ["minutes", "starts", "xg90", "xa90", "dc90"])
def test_players_counts_and_rates_are_not_negative(col: str) -> None:
    value = -1 if col in ("minutes", "starts") else -0.5
    found = problems(lambda o: o["players"].__setitem__(col, value))
    assert f"players.{col}: negative values" in found


def test_goalkeepers_must_have_zero_defensive_contributions() -> None:
    def keeper_with_dc(o: dict) -> None:
        o["players"].loc[o["players"].position == "GKP", "dc90"] = 1.0
    assert "players.dc90: goalkeepers with a non-zero value" in problems(keeper_with_dc)
    assert "players.dc90: goalkeepers with a non-zero value" not in problems(
        lambda o: o["players"].loc.__setitem__((o["players"].position == "DEF", "dc90"), 1.0))


def test_meta_must_equal_the_run_context() -> None:
    assert "meta.current_gw: 2, expected 3" in problems(set_col("meta", "current_gw", 2))
    assert "meta.next_gw: 5, expected 4" in problems(set_col("meta", "next_gw", 5))
    assert "meta.next_deadline_utc: '2026-09-05T12:00:00Z', expected '2026-09-04T12:00:00Z'" in (
        problems(set_col("meta", "next_deadline_utc", "2026-09-05T12:00:00Z")))
    assert "meta.run_utc: '2026-09-03 20:00', expected '2026-09-03T20:00:00Z'" in problems(
        set_col("meta", "run_utc", "2026-09-03 20:00"))
    assert "meta.max_horizon: 6, expected 5" in problems(set_col("meta", "max_horizon", 6))


def test_meta_commit_version_status_and_row_count() -> None:
    assert "meta.upstream_commit: '' is not a commit hash" in problems(
        set_col("meta", "upstream_commit", ""))
    assert "meta.model_version: empty" in problems(set_col("meta", "model_version", " "))
    assert "meta.status: 'weird', expected 'ok'" in problems(set_col("meta", "status", "weird"))
    assert "meta: 2 rows, expected 1" in problems(
        lambda o: o.update(meta=pd.concat([o["meta"]] * 2, ignore_index=True)
                           .assign(run_utc=["2026-09-03T20:00:00Z", "2026-09-04T20:00:00Z"])))


def test_next_deadline_must_be_strictly_after_the_run() -> None:
    ctx = context()
    due = ctx.deadlines[4]
    ctx = dataclasses.replace(ctx, run_utc=due)
    out = outputs()
    out["meta"].loc[0, "run_utc"] = due.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "meta.next_deadline_utc is not after run_utc" in output_problems(out, ctx)
    ctx = dataclasses.replace(ctx, run_utc=due - pd.Timedelta("1s"))
    out["meta"].loc[0, "run_utc"] = (due - pd.Timedelta("1s")).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "meta.next_deadline_utc is not after run_utc" not in output_problems(out, ctx)


def test_current_gw_must_be_one_before_next_gw() -> None:
    ctx = dataclasses.replace(context(), next_gw=5)      # as-of stays 3
    out = outputs()
    out["meta"].loc[0, "next_gw"] = 5
    out["meta"].loc[0, "next_deadline_utc"] = ctx.deadlines[5].strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "meta.current_gw is not next_gw - 1" in output_problems(out, ctx)
    assert "meta.current_gw is not next_gw - 1" not in output_problems(outputs(), context())


def test_a_double_gameweek_has_two_rows_per_team_and_a_blank_gameweek_none() -> None:
    ctx = context()
    fx = ctx.tables["fact_fixture"]
    ctx.tables["fact_fixture"] = frame("fact_fixture", [
        *fx.to_dict("records"), fixture("m7", 4, 2, 1, finished=False)])   # gameweek 4 is double
    out = outputs()
    extra = pd.DataFrame(
        [(2, "BET", "m7", 4, 1, "ALP", True, 1.2, 0.9, math.exp(-0.9)),
         (1, "ALP", "m7", 4, 2, "BET", False, 0.9, 1.2, math.exp(-1.2))],
        columns=out[FD].columns)
    out[FD] = typed(FD, pd.concat([out[FD], extra], ignore_index=True))
    assert output_problems(out, ctx) == []        # two rows each in gameweek 4, none in 5-8
    out[FD] = out[FD].iloc[:2]
    assert "fixture_difficulty: 2 fixtures missing and 0 unexpected against fact_fixture" in (
        output_problems(out, ctx))
