"""The minutes component's availability override, fixtures and projection, checked against
hand-computed values (brief 6.1). The per-player rates are in test_minutes_rates.py."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from fpl.ingest import ROOT, load_config
from fpl.models import minutes
from fpl.models.elo import model_config
from fpl.models.minutes import (
    OUT_COLUMNS,
    PROBABILITIES,
    MinutesError,
    MinutesSettings,
    availability,
    club_fixtures,
    minutes_from_tables,
    project,
)
from minutes_tables import PREM, tables


# (status, chance, factor in every gameweek, factor in the next gameweek)
@pytest.mark.parametrize(("status", "chance", "every", "next_gw"), [
    ("a", None, 1.0, 1.0),    # no concern
    ("a", 100, 1.0, 1.0),
    # 2025/26 GW2-10 snapshots give 345-565 available players a chance of 0 with no news;
    # about half played the next gameweek, as many as those at 100. Read as no concern.
    ("a", 0, 1.0, 1.0),
    # A chance of playing is for the next round only.
    ("d", 75, 1.0, 0.75), ("d", 50, 1.0, 0.5), ("d", 25, 1.0, 0.25),
    ("d", 0, 1.0, 0.0),       # not seen in either season; taken at its word
    ("a", 75, 1.0, 0.75),     # not seen; a chance below 100 scales whatever the status
    # Injured, suspended, unavailable and not available: 0 in every gameweek.
    ("i", 0, 0.0, 0.0), ("s", 0, 0.0, 0.0), ("u", 0, 0.0, 0.0),
    ("n", 0, 0.0, 0.0),       # FPL's "not available", e.g. ineligible against his parent club
    ("i", None, 0.0, 0.0), ("u", 100, 0.0, 0.0),
])
def test_availability_factors(status: str, chance: int | None, every: float,
                              next_gw: float) -> None:
    got_every, got_next = availability(pd.Series([status]), pd.Series([chance], dtype="Int64"))
    assert got_every.tolist() == [pytest.approx(every)]
    assert got_next.tolist() == [pytest.approx(next_gw)]


def test_an_unknown_status_or_a_chance_outside_0_to_100_is_an_error() -> None:
    with pytest.raises(MinutesError, match="unknown status"):
        availability(pd.Series(["a", "x"]), pd.Series([None, None], dtype="Int64"))
    with pytest.raises(MinutesError, match="chance"):
        availability(pd.Series(["d"]), pd.Series([120], dtype="Int64"))


def test_club_fixtures_are_the_league_fixtures_after_as_of_within_the_horizon() -> None:
    t = tables([], [
        (4, 1, 2),                    # m0: as-of gameweek, out
        (5, 1, 2), (5, 3, 4),         # m1, m2
        (6, 2, 1), (6, 1, 3),         # m3, m4: club 1's double; m4 is listed second...
        (6, 9, 1, "efl-cup"),         # m5: not a league fixture
        (8, 1, 4),                    # m6: beyond the horizon
    ])
    fx = t["fact_fixture"]
    # ...but kicks off first, so m3 is club 1's second fixture of GW6.
    fx.loc[fx.match_id == "m4", "kickoff_utc"] = "2025-08-01T12:00:00Z"
    out = club_fixtures(fx, 4, 3, PREM)
    assert list(out.columns) == ["team_id", "match_id", "gw", "kickoff_utc", "nth"]
    got = {(r.team_id, r.match_id): (r.gw, r.nth) for r in out.itertuples()}
    assert got == {
        (1, "m1"): (5, 0), (2, "m1"): (5, 0), (3, "m2"): (5, 0), (4, "m2"): (5, 0),
        (1, "m4"): (6, 0), (3, "m4"): (6, 0), (1, "m3"): (6, 1), (2, "m3"): (6, 0),
    }
    # Club 4 has no GW6 or GW7 fixture: a blank gameweek has no row.
    assert set(out[out.team_id == 4].gw) == {5}


OUTPUTS = [*PROBABILITIES, "exp_minutes"]
SETTINGS = MinutesSettings(windows=(1, 3, 6), weights=(1.0, 1.0, 1.0), prior_strength=1.0,
                           second_fixture_discount=0.1, long_minutes=60, max_horizon=5)
RATES_10 = {"start_rate": 0.7, "p60_given_start": 0.77, "minutes_given_start": 78.0,
            "bench_rate": 0.65 / 1.5, "minutes_given_bench": 18.8}


def players_frame(every: float = 1.0, next_gw: float | None = None,
                  **rates: float) -> pd.DataFrame:
    """Player 10 at club 1, available with factor `every` in every gameweek and `next_gw`
    (default `every`) in the next one."""
    return pd.DataFrame([{"player_id": 10, "team_id": 1, **RATES_10, **rates,
                          "available": every,
                          "available_next": every if next_gw is None else next_gw}])


def fixtures_frame(nths: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"team_id": 1, "match_id": [f"m{i}" for i in range(len(nths))],
                         "gw": 5, "kickoff_utc": [f"2025-09-0{i + 1}T12:00:00Z"
                                                  for i in range(len(nths))], "nth": nths})


def test_projection_combines_the_rates() -> None:
    r = project(players_frame(), fixtures_frame([0]), SETTINGS, 5).iloc[0]
    assert r.p_start == pytest.approx(0.7)
    assert r.p_appear == pytest.approx(0.7 + 0.3 * 0.65 / 1.5)          # 0.83
    assert r.p_60 == pytest.approx(0.7 * 0.77)                           # 0.539
    assert r.exp_minutes == pytest.approx(0.7 * 78 + 0.3 * 0.65 / 1.5 * 18.8)   # 57.044


def test_the_next_gameweeks_factor_scales_every_output_of_its_rows_only() -> None:
    # fixtures_frame's rows are all GW5.
    full = project(players_frame(), fixtures_frame([0]), SETTINGS, next_gw=5).iloc[0]
    part = project(players_frame(next_gw=0.75), fixtures_frame([0]), SETTINGS, 5).iloc[0]
    later = project(players_frame(next_gw=0.75), fixtures_frame([0]), SETTINGS, 4).iloc[0]
    for col in OUTPUTS:
        assert part[col] == pytest.approx(0.75 * full[col]), col
        assert later[col] == pytest.approx(full[col]), col
    for next_gw in (4, 5):
        out = project(players_frame(every=0.0), fixtures_frame([0]), SETTINGS, next_gw).iloc[0]
        assert out[OUTPUTS].tolist() == [0, 0, 0, 0]


def test_the_second_fixture_of_a_double_has_fewer_starts_but_can_come_off_the_bench() -> None:
    out = project(players_frame(), fixtures_frame([0, 1]), SETTINGS, 5)
    first, second = out.iloc[0], out.iloc[1]
    assert first.p_start == pytest.approx(0.7)
    assert second.p_start == pytest.approx(0.7 * 0.9)                    # 0.63
    assert second.p_appear == pytest.approx(0.63 + 0.37 * 0.65 / 1.5)    # 0.790333
    assert second.p_60 == pytest.approx(0.63 * 0.77)
    assert second.exp_minutes == pytest.approx(0.63 * 78 + 0.37 * 0.65 / 1.5 * 18.8)


def test_projection_rows_carry_the_keys_in_order() -> None:
    out = project(players_frame(), fixtures_frame([0, 1]), SETTINGS, 5)
    assert list(out.columns) == OUT_COLUMNS
    assert out.match_id.tolist() == ["m0", "m1"] and out.gw.tolist() == [5, 5]


def test_the_settings_come_from_model_yaml_and_the_60_minute_line_from_scoring_yaml() -> None:
    s = MinutesSettings.from_config(model_config(), load_config(ROOT / "config" / "scoring.yaml"))
    assert s.windows == (1, 3, 6) and s.long_minutes == 60 and s.max_horizon == 5
    assert len(s.weights) == 3 and s.prior_strength > 0 and 0 <= s.second_fixture_discount < 1
    assert s.gameweek_weights[0] == pytest.approx(1.0)


@pytest.mark.parametrize("change", [
    {"prior_strength": 0}, {"prior_strength": -1}, {"second_fixture_discount": 1.0},
    {"second_fixture_discount": -0.1}, {"long_minutes": 0}, {"max_horizon": 0},
    {"windows": (3, 1)}, {"weights": (1.0, 1.0)},
])
def test_bad_settings_are_rejected(change: dict) -> None:
    with pytest.raises(MinutesError):
        dataclasses.replace(SETTINGS, **change)


def horizon_tables(status: str, chance: int | None, gw6: str = "single") -> dict:
    """As-of 5 with a five-gameweek horizon (GW6-10) for club 1, whose GW6 is `gw6`: "single",
    "double" or "blank". Players 10 and 11 share one history; 10 has `status` and `chance`,
    11 no concern."""
    weeks = [(90, 1), (30, 0), (90, 1), (70, 1), (0, 0)]
    history = [(p, 1, g, m, s) for p in (10, 11) for g, (m, s) in enumerate(weeks, start=1)]
    fixtures = [(g, 1, 2) for g in range(1, 11) if not (g == 6 and gw6 == "blank")]
    fixtures += [(6, 3, 1)] if gw6 == "double" else []      # kicks off after (6, 1, 2)
    players = [(10, 1, "MID", status, chance), (11, 1, "MID", "a", None)]
    return tables(history, fixtures, players)


def outputs_of(out: pd.DataFrame, player: int) -> pd.DataFrame:
    """One player's outputs by (gw, match_id)."""
    return out[out.player_id == player].set_index(["gw", "match_id"])[OUTPUTS]


def test_a_chance_of_playing_scales_the_next_gameweek_only() -> None:
    out = minutes_from_tables(horizon_tables("d", 75), 5, SETTINGS, PREM)
    doubtful, fit = outputs_of(out, 10), outputs_of(out, 11)
    assert sorted(set(out.gw)) == [6, 7, 8, 9, 10] and (fit.p_start > 0).all()
    # FPL's chance is for the next round, GW6; GW7-10 use the unscaled rates.
    pd.testing.assert_frame_equal(doubtful.loc[[6]], 0.75 * fit.loc[[6]])
    pd.testing.assert_frame_equal(doubtful.loc[[7, 8, 9, 10]], fit.loc[[7, 8, 9, 10]])


def test_a_chance_of_playing_scales_both_fixtures_of_a_next_gameweek_double() -> None:
    out = minutes_from_tables(horizon_tables("d", 50, gw6="double"), 5, SETTINGS, PREM)
    doubtful, fit = outputs_of(out, 10), outputs_of(out, 11)
    assert len(fit.loc[[6]]) == 2
    pd.testing.assert_frame_equal(doubtful.loc[[6]], 0.5 * fit.loc[[6]])
    pd.testing.assert_frame_equal(doubtful.loc[[7, 8, 9, 10]], fit.loc[[7, 8, 9, 10]])
    # The second fixture keeps its rotation cut as well: 0.5 x 0.9 x the first's start rate.
    first, second = doubtful.loc[6].p_start
    assert second == pytest.approx(0.9 * first)
    assert first == pytest.approx(0.5 * fit.loc[6].p_start.iloc[0])


def test_with_a_blank_next_gameweek_the_chance_scales_nothing() -> None:
    out = minutes_from_tables(horizon_tables("d", 25, gw6="blank"), 5, SETTINGS, PREM)
    assert sorted(set(out.gw)) == [7, 8, 9, 10]
    pd.testing.assert_frame_equal(outputs_of(out, 10), outputs_of(out, 11))


@pytest.mark.parametrize("status", ["i", "s", "u", "n"])
def test_an_unavailable_status_zeroes_every_gameweek_of_the_horizon(status: str) -> None:
    out = minutes_from_tables(horizon_tables(status, 0), 5, SETTINGS, PREM)
    assert sorted(set(out[out.player_id == 10].gw)) == [6, 7, 8, 9, 10]
    assert (outputs_of(out, 10) == 0).all().all()
    assert (outputs_of(out, 11).p_start > 0).all()


def test_a_gameweek_row_after_as_of_changes_nothing() -> None:
    # A GW6 row (after as-of 5) for both players, unlike anything before it: 10 unused, 11
    # off the bench for 70 minutes. Neither may reach a rate or a prior.
    base = horizon_tables("a", None)
    later = dict(base)
    extra = pd.DataFrame({"player_id": [10, 11], "team_id": pd.array([1, 1], "Int64"),
                          "gw": [6, 6], "minutes": [0, 70], "starts": [0, 0]})
    later["fact_player_gw"] = pd.concat([base["fact_player_gw"], extra], ignore_index=True)
    pd.testing.assert_frame_equal(minutes_from_tables(later, 5, SETTINGS, PREM),
                                  minutes_from_tables(base, 5, SETTINGS, PREM))


def test_player_minutes_reads_load_as_of_with_its_own_arguments(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def load(*args: object, **kwargs: object) -> dict:
        calls.append((*args, *kwargs.values()))
        return horizon_tables("a", None)

    monkeypatch.setattr(minutes, "load_as_of", load)
    out = minutes.player_minutes("2026-2027", 5, "live")
    assert calls == [("2026-2027", 5, "live")]
    assert sorted(set(out.gw)) == [6, 7, 8, 9, 10]


def with_new_arrivals(statuses: dict[int, str]) -> dict:
    """`horizon_tables` plus midfielders at club 1 with no gameweek rows yet, by status."""
    t = dict(horizon_tables("a", None))
    new = pd.DataFrame({"player_id": list(statuses), "team_id": 1, "position": "MID",
                        "status": list(statuses.values()),
                        "chance_next": pd.array([None] * len(statuses), "Int64")})
    t["dim_player"] = pd.concat([t["dim_player"], new], ignore_index=True)
    return t


def test_a_new_arrival_gets_the_position_average_and_an_injured_one_zero() -> None:
    out = minutes_from_tables(with_new_arrivals({12: "a", 13: "i"}), 5, SETTINGS, PREM)
    # The MID prior is players 10 and 11's season: 3 starts in 5 fixtures, every start 60+
    # (90, 90, 70: 250/3 minutes), and a bench appearance in 1 of 2 non-starts (30 minutes).
    new = outputs_of(out, 12)
    assert len(new) == 5
    assert new.p_start.tolist() == pytest.approx([0.6] * 5)
    assert new.p_appear.tolist() == pytest.approx([0.6 + 0.4 * 0.5] * 5)
    assert new.p_60.tolist() == pytest.approx([0.6] * 5)
    assert new.exp_minutes.tolist() == pytest.approx([0.6 * 250 / 3 + 0.4 * 0.5 * 30] * 5)
    # The availability override applies as usual.
    assert (outputs_of(out, 13) == 0).all().all() and len(outputs_of(out, 13)) == 5
