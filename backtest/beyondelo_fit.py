"""The outside-source Elo check's ordered logistic fit and verdict (brief section 7, `CONTEXT.md`
**Predictive log-loss** and **Poor Elo rating**). Pure numpy: no data access.

The result of a match is away win, draw or home win (0, 1, 2). With gap g (home minus away
before-match rating) and parameters slope b and cut-points c1 < c2:
P(away) = F(c1 - b g), P(away or draw) = F(c2 - b g), F the logistic function. The no-skill
baseline is the same model with b = 0, so it predicts the fit window's away, draw and home rates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AWAY, DRAW, HOME = 0, 1, 2
OUTCOMES = {AWAY: "away win", DRAW: "draw", HOME: "home win"}


class FitError(RuntimeError):
    """No finite maximum-likelihood fit: an outcome is missing, the gap separates the
    outcomes, or Newton-Raphson didn't converge."""


@dataclass(frozen=True)
class OrderedFit:
    """A fitted ordered logistic model. `slope` is 0 for the no-skill baseline."""

    slope: float
    cut_away_draw: float
    cut_draw_home: float
    n: int
    iterations: int
    loglik: float


def _cdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -x))


def _check_finite_fit(gap: np.ndarray | None, y: np.ndarray) -> None:
    """Raise `FitError` when the likelihood has no finite, unique maximum.

    Every outcome must occur. With a gap, the maximum is infinite or not unique when the gaps,
    grouped by outcome, are sorted (allowing ties) in either direction: the slope can then grow
    without bound while the cut-points follow.
    """
    missing = [OUTCOMES[k] for k in (AWAY, DRAW, HOME) if not (y == k).any()]
    if missing:
        raise FitError(f"no finite fit: no {', no '.join(missing)} among {len(y)} matches")
    if gap is None:
        return
    lo = [gap[y == k].min() for k in (AWAY, DRAW, HOME)]
    hi = [gap[y == k].max() for k in (AWAY, DRAW, HOME)]
    rising = hi[AWAY] <= lo[DRAW] and hi[DRAW] <= lo[HOME]
    falling = lo[AWAY] >= hi[DRAW] and lo[DRAW] >= hi[HOME]
    if rising or falling:
        raise FitError(f"no finite fit: the gap separates the outcomes of {len(y)} matches")


def _bounds(params: np.ndarray, gap: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, ...]:
    """Each match's upper and lower linear predictor and their derivatives by parameter.

    Parameters are (c1, c2) or (c1, c2, b). An infinite bound (upper for a home win, lower
    for an away win) has a zero derivative row.
    """
    n, k = len(y), len(params)
    cuts = np.array([-np.inf, params[0], params[1], np.inf])
    eta = params[2] * gap if k == 3 else np.zeros(n)
    up, lo = cuts[y + 1] - eta, cuts[y] - eta
    d_up, d_lo = np.zeros((n, k)), np.zeros((n, k))
    rows = np.arange(n)
    has_up, has_lo = y < HOME, y > AWAY
    d_up[rows[has_up], y[has_up]] = 1.0
    d_lo[rows[has_lo], y[has_lo] - 1] = 1.0
    if k == 3:
        d_up[has_up, 2] = -gap[has_up]
        d_lo[has_lo, 2] = -gap[has_lo]
    return up, lo, d_up, d_lo


def _loglik(params: np.ndarray, gap: np.ndarray, y: np.ndarray) -> float:
    if params[0] >= params[1]:
        return -np.inf
    up, lo, _, _ = _bounds(params, gap, y)
    p = _cdf(up) - _cdf(lo)
    return float(np.log(p).sum()) if (p > 0).all() else -np.inf


def _newton_step(params: np.ndarray, gap: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """The Newton step and the Newton decrement's half square (the log-likelihood a full step
    is predicted to gain)."""
    up, lo, d_up, d_lo = _bounds(params, gap, y)
    fu, fl = _cdf(up), _cdf(lo)
    p = fu - fl
    du, dl = fu * (1 - fu), fl * (1 - fl)
    g_i = (du[:, None] * d_up - dl[:, None] * d_lo) / p[:, None]
    wu, wl = du * (1 - 2 * fu) / p, dl * (1 - 2 * fl) / p
    hess = (d_up.T * wu) @ d_up - (d_lo.T * wl) @ d_lo - g_i.T @ g_i
    grad = g_i.sum(axis=0)
    try:
        step = -np.linalg.solve(hess, grad)
    except np.linalg.LinAlgError as exc:
        raise FitError(f"no finite fit: singular Hessian ({exc})") from exc
    return step, float(grad @ step) / 2


def fit_ordered(gap: np.ndarray | None, y: np.ndarray, tol: float, max_iterations: int,
                max_halvings: int) -> OrderedFit:
    """Maximum-likelihood ordered logistic fit of outcomes `y` on `gap` (None: the baseline).

    Newton-Raphson from the baseline's exact fit, halving a step (at most `max_halvings`
    times, `_line_search`) until the log-likelihood doesn't fall. Converged when the Newton
    decrement's half square, the predicted gain of a full step, is at most `tol` nats. It is
    invariant to the gap's scale, so a source whose ratings are an affine transform of
    another's gets the same fit. Raises `FitError` if no finite fit exists or it doesn't
    converge in `max_iterations` steps.
    """
    y = np.asarray(y, dtype="int64")
    g = None if gap is None else np.asarray(gap, dtype="float64")
    if g is not None and not np.isfinite(g).all():
        raise FitError("a gap is missing or infinite")
    _check_finite_fit(g, y)
    n = len(y)
    share = np.cumsum([(y == k).sum() for k in (AWAY, DRAW)]) / n
    params = np.log(share / (1 - share))
    if g is not None:
        params = np.append(params, 0.0)
    gv = np.zeros(n) if g is None else g
    ll = _loglik(params, gv, y)
    for it in range(max_iterations + 1):
        step, gain = _newton_step(params, gv, y)
        if gain <= tol:
            slope = float(params[2]) if g is not None else 0.0
            return OrderedFit(slope, float(params[0]), float(params[1]), n, it, ll)
        if it == max_iterations:
            break
        params, ll = _line_search(params, step, ll, gv, y, max_halvings)
    raise FitError(f"Newton-Raphson didn't converge in {max_iterations} iterations "
                   f"(predicted gain {gain:.3g} nats, tolerance {tol:g})")


def _line_search(params: np.ndarray, step: np.ndarray, ll: float, gap: np.ndarray,
                 y: np.ndarray, max_halvings: int) -> tuple[np.ndarray, float]:
    """`params + t * step` and its log-likelihood, for the largest t in 1, 1/2, 1/4 ... (at
    most `max_halvings` halvings) whose log-likelihood isn't below `ll`.

    Raises `FitError` if none is: the step isn't an ascent direction, which for this concave
    log-likelihood means a numerical failure.
    """
    t = 1.0
    for _ in range(max_halvings + 1):
        new = params + t * step
        new_ll = _loglik(new, gap, y)
        if new_ll >= ll:
            return new, new_ll
        t /= 2
    raise FitError(f"Newton-Raphson step found no improvement after {max_halvings} halvings")


def probabilities(fit: OrderedFit, gap: np.ndarray | None, n: int | None = None) -> np.ndarray:
    """Each match's (away, draw, home) probabilities: an n x 3 array. With no gap (the
    baseline), `n` gives the number of matches."""
    g = np.zeros(n) if gap is None else np.asarray(gap, dtype="float64")
    eta = fit.slope * g
    a, ad = _cdf(fit.cut_away_draw - eta), _cdf(fit.cut_draw_home - eta)
    return np.column_stack([a, ad - a, 1 - ad])


def match_nll(fit: OrderedFit, gap: np.ndarray | None, y: np.ndarray) -> np.ndarray:
    """Each match's -ln(probability given to its actual result), in nats."""
    y = np.asarray(y, dtype="int64")
    p = probabilities(fit, gap, len(y))
    return -np.log(p[np.arange(len(y)), y])


def poor_elo_verdict(ours: np.ndarray, theirs: np.ndarray, base: np.ndarray, k: float,
                     decimals: int) -> dict:
    """The **Poor Elo rating** verdict from each scored match's -ln p under our ratings,
    beyondELO's and the no-skill baseline.

    Condition 1: the mean of (ours - theirs) per match is above zero by more than `k` standard
    errors, SE = sd (ddof 1) / sqrt(n). Condition 2: our mean log-loss isn't below the
    baseline's. Both comparisons are made after rounding to `decimals`, so floating-point noise
    (an affine copy of our ratings, an exact tie on the two-SE line) doesn't decide them.
    """
    ours, theirs, base = (np.asarray(a, dtype="float64") for a in (ours, theirs, base))
    n = len(ours)
    if n < 2:
        raise ValueError(f"the verdict needs at least 2 matches, got {n}")
    d = ours - theirs
    mean, sd = float(d.mean()), float(d.std(ddof=1))
    se = sd / np.sqrt(n)
    threshold = k * se
    worse = round(mean, decimals) > round(threshold, decimals)
    not_below = round(float(ours.mean()), decimals) >= round(float(base.mean()), decimals)
    return {"n": n, "ours": float(ours.mean()), "beyondelo": float(theirs.mean()),
            "baseline": float(base.mean()), "mean": mean, "sd": sd, "se": float(se),
            "threshold": float(threshold), "worse_than_beyondelo": bool(worse),
            "not_below_baseline": bool(not_below), "poor": bool(worse or not_below)}
