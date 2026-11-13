# Known gaps

Gaps found while building the model that are accepted for now, to be
addressed once the model is up and running. Each entry says what is missing,
what it affects, and a starting idea for the fix. Decisions and evidence are
in `docs/decisions.md` under the date given.

When a gap is fixed, delete its entry and log the fix in `docs/decisions.md`.

## Season edges

- **No players before the GW1 deadline** (2026-11-11).
  - **Gap:** no snapshot exists before GW1, and GW1's folder already holds
    post-deadline prices. So `load_as_of` at as-of 0 returns an empty
    `dim_player`.
  - **Effect:** backtests can't predict GW1, and a pre-season live run would
    publish an empty player list.
  - **Fix before:** 2027/28 GW1.
  - **Idea:** at as-of 0 in live mode, build `dim_player` from the master
    current-state files.
- **No Elo seed for some clubs early in a season** (2026-11-12).
  - **Gap:** a club entering the Elo run is seeded from its first upstream
    Elo in the read, and the Elo component raises an error while that is
    missing. That happens at 2025/26 as-of 0 (every GW1 value is still
    schedule only) and 2026/27 as-of 0-1 (Coventry's first value is at GW2).
    Upstream Elo is null from 2026/27 GW3, so if ClubElo stays down, no club
    promoted for 2027/28 will have a seed at all, and every other club will
    carry its own rating instead of being re-seeded. A club relegated and
    later promoted again would come back with its old rating.
  - **Effect:** no team goals or fixture difficulty from those reads, and
    none for 2027/28 until this is fixed.
  - **Fix before:** 2027/28 GW1.
  - **Idea:** seed a promoted club from the average final rating of the
    relegated clubs, or from an outside source that rates the Championship
    (beyondELO doesn't).
- **No fixture difficulty at 2025/26 as-of 1-2** (2026-11-13).
  - **Gap:** the Elo goals model needs at least `goals_model.min_matches`
    (30) finished matches in its pool and raises below that. With no earlier
    season loaded, 2025/26 has 10 at as-of 1 and 20 at as-of 2. At as-of 1 a
    fit would give an equal home side about twice the away side's goals,
    against about 1.25 times over the full season.
  - **Effect:** backtests have no team goals for 2025/26 GW2-3, which carry
    no pass marks. Live runs always have last season in the pool.
  - **Idea:** load 2024/25 results as a prior pool.

## Data timing

- **Provisional gameweek figures** (2026-11-10).
  - **Gap:** FPL keeps adjusting bonus, BPS and occasionally points for up to
    about 7 hours after upstream marks a match finished.
  - **Effect:** a run soon after a match shows provisional points; the next
    run corrects them.
  - **Idea:** gate on FPL's own `data_checked` flag in
    `gameweek_summaries.csv`.
- **Partly loaded matches** (2026-11-10).
  - **Gap:** the completeness check passes a match that is missing a few
    player rows or has provisional per-player xG. Across GW9-10, 7 matches
    did so for a while (unused substitutes and European per-player stats).
  - **Idea:** a consistency check, such as summed player xG against team xG
    or minutes per club, that holds a match back until it settles.
- **Backtests see the final fixture schedule** (2026-11-11).
  - **Gap:** later fixtures' gameweeks and kickoffs come from the final
    folders.
  - **Effect:** a backtest knows about rescheduled Premier League fixtures,
    blanks and doubles earlier than a manager would.
  - **Idea:** rebuild the schedule as it stood at each deadline from upstream's
    commit history.
- **Derived deadlines** (2026-11-11).
  - **Gap:** backtests derive each deadline as the first Premier League
    kickoff minus 90 minutes, which matches FPL for all 76 gameweeks of both
    seasons.
  - **Effect:** if a gameweek's first fixture were postponed after FPL set
    the deadline, the derived deadline would fall later than FPL's. A wholly
    postponed gameweek (2022/23 GW7) uses the previous gameweek's last
    kickoff instead. That is safe, but it can date a cup tie a gameweek late.
  - **Idea:** flag any gameweek where the derived deadline and the master
    `deadline_time` disagree in a live run.
- **Snapshot timing** (brief section 7).
  - **Gap:** a snapshot can land up to about 7 hours after the next deadline,
    and the 2025/26 folders were rewritten on 2026-07-22.
  - **Effect:** status, news and `ep_next` can include post-deadline news. The
    model-validator reports pre- and post-deadline snapshots separately.

## Missing inputs

- **Upcoming European and cup ties** (2026-11-11).
  - **Gap:** later cup and European fixtures are left out of as-of reads,
    because a future knockout tie reveals earlier results.
  - **Effect:** the minutes model can't see an upcoming midweek tie as a
    rotation risk.
  - **Idea:** in live mode only, read the current schedule for a v2 rotation
    feature, and check it can't be backtested unfairly.
- **2025/26 cup and European matches with no kickoff time** (2026-11-10).
  - **Gap:** 36 played matches from GW27 onwards are dropped.
  - **Effect:** 2025/26 backtests lose late-season rotation and fatigue
    inputs.
  - **Idea:** recover dates from another upstream file, such as `shots.csv`
    or `xg_by_minute.csv`, if one carries them.
- **Cup appearances by players who moved that gameweek** (2026-11-11).
  - **Gap:** a cup row's club comes from the snapshot of the gameweek it was
    played in. A player who moved clubs during that gameweek still shows his
    old club, so the row is dropped as `club_not_in_match`.
  - **Examples:** Semenyo, 90 minutes for Man City on 13 January 2026
    (2025/26 GW21), and Sávio, 19 minutes for Tottenham on 24 August 2026
    (2026/27 GW1).
  - **Effect:** a few genuine cup minutes are lost around transfer windows.
  - **Idea:** look the club up in later snapshots up to the as-of gameweek.
    The catch is that an as-of read would then no longer equal the full
    build for those rows.
- **Per-match goals conceded** (2026-11-10).
  - **Gap:** upstream's per-match figure is unreliable, so FPL's
    per-gameweek `goals_conceded` is used.
  - **Effect:** in a double gameweek, the split between the two matches is
    lost.

- **Elo counts Premier League matches only** (2026-11-09; 2026-11-12).
  - **Gap:** ClubElo also counts cup and European matches, and ours don't. By
    the end of 2025/26 ours sat 18 points below ClubElo's end-of-season
    rating on average (Aston Villa 48 below, Arsenal 36 below). Re-seeding
    from ClubElo each season resets this, but without upstream values (from
    2027/28 if ClubElo stays down) it builds up across seasons.
  - **Effect:** clubs in Europe can drift from their true strength.
  - **Idea:** include cup and European matches between two Premier League
    clubs, or re-anchor to an outside source each summer.

## Engineering

- **Writes aren't atomic across seasons** (2026-11-10).
  - **Gap:** a failure while writing the second season leaves mixed tables
    in `data/processed/`.
  - **Effect:** none in CI, which builds from scratch each run. Each
    season's `manifest.json` records its upstream commit, so a mix is
    detectable locally.
