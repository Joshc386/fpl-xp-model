"""The leakage assertions, shared by the synthetic and the real-data loader tests.

They check where a value comes from (its source row, club snapshot and gameweek), not only
that a rule was applied, because two real leaks passed rule-based checks.
"""

from __future__ import annotations

import pandas as pd

PREM = "prem"
OFFSET = pd.Timedelta(minutes=90)
RESULT_COLUMNS = [
    "home_goals", "away_goals", "home_xg", "away_xg", "home_npxg", "away_npxg",
    "home_upstream_elo", "away_upstream_elo",
]
ELO_COLUMNS = ["home_upstream_elo", "away_upstream_elo"]


def cutoff_of(fx: pd.DataFrame, as_of_gw: int) -> pd.Timestamp | None:
    """The GW as_of+1 deadline from the Premier League rows of a fixture table."""
    nxt = fx[(fx.tournament == PREM) & (fx.gw == as_of_gw + 1)]
    if nxt.empty:
        return None
    return pd.to_datetime(nxt.kickoff_utc, utc=True).min() - OFFSET


def league_elo(fx: pd.DataFrame, cutoff: pd.Timestamp | None) -> dict[int, set[float]]:
    """Per club, every Premier League kickoff Elo with a kickoff before the cutoff."""
    out: dict[int, set[float]] = {}
    kick = pd.to_datetime(fx.kickoff_utc, utc=True)
    for r in fx[(fx.tournament == PREM) & fx.finished].itertuples():
        if cutoff is not None and kick[r.Index] >= cutoff:
            continue
        sides = ((r.home_team_id, r.home_upstream_elo), (r.away_team_id, r.away_upstream_elo))
        for tid, elo in sides:
            if not pd.isna(tid) and not pd.isna(elo):
                out.setdefault(int(tid), set()).add(float(elo))
    return out


def expected_team_elo(fx: pd.DataFrame) -> dict[int, float]:
    """Each club's latest non-null kickoff Elo among the finished Premier League matches."""
    best: dict[int, tuple[str, float]] = {}
    for r in fx[(fx.tournament == PREM) & fx.finished].itertuples():
        sides = ((r.home_team_id, r.home_upstream_elo), (r.away_team_id, r.away_upstream_elo))
        for tid, elo in sides:
            if pd.isna(tid) or pd.isna(elo):
                continue
            if int(tid) not in best or r.kickoff_utc >= best[int(tid)][0]:
                best[int(tid)] = (r.kickoff_utc, float(elo))
    return {t: elo for t, (_, elo) in best.items()}


def assert_provenance(tables: dict[str, pd.DataFrame], as_of_gw: int, source: pd.DataFrame) -> None:
    """Every value traces to an allowed source.

    * Every row has `gw` up to as-of, bar the Premier League schedule (blank of results).
    * Every non-null `dim_team.upstream_elo` is a Premier League kickoff Elo of that club
      with a kickoff before the cutoff, in `source` (the full build's `fact_fixture`).
    * Every `fact_player_match` row's club is one of its match's clubs.
    """
    fx = tables["fact_fixture"]
    prem = fx.tournament == PREM
    assert (fx.gw[~prem] <= as_of_gw).all(), "a cup or European match with a later gameweek"
    pgw = tables["fact_player_gw"]
    assert pgw.empty or pgw.gw.max() <= as_of_gw, "player-gameweek rows leaked"
    ok = league_elo(source, cutoff_of(source, as_of_gw))
    for team_id, value in tables["dim_team"].set_index("team_id").upstream_elo.dropna().items():
        assert value in ok.get(team_id, set()), f"club {team_id}: Elo {value} is no league kickoff"
    clubs = tables["fact_player_match"].merge(
        fx[["match_id", "home_team_id", "away_team_id"]], on="match_id", how="left"
    )
    in_match = (clubs.team_id == clubs.home_team_id).fillna(False) | (
        clubs.team_id == clubs.away_team_id
    ).fillna(False)  # a European opponent has a null team_id
    stray = clubs[~in_match]
    assert stray.empty, f"player rows for a club not in the match: {len(stray)}"


def assert_no_leakage(
    tables: dict[str, pd.DataFrame], as_of_gw: int, full_fixture: pd.DataFrame | None = None
) -> None:
    """Nothing the read must not hold: results, xG, Elo, player rows, later cup matches.

    * Premier League fixtures after `as_of_gw` are schedule only.
    * No cup or European match at or after the GW as_of+1 deadline, in any folder, and no
      player row of one; no Elo on cup rows.
    * `dim_team.upstream_elo` is each club's latest Premier League kickoff value in the read.
    * The provenance checks of `assert_provenance`.

    With `full_fixture` (the full build's `fact_fixture`) it also checks the membership: every
    Premier League fixture is present, and a cup match is present exactly when it was played in
    a gameweek up to as-of.
    """
    fx = tables["fact_fixture"]
    prem, later = fx.tournament == PREM, fx.gw > as_of_gw
    assert not fx.loc[prem & later, ["finished", "stats_complete"]].any().any(), "flags leaked"
    assert fx.loc[prem & later, RESULT_COLUMNS].isna().all().all(), "result, xG or Elo leaked"
    assert fx.loc[~prem, ELO_COLUMNS].isna().all().all(), "upstream Elo on a cup row"
    source = fx if full_fixture is None else full_fixture
    cutoff = cutoff_of(source, as_of_gw)
    if cutoff is not None:
        assert (pd.to_datetime(fx.kickoff_utc, utc=True)[~prem] < cutoff).all(), "cup after cutoff"
    visible = set(fx.match_id[~(prem & later)])
    assert set(tables["fact_player_match"].match_id) <= visible, "player-match rows leaked"
    if full_fixture is not None:
        full_prem = set(full_fixture.match_id[full_fixture.tournament == PREM])
        assert set(fx.match_id[prem]) == full_prem, "the Premier League schedule is incomplete"
        cups = full_fixture[full_fixture.tournament != PREM]
        want = cups.match_id[cups.gw <= as_of_gw]
        assert set(fx.match_id[~prem]) == set(want), "wrong cup and European matches"
    assert_provenance(tables, as_of_gw, source)
    elo = tables["dim_team"].set_index("team_id").upstream_elo
    want_elo = expected_team_elo(fx)
    for team_id, value in elo.items():
        assert (pd.isna(value) and team_id not in want_elo) or want_elo[team_id] == value, team_id
