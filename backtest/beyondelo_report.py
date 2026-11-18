"""The outside-source Elo check's markdown report (`backtest/reports/{date}-beyondelo.md`)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

from backtest.md import table

if TYPE_CHECKING:
    from backtest.beyondelo_check import Inputs

CREDIT = "Ratings from beyondELO (https://beyondelo.com), CC BY 4.0."
SOURCES = (("ours", "Ours"), ("beyondelo", "beyondELO"), ("baseline", "Baseline"))


def _f(x: float, spec: str) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else format(x, spec)


def _verdict(r: dict) -> list[str]:
    v, c = r["verdict"], r["settings"]["beyondelo_check"]
    k = c["se_multiple"]
    head = ("**Poor Elo rating**" if v["poor"] else "**Not a poor Elo rating**")
    rows = [
        [f"1. Ours minus beyondELO's, mean per match, above zero by more than {k} SE",
         _f(v["mean"], ".6f"), _f(v["sd"], ".6f"), v["n"], _f(v["se"], ".6f"),
         _f(v["threshold"], ".6f"), "yes" if v["worse_than_beyondelo"] else "no"],
    ]
    second = [["2. Our log-loss isn't below the baseline's", _f(v["ours"], ".6f"),
               _f(v["baseline"], ".6f"), _f(v["ours"] - v["baseline"], ".6f"),
               "yes" if v["not_below_baseline"] else "no"]]
    return [
        "## Verdict", "",
        f"{head}, on the pooled scored windows ({v['n']} matches). A poor rating needs either "
        f"condition; both comparisons are made after rounding to {c['compare_decimals']} "
        "decimals. SE is the differences' sd (ddof 1) divided by the square root of n.", "",
        table(["Condition", "Mean", "SD", "n", "SE", f"{k} SE", "Fires"], rows), "",
        table(["Condition", "Ours (nats)", "Baseline (nats)", "Ours minus baseline", "Fires"],
              second), "",
    ]


def _log_loss(t: pd.DataFrame) -> str:
    rows = [[x.window, x.n, _f(x.ours, ".4f"), _f(x.beyondelo, ".4f"), _f(x.baseline, ".4f"),
             _f(x.ours - x.beyondelo, ".4f")] for x in t.itertuples()]
    return table(["Window", "Matches", "Ours", "beyondELO", "Baseline", "Ours minus beyondELO"],
                 rows)


def _log_losses(r: dict) -> list[str]:
    promoted = [f"- {season}: {', '.join(names) if names else 'none'}"
                for season, names in r["promoted"].items()]
    return [
        "## Predictive log-loss", "",
        "Nats per match, lower is better: the mean over scored matches of -ln(probability "
        "given to the actual result).", "",
        "### All scored matches", "", _log_loss(r["log_loss"]["all"]), "",
        "### Without matches involving a promoted club", "",
        "No verdict of its own. The fits are the same (every fit-window match); only matches "
        "with a promoted club on either side are left out of the scoring.", "",
        _log_loss(r["log_loss"]["without_promoted"]), "",
        "Promoted clubs (beyondELO's `promoted` flag):", "", *promoted, "",
    ]


def _fits(r: dict) -> list[str]:
    fit = r["fit_table"]
    rows = [[label, f.n, _f(f.slope, ".6g"), _f(f.cut_away_draw, ".6f"),
             _f(f.cut_draw_home, ".6f"), f.iterations, _f(f.loglik, ".4f")]
            for name, label in SOURCES for f in [r["fits"][name]]]
    w = r["settings"]["beyondelo_check"]["fit"]
    return [
        "## Fitted parameters", "",
        f"Ordered logistic fit of the result on the before-match gap (home minus away), once "
        f"per source on {w['season']} GW{w['gameweeks'][0]}-{w['gameweeks'][1]} "
        f"({len(fit)} matches). P(away win) = F(cut away/draw - slope x gap), "
        "P(away win or draw) = F(cut draw/home - slope x gap), F logistic. The baseline has no "
        "gap.", "",
        table(["Source", "n", "Slope", "Cut away/draw", "Cut draw/home", "Iterations",
               "Log-likelihood"], rows), "",
    ]


def _ranking(r: dict) -> list[str]:
    out = ["## Ranking agreement", "",
           "A diagnostic with no pass mark: Spearman's rank correlation of our `elo_before` with "
           "`beyondelo_before` over each gameweek's team-kickoffs (a double gameweek counts "
           "each kickoff; ties take their average rank).", ""]
    for x in r["ranking"]:
        gws = [[g.gw, g.n, _f(g.spearman, ".3f")] for g in x["by_gw"].itertuples()]
        d = [[y.team, y.match_id, _f(y.elo_before, ".1f"), _f(y.our_rank, "g"),
              _f(y.beyondelo_before, ".1f"), _f(y.beyondelo_rank, "g"), _f(y.rank_gap, "g")]
             for y in x["disagreements"].itertuples()]
        out += [f"### {x['window']}", "",
                f"Spearman: median {_f(x['median'], '.3f')}, minimum {_f(x['min'], '.3f')}.",
                "", table(["GW", "Team-kickoffs", "Spearman"], gws), "",
                f"The {len(d)} biggest rank disagreements at GW{x['last_gw']} (rank 1 is the "
                "highest rating):", "",
                table(["Club", "Match", "Ours", "Our rank", "beyondELO", "beyondELO rank",
                       "Rank gap"], d), ""]
    return out


def _counts(r: dict) -> list[str]:
    rows = [[name, c["matches"], c["finished_result"], c["our_rating"], c["beyondelo_rating"],
             c["complete"]] for name, c in r["counts"].items()]
    return ["## Match counts", "",
            "A match is in a window if a fixture, our ratings or beyondELO's place it there. "
            "The run stops, with no report, if any lacks a partner.", "",
            table(["Window", "Matches", "Finished result", "Our rating", "beyondELO rating",
                   "Complete"], rows), ""]


def _provenance(info: dict, inp: Inputs) -> list[str]:
    rows = [[k, v] for k, v in info.items()]
    rows.append(["upstream_commit in outputs/meta.csv (the publish elo_ratings.csv came from)",
                 inp.meta_upstream_commit or "(empty)"])
    rows += [[f"sha256 {path}", h] for path, h in inp.hashes.items()]
    return ["## Provenance", "",
            "`upstream_commit` is the local checkout that `load_as_of` read the results from.",
            "", table(["Item", "Value"], rows), ""]


def render(r: dict, info: dict, inp: Inputs) -> str:
    """The report: verdict, log-loss tables, fits, ranking agreement, counts, provenance and
    beyondELO's credit line. `inp` is the run's `Inputs` (file hashes, meta's commit)."""
    lines = [f"# Outside-source Elo check: {info.get('date', '')}", "", CREDIT, "",
             *_verdict(r), *_log_losses(r), *_fits(r), *_ranking(r), *_counts(r),
             *_provenance(info, inp), "## Credit", "", CREDIT, ""]
    return "\n".join(lines)
