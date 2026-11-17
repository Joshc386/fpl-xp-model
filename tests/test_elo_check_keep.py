"""The harness never corrupts a match listed in `score_corrections` (brief data rule 16).

The cleaning step fails a read whose upstream score for a listed match is not the entry's
`upstream` score, so every corruption leaves those matches exactly as upstream has them, in
`matches.csv` and `fixtures.csv`, and still corrupts every other selected match.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from backtest.elo_check import corruption, load_settings
from backtest.perturb import Corruption, copy_upstream, corrupt_after, corrupt_up_to, corrupt_within

import synth
from fpl.ingest import ROOT, load_config

SEASON = synth.SEASON
FILES = ["fixtures", "matches"]
BASE = Corruption(score=(0, 9), elo=(1200.0, 2200.0), xg=(0.0, 4.0), prem_tag="prem",
                  offset_minutes=90)
RESULTS = ["home_score", "away_score", "home_team_elo", "away_team_elo", "finished"]


@pytest.fixture
def copies(tmp_path: Path, synth_upstream: tuple[Path, dict]) -> tuple[Path, Path]:
    """(source data dir, scratch data dir)."""
    src = synth_upstream[0] / "data"
    dst = tmp_path / "copy" / "data"
    copy_upstream(src, dst, [SEASON], FILES)
    return src, dst


def read(data_dir: Path, gw: int, name: str = "matches") -> pd.DataFrame:
    path = data_dir / SEASON / "By Gameweek" / f"GW{gw}" / f"{name}.csv"
    return pd.read_csv(path, dtype=str, keep_default_na=False).set_index("match_id")


def listed(src: Path, gw: int, after: pd.Timestamp | None = None) -> str:
    """A Premier League match of GW `gw` (kicking off at or after `after`, if given)."""
    df = read(src, gw)
    rows = df.tournament == "prem"
    if after is not None:
        rows &= pd.to_datetime(df.kickoff_time, utc=True) >= after
    return str(df.index[rows][0])


def assert_kept_and_others_corrupted(src: Path, dst: Path, gw: int, mid: str,
                                     others: pd.Series | None = None) -> None:
    """`mid` is untouched in both files; every other selected match has a new home score."""
    for name in FILES:
        before, after = read(src, gw, name), read(dst, gw, name)
        cols = [c for c in RESULTS if c in before.columns]
        assert after.loc[mid, cols].equals(before.loc[mid, cols])
    before, after = read(src, gw), read(dst, gw)
    sel = (before.tournament == "prem") if others is None else others
    sel = sel & (before.index != mid)
    assert sel.any()
    assert (before.home_score[sel] != after.home_score[sel]).all()


def test_corrupt_up_to_leaves_a_listed_match_alone(copies: tuple[Path, Path]) -> None:
    src, dst = copies
    mid = listed(src, 4)  # GW4, not the blank GW5, so the folder has another match
    corrupt_up_to(dst, SEASON, 4, np.random.default_rng(1), replace(BASE, keep=frozenset({mid})))
    assert_kept_and_others_corrupted(src, dst, 4, mid)


def test_corrupt_after_leaves_a_listed_match_alone(copies: tuple[Path, Path]) -> None:
    src, dst = copies
    mid = listed(src, 8)
    corrupt_after(dst, SEASON, 7, np.random.default_rng(2), replace(BASE, keep=frozenset({mid})))
    assert_kept_and_others_corrupted(src, dst, 8, mid)


def test_corrupt_within_leaves_a_listed_match_alone(copies: tuple[Path, Path]) -> None:
    src, dst = copies
    split = pd.Timestamp(synth.FIRST_KICKOFF + pd.Timedelta(days=49, hours=3))  # GW7, 2nd slot
    mid = listed(src, 7, after=split)
    corrupt_within(dst, SEASON, 7, split, np.random.default_rng(3),
                   replace(BASE, keep=frozenset({mid})))
    m = read(src, 7)
    late = (m.tournament == "prem") & (pd.to_datetime(m.kickoff_time, utc=True) >= split)
    assert_kept_and_others_corrupted(src, dst, 7, mid, others=late)


def test_the_default_keeps_nothing(copies: tuple[Path, Path]) -> None:
    src, dst = copies
    corrupt_up_to(dst, SEASON, 5, np.random.default_rng(1), BASE)
    before, after = read(src, 5), read(dst, 5)
    prem = before.tournament == "prem"
    assert (before.home_score[prem] != after.home_score[prem]).all()


def test_the_keep_set_is_every_listed_match_in_the_pipeline_config() -> None:
    pcfg = load_config(ROOT / "config" / "pipeline.yaml")
    want = {e["match_id"] for e in pcfg["score_corrections"]}
    assert want  # the real config lists at least one (rule 16's first entry)
    assert corruption(load_settings(), pcfg).keep == frozenset(want)


def test_no_score_corrections_means_an_empty_keep_set() -> None:
    pcfg = load_config(ROOT / "config" / "pipeline.yaml")
    assert corruption(load_settings(), {**pcfg, "score_corrections": []}).keep == frozenset()
    without = {k: v for k, v in pcfg.items() if k != "score_corrections"}
    assert corruption(load_settings(), without).keep == frozenset()
