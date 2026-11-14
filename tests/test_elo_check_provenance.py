"""Provenance of an Elo check run: git state on one line, the harness hash, the report path."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from backtest.provenance import _git, harness_sha256, report_path, run_info, status_summary

from fpl.ingest import ROOT, load_config

PCFG = load_config(ROOT / "config" / "pipeline.yaml")
CHECKOUT = ROOT / PCFG["upstream"]["checkout_path"]


def test_a_clean_status_is_yes() -> None:
    assert status_summary("") == "yes"


def test_a_dirty_status_is_one_line_with_counts_and_paths() -> None:
    text = " M src/fpl/clean.py\nMM config/pipeline.yaml\n?? src/fpl/export.py\n?? src/fpl/x.py"
    out = status_summary(text)
    assert "\n" not in out
    assert out == ("no: 2 modified, 2 untracked (src/fpl/clean.py, config/pipeline.yaml, "
                   "src/fpl/export.py, src/fpl/x.py)")


def test_a_status_never_breaks_a_markdown_table() -> None:
    assert "|" not in status_summary("?? src/fpl/a|b.py").replace("\\|", "")


def test_a_rename_shows_the_new_path() -> None:
    assert status_summary("R  src/a.py -> src/b.py") == "no: 1 modified, 0 untracked (src/b.py)"


def test_the_harness_hash_covers_code_and_settings_but_not_reports(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "config.yaml").write_text("k: 2\n")
    first = harness_sha256(tmp_path)
    (tmp_path / "reports" / "2026-11-14.md").write_text("notes")
    assert harness_sha256(tmp_path) == first
    (tmp_path / "config.yaml").write_text("k: 3\n")
    second = harness_sha256(tmp_path)
    assert second != first
    (tmp_path / "a.py").write_text("x = 2\n")
    assert harness_sha256(tmp_path) not in (first, second)
    assert re.fullmatch(r"[0-9a-f]{64}", first)


def test_an_existing_dated_report_is_never_overwritten(tmp_path: Path) -> None:
    assert report_path(tmp_path, "2026-11-14") == tmp_path / "2026-11-14.md"
    (tmp_path / "2026-11-14.md").write_text("hand-written notes")
    assert report_path(tmp_path, "2026-11-14") == tmp_path / "2026-11-14-2.md"
    (tmp_path / "2026-11-14-2.md").write_text("second run")
    assert report_path(tmp_path, "2026-11-14") == tmp_path / "2026-11-14-3.md"


@pytest.mark.skipif(not (ROOT / ".git").exists() or not CHECKOUT.exists(),
                    reason="no git checkout of the repo or of upstream")
def test_run_info_records_the_commits_hashes_and_cleanliness() -> None:
    info = run_info(PCFG)
    assert re.fullmatch(r"[0-9a-f]{40}", info["commit"])
    for key in ("model_yaml_sha256", "settings_sha256", "harness_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", info[key])
    for key in ("code_clean", "harness_clean", "upstream_clean"):
        assert "\n" not in info[key] and info[key].split(":")[0] in ("yes", "no")
    model = yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))
    assert info["model_version"] == str(model.get("model_version") or "unset")


def test_git_status_read_through_git_keeps_the_first_path_whole(tmp_path: Path) -> None:
    """The first porcelain line starts with a space (" M a.txt"); stripping it cut the path."""
    git = ["-C", str(tmp_path)]
    _git(*git, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(*git, "add", "a.txt")
    _git(*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    (tmp_path / "a.txt").write_text("2")
    assert status_summary(_git(*git, "status", "--porcelain")) == (
        "no: 1 modified, 0 untracked (a.txt)")


def git_repo(path: Path, files: dict[str, str]) -> None:
    """A git repo at `path` with `files` committed."""
    path.mkdir(parents=True)
    _git("-C", str(path), "init", "-q")
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    _git("-C", str(path), "add", ".")
    _git("-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")


def test_run_info_counts_untracked_code_and_upstream_changes(tmp_path: Path) -> None:  # N19
    root, up = tmp_path / "repo", tmp_path / "upstream"
    git_repo(root, {"config/model.yaml": 'model_version: "9.9"\n', "src/fpl/a.py": "x = 1\n"})
    git_repo(up, {"data/f.csv": "a\n1\n"})
    pcfg = {"upstream": {"checkout_path": str(up)}}
    clean = run_info(pcfg, root=root)
    assert (clean["code_clean"], clean["upstream_clean"]) == ("yes", "yes")
    assert clean["model_version"] == "9.9"
    (root / "src" / "fpl" / "new.py").write_text("y = 2\n")
    (up / "data" / "f.csv").write_text("a\n2\n")
    dirty = run_info(pcfg, root=root)
    assert dirty["code_clean"] == "no: 0 modified, 1 untracked (src/fpl/new.py)"
    assert dirty["upstream_clean"] == "no: 1 modified, 0 untracked (data/f.csv)"
