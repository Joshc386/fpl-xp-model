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
    later promoted again, with no upstream value in its new season, would
    come back with its old rating.
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
    fit without priors would give an equal home side about twice the away
    side's goals, against about 1.25 times over the full season. With the
    goals priors added on 2026-11-14 it gives about 1.1 times, so the
    minimum now guards against less than it did.
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
- **Transfer and price-change columns just after a deadline** (2026-11-14).
  - **Gap:** `players.csv` takes `net_transfers_gw` and `price_change_gw`
    from the master file's newest row. A run between a deadline and
    upstream's first write after it publishes the previous window's figures,
    still labelled "since the last deadline".
  - **Effect:** for a few hours after a deadline, the workbook can show the
    last window's transfers and price changes.
  - **Idea:** compare the master's newest `gw` with the as-of gameweek, and
    flag or hold the run when they disagree.
- **`ppg` in a double gameweek with one match still loading** (2026-11-14).
  - **Gap:** when both of a club's matches in a gameweek are finished but
    only one is complete, that gameweek counts as one appearance, not two.
  - **Effect:** `ppg` reads high for those players until the second match's
    stats load, usually within hours.
  - **Idea:** count appearances from FPL's per-match minutes, if upstream
    ever publishes them.
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
    and 2025/26's GW1-10 snapshot files were rewritten weeks later (GW1 on
    2025-12-13, GW2-10 on 2025-11-19).
  - **Effect:** status, news and `ep_next` can include post-deadline news. The
    model-validator reports pre- and post-deadline snapshots separately.
  - **Fix:** task 3's pre-deadline view, for both seasons (decided
    2026-11-24).

- **A stalled upstream across a deadline** (2026-11-16, task 6 plan).
  - **Gap:** `update.yml` publishes only when upstream's commit changes. If
    upstream stops refreshing across a deadline, the published outputs keep
    the passed gameweek as the next one until upstream refreshes.
  - **Effect:** rare, since upstream refreshes about three times a day. The
    data age shows it after 24 hours.
  - **Idea:** publish anyway when the published `next_deadline_utc` has
    passed. Not done because it resets `run_utc`, so the data age would hide
    a stuck upstream.

## Missing inputs

- **Shots with no player (2026/27)** (2026-11-23, task 1).
  - **Gap:** 314 of 2,738 Premier League shots in GW1-10 have a blank
    `player_id` at upstream `ac8be9c`: 10.5% of shot xG, in 85 of 100
    matches, at 9-14% every gameweek. 2025/26 has none. Upstream's
    `player_name` is blank on every 2026/27 shot.
  - **Effect:** a player's own shot xG falls about 10% short of his team's
    xG on the pitch, which still counts those shots. The attack (task 7)
    must allow for it, on the holdout and live.
  - **Ideas:** take a player's own xG from `fact_player_match.xg`, which
    includes those shots; or assign a blank shot from `total_shots` where
    only one player fits (73 of 119 team-matches with blanks).

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
- **Players missing from a snapshot** (2026-11-13; corrected 2026-11-17 by
  QA's task 8 check).
  - **Gap:** at upstream `ac8be9c`, 7 2026/27 player-match rows are dropped
    as `player_not_in_snapshot`: 6 EFL Cup rows and 1 Champions League row,
    for players added to FPL after the gameweek they played in (ids 623,
    626, 660, 661, 667, 670 and 672). The first version of this entry named
    Mfuni, J.Angulo and Tutierov, which is no longer the case.
  - **Effect:** 3 of the 7 rows carry minutes (90, 45 and 90), so a little
    cup rotation data is lost. Premier League xG and xA are unaffected.
  - **Idea:** the same as for cup appearances: look the player up in later
    snapshots up to the as-of gameweek.
- **Players with no per-match rows** (2026-11-17).
  - **Gap:** at upstream `ac8be9c`, Mfuni, J.Angulo and Tutierov are in each
    gameweek's snapshot, but `playermatchstats` has no row for them in 8 of
    their Premier League player-gameweeks with minutes (Mfuni 5, J.Angulo 1,
    Tutierov 2). For example, Mfuni's 86th-minute goal in Coventry 4–1
    Newcastle (2026/27 GW6) is in `shots.csv` but not in
    `fact_player_match`.
  - **Effect:** their per-match minutes, goals, xG and xA are missing, so
    their xG90, xA90 and DC90 can read wrong. FPL's per-gameweek minutes and
    points for them are complete.
  - **Idea:** check whether a later upstream commit fills the rows; if not,
    flag such players in `players.csv` or fall back to FPL's per-gameweek
    minutes.
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

## Model

- **Players back from injury read low** (2026-11-23, minutes v1).
  - **Gap:** minutes v1 counts gameweeks a player missed through injury or
    suspension as non-starts. A regular starter back from injury reads low
    for up to six gameweeks.
  - **Effect:** his xP is understated until the missed gameweeks age out of
    the windows.
  - **Idea:** keep each player's status per gameweek (a contract change),
    and leave flagged gameweeks out of the rates.
- **A one-match ban zeroes the whole horizon** (2026-11-23, minutes v1).
  - **Gap:** status injured, suspended, unavailable or not available sets
    all five gameweeks to 0, however short the absence.
  - **Effect:** horizon xP, and later the transfer advice, understate such a
    player. The backtest scores the next gameweek only, so the gate isn't
    affected.
  - **Idea:** v2 reads return dates from `news`.

- **Home advantage shrunk towards zero in small pools** (2026-11-14).
  - **Gap:** the Elo goals model's prior on the home coefficient is centred
    on zero, although home advantage is known to be positive. The intercept
    is free, so the shrinkage moves goals from home sides to away sides. It
    is strongest in small pools early in a season and fades as the pool
    grows.
  - **Effect:** early in a season, home sides' expected goals run slightly
    low and away sides' slightly high, so home clean-sheet chances run
    slightly low and away ones slightly high.
  - **Idea:** centre the home prior on last season's home effect, or on a
    fixed league-wide value. Phase 2's Dixon-Coles model replaces this one
    for fixture difficulty.

- **The refit check assumes the goals model's log-linear form** (2026-11-16).
  - **Gap:** the Elo check compares coefficients implied by the outputs
    between as-of reads. The output is exactly log-linear today, so an
    unchanged fit gives the same coefficients on any horizon. Under another
    form, they would move with each read's horizon fixtures even when
    nothing was refitted.
  - **Effect:** none today. With another form, a wholly postponed gameweek
    would give a loud false FAIL on `refit`, never a silent PASS.
  - **Idea:** when the goals model's form changes (phase 2's Dixon-Coles),
    the validator revisits the rule, for example comparing outputs on a
    fixed set of fixtures.

## Workbook

- **Name search ignores accents** (2026-11-17, task 7 review).
  - **Gap:** the Player Database search is a case-insensitive "contains"
    match, but Excel has no accent folding, so "odegaard" doesn't find
    Ødegaard. 48 of 672 names carry an accent.
  - **Effect:** a user typing a plain spelling misses those players.
  - **Idea:** publish an accent-free `search_name` column in `players.csv`
    (a contract change), and search that.
- **A failed refresh can leave tables from different runs** (2026-11-17,
  task 7 review).
  - **Gap:** each Power Query refreshes on its own. If one CSV loses a
    column, that table's refresh fails and keeps its old rows while the
    others refresh, so README's "Last updated" can sit beside stale players.
  - **Effect:** none while the contract holds. The build gate and
    `update.yml`'s output checks catch a changed schema before it's
    published.
  - **Idea:** publish the run's `run_utc` in every CSV (a contract change),
    and have README flag tables whose stamps differ.
- **Run times out of date in the workbook and hand test** (2026-11-19).
  - **Gap:** the README sheet says runs happen "around 08:00 and 18:00 UTC",
    and `excel/HAND_TEST.md` step A1 names 08:23 and 18:23. Runs are every 3
    hours from 2026-11-19. Step A1 also asks for a download before a publish,
    which the test doesn't need: publishes never rebuild the committed
    workbook, so any download holds older data than `main`.
  - **Effect:** a user expects fewer updates than they get, and the hand
    test reads as if it needs timing.
  - **Fix:** in the excel-builder's next task, with a rebuild of the
    workbook.

## Engineering

- **Outside-source Elo check: two late stops and two untested edges** (2026-11-18).
  - **Gap:** in `backtest/beyondelo_check.py`, two stops run after the scored windows' log-losses are computed: fewer than 2 scored matches, and a promoted club with no `dim_team` name. Two edges are untested: the exact halving count in `beyondelo_fit._line_search` (an off-by-one survives), and the fewer-than-2 stop with exactly 1 match (only 0 is tested). In the report, the "five biggest rank disagreements" list cuts ties alphabetically: the 2026-11-18 report's GW38 fifth row is one of five clubs tied at a gap of 1.
  - **Effect:** none on the 2026-11-18 run. All six promoted clubs have names and 199 matches are scored. A stop after scoring shows and writes nothing, so nothing leaks.
  - **Fix before:** the check's next change, or a fourth holdout look.
  - **Idea:** move both checks before `_fits`. Add a test that counts the halvings tried, and one with exactly 1 scored match.

- **Writes aren't atomic across seasons** (2026-11-10).
  - **Gap:** a failure while writing the second season leaves mixed tables
    in `data/processed/`.
  - **Effect:** none in CI, which builds from scratch each run. Each
    season's `manifest.json` records its upstream commit, so a mix is
    detectable locally.
