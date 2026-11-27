"""The pre-deadline view's stored table, its read refusals, and the data copy's view."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from deadline_view_helpers import SHA, build, git_dir, stats_row, view_frame
from fpl.deadline_view import (
    COPY_VIEW_DIR,
    VIEW_COLUMNS,
    ViewError,
    apply_view,
    read_view,
    write_view,
)
from fpl.schema import PROCESSED_SCHEMA, column_names
from fpl.view_checkout import copy_view, head_commit


@pytest.fixture
def view_dir(tmp_path: Path) -> Path:
    write_view(tmp_path, "2026-2027", view_frame([2, 3, 4]), checkout_commit=SHA)
    return tmp_path


def test_the_view_has_the_dim_player_columns_then_its_five_own() -> None:
    assert VIEW_COLUMNS == column_names("dim_player") + [
        "gw", "deadline_utc", "upstream_commit", "commit_utc", "checkout_ends_early"]


def test_a_stored_view_reads_back_with_the_processed_dtypes(view_dir: Path) -> None:
    got = read_view(view_dir, "2026-2027", 3, SHA)
    assert got.gw.eq(3).all() and len(got) == 2
    assert list(got.columns) == VIEW_COLUMNS
    for col, kind, nullable in PROCESSED_SCHEMA["dim_player"]:
        want = {"int": "Int64" if nullable else "int64", "float": "float64"}.get(kind)
        if want:
            assert str(got[col].dtype) == want, col
    assert got.checkout_ends_early.dtype == bool


def test_a_missing_view_refuses_and_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(ViewError, match=r"python -m fpl\.pre_deadline"):
        read_view(tmp_path, "2026-2027", 3, SHA)


def test_a_table_without_its_record_of_the_checkout_commit_is_missing(view_dir: Path) -> None:
    (view_dir / "2026-2027.json").unlink()
    with pytest.raises(ViewError, match="missing"):
        read_view(view_dir, "2026-2027", 3, SHA)


def test_a_view_without_the_gameweek_refuses(view_dir: Path) -> None:
    with pytest.raises(ViewError, match=r"lacks GW9.*python -m fpl\.pre_deadline"):
        read_view(view_dir, "2026-2027", 9, SHA)


def test_a_view_of_another_season_is_not_this_seasons(view_dir: Path) -> None:
    with pytest.raises(ViewError, match="missing"):
        read_view(view_dir, "2025-2026", 3, SHA)


def test_a_view_built_from_another_checkout_commit_is_stale(view_dir: Path) -> None:
    with pytest.raises(ViewError, match=r"stale.*python -m fpl\.pre_deadline"):
        read_view(view_dir, "2026-2027", 3, "b" * 40)


def test_a_checkout_that_is_not_a_git_checkout_does_not_match_a_real_view(view_dir: Path) -> None:
    with pytest.raises(ViewError, match="stale"):
        read_view(view_dir, "2026-2027", 3, None)


def test_a_view_with_a_wrong_column_refuses(view_dir: Path) -> None:
    path = view_dir / "2026-2027.parquet"
    pd.read_parquet(path).rename(columns={"status": "state"}).to_parquet(path, index=False)
    with pytest.raises(ViewError, match="columns"):
        read_view(view_dir, "2026-2027", 3, SHA)


def test_a_view_with_a_repeated_player_refuses(view_dir: Path) -> None:
    path = view_dir / "2026-2027.parquet"
    df = pd.read_parquet(path)
    pd.concat([df, df[df.gw == 3]]).to_parquet(path, index=False)
    with pytest.raises(ViewError, match="duplicate"):
        read_view(view_dir, "2026-2027", 3, SHA)


def test_writing_a_view_with_a_wrong_schema_fails_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ViewError):
        write_view(tmp_path, "2026-2027", view_frame([2]).drop(columns="gw"), checkout_commit=SHA)
    assert list(tmp_path.iterdir()) == []


def test_the_record_holds_the_checkout_commit(view_dir: Path) -> None:
    info = json.loads((view_dir / "2026-2027.json").read_text(encoding="utf-8"))
    assert info["checkout_commit"] == SHA


# ---- the players of a read ----------------------------------------------------------------


def test_players_in_the_read_but_not_in_the_view_are_dropped_and_counted() -> None:
    snapshot, _ = build([1, 2, 3], [stats_row(1, 1), stats_row(2, 1), stats_row(3, 1)])
    view = view_frame([2]).query("player_id != 2")
    out, counts = apply_view(snapshot, view)
    assert out.player_id.tolist() == [1]
    assert counts == {"dropped": 2, "not_in_snapshot": 0}


def test_the_view_supplies_every_column_not_the_snapshot() -> None:
    snapshot, _ = build([1, 2], [stats_row(1, 1, status="a", now_cost=5.0),
                                 stats_row(2, 1, now_cost=5.0)])
    view = view_frame([2], price_add=7).assign(status="i")
    out, _ = apply_view(snapshot, view)
    assert (out.status == "i").all()
    assert out.price_tenths.tolist() == (view.price_tenths).tolist()
    assert list(out.columns) == column_names("dim_player")


def test_a_view_player_the_snapshot_lacks_is_kept_and_counted() -> None:
    snapshot, _ = build([1], [stats_row(1, 1)])
    out, counts = apply_view(snapshot, view_frame([2]))
    assert out.player_id.tolist() == [1, 2]
    assert counts == {"dropped": 0, "not_in_snapshot": 1}



# ---- the checkout's commit, read from files -----------------------------------------------


def test_a_folder_without_a_git_folder_has_no_commit(tmp_path: Path) -> None:
    assert head_commit(tmp_path) is None


def test_a_detached_head_is_its_own_commit(tmp_path: Path) -> None:
    assert head_commit(git_dir(tmp_path, SHA + "\n")) == SHA


def test_a_branch_ref_is_read_loose_or_packed(tmp_path: Path) -> None:
    root = git_dir(tmp_path, "ref: refs/heads/main\n")
    with pytest.raises(ViewError, match="refs/heads/main"):
        head_commit(root)
    packed = f"# pack-refs\n{'d' * 40} refs/heads/other\n{SHA} refs/heads/main\n"
    (root / ".git" / "packed-refs").write_text(packed, encoding="utf-8")
    assert head_commit(root) == SHA
    (root / ".git" / "refs" / "heads").mkdir(parents=True)
    (root / ".git" / "refs" / "heads" / "main").write_text("e" * 40 + "\n", encoding="utf-8")
    assert head_commit(root) == "e" * 40  # a loose ref wins over a packed one


# ---- giving a data copy its view ----------------------------------------------------------


def test_a_copy_gets_the_view_files_of_the_seasons_asked_for(
    view_dir: Path, tmp_path: Path
) -> None:
    checkout = git_dir(tmp_path / "checkout", SHA)
    copy_view(view_dir, checkout, tmp_path / "copy", ["2026-2027"])
    assert sorted(p.name for p in (tmp_path / "copy" / COPY_VIEW_DIR).iterdir()) == [
        "2026-2027.json", "2026-2027.parquet"]
    assert len(read_view(tmp_path / "copy" / COPY_VIEW_DIR, "2026-2027", 3, SHA)) == 2


def test_a_stale_or_missing_view_is_not_copied(view_dir: Path, tmp_path: Path) -> None:
    checkout = git_dir(tmp_path / "checkout", "f" * 40)
    with pytest.raises(ViewError, match="stale"):
        copy_view(view_dir, checkout, tmp_path / "copy", ["2026-2027"])
    with pytest.raises(ViewError, match=r"no pre-deadline view.*python -m fpl\.pre_deadline"):
        copy_view(view_dir, checkout, tmp_path / "copy", ["2025-2026"])
    assert not (tmp_path / "copy").exists()


# ---- a rebuild never leaves a new table beside an old record -------------------------------


def test_a_crash_while_writing_the_table_leaves_the_view_missing_not_mismatched(
    view_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(self: pd.DataFrame, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", crash)
    with pytest.raises(OSError, match="disk full"):
        write_view(view_dir, "2026-2027", view_frame([2, 3]), checkout_commit="b" * 40)
    monkeypatch.undo()
    with pytest.raises(ViewError, match="missing"):
        read_view(view_dir, "2026-2027", 3, SHA)
    with pytest.raises(ViewError, match="missing"):
        read_view(view_dir, "2026-2027", 3, "b" * 40)


def test_a_view_that_fails_its_schema_leaves_the_old_view_untouched(view_dir: Path) -> None:
    with pytest.raises(ViewError):
        write_view(view_dir, "2026-2027", view_frame([2]).drop(columns="gw"), checkout_commit=SHA)
    assert len(read_view(view_dir, "2026-2027", 3, SHA)) == 2
