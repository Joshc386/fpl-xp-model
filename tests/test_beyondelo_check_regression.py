"""Known-output regression test (Josh's rule for statistical code): the seeded synthetic world
gives these fitted parameters, log-losses and verdict figures. A refactor that changes any of
them changes the check's behaviour; update the numbers only for a deliberate method change."""

from __future__ import annotations

import pytest
from backtest.beyondelo_check import run_check

from beyondelo_check_synth import settings, world

TOL = 1e-9
FITS = {  # slope, cut_away_draw, cut_draw_home
    "ours": (0.004791129235886958, -1.4522797785819053, -0.5880690073448743),
    "beyondelo": (0.00871429951977262, -1.8766811372451184, -0.8914365107874483),
    # The fit window's rates: 16 away wins, 10 draws, 34 home wins of 60.
    "baseline": (0.0, -1.01160091167848, -0.26826398659467926),
}
LOG_LOSS = {  # window -> ours, beyondELO, baseline (nats per match)
    "2025-2026 GW13-18": (0.9996203905116214, 1.0101126891261842, 1.1299146325224392),
    "2026-2027 GW3-10": (0.9422134579720023, 0.9195836918609951, 1.0741209368367066),
    "pooled": (0.9668164290604102, 0.958381833546076, 1.0980325207020203),
}
VERDICT = {"mean": 0.008434595514334401, "sd": 0.2551778378932321, "se": 0.030499585231808516}


def test_the_seeded_world_gives_the_known_fits_and_log_losses() -> None:
    r = run_check(settings(), world(seed=20261117))
    for name, want in FITS.items():
        f = r["fits"][name]
        assert (f.slope, f.cut_away_draw, f.cut_draw_home) == pytest.approx(want, abs=TOL), name
    table = r["log_loss"]["all"].set_index("window")
    for label, want in LOG_LOSS.items():
        got = table.loc[label, ["ours", "beyondelo", "baseline"]].tolist()
        assert got == pytest.approx(list(want), abs=TOL), label
    v = r["verdict"]
    assert v["n"] == 70
    assert [v[k] for k in VERDICT] == pytest.approx(list(VERDICT.values()), abs=TOL)
