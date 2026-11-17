"""The `fpl.export` command line (what update.yml runs) and publish's clean-up after a failed
write. Small synthetic inputs; no data/ checkout and no Excel."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from export_tables import SEASON
from fpl import export
from test_export_build import COMMIT, MCFG, PCFG, built, deadlines, history

FILES = ["elo_ratings.csv", "fixture_difficulty.csv", "meta.csv", "players.csv"]


def stub_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace what `run_export` reads from the upstream checkout with the synthetic season."""
    pcfg = {**PCFG, "current_season": SEASON, "upstream": {"checkout_path": "unused"}}
    monkeypatch.setattr(export, "load_config",
                        lambda path: MCFG if path == export.MODEL_CONFIG else pcfg)
    monkeypatch.setattr(export, "live_deadlines", lambda season: deadlines())
    monkeypatch.setattr(export, "read_upstream_commit", lambda path: COMMIT)
    monkeypatch.setattr(export, "load_history", lambda season, as_of_gw, mode: history())


def test_main_writes_the_four_outputs_with_the_pinned_run_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_inputs(monkeypatch)
    out = tmp_path / "outputs"
    export.main(["--out-dir", str(out), "--run-utc", "2026-09-03T20:00:00Z"])
    assert sorted(p.name for p in out.iterdir()) == FILES
    meta = pd.read_csv(out / "meta.csv", keep_default_na=False)
    assert meta.run_utc.item() == "2026-09-03T20:00:00Z"
    assert (meta.current_gw.item(), meta.next_gw.item()) == (3, 4)


def test_main_passes_both_flags_to_run_export(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    monkeypatch.setattr(export, "run_export", lambda out_dir, run_utc: seen.append((out_dir,
                                                                                    run_utc)))
    export.main(["--out-dir", "somewhere", "--run-utc", "2026-09-03T20:00:00+00:00"])
    export.main(["--out-dir", "other"])
    assert seen[0] == (Path("somewhere"), pd.Timestamp("2026-09-03T20:00:00Z").to_pydatetime())
    assert seen[1] == (Path("other"), None)


def test_main_without_out_dir_is_an_argparse_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(export, "run_export", lambda *a: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as exc:
        export.main(["--run-utc", "2026-09-03T20:00:00Z"])
    assert exc.value.code == 2
    assert "--out-dir" in capsys.readouterr().err


def test_a_write_that_fails_part_way_leaves_no_partial_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, ctx = built()
    target = tmp_path / "out"
    target.mkdir()
    (target / "players.csv").write_text("old", encoding="utf-8")
    real, calls = pd.DataFrame.to_csv, []

    def flaky(self: pd.DataFrame, path: Path, **kw: object) -> None:
        calls.append(path)
        if len(calls) == 3:
            raise OSError("disk full")
        real(self, path, **kw)

    monkeypatch.setattr(pd.DataFrame, "to_csv", flaky)
    with pytest.raises(OSError, match="disk full"):
        export.publish(out, ctx, target)
    assert len(calls) == 3                      # two temporary files were written first
    assert [p.name for p in target.iterdir()] == ["players.csv"]
    assert (target / "players.csv").read_text(encoding="utf-8") == "old"
