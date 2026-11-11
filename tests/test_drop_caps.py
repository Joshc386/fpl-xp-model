"""Caps on the fact_player_match drops, and the floor on its rows per complete match."""

from __future__ import annotations

import pandas as pd
import pytest

import fpl.clean as clean
from fpl.clean import build_season
from fpl.ingest import RawSeason
from fpl.validate import ValidationError
from fpl.validate_tables import check_drops, check_rows_per_match

BOUNDS = {"max_dropped_rows": {"share": 0.005, "always_allowed": 5},
          "fact_player_match_rows_per_complete_match_min": 15}


def rec(rows_in: int, **dropped: int) -> pd.DataFrame:
    lines = [("fact_player_match", "rows_in", "", rows_in)]
    lines += [("fact_player_match", "dropped", k, v) for k, v in dropped.items()]
    lines += [("dim_team", "rows_in", "", 99999)]  # other tables' lines are ignored
    return pd.DataFrame(lines, columns=["table", "line", "reason", "rows"])


@pytest.mark.parametrize(("rows_in", "n", "fails"), [
    (1000, 5, False),  # a small read may have a few stray rows
    (1000, 6, True),
    (100_000, 500, False),  # 0.5% of the rows
    (100_000, 501, True),
    (14_786, 197, True),  # the real 2025/26 regression (clubs from the latest snapshot)
    (15_340, 2, False),  # the real 2025/26 value
])
@pytest.mark.parametrize("reason", ["club_not_in_match", "player_not_in_snapshot"])
def test_a_drop_count_over_its_cap_fails(rows_in: int, n: int, fails: bool, reason: str) -> None:
    problems = check_drops(rec(rows_in, **{reason: n}), BOUNDS)
    assert bool(problems) is fails
    if fails:
        assert reason in problems[0] and "cap" in problems[0]


def test_each_reason_has_its_own_cap_and_other_drops_are_not_capped() -> None:
    ok = check_drops(rec(1000, club_not_in_match=5, player_not_in_snapshot=5,
                         match_not_complete=900), BOUNDS)
    assert ok == []
    two = check_drops(rec(1000, club_not_in_match=6, player_not_in_snapshot=6), BOUNDS)
    assert len(two) == 2


def tables(rows: int, complete: int) -> dict:
    fx = pd.DataFrame({"stats_complete": [True] * complete + [False] * 3})
    return {"fact_fixture": fx, "fact_player_match": pd.DataFrame({"x": range(rows)})}


def test_the_rows_per_complete_match_floor() -> None:
    assert check_rows_per_match(tables(150, 10), BOUNDS) == []
    assert "under 15 a match" in check_rows_per_match(tables(149, 10), BOUNDS)[0]
    assert check_rows_per_match(tables(0, 0), BOUNDS) == []  # nothing complete yet (as-of 0)


def test_every_row_dropping_because_the_clubs_no_longer_line_up_fails_the_build(
    raw_2627: RawSeason, cfg: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = clean.build_fact_player_match

    def codes_broken(pms: pd.DataFrame, matches: pd.DataFrame, *args: object) -> tuple:
        return real(pms, matches.assign(home_team=-1.0, away_team=-1.0), *args)

    assert build_season(raw_2627, cfg).tables["fact_player_match"].shape[0] > 0
    monkeypatch.setattr(clean, "build_fact_player_match", codes_broken)
    with pytest.raises(ValidationError) as exc:
        build_season(raw_2627, cfg)
    text = "; ".join(exc.value.problems)
    assert "club_not_in_match" in text and "a match" in text  # the cap and the floor
