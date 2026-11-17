"""Player Database and Fixture Analysis, no Excel needed.

The expectations come from workbook_helpers (written out by hand), not from the builder's own
constants, so a relabelled column, a wrong number format, a dropdown that lists the wrong thing
or a gameweek header off by one fails here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from workbook_helpers import PLAYER_COLUMNS, ROOT, SAMPLE, contract_columns

# isort: split

import check_fixtures
import check_players
import wb_fixtures
import wb_players
import wb_style


def test_player_columns_match_the_contract_in_the_briefs_order() -> None:
    sources = [source for _, source, _ in PLAYER_COLUMNS]
    assert set(sources) == set(contract_columns("players.csv")) - {"player_id"}
    built = [(c.header, c.source, c.fmt) for c in wb_players.COLUMNS]
    assert built == list(PLAYER_COLUMNS)  # labels, source columns and number formats


def test_the_build_check_holds_the_same_expectations() -> None:
    checked = [(h, s, f) for h, s, f, _ in check_players.EXPECTED_COLUMNS]
    assert checked == list(PLAYER_COLUMNS)


def test_percentage_point_columns_never_use_the_whole_percent_format() -> None:
    # selected_pct is 47.6, not 0.476: "0%" would show 4760%.
    fmts = {s: f for _, s, f in PLAYER_COLUMNS}
    assert fmts["selected_pct"] == fmts["chance_next"] == '0.0"%"'
    assert all(c.fmt != wb_style.PCT_FMT for c in wb_players.COLUMNS)


def test_dropdown_lists_come_from_the_right_columns() -> None:
    assert wb_players.LISTS == {
        "in_team": ("A1", "=SORT(UNIQUE(tbl_players[team]))"),
        "in_position": ("B1", "=UNIQUE(tbl_players[position])"),
        "in_status": ("C1", "=SORT(UNIQUE(tbl_players[status]))"),
    }
    assert check_players.DROPDOWNS == {
        "in_team": ("lst_team", "team", True),
        "in_position": ("lst_position", "position", False),
        "in_status": ("lst_status", "status", True),
    }


def test_player_formulas_handle_blanks_explicitly_and_hide_no_errors() -> None:
    formulas = {c.source: wb_players.column_formula(c) for c in wb_players.COLUMNS}
    everything = [*formulas.values(), *wb_players.NAMES.values()]
    assert not any("IFERROR" in f or "IFNA" in f for f in everything)
    assert all("tbl_players[" in f for f in formulas.values())  # by table and column name
    assert '&""=""' in formulas["chance_next"]  # a blank is not shown as 0
    assert formulas["news"].endswith('&"")')
    assert all(f.startswith('=IF(pd_count=0,"",') for f in formulas.values())
    assert all(name.startswith("in_") for _, name, _ in wb_players.INPUTS)


def test_expected_rows_filters_and_sorts_like_the_sheet() -> None:
    csv = pd.read_csv(ROOT / "outputs" / "players.csv", dtype=str, keep_default_na=False)
    assert len(check_players.expected_rows(csv, {})) == len(csv)
    both = check_players.expected_rows(csv, {"in_team": "ARS", "in_max_price": 6.0})
    assert set(both["team"]) == {"ARS"} and (both["price_m"].astype(float) <= 6.0).all()
    points = check_players.expected_rows(csv, {})["total_points"].astype(int)
    assert points.is_monotonic_decreasing
    assert check_players.expected_rows(csv, {"in_search": "zzzz"}).empty


def test_sample_outputs_follow_the_contract_with_a_blank_and_a_double() -> None:
    fix = pd.read_csv(SAMPLE / "fixture_difficulty.csv")
    assert list(fix.columns) == contract_columns("fixture_difficulty.csv")
    assert not fix.duplicated(["team_id", "match_id"]).any()  # one row per team and match
    assert (fix.groupby("match_id").size() == 2).all()  # each match has both clubs
    meta = pd.read_csv(SAMPLE / "meta.csv")
    assert list(meta.columns) == contract_columns("meta.csv")
    per = fix.groupby(["team", "gw"]).size()
    assert set(per[per == 2].index) == {("CHE", 12), ("CRY", 12)}  # the doubles
    assert set(fix["team"]) == set(pd.read_csv(SAMPLE / "players.csv")["team"])
    present = set(zip(fix["team"], fix["gw"], strict=True))
    first = int(meta["next_gw"][0])
    blanks = {
        (t, g) for t in set(fix["team"]) for g in range(first, first + 5) if (t, g) not in present
    }
    assert blanks == {("CHE", 13), ("CRY", 13)}


def test_fixture_formulas_use_table_names_and_hide_no_errors() -> None:
    formulas = [
        wb_fixtures.number_formula(2, 5),
        wb_fixtures.text_formula(2, 5),
        wb_fixtures.average_formula(2, 5),
        wb_fixtures.bin_formula(2, 5),
        wb_fixtures.header_formula(2),
    ]
    assert not any("IFERROR" in f or "IFNA" in f for f in formulas)
    assert "tbl_fixtures[lambda_for]" in formulas[0] and "tbl_fixtures[p_cs]" in formulas[0]
    assert "in_horizon" in formulas[0] and "in_fixture_view" in formulas[0]
    assert wb_fixtures.DASH in formulas[1]  # a blank gameweek is explicit, not an error
    assert "FIXED(" in formulas[1] and "TEXT(" not in formulas[1]  # locale-proof number text
    assert wb_fixtures.letter(1) == "A" and wb_fixtures.letter(27) == "AA"


@pytest.mark.parametrize("k", range(1, 6))
def test_gameweek_headers_start_at_the_next_gameweek(k: int) -> None:
    # Column k shows GW next_gw + k - 1 (the first column is GW next_gw), empty past the horizon.
    assert wb_fixtures.header_formula(k) == (f'=IF({k}>in_horizon,"","GW "&(meta_next_gw+{k}-1))')
    assert wb_fixtures.NAMES["meta_next_gw"] == "=INDEX(tbl_meta[next_gw],1)"


def test_colour_is_by_per_match_average_so_a_double_cannot_swamp_the_scale() -> None:
    assert "COUNTIFS" in wb_fixtures.average_formula(1, 2)  # sum / number of fixtures
    assert f"{wb_fixtures.letter(wb_fixtures.C_AVG)}2" in wb_fixtures.bin_formula(1, 2)


def test_stepped_scale_matches_the_shared_palette() -> None:
    steps = [wb_style.scale_colour(i) for i in range(wb_style.SCALE_STEPS + 1)]
    assert steps[0] == wb_style.SCALE_LOW == "#F1A340"
    assert steps[wb_style.SCALE_STEPS // 2] == wb_style.SCALE_MID == "#F7F7F7"
    assert steps[-1] == wb_style.SCALE_HIGH == "#67A9CF"
    assert len(set(steps)) == len(steps)


def test_expected_grid_handles_blank_double_and_averages() -> None:
    fix = pd.read_csv(SAMPLE / "fixture_difficulty.csv", dtype=str, keep_default_na=False)
    teams = sorted(set(fix["team"]))
    grid = check_fixtures.expected_grid(fix, teams, 11, "Attack", 5)
    texts, values, total, averages = grid["CHE"]
    assert texts[2] == wb_fixtures.DASH and values[2] is None  # GW13
    assert " + " in texts[1] and " = " in texts[1]  # GW12 double
    assert averages[1] == pytest.approx(values[1] / 2)  # coloured by the mean of two matches
    assert total == pytest.approx(sum(v for v in values if v is not None))
    short = check_fixtures.expected_grid(fix, teams, 11, "Defence", 1)
    assert short["CHE"][0][1:] == [""] * 4  # beyond the horizon
