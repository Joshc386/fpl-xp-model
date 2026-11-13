"""The Elo run on small synthetic tables: provenance, seeds, cross-season joins, edge cases."""

from __future__ import annotations

import pandas as pd
import pytest

from elo_tables import (
    CODES_A,
    CODES_B,
    FIXTURES_A,
    FIXTURES_B,
    PREM,
    SETTINGS,
    season_read,
    two_seasons,
)
from fpl.models.elo import MissingSeedError, run_elo, team_rows

OUT_COLUMNS = ["team_id", "match_id", "season", "gw", "kickoff_utc", "elo_before", "elo_after"]


def rows(history: list) -> pd.DataFrame:
    return team_rows(run_elo(history, SETTINGS, PREM).matches)


def club_rows(out: pd.DataFrame, season: str, team_id: int) -> pd.DataFrame:
    return out[(out.season == season) & (out.team_id == team_id)].sort_values("kickoff_utc")


def test_rows_are_one_per_team_per_finished_match_with_contract_columns() -> None:
    out = rows(two_seasons())
    assert list(out.columns) == OUT_COLUMNS
    assert len(out) == 2 * (6 + 4)  # season A's 6 results, season B's 4 up to as-of 2
    assert not out.duplicated(["team_id", "match_id"]).any() and not out.isna().any().any()
    assert str(out.team_id.dtype) == "int64" and str(out.gw.dtype) == "int64"


def test_every_rating_change_cancels_within_its_match() -> None:
    out = rows(two_seasons())
    change = (out.elo_after - out.elo_before).groupby(out.match_id).sum()
    assert change.abs().max() < 1e-9


def test_the_first_match_uses_the_hand_computed_update() -> None:
    # 1600 v 1500, 2-0, HFA 50, K 20, power 0.5: 20 x 1.4142136 x 0.2966150 = 8.389539.
    first = rows(two_seasons()).iloc[:2]
    assert first.elo_before.tolist() == [1600.0, 1500.0]
    assert first.elo_after.tolist() == pytest.approx([1608.389539, 1491.610461], abs=1e-6)


def test_seeds_are_each_clubs_first_upstream_value_not_its_latest() -> None:
    out = rows(two_seasons())
    seeds = {t: club_rows(out, "2025-2026", t).elo_before.iloc[0] for t in CODES_A}
    assert seeds == {1: 1600.0, 2: 1500.0, 3: 1550.0, 4: 1450.0}  # GW1 values; dim_team says 9999


def test_a_promoted_club_takes_its_upstream_seed_and_a_relegated_one_drops_out() -> None:
    out = rows(two_seasons())
    assert club_rows(out, "2026-2027", 2).elo_before.iloc[0] == 1480.0  # code 35, promoted
    b = out[out.season == "2026-2027"]
    assert set(b.team_id) <= set(CODES_B)  # season B's own ids; code 34 (A id 4) is gone
    assert club_rows(out, "2026-2027", 4).elo_before.iloc[0] == 1520.0  # code 32: A's last value


def test_a_club_with_no_seed_in_the_read_raises() -> None:
    no_seed = [f[:5] + (f[5], None) if f[2] == 2 else f for f in FIXTURES_B]
    no_seed = [f[:5] + (None, f[6]) if f[1] == 2 else f for f in no_seed]
    history = [two_seasons()[0], season_read("2026-2027", 2, CODES_B, no_seed)]
    with pytest.raises(MissingSeedError, match="Club35"):
        run_elo(history, SETTINGS, PREM)


def test_as_of_0_has_no_seed_for_anyone_and_raises() -> None:
    schedule = [f[:3] + (None, None, None, None) for f in FIXTURES_A]
    with pytest.raises(MissingSeedError, match="Club31"):
        run_elo([season_read("2025-2026", 0, CODES_A, schedule)], SETTINGS, PREM)


def test_a_promoted_club_without_a_value_at_as_of_1_raises_even_with_one_later() -> None:
    late = [f[:5] + (f[5], None) if i == 0 else f for i, f in enumerate(FIXTURES_B)]
    late[2] = (2, 2, 3, 1, 1, 1490.0, 7777.0)  # its first value is at GW2, after the as-of
    with pytest.raises(MissingSeedError, match="Club35"):
        run_elo([two_seasons()[0], season_read("2026-2027", 1, CODES_B, late)], SETTINGS, PREM)
    out = rows([two_seasons()[0], season_read("2026-2027", 2, CODES_B, late)])
    assert club_rows(out, "2026-2027", 2).elo_before.iloc[0] == 1490.0  # seeded once in the read


def test_cup_rows_never_affect_a_rating() -> None:
    cups = [(2, 1, 3, 5, 0, 1700.0, 1400.0), (3, 2, 4, 0, 6, 1300.0, 1900.0)]
    with_cups = [season_read("2025-2026", 3, CODES_A, FIXTURES_A, cups=cups)]
    pd.testing.assert_frame_equal(rows(with_cups), rows(two_seasons()[:1]))


def test_late_season_results_count_whatever_stats_complete_says() -> None:
    late = FIXTURES_A + [(37, 1, 4, 3, 0, None, None), (38, 2, 3, 0, 2, None, None)]
    out = rows([season_read("2025-2026", 38, CODES_A, late)])
    assert set(out.gw) >= {37, 38}  # every fixture here has stats_complete false
    assert (out[out.gw == 38].elo_after != out[out.gw == 38].elo_before).all()


def test_results_after_the_as_of_gameweek_are_ignored() -> None:
    # Season B at as-of 1 still has GW2 results in its table: none may be used.
    run = run_elo(two_seasons(as_of_b=1), SETTINGS, PREM)
    out = team_rows(run.matches)
    assert (out[out.season == "2026-2027"].gw <= 1).all()
    truncated = [f if f[0] <= 1 else f[:3] + (None, None, None, None) for f in FIXTURES_B]
    clean = run_elo([two_seasons()[0], season_read("2026-2027", 1, CODES_B, truncated)],
                    SETTINGS, PREM)
    assert run.ratings == clean.ratings


def test_a_postponed_fixture_in_a_past_gameweek_is_skipped() -> None:
    postponed = [f[:3] + (None, None, None, None) if i == 3 else f
                 for i, f in enumerate(FIXTURES_B)]
    out = rows([two_seasons()[0], season_read("2026-2027", 2, CODES_B, postponed)])
    b = out[out.season == "2026-2027"]
    assert len(b) == 2 * 3 and b.match_id.nunique() == 3


def test_a_double_gameweek_chains_the_two_matches() -> None:
    double = FIXTURES_A[:2] + [(2, 1, 3, 0, 1, 1610.0, 1560.0), (2, 4, 1, 2, 2, 1440.0, 1610.0)]
    one = club_rows(rows([season_read("2025-2026", 2, CODES_A, double)]), "2025-2026", 1)
    assert (one.gw == 2).sum() == 2
    assert one.elo_before.iloc[1:].tolist() == one.elo_after.iloc[:-1].tolist()


def test_current_ratings_are_after_each_clubs_last_finished_match() -> None:
    run = run_elo(two_seasons(), SETTINGS, PREM)
    out = team_rows(run.matches)
    for b_id, code in CODES_B.items():
        assert run.ratings[code] == club_rows(out, "2026-2027", b_id).elo_after.iloc[-1]
