"""Build `ext_beyondelo` from beyondELO's matches and our processed tables. Pure functions, no I/O.

Two rows per Premier League match, one per club, keyed to our `team_id` and `match_id`. Clubs are
matched by exact name (plus the configured aliases), matches by home club, away club and date
(exact: our Premier League kickoffs are at most 20:00 UTC, so no kickoff crosses midnight in
either source). Every row dropped on either side is counted by reason; a finished match of ours
with no partner, or with a different score, fails the build.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

REQUIRED = [
    "id", "date", "season", "home", "away", "home_score", "away_score",
    "home_elo_before", "home_elo_after", "away_elo_before", "away_elo_after",
]
ELO = REQUIRED[-4:]
OUT_COLUMNS = [
    "team_id", "match_id", "season", "gw", "kickoff_utc", "home", "beyondelo_before",
    "beyondelo_after", "promoted", "beyondelo_match_id",
]
KEY = ["home_team_id", "away_team_id", "date"]


class BuildError(ValueError):
    """The beyondELO data and our tables do not reconcile, so no table is written.

    `refresh` is true when a re-pull could help (beyondELO has not caught up with a finished match).
    """

    def __init__(self, message: str, refresh: bool = False) -> None:
        super().__init__(message)
        self.refresh = refresh


def to_date(value: object) -> str:
    """The UTC calendar date (YYYY-MM-DD) of a date or datetime value."""
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            raise ValueError("empty")
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC")
        return ts.strftime("%Y-%m-%d")
    except (ValueError, TypeError) as exc:
        raise BuildError(f"unreadable beyondELO date {value!r}") from exc


def matches_frame(records: list[dict], max_wrong_share: float) -> pd.DataFrame:
    """beyondELO's records as a checked frame with `date` (UTC date) and `played`.

    Fails if more than `max_wrong_share` of the decided matches have a rating that moved the
    wrong way (`_check_rating_direction`). The season of each record is checked by the pull.
    """
    if not records:
        empty = pd.DataFrame({c: pd.Series(dtype="object") for c in REQUIRED})
        return empty.assign(played=pd.Series(dtype="bool"))
    missing = sorted({c for r in records for c in REQUIRED if c not in r})
    if missing:
        raise BuildError(f"beyondELO matches lack fields {missing}")
    df = pd.DataFrame.from_records(records)
    if df["id"].duplicated().any():
        raise BuildError("beyondELO returned a duplicate match id")
    df = df[REQUIRED].copy()
    df["id"] = df["id"].astype(str)
    df["date"] = df["date"].map(to_date)
    try:
        for c in ["home_score", "away_score", *ELO]:
            df[c] = pd.to_numeric(df[c], errors="raise").astype("float64")
    except (ValueError, TypeError) as exc:
        raise BuildError(f"a beyondELO score or rating is not numeric: {exc}") from exc
    scores = df[["home_score", "away_score"]].notna()
    if (scores.any(axis=1) & ~scores.all(axis=1)).any():
        raise BuildError("a beyondELO match has only one score")
    df["played"] = scores.all(axis=1)
    bad = df.loc[df["played"] & df[ELO].isna().any(axis=1), "id"].tolist()
    if bad:
        raise BuildError(f"played beyondELO matches without all four ratings: ids {bad}")
    _check_rating_direction(df, max_wrong_share)
    return df


def _check_rating_direction(df: pd.DataFrame, max_wrong_share: float) -> None:
    """In a played, decided match the winner's rating should rise and the loser's fall.

    A label mix-up (before/after, home/away) makes nearly every match wrong; a margin-based Elo can
    legitimately lower a narrow-winning favourite. So fail only above `max_wrong_share` of the
    decided matches; otherwise log the count, share and first ids.
    """
    won = np.sign(df["home_score"] - df["away_score"])
    home_move = np.sign(df["home_elo_after"] - df["home_elo_before"])
    away_move = np.sign(df["away_elo_after"] - df["away_elo_before"])
    decided = df["played"] & (won != 0)
    wrong = decided & ((home_move != won) | (away_move != -won))
    n_wrong, n_decided = int(wrong.sum()), int(decided.sum())
    share = n_wrong / n_decided if n_decided else 0.0
    msg = (f"{n_wrong} of {n_decided} decided matches ({share:.0%}) have a rating that moved the "
           f"wrong way; first ids {df.loc[wrong, 'id'].tolist()[:5]}")
    if share > max_wrong_share:
        raise BuildError(f"{msg}: above {max_wrong_share:.0%}; before/after or home/away mixed up?")
    log.log(logging.WARNING if n_wrong else logging.INFO, msg)


def _name_ids(dim_team: pd.DataFrame, aliases: dict[str, str]) -> dict[str, int]:
    """beyondELO club name -> our team_id: our names, plus the aliases whose target exists."""
    ids = dict(zip(dim_team["name"], dim_team["team_id"].astype(int), strict=True))
    return ids | {a: ids[t] for a, t in aliases.items() if t in ids}


def find_unmapped(
    beyond: pd.DataFrame, dim_team: pd.DataFrame, aliases: dict[str, str]
) -> list[str]:
    """Every beyondELO club name that is not one of the season's clubs after the aliases."""
    known = _name_ids(dim_team, aliases)
    names: Iterable[str] = set(beyond["home"]) | set(beyond["away"])
    return sorted(n for n in names if n not in known)


def add_team_ids(
    beyond: pd.DataFrame, dim_team: pd.DataFrame, aliases: dict[str, str]
) -> pd.DataFrame:
    """`home_team_id` and `away_team_id` by exact club name plus aliases.

    Call `find_unmapped` first: an unmapped name gets no id, and `build_season` fails on that.
    """
    ids = _name_ids(dim_team, aliases)
    return beyond.assign(
        home_team_id=beyond["home"].map(ids), away_team_id=beyond["away"].map(ids))


def _reconcile(
    beyond: pd.DataFrame, ours: pd.DataFrame
) -> tuple[pd.DataFrame, dict[tuple[str, str], int], list[str]]:
    """Match our finished matches to beyondELO's played ones; count every other row by reason."""
    for name, df in (("our fixtures", ours), ("beyondELO", beyond)):
        if df.duplicated(KEY).any():
            raise BuildError(f"{name} hold a home/away/date more than once")
    finished, played = ours[ours["finished"]], beyond[beyond["played"]]
    merged = finished.merge(played, on=KEY, how="left", validate="one_to_one")
    problems: list[str] = []
    lost = merged["id"].isna()
    if lost.any():
        problems.append(f"{lost.sum()} finished matches without a beyondELO partner: "
                        f"{merged.loc[lost, 'match_id'].tolist()}")
    hit = merged[~lost]
    differ = (hit["home_goals"].astype("float64") != hit["home_score"]) | (
        hit["away_goals"].astype("float64") != hit["away_score"])
    if differ.any():
        bad = hit.loc[differ, "match_id"].tolist()
        problems.append(f"score differs between the sources: {bad}")
    rest = beyond[~beyond["id"].isin(hit["id"])]
    keys = set(zip(*(ours[c] for c in KEY), strict=True))
    pairs = set(zip(ours["home_team_id"], ours["away_team_id"], strict=True))
    reasons = []
    for r in rest.itertuples():
        if not r.played:
            reasons.append("unplayed")
        elif (r.home_team_id, r.away_team_id, r.date) in keys:
            reasons.append("played_not_finished_in_ours")
        elif (r.home_team_id, r.away_team_id) in pairs:
            reasons.append("same_clubs_other_date")
        else:
            reasons.append("not_in_our_fixtures")
    tally = pd.Series(reasons, dtype="object").value_counts()
    counts = {("ours", "matched"): len(hit), ("ours", "finished_without_partner"): int(lost.sum()),
              ("ours", "not_finished"): int((~ours["finished"]).sum()),
              ("beyondelo", "matched"): len(hit)}
    for reason in ("unplayed", "not_in_our_fixtures", "same_clubs_other_date",
                   "played_not_finished_in_ours"):
        counts[("beyondelo", reason)] = int(tally.get(reason, 0))
    return hit, counts, problems


def _two_rows(matched: pd.DataFrame, dim_team: pd.DataFrame, prev_codes: set[int]) -> pd.DataFrame:
    """One row per club per matched match."""
    code = dim_team.set_index("team_id")["team_code"]
    sides = []
    for home in (True, False):
        side = "home" if home else "away"
        df = pd.DataFrame({
            "team_id": matched[f"{side}_team_id"].astype("int64"),
            "match_id": matched["match_id"], "season": matched["season"],
            "gw": matched["gw"].astype("int64"), "kickoff_utc": matched["kickoff_utc"],
            "home": home, "beyondelo_before": matched[f"{side}_elo_before"],
            "beyondelo_after": matched[f"{side}_elo_after"],
            "beyondelo_match_id": matched["id"],
        })
        sides.append(df)
    out = pd.concat(sides, ignore_index=True)
    out["promoted"] = ~out["team_id"].map(code).isin(prev_codes)
    return out.sort_values(["kickoff_utc", "match_id", "home"], ascending=[True, True, False],
                           ignore_index=True)[OUT_COLUMNS]


def build_season(
    beyond: pd.DataFrame, dim_team: pd.DataFrame, fixture: pd.DataFrame, prev_codes: set[int],
    season: str, prem_tag: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One season's `ext_beyondelo` and its reconciliation counts (season, source, reason, n).

    `beyond` must come from `add_team_ids`: a row without a team id fails the integer cast here.
    """
    beyond = beyond.astype({"home_team_id": "int64", "away_team_id": "int64"})
    ours = fixture[fixture["tournament"] == prem_tag].copy()
    ours["date"] = ours["kickoff_utc"].map(to_date)
    for c in ("home_team_id", "away_team_id"):
        ours[c] = ours[c].astype("int64")
    matched, counts, problems = _reconcile(beyond, ours)
    recon = pd.DataFrame(
        [(season, s, r, n) for (s, r), n in counts.items()],
        columns=["season", "source", "reason", "matches"])
    log.info("%s reconciliation: %s", season, {f"{s}/{r}": n for (s, r), n in counts.items()})
    if problems:
        raise BuildError(f"{season}: " + "; ".join(problems),
                         refresh=counts[("ours", "finished_without_partner")] > 0)
    return _two_rows(matched.assign(season=season), dim_team, prev_codes), recon
