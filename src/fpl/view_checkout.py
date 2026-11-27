"""The checkout's commit and the data copy's view, for the pre-deadline view.

A backtest read compares the view's record with the checkout's HEAD, which it reads from the
`.git` files (no process: the backtest harness forbids a predictor's read from starting one). A
data copy (`features.use_data_copy`) holds its own view in `{copy}/pre_deadline`, put there by
`copy_view`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fpl.deadline_view import COMMAND, COPY_VIEW_DIR, ViewError, view_paths


def head_commit(checkout: Path) -> str | None:
    """The commit a checkout's HEAD names, read from its `.git` files (None if `checkout` has no
    `.git` folder, so is not a git checkout).

    No process is started: the backtest harness forbids a predictor's read from starting one.
    Handles a branch ref (loose or packed) and a detached HEAD.
    """
    git_dir = Path(checkout) / ".git"
    if not git_dir.is_dir():
        return None
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    ref = head.removeprefix("ref: ")
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            sha, _, name = line.partition(" ")
            if name == ref and not line.startswith(("#", "^")):
                return sha
    raise ViewError(f"cannot find the commit of {ref} in {git_dir}")


def recorded_commit(view_dir: Path, season: str) -> str | None:
    """The checkout commit a view's record names (None if there is no record)."""
    _, record = view_paths(view_dir, season)
    if not record.exists():
        return None
    return json.loads(record.read_text(encoding="utf-8")).get("checkout_commit")


def copy_view(view_dir: Path, checkout: Path, data_copy: Path, seasons: list[str]) -> None:
    """Give a data copy its view: copy `view_dir`'s files for `seasons` to
    `{data_copy}/pre_deadline`, after checking each was built from `checkout`'s HEAD.

    A read inside a data copy takes its view from there and can't compare it with a checkout
    (it may not open the checkout, or start git), so this is where a stale view is refused.
    Raises `ViewError`, naming the command to run, if a view is missing or stale.
    """
    commit = head_commit(checkout)
    for season in seasons:
        table, record = view_paths(view_dir, season)
        if not table.exists() or not record.exists():
            raise ViewError(f"no pre-deadline view for {season} in {view_dir}; run `{COMMAND}`")
        built = recorded_commit(view_dir, season)
        if built != commit:
            raise ViewError(f"the pre-deadline view for {season} is stale: built from checkout "
                            f"commit {built}, the checkout is at {commit}; run `{COMMAND}`")
    dest = Path(data_copy) / COPY_VIEW_DIR
    dest.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        for path in view_paths(view_dir, season):
            shutil.copy2(path, dest / path.name)
