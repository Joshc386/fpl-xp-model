"""The outside-source Elo check on the real 2025/26 data only: fit GW1-26, score GW27-38.

Holdout: the test config keeps only the 2025/26 scored window, and the loaders are wrapped so
the test fails if anything asks for 2026/27. (`outputs/elo_ratings.csv` holds both seasons in
one file; `read_inputs` drops the other season's rows on read.) Skipped when the local data is
missing, as the other real-data tests are. The report goes to `tmp_path`, never to
backtest/reports/. About 15 s.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from backtest.beyondelo_check import read_inputs, run, run_check
from backtest.elo_check import load_settings
from backtest.provenance import run_info

from fpl.beyondelo import load_beyondelo
from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir

log = logging.getLogger(__name__)
Checked = tuple[dict, Path, list[str]]
SEASON = "2025-2026"
CFG = load_config(ROOT / "config" / "pipeline.yaml")
BE = ROOT / CFG["beyondelo"]["external_dir"] / f"{SEASON}.parquet"
NEEDED = [upstream_data_dir(CFG) / SEASON / "By Gameweek" / "GW38", BE,
          ROOT / "outputs" / "elo_ratings.csv", ROOT / "outputs" / "meta.csv"]

pytestmark = pytest.mark.skipif(not all(p.exists() for p in NEEDED),
                                reason="no local upstream checkout, beyondELO table or outputs")


def settings_2025_26() -> dict:
    """backtest/config.yaml with only the 2025/26 windows."""
    s = load_settings()
    c = s["beyondelo_check"]
    c["scored"] = [w for w in c["scored"] if w["season"] == SEASON]
    assert c["fit"]["season"] == SEASON and len(c["scored"]) == 1
    return s


@pytest.fixture(scope="module")
def checked(tmp_path_factory: pytest.TempPathFactory) -> Checked:
    seasons: list[str] = []

    def load(season: str, gw: int, mode: str) -> dict:
        seasons.append(season)
        assert season == SEASON, "the 2025/26 test asked for another season"
        return load_as_of(season, gw, mode)

    def load_be(season: str, base_dir: Path) -> pd.DataFrame:
        seasons.append(season)
        assert season == SEASON, "the 2025/26 test asked for another season"
        return load_beyondelo(season, base_dir)

    s = settings_2025_26()
    inp = read_inputs(s, CFG, ROOT, load, load_be)
    info = run_info(CFG) | {"date": f"{datetime.now(UTC):%Y-%m-%d}"}
    out = run(s, inp, info, tmp_path_factory.mktemp("beyondelo"))
    return run_check(s, inp), out, seasons


def test_only_2025_26_is_read(checked: Checked) -> None:
    r, _, seasons = checked
    assert set(seasons) == {SEASON}
    assert set(r["scored"].season) == {SEASON} and set(r["fit_table"].season) == {SEASON}


def test_the_windows_hold_261_and_119_complete_matches(checked: Checked) -> None:
    r, _, _ = checked
    full = {"finished_result", "our_rating", "beyondelo_rating", "complete"}
    assert r["counts"]["fit"] == {"matches": 261} | dict.fromkeys(full, 261)
    assert r["counts"][f"{SEASON} GW27-38"] == {"matches": 119} | dict.fromkeys(full, 119)


def test_the_baseline_is_the_fit_windows_rates_and_every_figure_is_finite(checked: Checked) -> None:
    r, _, _ = checked
    y = r["fit_table"].result
    b = r["fits"]["baseline"]
    away, draw = (y == 0).mean(), (y == 1).mean()
    assert b.cut_away_draw == pytest.approx(math.log(away / (1 - away)), abs=1e-9)
    assert b.cut_draw_home == pytest.approx(math.log((away + draw) / (1 - away - draw)), abs=1e-9)
    assert r["fits"]["ours"].slope > 0 and r["fits"]["beyondelo"].slope > 0
    t = r["log_loss"]["all"]
    assert t[["ours", "beyondelo", "baseline"]].notna().all().all()
    for x in r["ranking"]:
        assert x["by_gw"].n.min() >= 14 and x["by_gw"].spearman.notna().all()


def test_the_promoted_clubs_are_burnley_leeds_and_sunderland(checked: Checked) -> None:
    r, _, _ = checked
    assert r["promoted"] == {SEASON: ["Burnley", "Leeds", "Sunderland"]}


def test_the_report_is_written_to_the_temporary_folder_with_the_credit(checked: Checked) -> None:
    r, out, _ = checked
    assert out.name.endswith("-beyondelo.md") and "backtest" not in out.parent.parts[-2:]
    text = out.read_text(encoding="utf-8")
    assert "beyondELO (https://beyondelo.com)" in text and "CC BY 4.0" in text
    assert "2026-2027" not in text
    log.info("log-loss, all matches:\n%s", r["log_loss"]["all"].to_string())
    log.info("log-loss, without promoted clubs:\n%s",
             r["log_loss"]["without_promoted"].to_string())
    log.info("verdict %s", {k: r["verdict"][k] for k in (
        "n", "mean", "sd", "se", "threshold", "worse_than_beyondelo", "not_below_baseline",
        "poor")})
    log.info("fits %s", {k: (f.slope, f.cut_away_draw, f.cut_draw_home, f.iterations)
                         for k, f in r["fits"].items()})
    log.info("ranking %s", {x["window"]: (x["median"], x["min"]) for x in r["ranking"]})
