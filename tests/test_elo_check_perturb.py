"""Perturbation test of the Elo component on the synthetic upstream, with a planted leak.

The synthetic season (tests/synth.py) has full results in every folder, as the real final
folders do. Its copy is corrupted in a temporary directory, never in place.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from backtest.elo_leakage import (
    after_as_of_case,
    changed_values,
    peeking_goals,
    within_gameweek_case,
)
from backtest.perturb import (
    Corruption,
    copy_upstream,
    corrupt_after,
    corrupt_up_to,
    corrupt_within,
    redirect,
    restore_season,
)

import fpl.models.elo
import synth
from elo_check_synth import synth_point
from fpl.features import load_as_of
from fpl.models.elo import elo_ratings
from fpl.models.team_goals import elo_goals
from fpl.validate import ValidationError

RANGES = Corruption(score=(0, 9), elo=(1200.0, 2200.0), xg=(0.0, 4.0), prem_tag="prem",
                    offset_minutes=90)
FILES = ["fixtures", "matches", "players", "teams", "playerstats", "playermatchstats",
         "player_gameweek_stats"]
SEASON = synth.SEASON


@pytest.fixture
def scratch(tmp_path: Path, synth_upstream: tuple[Path, dict]) -> tuple[Path, Path, dict]:
    """(source data dir, scratch data dir, config pointed at the scratch copy)."""
    src = synth_upstream[0] / "data"
    dst = tmp_path / "copy" / "data"
    copy_upstream(src, dst, [SEASON], FILES)
    return src, dst, synth_point


def matches(data_dir: Path, gw: int) -> pd.DataFrame:
    return pd.read_csv(data_dir / SEASON / "By Gameweek" / f"GW{gw}" / "matches.csv")


def test_the_copy_holds_only_the_folders_files_and_no_master_file(scratch: tuple) -> None:
    src, dst, _ = scratch
    assert not (dst / SEASON / "playerstats.csv").exists()
    a = (src / SEASON / "By Gameweek" / "GW7" / "matches.csv").read_bytes()
    assert (dst / SEASON / "By Gameweek" / "GW7" / "matches.csv").read_bytes() == a


def test_corrupt_after_changes_every_later_result_and_keeps_the_schedule(scratch: tuple) -> None:
    src, dst, _ = scratch
    n = corrupt_after(dst, SEASON, 5, np.random.default_rng(1), RANGES)
    assert n > 0
    for gw in (1, 5):
        assert matches(dst, gw).equals(matches(src, gw))
    for gw in (6, 20, 38):
        before, after = matches(src, gw), matches(dst, gw)
        prem = before.tournament == "prem"
        assert (before.home_score[prem] != after.home_score[prem]).all()
        assert (before.away_score[prem] != after.away_score[prem]).all()
        keep = ["match_id", "gameweek", "kickoff_time", "home_team", "away_team", "tournament"]
        assert before[keep].equals(after[keep])


def test_a_cup_tie_played_before_the_as_of_deadline_is_left_alone(scratch: tuple) -> None:
    src, dst, _ = scratch
    corrupt_after(dst, SEASON, 5, np.random.default_rng(1), RANGES)
    def cup(data_dir: Path, gw: int, match_id: str) -> pd.Series:
        return matches(data_dir, gw).set_index("match_id").loc[match_id]

    # cup-late is filed in GW25 but was played in GW2; cup-10 was played in GW9.
    assert cup(dst, 25, "cup-late").home_score == cup(src, 25, "cup-late").home_score
    assert cup(dst, 10, "cup-10").home_team_elo != cup(src, 10, "cup-10").home_team_elo


def test_restore_puts_the_original_files_back(scratch: tuple) -> None:
    src, dst, _ = scratch
    corrupt_after(dst, SEASON, 5, np.random.default_rng(1), RANGES)
    restore_season(src, dst, SEASON)
    assert matches(dst, 20).equals(matches(src, 20))


def test_corrupt_within_keeps_finished_and_earlier_kickoffs(scratch: tuple) -> None:
    src, dst, _ = scratch
    split = pd.Timestamp(synth.FIRST_KICKOFF + pd.Timedelta(days=49, hours=3))  # GW7, 2nd slot
    corrupt_within(dst, SEASON, 7, split, np.random.default_rng(2), RANGES)
    before, after = matches(src, 7), matches(dst, 7)
    assert after.finished.all()
    first = before.kickoff_time == before.kickoff_time.min()
    assert before[first].equals(after[first])
    assert (before.home_score[~first] != after.home_score[~first]).all()


def test_the_redirect_is_the_loaders_data_copy(synth_upstream: tuple[Path, dict]) -> None:
    """`redirect` reaches a `load_as_of` call that names no config: the real loader then fails
    the real bounds on match ids that exist only in the synthetic copy."""
    with redirect(synth_upstream[0] / "data"), pytest.raises(ValidationError, match="m01-1-2"):
        load_as_of(SEASON, 5, "backtest")


def test_the_synthetic_point_reads_the_corrupted_copy(scratch: tuple) -> None:
    _, dst, point = scratch
    corrupt_after(dst, SEASON, 5, np.random.default_rng(1), RANGES)
    with point(dst):
        fx = fpl.models.elo.load_as_of(SEASON, 38, "backtest")["fact_fixture"]
    true = synth.schedule()
    hs = {m["id"]: (m["gw"] + m["home"]) % 4 for m in true if m["tournament"] == "prem"}
    late = fx[(fx.tournament == "prem") & (fx.gw > 5) & fx.finished]
    assert (late.home_goals != late.match_id.map(hs)).all()


def test_changed_values_counts_cells_and_treats_nan_as_equal() -> None:
    a = pd.DataFrame({"x": [1.0, np.nan], "y": ["a", "b"]})
    assert changed_values(a, a.copy()) == 0
    assert changed_values(a, a.assign(x=[1.0, 2.0])) == 1
    assert changed_values(a, a.iloc[:1]) == 4  # a shape change counts every value


def test_the_public_functions_pass_the_perturbation_test(scratch: tuple) -> None:
    src, dst, point = scratch
    out = after_as_of_case({"elo_ratings": elo_ratings, "elo_goals": elo_goals}, SEASON, 20,
                           src, dst, point, np.random.default_rng(3), RANGES, "backtest",
                           controls=["elo_ratings", "elo_goals"])
    assert out["corrupted_cells"] > 0
    assert {k: v["changed"] for k, v in out["functions"].items()} == {
        "elo_ratings": 0, "elo_goals": 0}
    assert out["functions"]["elo_goals"]["rows"] > 0
    # The control: results up to the as-of changed in the copy move both functions' output,
    # so each one does read the copy.
    assert out["control"]["elo_goals"]["changed"] > 0
    assert out["control"]["elo_ratings"]["changed"] > 0
    assert matches(dst, 20).equals(matches(src, 20))  # restored afterwards


def test_the_copy_control_flags_a_function_that_doesnt_read_the_copy(scratch: tuple) -> None:
    src, dst, point = scratch
    with point(dst):
        frozen = elo_goals(SEASON, 20, "backtest")
    out = after_as_of_case({"blind": lambda season, g, mode: frozen.copy()}, SEASON, 20, src,
                           dst, point, np.random.default_rng(3), RANGES, "backtest",
                           controls=["blind"])
    assert out["functions"]["blind"]["changed"] == 0  # passes the perturbation trivially
    assert out["control"]["blind"]["changed"] == 0  # and the control exposes it


def test_a_planted_leak_fails_the_perturbation_test(scratch: tuple) -> None:
    src, dst, point = scratch
    out = after_as_of_case({"peeking": peeking_goals}, SEASON, 20, src, dst, point,
                           np.random.default_rng(3), RANGES, "backtest")
    assert out["functions"]["peeking"]["changed"] > 0


def test_elo_before_ignores_its_own_and_later_results_within_a_gameweek(scratch: tuple) -> None:
    src, dst, point = scratch
    out = within_gameweek_case(elo_ratings, SEASON, 7, src, dst, point,
                               np.random.default_rng(4), RANGES, "backtest")
    assert out["checked"] > 0 and out["changed"] == 0
    assert out["control_changed"] > 0  # the corruption reached the ratings after the split


def test_a_rating_that_peeks_at_its_own_result_fails_the_within_gameweek_test(
        scratch: tuple) -> None:
    def peeking_ratings(season: str, as_of: int, mode: str) -> pd.DataFrame:
        out = elo_ratings(season, as_of, mode)
        return out.assign(elo_before=out.elo_after)  # "before" now includes the match itself

    src, dst, point = scratch
    out = within_gameweek_case(peeking_ratings, SEASON, 7, src, dst, point,
                               np.random.default_rng(4), RANGES, "backtest")
    assert out["changed"] > 0


def test_corrupt_up_to_changes_results_up_to_the_as_of_and_keeps_finished(scratch: tuple) -> None:
    src, dst, _ = scratch
    corrupt_up_to(dst, SEASON, 5, np.random.default_rng(6), RANGES)
    for gw in (1, 5):
        before, after = matches(src, gw), matches(dst, gw)
        prem = before.tournament == "prem"
        assert (before.home_score[prem] != after.home_score[prem]).all()
        assert after.finished.all()
    assert matches(dst, 6).equals(matches(src, 6))


# --- fixtures.csv carries result columns too (real upstream) --------------------------------

RESULT_ROW = {"home_score": "2.0", "away_score": "1.0", "home_team_elo": "1800.00",
              "away_team_elo": "1700.00", "home_expected_goals_xg": "1.50",
              "away_expected_goals_xg": "0.90", "home_non_penalty_xg": "1.20",
              "away_non_penalty_xg": "0.90", "finished": "True", "tournament": "prem"}


def two_folders(root: Path) -> Path:
    """A season of two gameweeks whose matches.csv and fixtures.csv both carry results."""
    for gw in (1, 2):
        folder = root / "S" / "By Gameweek" / f"GW{gw}"
        folder.mkdir(parents=True)
        row = {"gameweek": f"{gw}.0", "match_id": f"m{gw}",
               "kickoff_time": f"2025-08-{10 + 7 * gw}T14:00:00+00:00", **RESULT_ROW}
        pd.DataFrame([row]).to_csv(folder / "matches.csv", index=False)
        pd.DataFrame([row]).drop(columns="tournament").to_csv(folder / "fixtures.csv",
                                                              index=False)
    return root


def fixtures_csv(root: Path, gw: int) -> pd.Series:
    return pd.read_csv(root / "S" / "By Gameweek" / f"GW{gw}" / "fixtures.csv",
                       dtype=str).iloc[0]


def test_corrupt_after_corrupts_fixtures_csv_as_well(tmp_path: Path) -> None:
    src, dst = two_folders(tmp_path / "src"), two_folders(tmp_path / "dst")
    corrupt_after(dst, "S", 1, np.random.default_rng(7), RANGES)
    assert fixtures_csv(dst, 1).equals(fixtures_csv(src, 1))
    late, orig = fixtures_csv(dst, 2), fixtures_csv(src, 2)
    for col in ("home_score", "away_score", "home_team_elo", "home_expected_goals_xg"):
        assert late[col] != orig[col]
    assert late.match_id == orig.match_id and late.kickoff_time == orig.kickoff_time
    restore_season(src, dst, "S")
    assert fixtures_csv(dst, 2).equals(orig)


def test_corrupt_within_and_up_to_corrupt_fixtures_csv_too(tmp_path: Path) -> None:
    src, dst = two_folders(tmp_path / "src"), two_folders(tmp_path / "dst")
    corrupt_up_to(dst, "S", 1, np.random.default_rng(8), RANGES)
    assert fixtures_csv(dst, 1).home_score != fixtures_csv(src, 1).home_score
    assert fixtures_csv(dst, 1).finished == "True"
    corrupt_within(dst, "S", 2, pd.Timestamp("2025-08-01T00:00:00Z"),
                   np.random.default_rng(9), RANGES)
    assert fixtures_csv(dst, 2).home_score != fixtures_csv(src, 2).home_score
