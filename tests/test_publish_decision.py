"""The publish decision: skip when upstream is unchanged, publish otherwise, fail on a bad meta."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fpl.ingest import ROOT
from fpl.publish_decision import DEFAULT_META, PublishDecisionError, decide, main

SHA = "ac8be9ca" + "0" * 32
OTHER = "1234abcd" + "0" * 32
HEADER = "run_utc,upstream_commit,status"


def write_meta(path: Path, *rows: str, header: str = HEADER) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8", newline="\n")
    return path


def meta_with(tmp_path: Path, sha: str) -> Path:
    return write_meta(tmp_path / "meta.csv", f"2026-11-16T08:00:00Z,{sha},ok")


def test_same_sha_skips(tmp_path: Path) -> None:
    assert decide(SHA, meta_with(tmp_path, SHA)) is False


def test_different_sha_publishes(tmp_path: Path) -> None:
    assert decide(SHA, meta_with(tmp_path, OTHER)) is True


@pytest.mark.parametrize("published", [SHA.upper(), f"  {SHA}\n", f" {SHA.upper()} "])
def test_a_sha_differing_only_in_case_or_whitespace_skips(tmp_path: Path, published: str) -> None:
    assert decide(SHA, meta_with(tmp_path, f'"{published}"')) is False


def test_the_checkout_sha_is_normalised_too(tmp_path: Path) -> None:
    assert decide(f"{SHA.upper()}\n", meta_with(tmp_path, SHA)) is False


def test_no_meta_file_publishes(tmp_path: Path) -> None:
    assert decide(SHA, tmp_path / "missing.csv") is True


def test_an_empty_checkout_sha_fails(tmp_path: Path) -> None:
    with pytest.raises(PublishDecisionError, match="upstream SHA"):
        decide("  ", meta_with(tmp_path, SHA))


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (b"", "cannot read"),
        (b"\xff\xfe\x00garbage", "cannot read"),
        (b"run_utc,status\n2026-11-16T08:00:00Z,ok\n", "no upstream_commit column"),
        (b"run_utc,upstream_commit\n", "exactly one"),
        (
            b"run_utc,upstream_commit\nt1,aaa\nt2,bbb\n",
            "exactly one",
        ),
        (b"run_utc,upstream_commit\nt1,\n", "empty"),
        (b'run_utc,upstream_commit\nt1,"unterminated\n', "cannot read"),
    ],
)
def test_an_unusable_meta_file_fails_loudly(tmp_path: Path, content: bytes, match: str) -> None:
    path = tmp_path / "meta.csv"
    path.write_bytes(content)
    with pytest.raises(PublishDecisionError, match=match):
        decide(SHA, path)


def test_a_directory_in_place_of_meta_fails(tmp_path: Path) -> None:
    with pytest.raises(PublishDecisionError, match="cannot read"):
        decide(SHA, tmp_path)


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway git repo with one commit, and that commit's SHA."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    env = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), *env, "commit", "-q", "--allow-empty", "-m", "x"],
                   check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


@pytest.mark.parametrize(("same", "expected"), [(True, "false"), (False, "true")])
def test_main_writes_the_result_to_github_output(
    tmp_path: Path, checkout: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
    same: bool, expected: str,
) -> None:
    repo, sha = checkout
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    meta = meta_with(tmp_path, sha if same else OTHER)
    main(["--checkout", str(repo), "--meta", str(meta)])
    assert out.read_text(encoding="utf-8") == f"publish={expected}\n"


def test_main_without_github_output_still_runs(
    tmp_path: Path, checkout: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, _ = checkout
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    main(["--checkout", str(repo), "--meta", str(tmp_path / "missing.csv")])
    assert "publish=true" in capsys.readouterr().out


def test_main_exits_non_zero_on_a_bad_meta_and_writes_nothing(
    tmp_path: Path, checkout: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = checkout
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    meta = tmp_path / "meta.csv"
    meta.write_text("run_utc\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--checkout", str(repo), "--meta", str(meta)])
    assert exc.value.code != 0
    assert not out.exists()


def test_main_exits_non_zero_when_the_checkout_is_not_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(SystemExit) as exc:
        main(["--checkout", str(plain), "--meta", str(tmp_path / "meta.csv")])
    assert exc.value.code != 0


def test_an_all_digit_sha_is_read_as_text(tmp_path: Path) -> None:
    """Without dtype=str, pandas reads 1234...e... style or all-digit SHAs as numbers."""
    digits = "1" * 40
    assert decide(digits, meta_with(tmp_path, digits)) is False
    assert decide("0" * 39 + "1", meta_with(tmp_path, "0" * 39 + "1")) is False


def test_the_default_meta_path_is_outputs_meta_csv_under_the_repo_root() -> None:
    assert DEFAULT_META == ROOT / "outputs" / "meta.csv"
