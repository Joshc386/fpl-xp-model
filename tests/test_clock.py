"""The deadline clock: next and as-of gameweek from a run time and the deadlines table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest

from fpl.clock import DeadlineError, as_of_gameweek, next_gameweek, parse_deadlines

D1 = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SECOND = timedelta(seconds=1)
OFFSET = "{:%Y-%m-%dT%H:%M:%S}+00:00"


def table(n: int = 38, fmt: str = OFFSET) -> pd.DataFrame:
    """Deadlines a week apart from D1; rows shuffled, as the upstream file is."""
    ids = list(range(1, n + 1))
    df = pd.DataFrame({
        "id": [float(i) for i in ids],
        "deadline_time": [fmt.format(D1 + timedelta(weeks=i - 1)) for i in ids],
    })
    return df.sample(frac=1, random_state=3).reset_index(drop=True)


@pytest.fixture
def deadlines() -> pd.Series:
    return parse_deadlines(table())


def test_deadlines_are_parsed_into_a_series_sorted_by_gameweek(deadlines: pd.Series) -> None:
    assert deadlines.index.tolist() == list(range(1, 39))
    assert deadlines.loc[1] == pd.Timestamp(D1)
    assert str(deadlines.dt.tz) == "UTC"


@pytest.mark.parametrize(
    ("offset", "next_gw"),
    [(-SECOND, 1), (timedelta(0), 2), (SECOND, 2)],
    ids=["one second before", "exactly at", "one second after"],
)
def test_a_deadline_counts_as_passed_from_the_exact_second(
    deadlines: pd.Series, offset: timedelta, next_gw: int
) -> None:
    run = D1 + offset
    assert next_gameweek(deadlines, run) == next_gw
    assert as_of_gameweek(deadlines, run) == next_gw - 1


def test_the_same_boundaries_hold_at_a_later_deadline(deadlines: pd.Series) -> None:
    d20 = D1 + timedelta(weeks=19)
    assert next_gameweek(deadlines, d20 - SECOND) == 20
    assert next_gameweek(deadlines, d20) == 21
    assert next_gameweek(deadlines, d20 + SECOND) == 21


def test_before_the_first_deadline_the_as_of_gameweek_is_zero(deadlines: pd.Series) -> None:
    run = D1 - timedelta(days=60)
    assert next_gameweek(deadlines, run) == 1
    assert as_of_gameweek(deadlines, run) == 0


def test_the_last_gameweek_is_next_until_its_deadline(deadlines: pd.Series) -> None:
    d38 = D1 + timedelta(weeks=37)
    assert next_gameweek(deadlines, d38 - SECOND) == 38
    assert as_of_gameweek(deadlines, d38 - SECOND) == 37


@pytest.mark.parametrize("after", [timedelta(0), SECOND, timedelta(days=30)])
def test_at_or_after_the_last_deadline_there_is_no_next_gameweek(
    deadlines: pd.Series, after: timedelta
) -> None:
    run = D1 + timedelta(weeks=37) + after
    with pytest.raises(DeadlineError, match="GW38"):
        next_gameweek(deadlines, run)
    with pytest.raises(DeadlineError, match="GW38"):
        as_of_gameweek(deadlines, run)


def test_naive_and_z_stamped_deadlines_mean_the_same_instant() -> None:
    forms = ["{:%Y-%m-%dT%H:%M:%S}+00:00", "{:%Y-%m-%dT%H:%M:%S}Z", "{:%Y-%m-%dT%H:%M:%S}"]
    parsed = [parse_deadlines(table(5, fmt)) for fmt in forms]
    for p in parsed[1:]:
        pd.testing.assert_series_equal(p, parsed[0])


def test_mixed_formats_in_one_file_are_parsed() -> None:
    df = table(3)
    df.loc[df.id == 2.0, "deadline_time"] = "2026-08-28T17:30:00Z"
    df.loc[df.id == 3.0, "deadline_time"] = "2026-09-04T17:30:00"
    d = parse_deadlines(df)
    assert next_gameweek(d, datetime(2026, 8, 28, 17, 30, tzinfo=UTC)) == 3
    assert next_gameweek(d, datetime(2026, 9, 4, 17, 29, 59, tzinfo=UTC)) == 3


def test_a_non_utc_deadline_offset_is_converted() -> None:
    df = pd.DataFrame({"id": [1.0], "deadline_time": ["2026-08-21T18:30:00+01:00"]})
    assert parse_deadlines(df).loc[1] == pd.Timestamp("2026-08-21T17:30:00Z")


def test_a_naive_run_time_is_taken_as_utc_and_an_offset_one_is_converted(
    deadlines: pd.Series,
) -> None:
    assert next_gameweek(deadlines, datetime(2026, 8, 21, 17, 30)) == 2
    assert next_gameweek(deadlines, datetime(2026, 8, 21, 17, 29, 59)) == 1
    plus1 = timezone(timedelta(hours=1))
    assert next_gameweek(deadlines, datetime(2026, 8, 21, 18, 29, 59, tzinfo=plus1)) == 1
    assert next_gameweek(deadlines, datetime(2026, 8, 21, 18, 30, tzinfo=plus1)) == 2


@pytest.mark.parametrize("bad", ["duplicate", "gap", "null", "unordered", "unparseable", "empty"])
def test_a_malformed_deadlines_table_is_rejected(bad: str) -> None:
    df = table(5).sort_values("id").reset_index(drop=True)
    if bad == "duplicate":
        df.loc[1, "id"] = 1.0
    elif bad == "gap":
        df = df[df.id != 3.0]
    elif bad == "null":
        df.loc[2, "deadline_time"] = None
    elif bad == "unordered":
        df.loc[[0, 1], "deadline_time"] = df.loc[[1, 0], "deadline_time"].to_numpy()
    elif bad == "unparseable":
        df.loc[0, "deadline_time"] = "soon"
    else:
        df = df.iloc[0:0]
    with pytest.raises(DeadlineError):
        parse_deadlines(df)


def test_two_gameweeks_with_the_same_deadline_are_rejected() -> None:
    df = table(5).sort_values("id").reset_index(drop=True)
    df.loc[2, "deadline_time"] = df.loc[1, "deadline_time"]  # GW3 shares GW2's deadline
    with pytest.raises(DeadlineError, match="strictly increasing"):
        parse_deadlines(df)
    df.loc[2, "deadline_time"] = "2026-08-28T18:30:00+01:00"  # the same instant, other offset
    with pytest.raises(DeadlineError, match="strictly increasing"):
        parse_deadlines(df)


def test_the_number_of_gameweeks_can_be_enforced() -> None:
    parse_deadlines(table(38), n_gw=38)
    with pytest.raises(DeadlineError, match="38"):
        parse_deadlines(table(37), n_gw=38)
