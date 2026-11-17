"""beyondELO table build: club mapping, reconciliation in both directions, schema, promoted."""

from __future__ import annotations

import copy
import logging

import pandas as pd
import pytest

import beyondelo_helpers as h
from fpl import beyondelo_build as b

PREV = {10, 11, 12}  # Delta (code 13) is promoted


def frame(recs=None, share: float = 0.5) -> pd.DataFrame:
    return b.matches_frame(recs if recs is not None else h.records(), share)


def build(recs=None, fixture=None, aliases=None):
    fx = fixture if fixture is not None else h.fixture()
    beyond = b.add_team_ids(frame(recs), h.dim_team(), aliases or {})
    return b.build_season(beyond, h.dim_team(), fx, PREV, "2025-2026", "prem")


def counts(recon: pd.DataFrame) -> dict[tuple[str, str], int]:
    return {(r.source, r.reason): r.matches for r in recon.itertuples()}


# --- table --------------------------------------------------------------------------------

def test_schema_matches_the_contract_exactly():
    table, _ = build()
    assert list(table.columns) == [
        "team_id", "match_id", "season", "gw", "kickoff_utc", "home", "beyondelo_before",
        "beyondelo_after", "promoted", "beyondelo_match_id"]
    assert table["home"].dtype == bool and table["promoted"].dtype == bool
    assert table["beyondelo_before"].dtype == "float64" and table["gw"].dtype == "int64"
    assert not table.isna().any().any()


def test_two_rows_per_match_with_each_sides_ratings():
    table, _ = build()
    assert len(table) == 6 and table.groupby("match_id").size().eq(2).all()
    m1 = table[table.match_id == "m1"].set_index("home")
    assert m1.loc[True, "team_id"] == 1 and m1.loc[False, "team_id"] == 2
    assert (m1.loc[True, "beyondelo_before"], m1.loc[True, "beyondelo_after"]) == (1800.5, 1805.5)
    assert (m1.loc[False, "beyondelo_before"], m1.loc[False, "beyondelo_after"]) == (1700.0, 1695.0)
    assert set(m1["beyondelo_match_id"]) == {"101"}
    assert (m1["gw"] == 1).all() and (m1["kickoff_utc"] == "2025-08-16T16:30:00Z").all()


def test_promoted_flag_comes_from_previous_season_codes():
    table, _ = build()
    assert set(table.loc[table.promoted, "team_id"]) == {4}


def test_cup_and_unplayed_rows_are_not_in_the_table():
    table, _ = build()
    assert set(table.match_id) == {"m1", "m2", "m3"}


def test_aliases_map_names_and_datetime_dates_match():
    recs = h.records()
    recs[0].update(home="Alpha FC", date="2025-08-16T16:30:00+00:00")
    recs[3].update(home="Delta")
    table, _ = build(recs, aliases={"Alpha FC": "Alpha"})
    assert set(table.match_id) == {"m1", "m2", "m3"}


# --- names --------------------------------------------------------------------------------

def test_unmapped_names_are_all_listed():
    recs = h.records()
    recs[0].update(home="Alpha FC")
    recs[1].update(away="Delta United")
    assert b.find_unmapped(frame(recs), h.dim_team(), {}) == ["Alpha FC", "Delta United"]


def test_alias_to_an_unknown_team_is_unmapped():
    recs = h.records()
    recs[0].update(home="Alpha FC")
    assert b.find_unmapped(frame(recs), h.dim_team(), {"Alpha FC": "Nobody"}) == ["Alpha FC"]


# --- reconciliation -----------------------------------------------------------------------

def test_reconciliation_counts_in_both_directions():
    _, recon = build()
    assert counts(recon) == {
        ("ours", "matched"): 3, ("ours", "finished_without_partner"): 0,
        ("ours", "not_finished"): 1,
        ("beyondelo", "matched"): 3, ("beyondelo", "unplayed"): 1,
        ("beyondelo", "not_in_our_fixtures"): 1, ("beyondelo", "same_clubs_other_date"): 0,
        ("beyondelo", "played_not_finished_in_ours"): 0,
    }
    assert (recon["season"] == "2025-2026").all()


def test_played_match_we_have_not_finished_is_counted():
    recs = h.records()
    recs[3].update(home_score=1, away_score=0, home_elo_before=1.0, home_elo_after=2.0,
                   away_elo_before=2.0, away_elo_after=1.0)
    table, recon = build(recs)
    assert counts(recon)[("beyondelo", "played_not_finished_in_ours")] == 1
    assert counts(recon)[("beyondelo", "unplayed")] == 0 and "m4" not in set(table.match_id)


def test_same_clubs_on_another_date_is_counted():
    recs = [*h.records(), h.record(106, "2025-12-01", "Alpha", "Beta", 1, 1)]
    _, recon = build(recs)
    assert counts(recon)[("beyondelo", "same_clubs_other_date")] == 1
    assert counts(recon)[("beyondelo", "not_in_our_fixtures")] == 1


def test_same_clubs_on_another_date_fails_our_match():
    recs = h.records()
    recs[0]["date"] = "2025-08-17"
    with pytest.raises(b.BuildError, match="m1"):
        build(recs)


def test_finished_match_without_partner_fails_and_names_it():
    with pytest.raises(b.BuildError, match="m3"):
        build(h.records()[:2] + h.records()[3:])


def test_unplayed_partner_of_a_finished_match_fails():
    recs = h.records()
    recs[2].update(home_score=None, away_score=None)
    with pytest.raises(b.BuildError, match="m3"):
        build(recs)


@pytest.mark.parametrize(("field", "value"), [("home_score", 1), ("away_score", 2)])
def test_score_mismatch_fails(field, value):
    recs = h.records()
    recs[0][field] = value
    with pytest.raises(b.BuildError, match="score"):
        build(recs)


def test_our_duplicate_fixture_fails():
    fx = pd.concat([h.fixture(), h.fixture().iloc[[0]].assign(match_id="dup")], ignore_index=True)
    with pytest.raises(b.BuildError, match="more than once"):
        build(fixture=fx)


# --- beyondELO response checks --------------------------------------------------------------

def test_missing_field_fails():
    recs = copy.deepcopy(h.records())
    del recs[0]["home_elo_after"]
    with pytest.raises(b.BuildError, match="home_elo_after"):
        frame(recs)


def test_played_match_without_ratings_fails():
    recs = h.records()
    recs[0]["home_elo_before"] = None
    with pytest.raises(b.BuildError, match="101"):
        frame(recs)


def test_duplicate_beyondelo_id_fails():
    recs = h.records()
    recs[1]["id"] = 101
    with pytest.raises(b.BuildError, match="duplicate"):
        frame(recs)


def test_unparseable_date_fails():
    recs = h.records()
    recs[0]["date"] = "soon"
    with pytest.raises(b.BuildError, match="date"):
        frame(recs)


def test_non_numeric_score_fails():
    recs = h.records()
    recs[0]["home_score"] = "two"
    with pytest.raises(b.BuildError, match="not numeric"):
        frame(recs)


def test_one_score_missing_fails():
    recs = h.records()
    recs[0]["away_score"] = None
    with pytest.raises(b.BuildError, match="only one score"):
        frame(recs)


def test_non_utc_offsets_are_converted_to_the_utc_date():
    assert b.to_date("2025-08-16T23:30:00-05:00") == "2025-08-17"
    assert b.to_date("2025-08-17T00:30:00+02:00") == "2025-08-16"
    assert b.to_date("2025-08-16") == "2025-08-16"


def test_null_date_fails():
    with pytest.raises(b.BuildError, match="date"):
        b.to_date(None)


@pytest.mark.parametrize("swap", ["before_after", "home_away"])
def test_rating_direction_catches_label_mixups(swap):
    recs = h.records()
    for r in recs:  # a mix-up hits every match
        if swap == "before_after":
            r["home_elo_before"], r["home_elo_after"] = r["home_elo_after"], r["home_elo_before"]
            r["away_elo_before"], r["away_elo_after"] = r["away_elo_after"], r["away_elo_before"]
        else:
            for k in ("elo_before", "elo_after"):
                r[f"home_{k}"], r[f"away_{k}"] = r[f"away_{k}"], r[f"home_{k}"]
    with pytest.raises(b.BuildError, match=r"wrong way.*\['101', '103'\]"):
        frame(recs)


def decided(n: int, wrong_home: int = 0, wrong_away: int = 0) -> list[dict]:
    """n decided home wins; the first `wrong_home` have a home rating that fell, and the first
    `wrong_away` an away rating that rose."""
    return [
        h.record(i, "2025-08-16", "Alpha", "Beta", 2, 1,
                 ha=1790.0 if i < wrong_home else 1810.0, aa=1710.0 if i < wrong_away else 1690.0)
        for i in range(n)
    ]


@pytest.mark.parametrize("kind", ["home", "away"])
def test_one_sided_violations_are_caught(kind):
    n = {"home": (10, 0), "away": (0, 10)}[kind]
    recs = decided(10, wrong_home=n[0], wrong_away=n[1])
    with pytest.raises(b.BuildError, match="10 of 10"):
        frame(recs)


def test_share_of_wrong_matches_at_the_threshold_passes_and_just_over_fails(caplog):
    caplog.set_level(logging.INFO)
    assert len(frame(decided(10, wrong_home=5))) == 10          # 50% is not above 50%
    assert "5 of 10" in caplog.text and "['0', '1', '2', '3', '4']" in caplog.text
    with pytest.raises(b.BuildError, match="6 of 10"):
        frame(decided(10, wrong_home=6))
    with pytest.raises(b.BuildError, match="1 of 2"):
        frame(decided(2, wrong_home=1), share=0.4)


def test_wrong_matches_log_a_warning_and_none_logs_info(caplog):
    caplog.set_level(logging.INFO)
    frame(decided(10, wrong_home=1))
    assert [r.levelname for r in caplog.records if "wrong way" in r.message] == ["WARNING"]
    caplog.clear()
    frame(decided(10))
    assert [r.levelname for r in caplog.records if "wrong way" in r.message] == ["INFO"]


def test_draws_and_unplayed_matches_are_not_direction_checked():
    recs = [h.record(1, "2025-08-16", "Alpha", "Beta", 1, 1, ha=1700.0, aa=1800.0),
            h.record(2, "2025-08-17", "Alpha", "Beta", None, None, None, None, None, None)]
    assert len(frame(recs, share=0.0)) == 2


def test_build_season_refuses_a_club_without_a_team_id():
    beyond = b.add_team_ids(frame(), h.dim_team(), {}).assign(home_team_id=float("nan"))
    with pytest.raises(ValueError, match="non-finite"):
        b.build_season(beyond, h.dim_team(), h.fixture(), PREV, "2025-2026", "prem")


def test_empty_response_gives_an_empty_frame_and_a_failed_build():
    assert frame([]).empty
    with pytest.raises(b.BuildError, match="without a beyondELO partner"):
        build([])
