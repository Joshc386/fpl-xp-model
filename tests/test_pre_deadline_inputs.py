"""`fpl.pre_deadline`'s deadlines, first-parent line and refusals, on a synthetic git repo."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

import synth
import view_repo
from deadline_view_helpers import SHA, view_frame
from fpl import pre_deadline
from fpl.deadline_view import ViewError
from fpl.pre_deadline import build_season_view, build_views
from view_repo import Commit, clone_edit, deadline, expected_commit

pytest_plugins = ["pre_deadline_fixtures"]
SEASON = synth.SEASON


# ---- the deadline is the earlier of the derived one and FPL's -------------------------------

GW = 6  # before_5 is at the derived deadline minus 2 hours; after_5 an hour after it
FMT = "%Y-%m-%dT%H:%M:%SZ"


def change_fpl(repo: Path, tmp_path: Path, shift: pd.Timedelta | None) -> Path:
    """A clone whose master gameweek_summaries moves GW6's deadline by `shift` (or drops it)."""
    def edit(root: Path) -> None:
        path = root / "data" / SEASON / "gameweek_summaries.csv"
        summaries = pd.read_csv(path)
        if shift is None:
            summaries = summaries[summaries.id != GW]
        else:
            at = summaries.id == GW
            moved = pd.to_datetime(summaries.deadline_time[at], utc=True) + shift
            summaries.loc[at, "deadline_time"] = moved.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        summaries.to_csv(path, index=False)

    return clone_edit(repo, tmp_path / "clone", edit)


def test_an_fpl_deadline_earlier_than_the_derived_one_is_used_and_logged(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    shift = pd.Timedelta(hours=-3)
    clone = change_fpl(repo[0], tmp_path, shift)
    with caplog.at_level("WARNING", logger="fpl.pre_deadline"):
        view, report = build_season_view(clone, git_cfg, git_cfg["seasons"][0])
    rows = view[view.gw == GW]
    assert set(rows.deadline_utc) == {(deadline(GW) + shift).strftime(FMT)}
    earlier = [c for c in repo[1] if c.time < deadline(GW) + shift][-1]
    assert set(rows.upstream_commit) == {earlier.sha}
    assert earlier.sha != expected_commit(repo[1], GW).sha
    assert report["deadline_gaps"] == [GW]
    assert any(f"[{GW}]" in r.getMessage() for r in caplog.records)


def test_an_fpl_deadline_later_than_the_derived_one_leaves_the_derived_one_in_use(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    clone = change_fpl(repo[0], tmp_path, pd.Timedelta(hours=5))
    view, report = build_season_view(clone, git_cfg, git_cfg["seasons"][0])
    rows = view[view.gw == GW]
    assert set(rows.deadline_utc) == {deadline(GW).strftime(FMT)}
    assert set(rows.upstream_commit) == {expected_commit(repo[1], GW).sha}
    assert report["deadline_gaps"] == [GW]


def test_a_gameweek_missing_from_fpls_summaries_uses_the_derived_deadline(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    clone = change_fpl(repo[0], tmp_path, None)
    view, report = build_season_view(clone, git_cfg, git_cfg["seasons"][0])
    assert set(view[view.gw == GW].deadline_utc) == {deadline(GW).strftime(FMT)}
    assert report["deadline_gaps"] == [GW]


# ---- only the first-parent line counts -----------------------------------------------------


def test_a_side_branch_commit_merged_after_the_deadline_is_not_used(tmp_path: Path) -> None:
    from conftest import ROOT
    from fpl.ingest import load_config

    repo, commits = view_repo.make_repo(tmp_path, states=(1,))
    side_time = deadline(2) - pd.Timedelta(hours=1)  # after before_1, before the deadline
    view_repo.git(repo, "checkout", "-q", "-b", "side", commits[0].sha)
    view_repo.write_state(repo, 7)
    view_repo.git(repo, "add", "-A")
    view_repo.git(repo, "commit", "-q", "-m", "side", when=side_time)
    side = view_repo.git(repo, "rev-parse", "HEAD")
    view_repo.git(repo, "checkout", "-q", "main")
    view_repo.git(repo, "merge", "-q", "--no-ff", "-s", "ours", "-m", "merge", "side",
                  when=deadline(2) + pd.Timedelta(hours=2))
    base = {**load_config(ROOT / "config" / "pipeline.yaml"), "score_corrections": []}
    git_cfg = synth.synth_cfg(base, repo)
    git_cfg["seasons"] = [s for s in base["seasons"] if s["id"] == SEASON]
    git_cfg["validation"] = {**git_cfg["validation"], "players_rows_per_snapshot": [8, 9],
                         "playerstats_rows_snapshot": [8, 9]}
    view, _ = build_season_view(repo, git_cfg, git_cfg["seasons"][0])
    rows = view[view.gw == 2]
    assert side not in set(view.upstream_commit)
    assert set(rows.upstream_commit) == {commits[1].sha}  # before_1, on the first-parent line
    assert (rows.price_tenths == 50 + rows.player_id + 1).all()  # state 1, not the side's 7


# ---- inputs the builder refuses ------------------------------------------------------------


def edit_csv(path: Path, change: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    change(pd.read_csv(path)).to_csv(path, index=False)


def test_a_club_whose_id_and_code_differ_between_gameweek_folders_fails(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    def swap(root: Path) -> None:
        edit_csv(root / "data" / SEASON / "By Gameweek" / "GW7" / "teams.csv",
                 lambda df: df.assign(code=df.code.iloc[::-1].to_numpy()))

    clone = clone_edit(repo[0], tmp_path / "clone", swap)
    with pytest.raises(ViewError, match="id and team code differ"):
        build_season_view(clone, git_cfg, git_cfg["seasons"][0])


def test_deadlines_that_do_not_increase_fail_the_build(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    def early(root: Path) -> None:  # GW5's kickoffs move to before GW4's
        edit_csv(root / "data" / SEASON / "By Gameweek" / "GW5" / "matches.csv",
                 lambda df: df.assign(kickoff_time="2025-08-01T10:00:00+00:00"))

    clone = clone_edit(repo[0], tmp_path / "clone", early)
    with pytest.raises(ViewError, match="deadlines can't be derived"):
        build_season_view(clone, git_cfg, git_cfg["seasons"][0])


def test_a_gameweek_with_no_deadline_to_derive_fails_the_build(
    repo: tuple[Path, list[Commit]], git_cfg: dict, tmp_path: Path
) -> None:
    def blank(root: Path) -> None:  # no Premier League fixture in GW1 or GW2
        for gw in (1, 2):
            edit_csv(root / "data" / SEASON / "By Gameweek" / f"GW{gw}" / "matches.csv",
                     lambda df: df.assign(tournament="x"))

    clone = clone_edit(repo[0], tmp_path / "clone", blank)
    with pytest.raises(ViewError, match="deadlines can't be derived"):
        build_season_view(clone, git_cfg, git_cfg["seasons"][0])


# ---- the two seasons must be read at one head ------------------------------------------------


def test_seasons_read_at_different_heads_fail_the_build_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(checkout: Path, git_cfg: dict, scfg: dict) -> tuple[pd.DataFrame, dict]:
        head = SHA if scfg["id"] == "a" else "b" * 40  # the checkout moved between the seasons
        return view_frame([2]), {"checkout_commit": head}

    monkeypatch.setattr(pre_deadline, "build_season_view", fake)
    git_cfg = {"seasons": [{"id": "a"}, {"id": "b"}]}
    with pytest.raises(ViewError, match="checkout moved during the build"):
        build_views(tmp_path, git_cfg, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    monkeypatch.setattr(pre_deadline, "build_season_view",
                        lambda *a: (view_frame([2]), {"checkout_commit": SHA}))
    build_views(tmp_path, git_cfg, tmp_path / "out")  # the same head is fine
    assert (tmp_path / "out" / "a.json").exists()
