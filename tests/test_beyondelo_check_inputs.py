"""What the outside-source Elo check reads: only the configured seasons, results through the
loader at each season's last window gameweek, and the hashes of every file read."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd
import pytest
from backtest import beyondelo_check as bc
from backtest.beyondelo_check import read_inputs, run_check
from backtest.beyondelo_data import CheckError

from beyondelo_check_frames import PREM
from beyondelo_check_synth import NAMES, S1, S2, settings, world

PCFG = {"premier_league_tag": PREM, "beyondelo": {"external_dir": "data/external/beyondelo"}}


class Fakes:
    """Stand-ins for `load_as_of` and `load_beyondelo` over the synthetic world, on files
    written under `root` (so the hashes are of real files)."""

    def __init__(self, root: Path) -> None:
        self.w = world()
        self.root = root
        self.loads: list[tuple[str, int, str]] = []
        self.be_loads: list[tuple[str, Path]] = []
        (root / "outputs").mkdir()
        self.w.ours.to_csv(root / "outputs" / "elo_ratings.csv", index=False)
        pd.DataFrame({"upstream_commit": ["6df7a43"]}).to_csv(root / "outputs" / "meta.csv",
                                                              index=False)
        be = root / PCFG["beyondelo"]["external_dir"]
        be.mkdir(parents=True)
        for season, df in self.w.beyondelo.items():
            df.to_parquet(be / f"{season}.parquet")

    def load(self, season: str, as_of: int, mode: str) -> dict[str, pd.DataFrame]:
        self.loads.append((season, as_of, mode))
        f = self.w.fixtures[season]
        return {"fact_fixture": f[f.gw <= as_of],
                "dim_team": NAMES.rename("name").rename_axis("team_id").reset_index()}

    def load_be(self, season: str, base_dir: Path) -> pd.DataFrame:
        self.be_loads.append((season, base_dir))
        return pd.read_parquet(base_dir / f"{season}.parquet")

    def read(self, s: dict) -> bc.Inputs:
        return read_inputs(s, PCFG, self.root, self.load, self.load_be)


def only_2025_26(s: dict) -> dict:
    s["beyondelo_check"]["scored"] = s["beyondelo_check"]["scored"][:1]
    return s


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_results_are_read_once_per_season_at_its_last_window_gameweek(tmp_path: Path) -> None:
    f = Fakes(tmp_path)
    inp = f.read(settings())
    assert f.loads == [(S1, 18, "backtest"), (S2, 10, "backtest")]
    assert [s for s, _ in f.be_loads] == [S1, S2]
    assert f.be_loads[0][1] == tmp_path / "data" / "external" / "beyondelo"
    assert inp.fixtures[S2].gw.max() == 10 and inp.prem == PREM


def test_a_config_with_no_2026_27_window_never_reads_2026_27(tmp_path: Path) -> None:
    f = Fakes(tmp_path)
    inp = f.read(only_2025_26(settings()))
    assert f.loads == [(S1, 18, "backtest")] and [s for s, _ in f.be_loads] == [S1]
    assert set(inp.ours.season) == {S1} and set(inp.beyondelo) == {S1}


def test_every_file_read_is_hashed_and_meta_gives_the_publish_commit(tmp_path: Path) -> None:
    f = Fakes(tmp_path)
    inp = f.read(settings())
    be = tmp_path / "data" / "external" / "beyondelo"
    assert inp.hashes == {
        "outputs/elo_ratings.csv": sha(tmp_path / "outputs" / "elo_ratings.csv"),
        f"data/external/beyondelo/{S1}.parquet": sha(be / f"{S1}.parquet"),
        f"data/external/beyondelo/{S2}.parquet": sha(be / f"{S2}.parquet"),
    }
    assert inp.meta_upstream_commit == "6df7a43"


def test_the_files_read_back_give_the_same_check_as_the_frames(tmp_path: Path) -> None:
    f = Fakes(tmp_path)
    a, b = run_check(settings(), f.w), run_check(settings(), f.read(settings()))
    assert a["verdict"] == b["verdict"]
    pd.testing.assert_frame_equal(a["log_loss"]["all"], b["log_loss"]["all"])


def test_a_ratings_file_without_the_hand_off_columns_stops(tmp_path: Path) -> None:
    f = Fakes(tmp_path)
    f.w.ours.drop(columns="elo_before").to_csv(tmp_path / "outputs" / "elo_ratings.csv",
                                               index=False)
    with pytest.raises(CheckError, match="elo_before"):
        f.read(settings())


def test_main_stops_with_a_plain_message_and_no_report(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    f = Fakes(tmp_path)
    s = settings() | {"report_dir": str(tmp_path / "reports")}
    broken = f.read(s)
    broken.ours = broken.ours.iloc[1:]
    monkeypatch.setattr(bc, "load_settings", lambda: s)
    monkeypatch.setattr(bc, "load_config", lambda path: PCFG)
    monkeypatch.setattr(bc, "read_inputs", lambda *a, **k: broken)
    monkeypatch.setattr(bc, "run_info", lambda pcfg: {"commit": "c0ffee"})
    with caplog.at_level(logging.ERROR):
        assert bc.main() == 1
    assert "lacks a partner" in caplog.text
    assert not (tmp_path / "reports").exists()


def test_main_writes_the_dated_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = Fakes(tmp_path)
    s = settings() | {"report_dir": str(tmp_path / "reports")}
    monkeypatch.setattr(bc, "load_settings", lambda: s)
    monkeypatch.setattr(bc, "load_config", lambda path: PCFG)
    monkeypatch.setattr(bc, "read_inputs", lambda *a, **k: f.read(s))
    monkeypatch.setattr(bc, "run_info", lambda pcfg: {"commit": "c0ffee"})
    assert bc.main() == 0
    [out] = list((tmp_path / "reports").iterdir())
    assert out.name.endswith("-beyondelo.md") and "c0ffee" in out.read_text(encoding="utf-8")
