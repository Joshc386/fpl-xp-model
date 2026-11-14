# Decisions log

Dated log of design decisions and component hand-off notes, oldest first.
Every entry has a date and a reason. Heading format:
`### YYYY-MM-DD: <area> - <topic>`.

### 2026-11-08: scoring - 2026/27 rules
- **Decision:** filled `config/scoring.yaml` from the official 2026/27 rules.
  Every points value is keyed by position (GKP, DEF, MID, FWD).
- **Sources (all read 2026-11-08):**
  - Official rules page, https://fantasy.premierleague.com/help/rules
    (sections "How are points scored?", "Defensive contributions", "Clean
    sheets", "Red Cards", "Assists", "Bonus Points", "Transfer rules", "Player
    Prices", "Squad Size", "Choosing Your Starting 11").
  - Official FPL API, https://fantasy.premierleague.com/api/bootstrap-static/:
    `game_config.scoring`, `game_settings` and `element_types`. Confirmed as
    2026/27: GW1 deadline 2026-08-21T17:30Z; Coventry, Hull and Ipswich in
    `teams`.
  - Premier League, "All you need to know about changes to FPL for 2026/27"
    (31 July 2026),
    https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627.
    The only scoring-related change it lists is a Bonus Points System
    rebalance. Points values are unchanged from 2025/26.
  - Premier League, defensive contributions in 2026/27 (20 July 2026),
    https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy.
- **Values:** appearance 1 (1-59 min) / 2 (60+ min, excluding stoppage time);
  goal GKP 10, DEF 6, MID 5, FWD 4; assist 3; clean sheet GKP/DEF 4, MID 1
  (needs 60+ min); -1 per 2 goals conceded (GKP/DEF); 1 per 3 saves (GKP);
  penalty save 5; penalty miss -2; yellow -1; red -3 (includes any yellow);
  own goal -2; bonus 3/2/1 per match.
- **Defensive contributions:** 2 points, no stacking. DEF: 10+ clearances,
  blocked shots, interceptions and tackles (CBIT). MID and FWD: 12+ CBIT plus
  recoveries (CBIRT). GKs are not eligible (API value 0; their count is always 0).
- **Game rules:** £100.0m budget; squad 2/5/5/3; XI with 1 GK, 3-5 DEF, 2-5
  MID, 1-3 FWD; max 3 per club; captain x2; 1 free transfer per GW, up to 5
  banked (API `max_extra_free_transfers` = 4); hit 4 points per extra transfer;
  20 transfers per GW cap outside Wildcard/Free Hit; selling price keeps half
  of a rise, rounded down to £0.1m (API `transfers_sell_on_fee` = 0.5).
  Wildcard and Free Hit keep saved free transfers.
- **Verification:**
  - Recomputed points from `scoring.yaml` reproduce FPL's official
    `total_points` for all 2,679 single-fixture player-gameweeks in GW7-10
    (1,231 with minutes > 0), with 0 mismatches. Source:
    https://fantasy.premierleague.com/api/event/{gw}/live/.
  - The same data shows the DC thresholds exactly. DEF: 9 never scores, 10
    always does. MID: 11 never scores, 12 always does.
  - FPL's DC count = `clearances_blocks_interceptions` + `tackles` for DEF,
    + `recoveries` for MID/FWD (362 DEF and 592 MID/FWD rows with recoveries
    > 0, all matching).
- **Not stated on the rules page:** that a price fall is passed on in full
  when selling. This is standard FPL behaviour and consistent with the API
  (`element_sell_at_purchase_price` = false; the sell-on fee applies to
  rises), so the brief's rule stands.
- **Effect downstream:**
  - The 2026/27 BPS rebalance moves bonus away from centre-backs and towards
    GKs, full-backs and attackers. CBI earns +1 BPS per 3 instead of per 2;
    "being tackled" is removed; new save items are added. A v1 bonus
    regression fitted only on 2025/26 learns the old regime.
  - FPL assists include won penalties and won free-kicks that are scored
    directly, and rebounds, so they run above xA.
  - Squad and transfer rules live in `scoring.yaml` under `game_rules`,
    because they are official facts the main session owns. The optimiser
    reads them from there rather than restating them in `optimiser.yaml`.

### 2026-11-08: data - phase 0 verify list
- Upstream commit inspected: 66e73ea (2026-11-08T14:25Z), sparse blobless clone in data/raw/upstream/repo (gitignored). Exploration scripts in data/scratch_scripts/.
- **Fixtures:** each `GW{n}/fixtures.csv` holds only GW n (all competitions, same rows as that folder's `matches.csv`). Folders GW1-GW38 all exist for 2026/27, so the pipeline concatenates `GW{next}..GW{next+4}/fixtures.csv` and filters `tournament == 'prem'`. No master-level fixtures file. Blank/double GWs are visible in 2025/26 (GW26 11 PL fixtures, GW31 8, GW33 13, GW34 7, GW36 11); 2026/27 currently has none (380 fixtures, 10 per GW, 38 per team).
- **IDs:** `player_id` and `teams.id` are season-specific (25/26 vs 26/27: 5 of 482 shared player codes keep the same id; 5 of 17 shared team codes keep the same id). `player_code` and `teams.code` are the stable keys. Within a season `player_id` is stable across all GW folders and the master.
- **Price:** `now_cost` is already in GBP m (15.8), not tenths, in all three seasons and in both master and per-GW files. `cost_change_event` and `cost_change_start` are integer tenths. Brief data rule 7 is wrong for this source. Cleaning rule to add: `price_tenths = round(now_cost * 10)`, `price_m = price_tenths / 10`.
- **Elo is missing for 2026/27:** `teams.elo` and `teams.strength` are 100% null in every 26/27 file, and `matches.home/away_team_elo` is populated only for 17 of 95 finished PL matches (GW1-2 only; none from GW3). 2025/26 and 2024/25 are complete. Blocks the Elo-based `fixture_difficulty.csv` and `dim_team.elo`; escalated to the main session.
- **Minutes:** `minutes_played` is capped at 90 (no stoppage time; >90 occurs only in cup extra time). In 25/26 it equals FPL `minutes` in 100% of 10,068 single-fixture rows. In 26/27 it equals it in 79% of 3,470 rows; starters subbed off are +1 vs FPL (686 of 750), 27 full-match starters are 89 vs 90, 21 rows reach 60 in `minutes_played` but 59 in FPL. `fact_player_gw.minutes` must come from `player_gameweek_stats.minutes`; `fact_player_match.minutes` from `minutes_played`.
- **Defensive contribution inputs (26/27):** `playermatchstats.tackles` and `defensive_contributions` are 100% null; `tackles_won` is populated. `player_gameweek_stats.tackles` equals `tackles_won` in 99.85% of rows. In 25/26 `tackles` is populated and matches pgs `tackles` in 97.5%. 25/26 pgs `defensive_contribution` for DEF includes recoveries in GW2-10 only.
- **Penalty xG:** constant 0.7884 per penalty in `shots.csv` (situation == 'penalty'; 15 in 26/27, 122 in 25/26 of which 2 at 0.76). Match-level xG minus npxG is 0.78-0.79 per penalty (rounded to 0.01) in 24/25, 25/26, 26/27.
- **Snapshot timing:** GW folders keep being re-exported until the next GW becomes current. 26/27 last refresh was -6.6h to +7.4h from the next deadline (4 of 10 GWs after it). 25/26 folders were all rewritten on 2026-07-22, so their history is not original time-stamped data.
- **Unprocessed matches:** 4 of 95 finished PL matches in 26/27 and 20 of 380 in 25/26 fail `stats_processed & player_stats_processed`; the player rows exist but are excluded by rule 4.
- **26/27 sparse nulls:** in processed PL rows with minutes > 0, `xg`, `xa`, `total_shots` are null for 52%/32%/52% (null means no event); `saves`/`goals_conceded` null for outfielders; `goals`/`assists`/`blocks` null for GKs. 25/26 is dense. Filling these with 0 changes values, so it needs approval before it becomes a cleaning rule.
- Effect downstream: no code written this phase. Proposed contract changes are in the phase 0 report.

### 2026-11-08: main - phase 0 review of the data verify list
- **Re-checked against the clone (commit 66e73ea):**
  - 26/27 `teams.elo` is null for 20 of 20 teams.
  - PL match Elo is present only in GW1 (8 of 10) and GW2 (9 of 10).
  - `now_cost` is float £m, ranging 3.9-15.8.
  - 26/27 `playermatchstats.tackles` and `defensive_contributions` are 100% null.
  - `shots.csv` penalty xG is 0.7884 for all 15 penalties.
  - All of the data-engineer's claims checked hold.
- **Correction (not in the data-engineer's report):** in `matches.csv` and
  `fixtures.csv`, `home_team`/`away_team` are **team codes**, not `teams.id`,
  in both 2025/26 and 2026/27.
  - Evidence: all 20 distinct values are in `teams.code`, and not all are in
    `teams.id`.
  - The 26/27 GW1 opener maps to Arsenal v Coventry City as codes, but to
    Bournemouth v Everton as ids. The 25/26 opener maps to Liverpool v
    Bournemouth as codes.
  - Brief data rule 5 is wrong for this source. Eleven values (1, 2, 3, 4, 6,
    7, 8, 9, 11, 14, 17) are valid as both, so a join on `teams.id` would
    silently mislabel clubs.
- **Upstream Elo source:** ClubElo.com (upstream README). api.clubelo.com
  returned HTTP 502 on 2026-11-08, which is consistent with upstream Elo
  stopping after GW2.
  - Upstream's GW1-2 match Elo gives a seed for 19 of 20 clubs: Hull 1532.88,
    Ipswich 1640.00, Coventry 1661.48. The exception is Arsenal, whose GW1-2
    rows are both null.
- **Power Query outside Windows:** Microsoft's "Power Query data sources in
  Excel versions" page lists no Web source for Excel for Mac. Excel for the
  web lists only Table/Range and OData as anonymous sources, and Web API with
  user/password. Live refresh from GitHub raw URLs is therefore Windows-only.
- **Status:** brief and contract corrections are proposed to Josh, not yet
  applied. Applied on 2026-11-09 (below).

### 2026-11-09: data - Elo computed in-house
- **Decision (Josh chose in-house or elofootball.com; main session picked
  in-house):** the pipeline computes its own Elo from processed Premier League
  results. It is seeded from each club's last upstream ClubElo value: GW1-2
  2026/27 match rows for 19 clubs, and Arsenal's last 2025/26 value. Brief
  data rule 12 sets this out.
- **Why not ClubElo directly:** api.clubelo.com returned HTTP 502 again on
  2026-11-09. It is the same source that left upstream's Elo empty from GW3.
- **Why not elofootball.com:** it has no API or export, no stated terms of
  use, no named operator, and its About page returns 404. Using it would mean
  scraping HTML, which is fragile and of unknown permission. It can still
  serve as a manual sanity check.
- **Method:**
  - Standard Elo with a home advantage and a goal-margin factor.
  - Settings live in the new `config/pipeline.yaml`, owned by the
    data-engineer.
  - Settings are calibrated by replaying 2025/26, where upstream ClubElo is
    complete.
  - Phase 1 acceptance: Spearman rank correlation with upstream ClubElo of at
    least 0.9 at every GW from GW6 (a starting target).
- **Trade-off:** our Elo uses Premier League matches only, while ClubElo also
  counts cup and European matches. Expect some drift for clubs in Europe.

### 2026-11-09: main - Python 3.13
- **Decision:** Python 3.13 replaces 3.12 in the brief and CLAUDE.md.
- **Why:** 3.12 isn't installed here. 3.13 is the default `python` and is
  already used by the data-engineer's venv.
- **Evidence:** `pip install --dry-run --only-binary=:all:` resolves the full
  stack (pandas, numpy, scipy 1.18.1, statsmodels 0.15.0, PuLP 4.2.0, pyarrow
  26.0.1, PyYAML, pytest) on both 3.13 and 3.14. 3.14 would also work, but
  offers nothing this project needs.

### 2026-11-09: model - bonus uses same-season data only
- **Decision (Josh):** the bonus model is fitted walk-forward only on matches
  from the target gameweek's own season. Another season's bonus is never used,
  as training data or as a prior.
- **Why:** the BPS is rebalanced between seasons. 2026/27 removed "being
  tackled", moved CBI from +1 per 2 to +1 per 3, and added new save items.
  That shifts bonus from centre-backs towards goalkeepers, full-backs and
  attackers.
- **Early-season fallback:** a rule-based estimate that uses no other
  season's bonus, for example sharing each match's 6 bonus points by non-bonus
  xP. The threshold for switching to the fitted model goes in
  `config/model.yaml`.
- Brief section 6.7 is updated.

### 2026-11-09: main - phase 0 corrections applied to brief and contract
- **Brief, section 1 and 10:** the workbook is Windows Excel only; Mac and
  Excel for the web can't refresh from a web source.
- **Brief, section 4:**
  - Corrected the "Files used" grains: master `playerstats.csv` is player ×
    gameweek, and `fixtures.csv` is per-gameweek only.
  - Data rule 2 now takes FPL `player_gameweek_stats.minutes` for
    60-minute logic.
  - Rule 5 now joins match teams on `teams.code`.
  - Rule 6 also covers `teams.id`.
  - Rule 7 records that `now_cost` is already £m.
  - Rule 10 adds the promoted clubs' Elo seeds.
  - Added rules 12 (in-house Elo), 13 (previous seasons) and 14 (defensive
    contribution sources).
- **Brief, section 6:**
  - The penalty xG value is 0.7884.
  - "Expected assists" means expected FPL assists, which are wider than xA.
  - Bonus uses same-season data only.
- **Brief, section 7:** the development window is confirmed, and the
  snapshot-timing limitation is added with a check for the validator.
- **Brief, section 9:** the free-transfer cap is 5 and the hit cost is 4,
  both from `scoring.yaml` `game_rules`.
- **Brief, sections 12-14:** added `config/pipeline.yaml`; added the Elo
  acceptance test to phase 1; renamed xp-modeller to
  expected-points-modeller, matching Josh's CLAUDE.md change, in the brief and
  four agent files.
- **Brief, section 15:** every verify item is ticked with its answer.
- **Contract:**
  - Added `dim_player.ep_next`, for the backtest baseline and
    `player_summary.ep_next_fpl`.
  - Added `fact_player_match.team_id`, for team shares, taken from the GW
    snapshot.
  - Added `fact_player_gw.own_goals`, `tackles`, `cbi`, `recoveries` and
    `defensive_contribution`, for card and own-goal rates and FPL-consistent
    defensive contribution rates.
  - Added source notes.
  - Clarified that the nulls rule applies to published outputs.
- **Flagged, not changed:**
  - CLAUDE.md says money is integer tenths internally, but the contract's
    processed tables carry `price_m`. The brief wins, so the contract stands.
    Revisit if the optimiser needs integer budgets from the processed tables.
  - The 2026/27 sparse-null fill rule awaits Josh's approval.

### 2026-11-09: data - blank match stats mean zero
- **Decision (Josh approved):** in processed Premier League matches, for rows
  with minutes > 0, fill blanks with 0 in these `fact_player_match` columns:
  `goals`, `assists`, `xg`, `xa`, `pens_scored`, `pens_missed`, `tackles`,
  `interceptions`, `clearances`, `blocks`, `recoveries`, `saves`. Brief data
  rule 15 sets this out.
- **Evidence:** 2026/27 GW1-10, 2,803 played rows.
  - Blanks follow position. Goalkeepers are blank for goals, assists, blocks
    and xG; outfielders are blank for saves and goals conceded.
  - Blank xG appears in exactly the rows with blank shots (48.7% of
    outfielders), and never beside `total_shots` > 0. Upstream writes no
    explicit zeros in xG.
  - Zero-filled goals, saves and missed penalties equal FPL's
    `player_gameweek_stats` in 100% of rows.
  - FPL's `expected_goals` is 0 in all 1,459 blank-xG rows.
  - FPL's `expected_assists` is 0 in 909 of 910 blank-xA rows.
- **Exceptions:**
  - Whole-season empty columns aren't filled. 2026/27 `tackles` and
    `defensive_contributions` are 100% blank, so take tackles from
    `tackles_won`.
  - `team_gc_on_pitch` isn't filled. 2025/26 has 241 blanks across 83
    matches (GW16-36, players with 1-90 minutes), which are genuinely
    missing. The data-engineer proposes handling in phase 1.
  - Upstream's goalkeeper-only `goals_conceded` isn't used.
- **Guards:** validation fails the run if a listed column is empty for a
  whole season, or if a blank xG sits beside `total_shots` > 0.
- **Note:** concatenated GW files load these columns as object dtype even
  though every value parses as a number. Read them with explicit numeric
  dtypes.

### 2026-11-09: data - processed prices in integer tenths
- **Decision (Josh):** `dim_player.price_m` and `fact_player_gw.price_m`
  become `price_tenths`, an integer number of tenths of £m (55 = £5.5m).
  Published outputs keep `price_m` in £m to one decimal.
- **Why:** CLAUDE.md says money is handled in £0.1m units internally. The
  optimiser sums prices against a budget, and integers avoid float rounding.
  This resolves the conflict flagged in the 2026-11-09 corrections entry.
- **Updated:** brief section 5 and its conventions, and docs/data_contract.md
  (tables, price source note, conventions).
- **Dependent agents to tell:** the data-engineer (phase 1 builds these
  columns), the expected-points-modeller and the optimiser.

### 2026-11-09: main - public repo
- **Decision (Josh):** the repo is public on GitHub under Joshc386. Power
  Query can then read the raw output CSV URLs without authentication (brief
  section 3).
- **Upstream permission:** olbauday/FPL-Core-Insights has no licence file.
  Its README says: "Feel free to use the data from this repository in
  whatever way works best for you", and asks for a link back as the data
  source.
  - Publishing derived outputs is fine with credit.
  - Credit goes on the workbook's README sheet (brief data rule 11), and
    should also go in the repo README once that is written.
- **Repo name:** `fpl-xp-model`, per brief section 12. The local folder
  stays `fpl-model`.

### 2026-11-09: main - phase 1 plan review (/grill-with-docs)
Josh's decisions from grilling `docs/plans/phase-1.md`. `CONTEXT.md` was
created in the same session. The brief and the contract are updated.

1. **Next gameweek:** the first gameweek whose deadline is after the run time.
   - Why: the deadline is the last point at which transfers count.
   - The as-of gameweek is the one before it, and `meta.current_gw` reports
     it.
   - A gameweek whose deadline has passed never appears in the outputs.
   - Upstream's `is_current`/`is_next` flags aren't used, because they lag
     deadlines by hours.
2. **Horizon:** 5 gameweeks stay projected. Josh briefly chose
   next-gameweek-only, then reversed it in favour of a user-chosen horizon.
3. **One workbook-wide horizon picker** (1 to `max_horizon`).
   - Why: varying horizons across sections at once makes no sense.
   - Python precomputes `player_summary.csv` per horizon, and
     `optimal_squads.csv` per horizon × budget (55 solves). The runtime
     target becomes 5 minutes for all 55.
4. **No decay.** All totals are plain sums over the chosen horizon.
   - Removed: `xp_horizon_weighted`, the decay config, `meta.decay` and the
     optimiser's `w_g`.
   - Trade-off accepted: far gameweeks are trusted as much as near ones. The
     answer to that is choosing a shorter horizon.
5. **`meta.csv` ships in phase 1.**
   - `horizon` becomes `max_horizon`, and `decay` is removed.
   - `model_version` is filled (for example `0.1.0-elo`).
   - The backtest MAEs may be null only until the first backtest.
6. **`fixture_difficulty.csv` is one row per team per fixture**, keyed on
   `team_id` + `match_id`, with no row for a blank gameweek and two rows for
   a double. `is_blank` and `is_double` are dropped.
   - `projections.csv` follows the same convention: no row for a blank
     gameweek, and `opponent` lists both opponents in a double. `opponent`
     leaves the nullable list.
7. **`players.csv` metric definitions** are approved and recorded in
   `CONTEXT.md`.
   - Per-90 stats are 0 at 0 minutes, with no minimum-minutes cut-off.
   - xG and xA come from upstream match data, not FPL's `expected_goals`.
8. **Runs at 08:00 and 18:00 UTC only** (Josh). Twice a day is enough.
   - Upstream actually commits about three times a day, at drifting times in
     roughly 02:00-04:00, 13:00-16:00 and 19:00-22:00 UTC. That contradicts
     the brief's 07:30 and 17:30.
   - The freshness criterion becomes "each run publishes the newest upstream
     commit that existed when it started". The 1-hour target is dropped.
   - 30-minute polling was proposed and rejected as too much.
9. **The Elo goals model goes to the expected-points-modeller**, as the team
   goals fallback and benchmark, rather than to the data-engineer. This
   avoids two versions of the same model and keeps model logic out of the
   data-engineer's code.
10. **The modeller also owns the Elo ratings**, as one Elo component
    (`models/elo.py`).
    - The data-engineer passes upstream ClubElo through unchanged as
      `upstream_elo` (renamed from `elo`, `home_elo` and `away_elo`).
    - Elo settings move from `pipeline.yaml` to `model.yaml`.
    - Why: one owner and one verdict, so a poor result can go to a new Elo
      agent cleanly.
11. **The model-validator judges the Elo component** against the pass marks
    in brief section 7.
    - Josh separately compares our ratings with an outside Elo source,
      covering 2026/27 GW3 onwards, where upstream Elo stops.
    - Advice given: compare ranking and predictive log-loss, not raw rating
      levels, because the scales differ.
12. **`elo_ratings.csv` is published** (team × Premier League match, 2025/26
    and 2026/27, `elo_before` and `elo_after`) for Josh's comparison. It is
    not loaded by the workbook.
13. **Each reviewed task is committed straight to `main` and pushed**; there
    is no `phase-1` branch.
    - Why: GitHub only offers manual workflow runs from the default branch,
      and branch-based Power Query URLs would need switching at go-live.
    - Josh approved pushes for phase 1.
14. **Josh's Elo verdict gates only the phase 2 Dixon-Coles work.** The
    minutes model doesn't use Elo and can start after phase 1 sign-off.

### 2026-11-09: optimiser - customisable budget on a £0.5m grid
- **Decision (Josh):** budgets are customisable, because managers' budgets
  drift as their players' prices rise and fall.
  - `in_budget` accepts any budget to £0.1m.
  - Python solves every horizon × budget from £95.0m to £110.0m in £0.5m
    steps: 155 solves, with the range and step in `config/optimiser.yaml`.
  - The workbook shows the squad for the largest solved budget at or below
    the typed one, and says which.
- **Supersedes:** the £95.0m-£105.0m range in £1.0m steps and the 55-solve
  figure in the plan-review entry above.
- **Why a grid:** workbook users have no Python, so squads must be
  precomputed.
  - A £0.1m grid would need about 755 solves per run.
  - A £1.0m grid could leave up to £0.9m unused; the £0.5m grid leaves at
    most £0.4m.
- **Runtime target:** under 20 minutes for all 155 solves. This is a starting
  target, confirmed in phase 4.
- The Transfer Planner is unaffected, because it already uses the user's own
  selling values and bank.

### 2026-11-09: main - optimiser agent file aligned with the brief
- Edited `.claude/agents/optimiser.md` with Josh's permission:
  - Removed the decay and decay-weights mention.
  - A player with no `projections.csv` row in a gameweek now has xP 0 (Josh),
    replacing "a missing row is a data problem".
  - Solves, runtime, sanity checks and the results table now cover every
    horizon × budget.
  - The hit cost is read from `game_rules` in `config/scoring.yaml`.
- `expected-points-modeller.md` still lists `xp_horizon_weighted` and decay.
  It has not been edited; the brief wins, and the modeller will be told in its
  task message.

### 2026-11-10: main - phase 1 task 1 cleaning rules
Made by the main session before task 1, from checks on upstream commit
66e73ea. Josh confirmed rules 1 and 3 on 2026-11-10.

1. **Rule 9 also requires `finished`.**
   - Evidence: in 2026/27, 14 unfinished matches are flagged
     `stats_processed` and `player_stats_processed`. Four are GW10 Premier
     League matches that kicked off at 14:00 on 2026-11-08 and show 0-0 in the
     14:25 snapshot.
   - Why: a Saturday 18:00 run could otherwise pick up a 17:30 kickoff as a
     finished result.
2. **`fact_fixture.finished` means a processed match.** Otherwise the result
   and xG columns are null, and the contract's nullable list now includes
   them.
   - Why: fixture difficulty needs future fixtures in the table (324
     unfinished 2026/27 rows), and they have no results.
3. **Rule 15 covers 0-minute rows,** which are kept.
   - Evidence: 2026/27 has 1,194 0-minute rows, and every one is blank in
     `goals`, `assists`, `xg`, `xa`, `tackles_won`, `interceptions`,
     `clearances`, `blocks`, `recoveries` and `saves`. Its 1,459 2025/26
     counterparts hold explicit zeros.
   - Why: nothing can happen in 0 minutes. The rows also carry the "in squad,
     unused" signal for cup matches, which `fact_player_gw` (Premier League
     only) can't give.
   - `team_gc_on_pitch` is still never filled.
4. **Matches with no `kickoff_time` are dropped** from `fact_fixture` and
   counted by reason.
   - Evidence: four unfinished 2025/26 rows (GW32 Europa League, two GW32 EFL
     Cup, GW33 Europa League).
5. **Processed tables are stored per season** in `data/processed/{season}/`.
   - Why: `player_id` and `team_id` are season-specific, and `dim_player`,
     `dim_team` and `fact_player_match` have no season column.
- **Flagged for the data-engineer, not decided:** upstream's
  `team_goals_conceded` is non-zero for 909 0-minute rows in 2025/26 and 843
  in 2026/27. It may be the whole-match figure rather than goals conceded on
  the pitch. The data-engineer verifies this in task 1.
- **Updated:** brief data rules 9 and 15, `docs/data_contract.md` (storage,
  `fact_fixture` notes, blanks note, nullable list) and `CONTEXT.md`
  (processed match).

### 2026-11-10: data - phase 1 task 1 build
- **Built from** upstream commit `020660035e6fe7ae13fb855b8f892f5ad97abdd9`
  (2026-11-10 04:44 UTC, pulled over the phase 0 clone at 66e73ea). Latest
  played gameweek: 38 for 2025/26, 10 for 2026/27.
- **Layout:** `ingest.py` reads each `GW{n}` folder (never the master files)
  into `RawSeason`, tagging rows with `snapshot_gw`; `clean.py` holds pure
  builders; `validate.py` holds the input and table checks; `reconcile.py`
  and `run_pipeline.py` (`python -m fpl.run_pipeline`) write Parquet,
  `reconciliation.csv` and `manifest.json` (upstream SHA, latest GW, row
  counts) to `data/processed/{season}/`. Nothing is written until both
  seasons pass every check.
- **Season ids** are upstream's folder names, `2025-2026` and `2026-2027`.
- **Read once, keep what is used:** ingest keeps only the upstream columns in
  `schema.RAW_SCHEMA`. That is also why `start_min` and `finish_min` can never
  reach the tables (data rule 2).
- **Row counts (2025-2026 / 2026-2027):** `dim_player` 841 / 672, `dim_team`
  20 / 20, `fact_fixture` 485 / 484, `fact_player_match` 13,824 / 5,152,
  `fact_player_gw` 29,978 / 6,596. Reconciliation is in
  `data/processed/{season}/reconciliation.csv`.
- **Checks on the output:** `fact_player_gw` points and minutes totals equal
  the sum of `player_gameweek_stats` (34,382 / 9,145 points; 748,552 /
  196,649 minutes). All 380 Premier League matches in each season have their
  two clubs mapped through `teams.code`, and the clubs agree with the
  `match_id` slug in 380 of 380 in both seasons. Every Premier League
  `fact_player_match.team_id` is one of the match's two clubs.
- **Foreign keys:** `fact_player_match` and `fact_player_gw` are not required
  to have their `player_id` in `dim_player`. `dim_player` is the latest
  snapshot, and a player can leave the list (the 2025/26 GW2 sample has one).
  At the full-season builds there are no such orphans.
- **Cleaning rules added:**
  - `fact_player_match` rows are dropped, in this order, when their match has
    no `kickoff_time`, when it is not a processed match, or when the player is
    not in that gameweek's snapshot `players.csv`. Counted separately.
  - `dim_player` drops players with no `playerstats` row, counted (0 at the
    latest snapshots).
  - An unknown position, a Premier League club not in `teams`, or a
    non-integer count is an error, not a fix.

### 2026-11-10: data - no-kickoff rows are 40, not 4
- **Found:** 2025/26 has **40** matches with no `kickoff_time`, not four. Four
  are unfinished placeholders (2 EFL Cup, 2 Europa League). The other 36 are
  finished and have player stats: 16 Champions League, 12 Europa League, 7
  Conference League and one EFL Cup tie. The same 40 are in 66e73ea. 2026/27
  has none.
- **Applied:** the stated rule as written. All 40 are dropped from
  `fact_fixture`, and their 749 `fact_player_match` rows go with them, counted
  under `no_kickoff_time` and `match_has_no_kickoff_time`.
- **Effect:** 2025/26 loses 36 played cup and European matches that the
  rotation and fatigue features (brief data rule 3) could have used. Not
  decided here: the main session chooses between keeping the rule, or dropping
  only the four unfinished rows and allowing a null `kickoff_utc`.

### 2026-11-10: data - rule 9 premise not reproduced
- **Found:** in none of the last 14 upstream commits (up to
  `0206600`) does an unfinished match carry `stats_processed` or
  `player_stats_processed`. At 66e73ea the four GW10 matches that kicked off
  at 14:00 on 2026-11-08 had `finished`, `stats_processed` and
  `player_stats_processed` all false, with part-played scores of 0-0, 0-0, 0-0
  and 0-1.
- **The "14":** at 66e73ea, 14 matches in 2026/27 were `finished` with only
  one processed flag true: 10 cup or European matches (5 EFL Cup, 3 Europa
  League, 1 Champions League, 1 Conference League) and 4 Premier League
  matches. All 14 have final scores, so they are not the four part-played ones.
- **Effect:** none on the build. The rule (all three flags) is still right and
  harmless, and part-played scores are still nulled because those matches are
  not finished. The brief's rule 9 evidence line is what needs correcting.

### 2026-11-10: data - team_gc_on_pitch is two different numbers
- **Found** (processed tables, single-fixture Premier League gameweeks,
  compared with FPL's `goals_conceded` in `player_gameweek_stats`):
  - **Players with minutes > 0, 2026/27 GW1-10 and 2025/26 GW26-38:** it is
    goals conceded while the player was on the pitch. It equals FPL's figure
    in 99.8% (2,958 rows) and 99.5% (2,787 rows). For substituted players,
    where the whole-match figure and FPL's differ (750 and 673 rows), it
    equals FPL's in 744 and 663.
  - **0-minute rows, both seasons:** it is the team's whole-match goals
    conceded. Every non-zero value equals the opponent's final score (622 of
    622 Premier League rows in 2026/27; 661 of 661 in 2025/26, all in GW26-36).
    FPL's figure for these players is 0.
  - **2025/26 GW1-25:** 0-minute rows are 0, but for substituted players it is
    mostly the whole-match figure: of 2,024 rows where the two differ, 1,593
    equal the opponent's score, 340 equal FPL's, 91 equal neither.
  - Full-match players (90+ minutes) agree with FPL in 99.8-100% of rows in
    every period.
- **Nulls (2025/26):** 262 in `fact_player_match`, of which 241 are Premier
  League rows in 83 matches, GW16-36 (100 at 90 minutes, 141 at 1-89), and 21
  are cup rows. 223 of the 241 are in single-fixture gameweeks.
- **No values changed.** Proposals are in the task report.

### 2026-11-10: data - future gameweek folders (2026/27 GW11-38)
- Each holds `fixtures.csv` and `matches.csv` with that gameweek's scheduled
  matches (319 in total: 280 Premier League, 39 cup and European), a
  `players.csv` identical in content to GW10's (row order differs), the same
  `teams.csv`, and **header-only** `playerstats`, `playermatchstats` and
  `player_gameweek_stats` (0 rows, same headers as GW10).
- The scheduled matches have no score, xG, Elo or processing flag (all null or
  false), and kickoffs from 2026-11-21 12:30 to 2027-05-30 15:00.
- **Handling:** ingest reads the player files for every folder but keeps rows
  only up to the latest gameweek with `player_gameweek_stats` rows. Validation
  fails if player stats or a processed match appear after that gameweek, or if
  a gameweek before it is empty. Header-only files are why concatenated
  numerics load as object without explicit dtypes.

### 2026-11-10: data - other things seen
- Two 2026/27 `playermatchstats` rows (players 667 and 672, 0 minutes, cup
  matches in GW4 and GW9) are for players missing from that gameweek's snapshot
  `players.csv`, so they have no `team_id`. They are dropped and counted
  (`player_not_in_snapshot`).
- `dim_player` has nulls in `chance_next`, `news`, `pen_order`, `fk_order` and
  `corner_order`, and 1 null `ep_next` in 2025/26. Proposed for the contract.
- 20 finished 2025/26 Premier League matches (all of GW37 and GW38) are not
  fully processed upstream, so `fact_fixture` shows them unfinished with null
  results and `fact_player_match` has no rows for them, while `fact_player_gw`
  has FPL's points for them.
- `match_id` is unique within each season (525 and 484 rows) and does not
  repeat across the two seasons; both are validated on every run.

### 2026-11-10: main - task 1 review decisions
Josh decided items 1-4 after the data-engineer's report and Code Review. The
main session approved items 5-8. Upstream commit `0206600`.

- **Correction:** the evidence in "phase 1 task 1 cleaning rules", rule 1,
  was wrong. The main session misread a crosstab; no unfinished match carries
  the processed flags in any commit checked. Requiring `finished` is kept as
  a guard. Rule 2 of that entry is superseded by item 1 below, and rule 4's
  count is corrected by item 2.

1. **Results come from every finished match (Josh).** `fact_fixture` gains
   `processed`, and `finished` is upstream's own flag. Scores are kept for
   every finished match; xG, npxG and `fact_player_match` rows come only from
   processed matches.
   - Evidence: 20 Premier League matches in 2025/26 GW37-38 and 4 in 2026/27
     (one from GW1) are finished, with scores, but never processed. Josh
     confirmed that GW37 has a result for every game.
   - Why: otherwise the Elo ratings miss 24 results.
2. **Matches with no kickoff time are dropped (Josh).** There are 40, all
   2025/26 cup or European matches, and 36 of them were played. Josh: the
   xP model doesn't need non-Premier League matches. A Premier League match
   with no kickoff time fails validation.
   - Brief rule 3 still keeps the cup and European matches that do have a
     kickoff time, as rotation and fatigue inputs for the minutes model.
3. **`team_gc_on_pitch` is removed; `fact_player_gw.goals_conceded` is added
   (Josh).** It is FPL's own on-pitch figure.
   - Evidence (data-engineer, verified by the main session): upstream's
     `team_goals_conceded` equals the opponent's full score for every
     non-zero 0-minute row (661 of 661 in 2025/26). It is mostly the
     whole-match figure for 2025/26 GW1-25 substitutes, and has 241 genuine
     gaps in 2025/26.
   - Why: the defence model works from `lambda_against` and expected minutes,
     and FPL's figure is what gets scored. The only loss is a per-match split
     within double gameweeks.
4. **`fact_player_gw` keeps a row only when all the club's Premier League
   fixtures that gameweek are finished (Josh).** Blank-gameweek rows stay.
   Others are dropped and counted under `club_fixture_not_finished`.
   - Evidence (Code Review, verified): the current build holds 63 played GW10
     rows (182 points) for Chelsea, Coventry, Everton and Sunderland, whose
     matches aren't processed. At upstream `027b5a74` (2026-11-07 03:04 UTC)
     GW10 held 670 rows when only one match had been played.
   - Why: a Saturday 18:00 run would record every Sunday player as 0 minutes
     and 0 points.
5. **`dim_player` nulls:** `chance_next`, `news`, `pen_order`, `fk_order`,
   `corner_order` and `ep_next` may be null.
6. **Foreign keys:** fact tables may hold players missing from `dim_player`,
   which is the latest snapshot.
7. **Drop reasons** `no_playerstats_row` (`dim_player`) and
   `player_not_in_snapshot` (`fact_player_match`) are documented filters.
8. **Season ids** use upstream's folder names, such as `2025-2026`.
- **Note for task 5:** `players.csv` xG90 and xA90 must divide by the
  minutes of the same processed matches that supply the xG and xA
  (`fact_player_match`), not `fact_player_gw` minutes. Otherwise a finished
  but unprocessed match adds minutes with no xG.
- **Deferred to task 2:** input validation for part-seasons (Code Review
  finding 3), and the future fixture list for as-of reads.
- **Not done:** atomic writes across seasons. CI builds from scratch, and
  each season's `manifest.json` records its upstream commit.
- **Updated:** brief data rules 9 and 15 and the section 5 tables,
  `docs/data_contract.md` and `CONTEXT.md`.

### 2026-11-10: data - task 1 fix round
- **Built to the updated contract** on upstream `0206600`:
  - `fact_fixture` has `processed`, and `finished` is upstream's flag. Scores
    are kept for every finished match; xG and npxG only for processed ones.
    Finished-but-unprocessed Premier League results now kept: 20 in 2025/26
    (GW37-38) and 4 in 2026/27.
  - `team_gc_on_pitch` and the `team_goals_conceded` mapping are gone.
    `fact_player_gw.goals_conceded` is FPL's figure, never null.
  - `fact_player_gw` keeps a row only once every Premier League fixture of the
    player's club in that gameweek is `finished`. The club is the player's
    `team_code` in that gameweek's snapshot. Dropped rows are counted under
    `club_fixture_not_finished`; blank-gameweek clubs keep their rows.
    A player missing from the snapshot has no club to gate, so the row is
    kept (34 such 0-minute rows in 2026/27, none with points).
- **At `0206600` the count is 0** for 2026/27 GW10 and for every other
  gameweek, because all 10 GW10 Premier League matches are now finished. The
  gate is covered by tests (part-played gameweek, double gameweek, blank
  gameweek, finished-but-unprocessed, snapshot club).
- **Validation:** a Premier League match with no `kickoff_time` fails. The
  Premier League tag is read from `premier_league_tag`. `prem_matches_rows` is
  now [370, 380]; a count below 380 passes with a logged warning, for postponed
  matches that have no gameweek folder. Table checks now also fail on scores
  on unfinished matches, xG on unprocessed ones, and processed-but-unfinished.
- **Fixes from Code Review:** `as_of_gw=0` reads no folders (was the whole
  season); tests now cover a passing season followed by a failing one with
  nothing written, `validate_inputs` failing on the rule 15 guards, and the
  meaningless empty-directory assertion is removed.
- **Refactor:** error classes, `checked_merge`, `to_int`, `tenths`,
  `normalise_kickoff` and `map_codes` moved to `src/fpl/frames.py`; `clean.py`
  re-exports them.

### 2026-11-10: main - task 1 second review
Code Review's second pass approved the fix round: every fix was checked by a
mutant that undoes it.
- **Players missing from the snapshot are gated too (main session).** Their
  `fact_player_gw` rows were never gated. All 34 at upstream `0206600` are
  2026/27 GW1-3 players added to FPL mid-gameweek, with 0 minutes. Such a row
  is now held until every Premier League fixture in the gameweek is finished.
- **Open for Josh:**
  - Brief rule 8 is wrong. A gameweek folder's snapshot fields describe the
    run-up to the next deadline. Evidence: GW9's `transfers_in_event` totalled
    0 at `70f70217` (2026-10-31 13:47 UTC, after the GW9 deadline) and
    6,852,210 at `0206600`. 39 of 669 `now_cost` and 177 `selected_by_percent`
    values changed in between.
  - The `finished` gate releases provisional rows. Bonus, BPS and up to 7
    rows' points per commit kept changing for up to 7 hours after kickoff
    across GW9-10. The next run corrects them, and backtests read final
    folders.
- **Gate for players missing from the snapshot:** a `fact_player_gw` row whose
  player is missing from that gameweek's snapshot `players.csv` is held while
  any Premier League fixture in the gameweek is unfinished, counted under
  `no_club_gameweek_not_finished` (0 at `0206600`; the 34 GW1-3 rows stay).

### 2026-11-10: main - upstream's processed flags dropped (Josh)
- **Decision (Josh):** stop using upstream's `stats_processed` and
  `player_stats_processed` flags. A **complete match** is a finished match
  with both team xG values present and `playermatchstats` rows for each club
  that has a Premier League `team_id`. Complete matches supply xG and player
  match stats; every finished match supplies its result. A finished match
  that isn't complete is left out of the stats and counted.
- **Evidence (upstream `0206600`):**
  - All 20 2025/26 GW37-38 Premier League matches have `stats_processed`
    false, yet each has a result, xG and full player stats. They have a median
    of 39 player rows (32 for flagged matches) and 1,972 minutes (1,973), and
    the gap between summed player xG and team xG is 0.01 (0.01).
  - The 4 such 2026/27 matches are the same. Josh also checked by hand that
    every 2025/26 game has a result, including the Europa League final
    (Aston Villa 3-0 Freiburg, dropped only for its missing kickoff time).
  - The flags were discarding 924 good Premier League player-match rows (767
    in 2025/26, 157 in 2026/27) and those 24 matches' xG.
- **Trade-off:** a partly loaded match (some players missing, not all)
  passes the completeness check.
  - **Corrected after Code Review:** the main session first wrote that "the
    flags didn't catch that either". That is wrong for live gameweeks.
    Code Review replayed `complete_matches` over every GW9-10 commit and found
    7 matches called complete while their player stats were still changing.
    All 7 had `player_stats_processed` false at the time, and no flagged match
    ever changed afterwards.
  - Two Premier League matches and one EFL Cup match were each missing one
    0-minute row, for players 671 and 672, both late additions to FPL. Three
    European matches had per-player xG or xA revised for 6-8 players.
  - Team xG and minutes never changed.
  - So the flags did carry a live signal, but a small one: it concerned
    unused substitutes and European per-player stats (not used for points).
    The next run corrects it, and backtests read final folders. The decision
    stands; this is the true trade-off.
- **Renamed:** `fact_fixture.processed` becomes `stats_complete`, and the
  CONTEXT.md term "Processed match" becomes "Complete match", so upstream's
  flags aren't reintroduced by name.
- **Supersedes:** item 1 of "task 1 review decisions" (the flag part only;
  results from every finished match stand) and rule 1 of "phase 1 task 1
  cleaning rules".
- **The 4 no-result 2025/26 rows** are draw placeholders with the opponent
  still undecided (for example `aston-villa-vs-bologna/roma`). The real
  fixtures sit alongside them with results.
- **Updated:** brief data rules 9, 12 and 15 and the section 5 table,
  `docs/data_contract.md` and `CONTEXT.md`.

### 2026-11-10: main - rule 8 relabelled, provisional rows accepted (Josh)
Both were open items from "task 1 second review".
1. **Rule 8 relabelled (Josh).** A gameweek folder's snapshot fields
   (`now_cost`, `selected_by_percent`, `form`, `transfers_in_event`,
   `transfers_out_event`) describe the run-up to the next deadline, so
   `fact_player_gw` row g is known when predicting g+1, never g. No code
   change: the values stay in their own gameweek's row.
   - Evidence: GW9's `transfers_in_event` totalled 0 at `70f70217`
     (2026-10-31 13:47 UTC, after the GW9 deadline) and 6,852,210 at
     `0206600`. 39 of 669 prices and 177 ownership figures changed in
     between.
   - Rejected: shifting the columns down one gameweek. GW1 would be blank,
     and it would add code for no gain. The loader already predicts g+1 from
     rows up to g.
2. **Provisional rows accepted (Josh).** The `finished` gate stays. A
   released row can be provisional for some hours, and the next run corrects
   it.
   - Evidence (Code Review): across GW9-10 commits, up to 61 released rows
     per commit later changed, up to 7 of them in `event_points`, for up to 7
     hours after kickoff.
   - Rejected: a gate on upstream's processed flags, which are no longer used
     and would hold back matches whose data is complete.
   - **For phase 2:** the bonus model fits only on gameweeks before the as-of
     gameweek, in live and backtest runs alike (brief section 6.7).
- **Updated:** brief data rules 8 and 9 and section 6.7, and
  `docs/data_contract.md` (`fact_player_gw` notes).

### 2026-11-10: data - completeness check replaces processed flags
- **Done on upstream `0206600`.** `src/fpl/complete.py` (`complete_matches`)
  replaces `is_processed`. A complete match is finished, has both team xG
  values, and has `playermatchstats` rows for each of its clubs that is in
  `teams` (clubs from that gameweek's snapshot `players.csv`). Cup opponents
  outside the Premier League need no rows. No code in `src/` reads
  upstream's two processing flags, and a test fails if one does; the schema
  no longer lists them.
- `fact_fixture.processed` is `stats_complete`; xG and npxG are null unless
  it is true, and scores stay null unless `finished`.
- `fact_player_match` drops, in order, `match_has_no_kickoff_time`,
  `match_not_finished`, `match_not_complete` and `player_not_in_snapshot`.
  The reconciliation info lines are `finished_but_not_complete` and
  `finished_prem_but_not_complete`.
- **Result:** every finished match left in `fact_fixture` is complete, in both
  seasons (0 Premier League, 0 other). `fact_player_match` rows: 14,591 in
  2025/26 (was 13,824) and 5,528 in 2026/27 (was 5,152).

### 2026-11-10: main - npxG may be null on complete cup matches
- **Decision (main session):** `home_npxg` and `away_npxg` may be null on
  complete cup and European matches. A complete Premier League match without
  npxG fails validation.
- **Evidence (Code Review):** five complete 2025/26 EFL Cup matches (GW3-4,
  for example Man Utd v Grimsby) have null npxG. Under the old rule they were
  flagged processed too, so this predates the completeness change.
- **Why not make npxG part of completeness:** that would drop those matches'
  cup minutes, which the minutes model uses (brief rule 3). The model needs
  npxG only for Premier League matches, where a gap should be loud.
- **npxG check:** `validate_tables(tables, prem_tag)` now fails a complete
  Premier League match with null `home_npxg` or `away_npxg`. Complete cup and
  European matches may have null npxG (five 2025/26 EFL Cup matches do).
- **Validation never leaks a bare `JoinError`:** if completeness can't be
  worked out (for example a duplicate `(snapshot_gw, player_id)` in `players`),
  `validate_inputs` lists it as a problem with the others and skips the checks
  that need it. Completeness is computed once per call; `build_season` computes
  it once and passes the same Series to `build_fact_fixture` and
  `build_fact_player_match`.

### 2026-11-11: main - task 2 loader design settled before delegation
Main session, from the phase 1 plan and Code Review's task 1 notes. Josh gave
the go-ahead for task 2 on 2026-11-11.
1. **Later fixtures are schedule only.** In backtest mode `fact_fixture`
   carries fixtures from gameweeks after `as_of_gw`, with `finished` and
   `stats_complete` false and results, xG and upstream Elo null. This
   replaces the contract's "never returns a match after `as_of_gw`".
   - Why: fixture difficulty needs the upcoming schedule. In a 2025/26
     backtest the later folders hold full results (Code Review, task 1).
   - Upstream Elo is nulled too: it is the rating at kickoff, so it reflects
     results up to that match.
   - Known limitation: the schedule comes from the final folders, so a
     backtest sees reschedulings early.
2. **`fact_player_gw.team_id` added.** It is the club from that gameweek's
   snapshot, the same club the row gate already uses.
   - Why: recent minutes and starts must skip blank gameweeks and follow
     transfers, and `fact_player_gw` had no club.
3. **Deadline clock:** the next gameweek is the first with `deadline_time`
   strictly after the run time. A run at the exact deadline treats it as
   passed. As-of 0 applies before the GW1 deadline, and a run after the GW38
   deadline fails with a clear error. It uses the master
   `gameweek_summaries.csv`, so it is live only.
4. **Recent minutes and starts** are at gameweek grain from FPL's own
   figures, over the last N gameweeks in which the club had a fixture, with
   N given by the caller. Cup minutes and days since the last match are left
   to the minutes model.
5. **Brief rule 8 wording:** a snapshot can land up to about 7 hours after
   the next deadline (brief section 7), so "shortly before its deadline"
   became "around its deadline".
- **Updated:** `docs/data_contract.md` (`fact_player_gw`, source notes,
  nullable list, point-in-time loader), brief section 5 (`fact_player_gw`,
  loader) and brief data rule 8.

### 2026-11-11: data - task 2 point-in-time loader built
- **Built on upstream `0b9378f088317a7e9814a924e9b13c582df0a396`** (2026-11-11
  02:56 UTC, pulled over `0206600`). Row counts are unchanged:
  2025/26 841 / 20 / 485 / 14,591 / 29,978 and 2026/27 672 / 20 / 484 / 5,528 /
  6,596 (`dim_player` / `dim_team` / `fact_fixture` / `fact_player_match` /
  `fact_player_gw`). `fact_player_gw.team_id` is null in 0 rows for 2025/26 and
  34 for 2026/27 (GW1 6, GW2 26, GW3 2; the players added mid-gameweek, all 0
  minutes and 0 points).
- **Layout:** `features.py` (`load_as_of`, `live_gameweeks`, `recent_minutes`),
  `clock.py` (the deadline clock, pure), `overlay.py` (the live overlay, pure),
  `playergw.py` (`fact_player_gw`, moved out of `clean.py` for the 300-line
  limit; `fpl.clean` still exports `build_fact_player_gw`). `ingest.py` gained
  the schedule read, `read_deadlines`, `read_master_state` and
  `upstream_data_dir`. These last two are the only readers of master files.
- **Signature:** `load_as_of(season, as_of_gw, mode, *, cfg=None, root=ROOT)`.
  `cfg` and `root` are only for tests and for pointing at another checkout.
  It reads the upstream folders (not the Parquet), validates the inputs and the
  built tables, and raises on any failure. It does not call git; the upstream
  commit is the manifest's job.
- **Schedule read (`ingest.read_season(as_of_gw=)`):** folders up to `as_of_gw`
  are read in full. Folders after it are read for `fixtures.csv` and
  `matches.csv` only, and `blank_results` sets `finished` false and the scores,
  xG, npxG and both Elo columns null before anything else sees them. So no
  later stage can leak a result, and the clean/validate code is unchanged apart
  from `fact_player_gw.team_id`.
- **Part-season validation (task 1 finding 3):** because the schedule of every
  folder is read, the existing full-season checks are correct again. Folders
  after `as_of_gw` must still have `matches` and `fixtures` (a missing file
  fails), `matches_rows` and `prem_matches_rows` count the whole season, and a
  *finished* match in a folder after the latest played one still fails the
  run; after blanking it can only appear if the blanking is removed. The player
  file bounds apply to the folders read. `as_of_gw` 0 is allowed to have no
  player data and no `playerstats` snapshot. Checked on real data at the real
  bounds: `as_of_gw` 5 for both seasons, and all 39 values for 2025/26.
- **`as_of_gw` 0:** `fact_fixture` is the whole schedule (nothing finished),
  `dim_team` has the GW1 ids, codes and names with `upstream_elo` null, and
  `dim_player` and the player fact tables are empty with the right columns. GW1's
  prices and `ep_next` come from after the first gameweek, so they are not used.
- **Live overlay:** each `dim_player` row takes `status`, `news`, `chance_next`
  and `price_tenths` from the player's row with the highest `gw` in the master
  `playerstats.csv`. A cleared concern (blank in the master) clears the snapshot
  value. A player with no master row keeps the snapshot values (warning
  logged); master rows for players not in `dim_player` are ignored. A duplicate
  `(id, gw)`, a null `status` or a price outside `now_cost_m` fails the run.
  `team_id` is not overlaid, so a transfer shows from the next gameweek's
  snapshot.
- **Deadline clock** (`clock.py`): `parse_deadlines`, `next_gameweek`,
  `as_of_gameweek`, and `features.live_gameweeks(season, run_utc)` to read the
  master file. Strictly after; a run at the exact deadline counts it as passed;
  before the GW1 deadline the as-of gameweek is 0; at or after the GW38
  deadline `DeadlineError` names GW38. Offset, `Z` and naive stamps are all UTC
  (a naive run time too). The table must be gameweeks 1..N with strictly
  increasing deadlines, else `DeadlineError`. Evidence: in both seasons all 38
  `deadline_time` values are 25 characters, `YYYY-MM-DDTHH:MM:SS+00:00`, and the
  rows are not in gameweek order in the file (GW1, 2, 15, 16 ...). The mixed
  formats are handled but not seen.
- **Recent minutes and starts** (`features.recent_minutes(tables, as_of_gw,
  windows, prem_tag=None)`): one row per player and window (`player_id`,
  `window`, `minutes`, `starts`, `fixtures`). A gameweek counts for a player
  when he has a `fact_player_gw` row and his club (that row's `team_id`) has at
  least one Premier League fixture in `fact_fixture` that gameweek. A blank
  gameweek is skipped, a double counts once with `fixtures` 2, a row with no
  club is skipped, and a gameweek still being played for his club has no row
  yet (the gate), so it is not counted. A player with no such gameweek (including
  anyone only in `dim_player`) gets zeros. Windows must be distinct positive
  integers.
- **Tests:** a synthetic 38-gameweek season (`tests/synth.py`: 4 clubs, a blank
  gameweek, a double, a transfer, a cup match, full results in every folder as in
  the real final folders, poisoned master files). Leakage is tested for all 39
  values of `as_of_gw` on the synthetic season and, when the checkout exists, on
  real 2025/26 (a spread by default, all 39 with `FPL_FULL_SWEEP=1`; both
  passed). 314 tests, 99% line coverage of `src/fpl`. Each protection was
  mutated by hand and the tests failed: reading every folder, not blanking
  results, overlaying in backtest mode, reading a master file in backtest mode,
  taking `team_id` from the wrong snapshot, not skipping blank gameweeks, and a
  deadline comparison of `>=`.
- **Runtime:** a full backtest sweep (2025/26, `as_of_gw` 1-38, real data, with
  validation and the leakage check): 39.8 s in total, 1.04 s a call on average
  (0.54 s at GW1, 1.59 s at GW38). No caching added.

### 2026-11-11: data - cup and European matches sit in the folder of the next deadline
- **Found** (upstream `0b9378f`, `matches.csv` kickoffs against the master
  `deadline_time`): every Premier League match, 380 of 380 in both seasons, is in
  the folder of the FPL window it kicked off in (deadline g <= kickoff <
  deadline g+1 is folder g). Cup and European matches are not:
  - **2026/27:** all 104 (champions-league 40, europa-league 24, efl-cup 34,
    conference-league 6) are in folder g+1. A midweek match played between the
    GW g and GW g+1 deadlines is in the **GW g+1 folder**.
  - **2025/26:** of 105 with a kickoff, 64 are in folder g, 35 in folder g+1
    and 6 far later (champions-league 4, europa-league 1, conference-league 1;
    for example a GW4-window match in the GW30 folder). The 2025/26 folders were
    rewritten on 2026-07-22 (brief section 7), so that is not live behaviour.
- **Evidence it is available early:** the GW10 folder at `92a90c26`
  (2026-11-06 15:16 UTC, before the 18:30 GW10 deadline) already held the 9
  cup and European matches of 3-5 November, finished, with 185
  `playermatchstats` rows.
- **Effect:** a read with `as_of_gw` = g treats folder g+1 as schedule only, so
  the midweek cup and European matches just before the GW g+1 deadline are not
  visible, in live or backtest, until g+1 becomes the as-of gameweek. That is
  consistent between the modes (no leakage), but the freshest rotation and
  fatigue signal for the minutes model is hidden at the moment of the decision.
  No code change; proposed in the report as a decision for the main session.

### 2026-11-11: data - the newest folder and as-of gameweek, and 2025/26 team Elo
- **`as_of_gw` ahead of the newest folder with data happens.** For GW2-10 of
  2026/27 the first commit in which `GW{g}/player_gameweek_stats.csv` has rows
  came 1.9 to 7.9 hours after the GW g deadline: GW2 2.0 h, GW3 7.8, GW4 5.3, GW5
  7.9, GW6 3.9, GW7 7.9, GW8 1.9, GW9 2.8, GW10 2.5. Until then the folder is
  header-only. A run at 18:00 UTC fell inside that gap for GW2, GW3, GW5 and
  GW8 (4 of 9); an 08:00 run for none. In the gap the next gameweek is g+1, so
  the as-of gameweek g is one ahead of the newest folder with data (g-1). The
  loader then returns what exists: the tables through g-1, with GW g's matches as
  unfinished schedule rows. Tested on a synthetic season and on real 2026/27
  with `as_of_gw` = newest + 3. Today (2026-11-11) it does not occur: the next
  deadline is GW11 on 2026-11-21 11:00 UTC, so the as-of gameweek is 10, the
  newest folder.
- **2025/26 `teams.csv` Elo is not per gameweek.** It is identical in folders GW1
  to GW25 (for example team code 1: 1881) and changes at GW26 and in most later
  folders. So `dim_team.upstream_elo` in a 2025/26 backtest with `as_of_gw` <= 25
  is the same pre-season-looking value. No future value leaks, but it is not the
  rating at that gameweek. The match-level `home_upstream_elo` and
  `away_upstream_elo` in `fact_fixture` are per match and should be used for
  anything Elo-related. 2026/27 `teams.elo` is null in every folder.

### 2026-11-11: main - task 2 review decisions
Josh decided items 1-4 after the data-engineer's report and Code Review. The
main session confirmed the evidence on upstream `0b9378f`.
1. **Cup and European matches count once they kick off before the next
   deadline (Josh).** A read at as-of g holds Premier League fixtures up to g,
   plus cup and European matches that kicked off before the GW g+1 deadline,
   whichever folder holds them.
   - Evidence: all 65 2026/27 cup and European matches in folders 1-11 sit
     one folder after the window they kicked off in. So a midweek tie before
     the GW g+1 deadline is in folder g+1, and the minutes model's "cup
     minutes in the previous 7 days" would otherwise never see it.
   - The deadline is derived as the first Premier League kickoff minus 90
     minutes, which is exact for all 38 2026/27 gameweeks. This keeps
     backtests off the master files.
2. **`dim_team.upstream_elo` becomes each club's latest kickoff Elo in the
   read (Josh chose the alternative to dropping it).**
   - Evidence: 2025/26 `teams.csv` Elo is identical in folders GW1-25 and
     equals clubs' GW26-30 kickoff Elo (mean gap 0.3). For example, Arsenal
     reads 2065 against 1993 at the GW1 kickoff. The data-engineer's report
     said nothing leaks; the main session found otherwise.
   - Effect: point-in-time correct in every read. For 2026/27 it gives the
     GW1-2 seeds (Arsenal null, as phase 0 found).
3. **Nothing before the GW1 deadline is accepted (Josh)** and logged in the
   new `docs/known_gaps.md`, which Josh asked for to record gaps to address
   once the model is running.
4. **Later cup and European matches are left out of as-of reads (Josh).**
   Later Premier League fixtures stay as schedule only.
   - Evidence (Code Review, confirmed): a 2025/26 backtest at as-of 10 held
     48 later cup and European fixtures, including the EFL Cup semi-finals
     (Arsenal v Chelsea, Man City v Newcastle). Those were decided by
     quarter-finals in folders 16-17. The 2026/27 holdout has the same
     problem.
- **Approved by the main session:**
  - the loader's names and signatures, now in the contract;
  - the live overlay rules: the newest master row wins, cleared concerns
    clear, players with no master row keep their snapshot values, and rows
    are matched by `player_id`;
  - a live run at as-of 1 before upstream writes GW1 returns the as-of-0
    tables, as the contract says;
  - `FPL_FULL_SWEEP=1` in CLAUDE.md's commands.
- **Code Review fixes, sent with these decisions:**
  - Live runs between a deadline and upstream's first player figures fail on
    finished European matches already in the folder. Confirmed on upstream
    `92a90c26`: an 18:00 run loads, a 19:00 run raises.
  - The overlay crashes when a player has no master row.
  - The overlay matches rows by position.
  - Tests are missing for equal deadlines and for the as-of filter in
    `recent_minutes`.
- **Updated:** `docs/data_contract.md` (Elo source note, loader section),
  brief data rule 12 and section 5, `CONTEXT.md`, `CLAUDE.md`, and the new
  `docs/known_gaps.md`.

### 2026-11-11: data - task 2 fix round
Built to the updated contract on upstream `0b9378f` (unchanged since the first
build).
- **Which matches a read holds** (`src/fpl/asof.py`, pure; `read_season` now
  takes `prem_tag` and `offset_minutes`, from `premier_league_tag` and the new
  `loader.deadline_offset_minutes: 90` in `config/pipeline.yaml`):
  - The cutoff for as-of g is the first Premier League kickoff of GW g+1 minus
    90 minutes, from the schedule. At as-of 38 (or beyond) there is no cutoff
    and every match counts. A gameweek with no Premier League kickoff raises
    `ScheduleError`.
  - Premier League matches after g are blanked to schedule only (as before).
    A cup or European match is held iff it kicked off strictly before the
    cutoff, whichever folder holds it, and is left out entirely otherwise
    (including one with no kickoff time, until as-of 38).
  - `players` and `playermatchstats` are read for a later folder only if it
    holds a held cup match. Those rows are kept for cup and European matches
    from any folder read, so clubs come from that folder's snapshot; Premier
    League player rows still stop at the latest played gameweek. The full read
    (`as_of_gw=None`) follows the same rule, so cup rows in a folder after the
    latest played one now reach `fact_player_match` there too.
  - Real data, 2026/27 as-of 9 (backtest): 65 cup and European matches (all
    finished and complete) with 1,543 player rows, of which 9 matches and 185
    rows are filed in the GW10 folder. As-of 10: the same 65 and 1,543, none
    from folder 11 (it holds no cup match yet).
  - The derived deadline equals FPL's `deadline_time` for all 38 gameweeks of
    2026/27 (tested, `tests/test_loader_real.py`).
- **`dim_team.upstream_elo`** is each club's latest non-null kickoff Elo among
  the finished matches in the read (`clean.latest_kickoff_elo`). `teams.elo` is
  no longer read (removed from `RAW_SCHEMA`). 2025/26 at as-of 1: Arsenal
  1993.36, Liverpool 1993.42, Man City 1959.96 (`teams.csv` says 2065 for
  Arsenal); at as-of 25: 2062.52, 1958.14, 1964.84. The full 2026/27 build
  has 19 clubs with a value (Arsenal null).
- **Validation (finding 6):** "data after the latest gameweek" now means
  Premier League data. `check_latest_gw` flags finished Premier League matches
  in later folders, and `gw_rows["playermatchstats"]` counts Premier League
  rows only; finished cup matches and their rows there are normal. This also
  stops the plain pipeline failing the first time a GW g+1 cup tie finishes
  before upstream writes GW g+1. The `matches_rows` floor is lowered to the
  Premier League floor on an as-of read (later cup matches are left out); the
  Premier League bound and the ceiling still apply. The per-match player row
  bound now covers every complete match, not only those up to the latest
  gameweek. Real repro (`92a90c26`, `probe_real_gap.py`): a live run at 18:00
  gives next 10, as-of 9 and loads (`fact_fixture` 445, `fact_player_match`
  5,130, `fact_player_gw` 5,924); at 19:00 it gives next 11, as-of 10 and now
  loads with the same row counts (it raised before). The test uses a sample cut
  from that snapshot (`tests/fixtures/upstream_gap`, built by
  `tests/fixtures/build_gap_fixture.py`).
- **Overlay (7, 8):** rows are matched by `player_id` with `.loc`, never by
  position; values are cast to the column's dtype, so a player with no master
  row keeps his snapshot values and `price_tenths` stays int64. Duplicate
  `player_id` in `dim_player` raises. Tests: shuffled and filtered
  `dim_player`, schema check.
- **As-of 1 before GW1 is written (9):** a read with no player figures at all
  passes validation at as-of 0 or 1, and returns the as-of-0 tables (tested
  through `load_as_of` in both modes). Any other as-of with no figures still
  fails. `teams` comes from GW1 whenever nothing is played.
- **Other test gaps (10):** equal deadlines are rejected (`parse_deadlines`
  already did via `duplicated()`; now tested, including the same instant in
  another offset). The redundant fixture-side as-of filter in `recent_minutes`
  was removed, so the `gw <= as_of_gw` filter is the single guard and a test
  with a player whose rows all come after as-of kills its removal.
- **Leakage checks (11):** `assert_no_leakage` now also checks that no cup match
  at or after the cutoff and no player row of one is present, that membership
  equals the full build's (every Premier League fixture, cup matches iff before
  the cutoff), and that `dim_team.upstream_elo` equals a plain-loop recomputation
  from the read's own fixtures. The synthetic season gained `cup-late` (filed in
  the GW25 folder, played before GW3), and its `truncate_after` now leaves
  finished cup matches and their rows in the folders after the last played one,
  as upstream does.
- **Speed:** `read_table` reads only the columns in `RAW_SCHEMA` (`usecols`),
  which cut a read of all 38 folders from 4.4 s to 2.4 s on a busy machine. Full
  backtest sweep, 2025/26 as-of 1-38 with validation and the leakage check:
  73 s in total, 1.87 s a call (0.49 s to 2.81 s). Earlier today the same sweep
  took 39.8 s on a quieter machine, before the cup folders were added and
  `usecols`.
- **Files:** `master.py` (the master readers, moved from `ingest.py` so the only
  code that can open a master file is in one place), `asof.py`. `validate.py` is
  at 295 lines.
- **Checks:** 371 tests, 99% line coverage of `src/fpl`; `ruff check .` clean;
  the `FPL_FULL_SWEEP=1` run of `tests/test_loader_real.py` (all 39 as-of values
  of 2025/26, 0-10 of 2026/27, the rest) passed 59 tests. Mutants, all killed:
  cutoff `<=`, later cups kept, cups by folder instead of kickoff, finished-cup
  check not restricted to the Premier League, cup rows counted as Premier League
  rows, Elo `first` not `last`, Elo from unfinished matches, positional overlay,
  float overlay dtype, equal deadlines allowed, no `as_of` filter in
  `recent_minutes`, as-of 1 gap rejected, deadline offset ignored, no extra-folder
  read.

### 2026-11-11: main - task 2 second review decisions (Josh)
Code Review's second pass confirmed every first-round fix and found two new
2025/26 leaks that the leakage tests missed. The main session confirmed both
on the data. Josh approved both recommendations.
1. **Upstream Elo is kept for Premier League matches only.** Cup and
   European rows' `home_upstream_elo` and `away_upstream_elo` are null, and
   `dim_team.upstream_elo` comes from Premier League kickoffs only. This
   refines decision 2 of the first review (latest kickoff Elo).
   - Evidence: at 2025/26 as-of 2, Bournemouth's `upstream_elo` was 1871.97,
     from its 26 August EFL Cup tie. It reaches that value only at Premier
     League kickoffs in GW34-38; its GW1-2 kickoff Elo was 1804 and 1808.
     Brentford and Fulham look the same.
   - Scale: 38 (club, as-of) pairs across as-of 1-37, and 71 of 103 cup rows
     sit more than 10 points from the surrounding league ratings. 2026/27 cup
     rows carry no Elo.
2. **A cup or European match's `gw` is the gameweek it was played in.** That
   is the latest deadline at or before kickoff. Players' clubs come from that
   gameweek's snapshot.
   - Evidence: Palace's 23 October 2025 Conference League tie is filed in the
     GW30 folder. That folder's snapshot puts Guéhi (player 260, 90 minutes)
     at Man City, so every read from as-of 8 to 22 knew about his January
     move.
   - Effect: "gw up to as-of" now means the same for every competition.
     Premier League matches are unchanged, because all 380 per season are
     already in their own gameweek.
   - Rows whose club isn't one of the match's clubs are dropped and counted
     under `club_not_in_match`, and validation checks it. Code Review counts
     1 in 2025/26 (Bailey in Kairat v Arsenal, an upstream id error) once
     Guéhi is fixed, and 5 EFL Cup rows in 2026/27.
- **Also sent as fixes:**
  - a header-only `players.csv` passed validation (it predates task 2);
  - a missing next-gameweek `matches.csv` raised before validation;
  - stale docstrings.
- **Added to `docs/known_gaps.md`:** derived deadlines would drift if a
  gameweek's first fixture were postponed late. It hasn't happened in
  either season.
- **Updated:** `docs/data_contract.md` (`fact_fixture.gw`,
  `fact_player_match.team_id`, Upstream Elo, loader section), brief data
  rules 5 and 12, and `CONTEXT.md` (Match).

### 2026-11-11: data - task 2 second fix round
Built to the second review decisions on upstream `5ae1d4a` (2026-11-11 15:30
UTC, pulled during the round). Row counts are the same as at `0b9378f` except
`fact_player_match`.
- **Upstream Elo for Premier League matches only.** `build_fact_fixture` nulls
  `home_upstream_elo` and `away_upstream_elo` on every cup and European row, so
  `dim_team.upstream_elo` can only come from league kickoffs. `validate_tables`
  fails any cup row with Elo. 2025/26 as-of 2: Bournemouth 1804.01 (its GW2
  kickoff; the 26 Aug EFL Cup row said 1871.97), Brentford 1799.19, Fulham
  1784.41.
- **A cup or European match's `gw` is the gameweek it was played in** (`asof.py`):
  `deadlines()` derives every gameweek's deadline from the schedule (first
  Premier League kickoff minus 90 minutes), and `played_gw()` is the latest
  gameweek whose deadline is at or before kickoff, 0 before GW1.
  - `select_matches` holds a match iff it is a Premier League match or its
    played gameweek is up to as-of (every match at the last gameweek). The old
    cutoff function is gone. `snapshot_gw` still records the filing folder and
    `gameweek` becomes the played gameweek, in the full read too, so the full
    and as-of builds agree. Matches without a kickoff time keep their folder's.
  - Clubs come from the `players` snapshot of that gameweek, at least GW1: the
    rows are read from the filing folder, then get that `snapshot_gw` (`_at_club_snapshot`
    in `ingest.py`). Only a read at as-of 0 needs a `players` folder it hasn't
    already read (GW1).
  - `read_season` now requires `offset_minutes`, since cup gameweeks need the
    deadlines in every read. `check_references` compares `gameweek` with the
    folder for Premier League matches only.
  - Real data: no GW0 cup or European match exists in either season (0 and 0;
    the first cup match is in gameweek 2 in 2025/26 and 1 in 2026/27). A
    synthetic and a doctored-sample test cover GW0.
- **`club_not_in_match`** (`build_fact_player_match`, logged with player and
  match, counted in the reconciliation; `validate_tables` also fails any row
  whose `team_id` is neither of the match's clubs, reading a null opponent as
  "not the club", which an early version of the check got wrong).
  - 2025/26: 2 rows. Semenyo (id 82, Bournemouth) in the EFL Cup tie Man City
    v Newcastle, 90 minutes; Bailey (id 49, Aston Villa) in the Champions
    League tie Kairat v Arsenal, 13 minutes. Guéhi is fixed, not dropped.
  - 2026/27: 6 rows, all EFL Cup: Savinho (403, Man City, 19 min) in Tottenham v
    Charlton; Watson (133, Brighton, 90) in Ipswich v Leicester; Morato (470,
    Nott'm Forest, 83), Piroe (348, Leeds, 7) and Mukasa (409, Man City, 51) in
    West Ham v Fulham; Neave (466, Newcastle, 90) in Everton v Wolves. Code
    Review expected 5.
  - **Side effect:** with clubs read at the played gameweek, 2026/27
    `player_not_in_snapshot` rises from 2 to 7 rows: players absent from the
    GW1, GW3, GW4 or GW8 snapshot who played a cup tie then. Three have
    minutes: 623 (90, Plymouth/Exeter v Coventry), 626 (45, Fulham v Bournemouth)
    and 661 (90, Reading v Brentford); the others have 0. Dropped and counted,
    as the contract says.
  - Row counts: `fact_player_match` 14,589 in 2025/26 (was 14,591) and 5,517 in
    2026/27 (was 5,528); the other tables are unchanged (841 / 20 / 485 /
    29,978 and 672 / 20 / 484 / 6,596, with 34 null `fact_player_gw.team_id`
    in 2026/27). Real as-of 9 on 2026/27: 65 cup matches, 1,532 player rows.
  - Guéhi (260) for AEK Larnaca v Crystal Palace (23 Oct 2025, filed in the
    GW30 folder) at as-of 8: Crystal Palace (team 8), 90 minutes.
- **Validation:** a players snapshot that the read needs (gameweeks 1 to the
  latest, and the snapshots of held cup rows) and that has no rows now fails the
  bound (`reindex(..., fill_value=0)`; a groupby never saw it). A missing
  next-gameweek `matches.csv` no longer raises `ScheduleError`: deadlines are NaT
  for a gameweek with no kickoff, and the missing file is reported with the other
  problems. `validate.py` is split: table checks live in `validate_tables.py`
  (251 and 76 lines).
- **Leakage tests by provenance** (`tests/leakage.py::assert_provenance`, in
  `assert_no_leakage`, run by the real sweep at all 39 as-of values of 2025/26
  and 0-10 of 2026/27): every non-null `dim_team.upstream_elo` is a league
  kickoff Elo of that club before the cutoff in the full build; every
  `fact_player_match` club is one of the match's clubs; every cup or European
  row has `gw` up to as-of. Proof on the reverted code (real 2025/26, as-of 2 and
  8, provenance check alone, with the validation checks switched off):
  - Elo fix reverted: "club 3: Elo 1728.84 is no league kickoff";
  - club fix reverted (filing-folder snapshot, no drop): "player rows for a club
    not in the match: 1";
  - `gw` fix reverted: "a cup or European match with a later gameweek".
  All three pass on the fixed code. Further mutants killed: no NA fill in the
  table club check, players bound without reindex, club snapshot not applied,
  no `club_not_in_match` drop, cup `gw` as folder, cup Elo kept, GW1 players not
  read at as-of 0.
- **Docstrings** in `overlay.py` and `features.py` updated. **Checks:** 391
  tests, 99% coverage of `src/fpl`, `ruff check .` clean, no file over 300
  lines; `FPL_FULL_SWEEP=1` run of `tests/test_loader_real.py` passed 61 tests.
  Full backtest sweep, 2025/26 as-of 1-38: 64.5 s, 1.62 s a call.
- **For the main session:** the contract's as-of 0 bullet says `fact_fixture` is
  the Premier League schedule; under the revised rule a read at as-of 0 also
  holds any cup match played before the GW1 deadline (none exist in the data).

### 2026-11-11: main - task 2 final review follow-ups
Code Review's third pass approved task 2, committed as `f41e60a`. Its four
non-blocking findings were settled by the main session:
1. **Drops are capped.** `club_not_in_match` and `player_not_in_snapshot`
   get per-season caps in `config/pipeline.yaml`. Code Review simulated two
   club-mapping regressions on the real 2025/26 build: one dropped 195
   genuine rows, the other emptied `fact_player_match` entirely, and
   validation passed both.
2. **Cup rows of players who moved that gameweek stay dropped** and are
   logged in `docs/known_gaps.md`. Two genuine rows are affected: Semenyo
   (2025/26 GW21) and Sávio (2026/27 GW1).
   - Why: recovering them from later snapshots would break the rule that an
     as-of read equals the full build for its gameweeks.
3. **A gameweek with no Premier League fixture takes the previous
   gameweek's last Premier League kickoff as its deadline**, and its folder
   may be empty.
   - Why: on a synthetic wholly postponed gameweek (as in 2022/23 GW7), a
     cup tie was dated a gameweek early and its result was visible at the
     earlier as-of. An empty folder failed every read. The new deadline can
     only date a tie late.
4. **Derived deadlines must strictly increase.** A single mis-dated kickoff
   otherwise moved two cup ties out of every read until as-of 30.
- Also: stale docstrings in `clean.py` and `complete.py`.
- **Updated:** `docs/data_contract.md` (`fact_player_match` drop caps,
  loader deadline rules) and `docs/known_gaps.md`.

### 2026-11-11: data - task 2 final follow-ups
Built on upstream `5ae1d4a`; row counts are unchanged (841 / 20 / 485 / 14,589 /
29,978 and 672 / 20 / 484 / 5,517 / 6,596).
- **Drop caps** (`validation.max_dropped_rows` and
  `fact_player_match_rows_per_complete_match_min` in `config/pipeline.yaml`;
  `check_drops` and `check_rows_per_match` in `validate_tables.py`, run at the end
  of `build_season`, which raises `ValidationError`).
  - A **share** of the `playermatchstats` rows read, 0.5%, with at least 5 rows
    always allowed, for each of `club_not_in_match` and `player_not_in_snapshot`.
    A share because the same cap then fits both seasons and every as-of read
    (a count would need scaling with the rows read); the 5-row floor is because the
    worst real case is 2 stray rows in 615 (0.33%, 2026/27 as-of 1), which a pure
    0.5% would only just pass. Real worst cases over all as-of reads: 0.33% and
    0.02% (full 2025/26); the latest-snapshot regression is 1.3%, so it is caught
    with a cap of 77 rows (197 dropped).
  - Floor: 15 `fact_player_match` rows per complete match after the drops (real
    minimum over all as-of reads 25.3). The synthetic season lowers it to 2.
  - Probe `probe_club_drop.py`: as built passes (14,589 rows); clubs from the latest
    snapshot fails ("197 of 15340 rows dropped for club_not_in_match, over the cap
    of 77"); misaligned club codes fails (cap and floor: "0 rows for 485 complete
    matches"). Both are also real-data tests.
- **A gameweek with no Premier League fixture** takes the last Premier League
  kickoff of the latest earlier gameweek that has one as its deadline (no offset;
  NaT for GW1), with a warning (`asof.deadlines`). An empty matches file for such a
  gameweek no longer fails `check_latest_gw` (it logs a warning); a missing file
  still fails as a missing file, and the Premier League count bound still applies.
  Probe `probe_empty_gw.py` (GW12 league fixtures moved to GW13, a 9 Nov cup tie in
  folder 12): deadlines GW11-13 are 1 Nov 12:30, 1 Nov 17:00, 15 Nov 12:30; the tie
  is dated gw 12; at as-of 11 it loads and the tie is absent; at as-of 12 it is
  held (gw 12, finished, 3-1). The empty-folder variant loads at as-of 11-13.
- **Derived deadlines must strictly increase** (`asof.deadline_problems`, in
  `validate_inputs`), skipping gameweeks that take the fallback. Probe
  `probe_bad_kickoff.py` (one GW30 fixture dated 1 Sep 2025): as-of 9, 29 and 30
  all fail with "derived deadline of GW30 is not after that of the gameweek before
  it". The real 2025/26 and 2026/27 deadlines pass.
- **Docstrings** in `clean.py` (`build_fact_player_match`) and `complete.py` now say
  the club comes from the snapshot named by the row's `snapshot_gw`, and mention
  `club_not_in_match` and the caps. Semenyo and Sávio stay dropped; GW0 is unchanged.

### 2026-11-12: main - task 3 Elo design settled before delegation (Josh)
The main session checked upstream Elo on upstream `5ae1d4a` (through
`load_as_of`) before writing task 3. Two premises of the brief were wrong.
Josh took all eight recommendations.
- **Evidence:**
  - **2025/26 upstream Elo is frozen for stretches.** Counting, per gameweek,
    the clubs whose kickoff Elo differs from their previous kickoff: all 20 at
    GW2-26 (except GW20, 12 of 20), none at GW27-32, 20 of 26 kickoffs at GW33
    (a double gameweek), 14 of 14 at GW34, 6 of 20 at GW35 and none at
    GW36-38. Every club's last change is in GW34 (14 clubs) or GW35 (6).
  - **Size of a freeze:** upstream's ranking at GW32 (frozen since GW26)
    against GW33 (moving again) has Spearman 0.931, a mean change of 21.5
    points and a maximum of 78.2. So a model that tracked ClubElo perfectly
    could sit near the 0.9 pass mark on frozen weeks.
  - **The 2026/27 GW1-2 values are stale 2025/26 values.** For all 16 clubs
    with a value in both seasons, the 2026/27 value equals the club's 2025/26
    GW38 kickoff value exactly, and GW1 equals GW2 wherever both exist. 2026/27
    has values for 16 clubs at GW1 and 18 at GW2; Arsenal has none, Coventry,
    Leeds and Nott'm Forest only GW2, and Aston Villa only GW1. Arsenal's last
    2025/26 kickoff value is 2063.76 (GW38).
  - **Where it moves, it is the pre-match rating.** Across 2025/26, a club's
    change to its next kickoff correlates 0.51 with this match's result and
    0.05 with the previous match's.
  - scipy and statsmodels are not installed (`requirements.txt` has numpy,
    pandas, pyarrow and PyYAML).
- **Decisions:**
  1. **Tune and judge the ratings only where upstream Elo moves.** The pass
     mark becomes Spearman ≥ 0.9 at GW6-26 and GW33-34; frozen gameweeks are
     reported without a pass mark. Trade-off: the late-season check covers two
     gameweeks; Josh's outside-source comparison covers the frozen and missing
     stretches.
  2. **One continuous Elo run from 2025/26 GW1**, replacing "seed 2026/27 from
     its GW1-2 rows, and Arsenal from 2025/26". Every 2025/26 club is seeded
     from its GW1 kickoff Elo and the ratings run on through 2026/27. Coventry,
     Hull and Ipswich are seeded from their 2026/27 rows.
     - Why: every result is used once, frozen values never enter, and the
       published 2026/27 ratings continue the run that was tuned and checked.
     - Trade-off: our ratings count Premier League matches only, while ClubElo
       counts every competition, so clubs in Europe can drift. The 2025/26
       replay shows how much. Rejected: the brief as written, which loses
       every club's 2025/26 GW35-38 results.
  3. **The Elo goals model fits on results up to and including the as-of
     gameweek.** A finished result is final, unlike bonus, so "before the
     as-of gameweek" only threw away the newest results.
  4. **The Elo goals model fits on this season and last** (brief 6.2); 2025/26
     has no earlier season loaded, so it fits on itself. The modeller sets a
     minimum sample in `config/model.yaml` and reports what happens below it.
     Trade-off: 2025/26 GW1-3 are weak, and they carry no pass marks. Rejected:
     loading 2024/25 for priors.
  5. **Components return DataFrames; task 5's `export.py` writes
     `elo_ratings.csv` and `fixture_difficulty.csv`.** This settles a conflict
     between the contract (the Elo component writes the file), the plan
     (`export.py`) and the agent file (only `xp.py` writes outputs).
     - The Elo goals model returns `lambda_for`, `lambda_against` and `p_cs`
       for each team's Premier League fixtures in the next `max_horizon`
       gameweeks. `lambda_pen` comes with the phase 2 team goals model.
     - Component functions take `(season, as_of_gw, mode)`, since
       `load_as_of` needs a mode.
     - `elo_ratings.csv` holds finished matches only.
  6. **Tuning:** a grid search over K, home advantage and the goal-margin
     factor, on 2025/26 only, minimising the mean absolute gap to upstream Elo
     at the kickoffs where it moves (GW2-26, GW33-34). Spearman by gameweek and
     match-result log-loss are reported alongside. Nothing is tuned on 2026/27,
     the holdout. Trade-off: this tunes towards tracking ClubElo rather than
     predicting results; the log-loss shows if the two disagree.
  7. **No new dependency.** The three-parameter Poisson is fitted in numpy,
     with a known-answer test. scipy waits for Dixon-Coles.
  8. **`.claude/agents/expected-points-modeller.md` is aligned with the brief**
     (Josh's permission): decay and `xp_horizon_weighted` removed, the Elo row
     added, team goals depends on Elo, and components return DataFrames.
- **Decided by the main session while writing the task (say if you
  disagree):** seeds are point-in-time. A club entering the run is seeded from
  its first non-null Premier League kickoff Elo in the read. A club that needs
  a rating with no seed in the read makes the component raise a clear error,
  rather than guess. That happens at 2025/26 as-of 0 (GW1 is still schedule
  only) and 2026/27 as-of 0-1 (Coventry's first value is at GW2; Hull's and
  Ipswich's are at GW1). Rejected: a fallback seed such as the relegated
  clubs' average, which adds a rule for two early-season reads that carry no
  pass marks.
- **Added to `docs/known_gaps.md`:** clubs with no seed early in a season
  (including any club promoted for 2027/28), and the Premier League-only Elo.
- **Updated:** brief data rule 12, sections 5, 6.2 and 7; `docs/data_contract.md`
  (Upstream Elo source note, `elo_ratings.csv` and `fixture_difficulty.csv`
  notes, component hand-offs); `CONTEXT.md` (Elo rating, Upstream Elo);
  `docs/plans/phase-1.md` (task 3).

### 2026-11-13: model - Elo component v1
Revised in the task 3 fix round (same day) to the review decisions logged
after this note: each season is re-seeded from upstream, the tuning target
drops GW34, the tuner reports an end-of-season comparison, and Code Review's
test gaps are closed.
- **Built on upstream `b6854dcdd88dca8b613687b0d83df5063d9b8428`** (2026-11-12
  04:02 UTC), as-of 10 of 2026/27. Two components and a tuner:
  - `models/elo.py`: `elo_ratings(season, as_of_gw, mode)` gives our Elo rating
    before and after every finished Premier League match, from 2025/26 GW1 on
    (the `elo_ratings.csv` rows).
  - `models/team_goals.py`: `elo_goals(season, as_of_gw, mode)` is the Elo goals
    model, giving fixture difficulty for each team's fixtures in the next
    `max_horizon` gameweeks (the `fixture_difficulty.csv` rows).
  - `models/elo_tune.py`: `python -m fpl.models.elo_tune` reruns the tuning. It
    only logs (about 20 s) and writes nothing.
  - Pure cores, for tests and the tuner: `run_elo(history, settings,
    prem_tag)` and `goals_from_history(history, elo_settings, goals_settings,
    prem_tag)`. `load_history(season, as_of_gw, mode)` does the reads: each
    earlier season of the run at its last gameweek in backtest mode, then
    `season` at `as_of_gw` in `mode`.
- **Method (Elo):**
  - E = 1 / (1 + 10^(-(r_home + home_advantage - r_away) / scale)), and the
    home club gains k × max(1, |goal difference|)^margin_power × (result - E).
    The away club loses the same amount, so every match is zero-sum.
  - **Margin factor:** a power of the goal difference, counted from 1, so
    draws and one-goal results weigh 1. Why: it has one parameter, and it nests
    plain Elo (power 0), so the tuning could have rejected a margin factor
    altogether; power 0.5 is the square-root form often used for football.
    Rejected: eloratings.net's fixed steps (nothing to tune) and
    FiveThirtyEight's autocorrelation term (a second parameter, for a bias
    there is no evidence of here).
  - Results are every finished Premier League fixture with `gw` <= as-of, in
    kickoff order, whatever `stats_complete` says. Cup and European rows never
    enter. Kickoff order equals gameweek order in both seasons (0 inversions),
    so a run at as-of g is an exact prefix of a later run.
  - **Clubs are keyed by `team_code`.** Seeds come only from Premier League
    kickoff upstream Elo among the finished matches in the read. Each season's
    seeds are set before its first match, so a re-seeded club's current rating
    is right even before it has played (`prepare` and `play`):
    - in 2025/26, the first season of the run, each club's first non-null
      value (the 20 GW1 values);
    - in a later season, a club with a value at its last Premier League match
      of the previous season is re-seeded from it. That value comes from the
      previous season's read, never the new season's rows. For 2026/27 it is
      ClubElo's end-of-season 2025/26 rating, Arsenal (2063.76) included. A
      club whose last-match value is null carries its own rating, even if an
      earlier value exists; that is every club from 2027/28 if ClubElo stays
      down;
    - a club new to the run from its first non-null value in the new season:
      Coventry 1661.48 (its GW2 value, also used for its GW1 match), Hull
      1532.88 and Ipswich 1640.00.
    - A club with no seed raises `MissingSeedError`, naming the club.
    - At 2026/27 GW1 the re-seed moves the 17 continuing clubs by +16.8 points
      on average against our own 2025/26 end ratings, from -20.4 (Man City) to
      +47.8 (Aston Villa).
- **Method (goals model):**
  - log λ = intercept + gap × (own `elo_before` - opponent's) + home × is_home,
    fitted by Newton's method in numpy.
  - The pool is one row per team per finished Premier League match of the last
    `pool_seasons` (2) seasons of the run, up to and including the as-of
    gameweek.
  - Every fixture with `gw` in (as-of, as-of + `max_horizon`] gets two rows,
    each built from both clubs' current ratings. `lambda_against` is the
    opponent's `lambda_for`, and `p_cs` = e^(-`lambda_against`).
  - **Minimum sample:** `min_matches` 30. Below it the model raises
    `InsufficientSampleError` and fits nothing. Only 2025/26 as-of 1-2 are
    affected; as-of 0 already raises for seeds. Evidence from 2025/26 fits:
    | As-of | Matches | Home coef | Gap coef per 100 pts | Home v away λ, equal clubs |
    | --- | --- | --- | --- | --- |
    | 1 | 10 | 0.72 | 0.29 | 1.55 v 0.76 |
    | 2 | 20 | 0.41 | 0.32 | 1.43 v 0.95 |
    | 3 | 30 | 0.26 | 0.21 | 1.42 v 1.10 |
    | 10 | 100 | 0.33 | 0.17 | 1.51 v 1.09 |
    | 38 | 380 | 0.22 | 0.14 | 1.49 v 1.19 |
    - From 30 matches on, the coefficients sit in the full-season range.
    - Rejected fallbacks: full-season coefficients, which would leak 2025/26
      outcomes into its own early reads, and fixed league averages in config,
      which would be invented numbers.
- **Tuning (2025/26 only; nothing tuned on or compared with 2026/27):**
  - **Grid:** K {10-30 in steps of 2, 35, 40} × home advantage {0-100 in steps
    of 10} × margin power {0, 0.125, 0.25, 0.375, 0.5, 0.75, 1}, 1,001 points.
    The objective is the mean absolute gap to upstream kickoff Elo at the
    target gameweeks, GW2-26 and GW33, where upstream is a before-match rating.
    (The first version also used GW34; dropping it changed nothing.)
  - **Chosen:** K 18, home advantage 30, margin power 0.375.
    - Mean gap 9.85 points; mean signed gap -7.29, so ours run lower.
    - Match-result log-loss 0.6594 (expected score against the result, a draw
      counting 1/2). Tuning stays on the gap (Josh).
  - **Spearman** is computed per gameweek, at each club's first kickoff.
    - Target gameweeks GW2-26: 0.982-1.000. GW33: 0.988. Lowest from GW6: 0.982.
    - Not targets: GW27-32 0.956-0.979; GW34-38 0.908-0.977 (GW34, against
      the end-of-season rating, is 0.908). GW1 is the seed (1.0).
  - **End of season (reported only, never tuned on):** each club's rating
    after its last 2025/26 match against upstream's value there (ClubElo's
    end-of-season rating): Spearman 0.982, mean signed gap -18.0, mean gap
    20.0, for 20 clubs.
  - **The settings are in-sample for the development window,** which the brief
    allows: these full-season 2025/26 values are used in every 2025/26 read.
- **Inputs:**
  - `fact_fixture`: `match_id`, `season`, `gw`, `kickoff_utc`, `tournament`,
    `home_team_id`, `away_team_id`, `home_upstream_elo`, `away_upstream_elo`,
    `finished`, `home_goals`, `away_goals`.
  - `dim_team`: `team_id`, `team_code`, `name`.
  - `pipeline.yaml`: `seasons` and `premier_league_tag`, read only.
- **Outputs:**
  - Elo: `team_id`, `match_id`, `season`, `gw`, `kickoff_utc`, `elo_before`,
    `elo_after`, home row first. 960 rows at 2026/27 as-of 10.
  - Goals model: `team_id`, `match_id`, `gw`, `opponent_id`, `home`,
    `lambda_for`, `lambda_against`, `p_cs`. 100 rows at 2026/27 as-of 10
    (GW11-15).
  - Both modes give identical output.
- **Config keys added (new `config/model.yaml`):** `max_horizon`; `elo.
  {start_season, scale, k, home_advantage, margin_power}`; `elo.tuning.{season,
  target_gameweeks, check_from_gw, check_min_spearman, grid}`;
  `goals_model.{pool_seasons, min_matches, newton_tol, newton_max_iter}`.
- **Assumptions and known weaknesses:**
  - **Reads that raise (the validator should skip them):** `MissingSeedError`
    at 2025/26 as-of 0 and 2026/27 as-of 0-1; `InsufficientSampleError` at
    2025/26 as-of 1-2.
  - **GW34's upstream Elo is not a kickoff rating** (found in the first
    version; settled in the review decisions). Every value from GW34 on equals
    the club's final 2025/26 value, and it agrees best with our ratings after
    GW38. So GW34 left the tuning target, with no change to the settings.
  - **The gap objective barely identifies the home advantage:** 0-50 points are
    all within 0.05 of the minimum.
  - **The two tuning measures disagree on K.** Log-loss prefers K 35, home
    advantage 50 and no margin factor (0.6538), which has a mean gap of 18.0.
    Tracking ClubElo and predicting results pull K in different directions.
  - The fixture window is chosen by gameweek, not `finished`, and seeds come
    from finished matches in the read. The contract now says both.
  - A club relegated and later promoted again, with no value at a last match
    of the previous season, comes back with its old rating instead of being
    re-seeded.
  - The Elo home advantage (30 rating points) and the goals model's home term
    (0.23 in log goals at 2026/27 as-of 10) are separate parameters.
  - **Guards:** the kickoff sort is tested against rows out of kickoff order,
    since upstream lists some GW33 doubles later match first. A Premier League
    club missing from `dim_team` and a finished fixture with no score raise
    `EloError`. `goals_model.pool_seasons` below 1 is rejected. The tuner
    refuses any tuning season after the run's first season, and the newest
    configured season, judged by position in `pipeline.yaml`'s season list.
  - **Goals model at 2026/27 as-of 10 after the re-seed:** intercept 0.1760,
    gap 0.1331 per 100 points (0.1352 before), home 0.2283, 480 matches.
- **Follow-ups after the second review (same day):**
  - A club that didn't play the previous season is now seeded from its first
    upstream value in the new season, whether it is new to the run or coming
    back after a relegation, as brief data rule 12 says. One coming back with
    no such value carries its old rating; one new to the run raises
    `MissingSeedError`. This has no effect before 2027/28.
  - `play()` raises `EloError` if any result's season has no seeds, instead of
    skipping it.
  - A three-season test covers the tuner's "after the run's first season"
    clause on its own.
  - Real data is unchanged: 960 rating rows and 100 fixture rows at 2026/27
    as-of 10, Arsenal's 2026/27 GW1 `elo_before` 2063.76, and the tuner still
    picks K 18, home advantage 30 and margin power 0.375.

### 2026-11-13: main - task 3 review decisions (Josh)
The modeller's first report and Code Review's first pass on task 3. The main
session rechecked the key evidence on upstream `b6854dc`. Josh decided all
five items.
- **Evidence (main session, confirming the modeller's finding):**
  - **Upstream's GW34-38 Elo is ClubElo's end-of-season rating, not a
    kickoff rating.** All 96 kickoff values from GW34 to GW38 equal each
    club's final 2025/26 value. The six clubs that "move" at GW35 are the
    six with no GW34 fixture. Each club's jump from its GW33 value to that
    final value correlates 0.794 with its points in GW34-38, and only 0.17
    with its points in GW33. So the GW34 pass-mark comparison set our
    before-match ratings against a value that already included later
    results (Spearman 0.908 there).
  - **GW33 is a genuine kickoff value.** The jump from GW26 to GW33
    correlates 0.509 with points in GW26-32, and 0.061 with points in
    GW33-38.
  - **Correction to 2026-11-12:** the main session said the 2026/27 GW1-2
    values were stale 2025/26 ratings missing GW35-38. That was wrong. They
    are the same end-of-season rating, taken after GW38.
  - **Our ratings against ClubElo's end-of-season rating:** after GW38 ours
    sit 18.0 points below it on average (mean absolute 20.0, from 47.8 below
    for Aston Villa to 20.4 above for Man City), with Spearman 0.982. The
    in-season mean gap is 7.7 below. The difference builds up from cup and
    European results, which ClubElo counts and ours don't. Promoted clubs
    are seeded on ClubElo's scale, so with one continuous run they would
    start about 18 points too strong relative to the rest.
  - **Fixture rows aren't in kickoff order** (Code Review, confirmed): 126
    out-of-order steps in 2025/26 and 63 in 2026/27. In the 2025/26 GW33
    double gameweek, three clubs have their 22 April match listed before
    their 18 or 19 April one. The Elo code sorts by kickoff, but no test
    covered it.
- **Decisions:**
  1. **Tune and judge only where upstream Elo is a before-match rating:**
     GW2-26 and GW33 for tuning, and the pass mark at GW6-26 and GW33. The
     tuned settings don't change without GW34 (gap 9.85). The modeller's
     tuner also reports our ratings after GW38 against ClubElo's
     end-of-season rating, without tuning on it: no K can make up for
     matches the model doesn't count.
     - Rejected (Josh asked): filling GW27-38 with ratings from our own
       model fitted on GW1-26 and tuning on the full season. The filled
       weeks would be the model's own output, so tuning on them adds nothing
       and only flatters the fit.
  2. **Re-seed 2026/27 from ClubElo's end-of-season ratings** (reverses
     2026-11-12 decision 2, back to the brief's original rule). Each club
     with an upstream value at its last Premier League match of the previous
     season is re-seeded from it, Arsenal included; promoted clubs from
     their first 2026/27 value; a club with no such value carries its own
     rating. Why: all 20 clubs start on one scale and keep ClubElo's
     cup and European information. Trade-off: 2026/27 restarts from ClubElo
     instead of continuing our tuned run (same method and settings).
  3. **Keep tuning on the gap to ClubElo** (Josh), though match-result
     log-loss alone would pick K 35, home advantage 50 and no margin factor
     (0.6538 against 0.6594, under 1% better, at a gap of 18.3).
  4. **The goals model's 30-match minimum stays.** Below it the model raises
     `InsufficientSampleError`; that happens only at 2025/26 as-of 1-2.
     Equal-club home multiples by pool size: ×2.05 at 10 matches, ×1.51 at
     20, ×1.29 at 30, ×1.25 over the full season.
  5. **Contract wording:** seeds come from finished matches in the read, and
     horizon fixtures are chosen by gameweek, not by `finished`. Both match
     the code and give identical results on real data.
- **Outside Elo source: beyondELO** (Josh suggested it; the main session
  checked its site, terms, API and data on 2026-11-13).
  - Its API gives each club's rating before and after every match, including
    all of 2025/26 and 2026/27 to date. The API data is CC BY 4.0 with the
    credit "beyondELO (https://beyondelo.com)", and a free key allows 100
    requests a day.
  - It doesn't rate the Championship: West Ham, Wolves and Burnley's last
    rated match is 24 May 2026, and Leicester and Southampton's 25 May 2025.
    So a promoted club's rating is from its last Premier League spell
    (Coventry's was 2000/01). Its scale also differs: it adds about 240
    points for English clubs, learns a home advantage per club and weights
    results by uncertainty.
  - It names no operator. Its terms page (personal, non-commercial, no
    scraping) and API page (CC BY 4.0) differ; use through the official API
    with credit is covered by both.
  - **Decision (Josh):** ClubElo stays the seed and tuning source. beyondELO
    becomes the source for Josh's outside-source check after task 5 (ranking
    agreement and predictive log-loss, which don't depend on scale),
    covering 2025/26 GW27-38 and 2026/27 from GW3. A small data-engineer task
    pulls it through the API; Josh creates the key.
- **Code Review's first pass:** approve with non-blocking findings. All 12
  listed protections fail a test when broken; its independent provenance
  check passed at 2025/26 as-of 5 and 20 and 2026/27 as-of 3 and 10. Seven
  extra mutants survived, all test gaps, sent to the modeller with these
  decisions: the kickoff sort, the tuner's own loads, two unexercised input
  guards, the `min_matches` boundary, `pool_seasons` below 1, and three
  missing docstrings.
- **Updated:** brief data rule 12 and sections 5 and 7; `docs/data_contract.md`
  (Upstream Elo source note, `elo_ratings.csv` note, component hand-offs and
  the seed notes); `CONTEXT.md` (Elo rating, Upstream Elo);
  `docs/plans/phase-1.md` (task 3, the outside-source check, steps for Josh);
  `docs/known_gaps.md`; `CLAUDE.md` (the tuner command).

### 2026-11-13: main - task 3 second review
Code Review's second pass approved task 3, committed as `a23a48e`. All
first-round findings are fixed, 41 of 42 mutants die, and its independent
provenance check matches to 0.0 at 2025/26 as-of 5 and 20 and 2026/27 as-of
3 and 10. The main session confirmed on real data that all 17 continuing
clubs start 2026/27 at their last 2025/26 upstream value, and that the tuner
reproduces K 18, home advantage 30 and margin power 0.375. Three
low-severity findings go to the modeller as follow-ups:
1. **Holdout guard:** the "no season after the run's first" clause has no
   test of its own (the newest-season clause catches every two-season case).
   It matters once a third season is configured.
2. **Silent skip:** `play()` ignores results whose season label has no seed
   key, giving NaN ratings without an error. Not reachable through
   `load_history`, but it must raise.
3. **Clubs promoted back (brief wins):** brief data rule 12 seeds a promoted
   club from its first upstream Elo in the new season. The code and the
   contract did so only for a club new to the run, so a club coming back
   after a relegation carried its old rating even when upstream had a new
   value. Per `CLAUDE.md` the brief wins: the contract now follows it, and the
   code will. No effect before 2027/28.
- **Updated:** `docs/data_contract.md` (Elo seed notes) and
  `docs/known_gaps.md`.

### 2026-11-13: main - model-validator agent file fixed
- Edited `.claude/agents/model-validator.md` with Josh's permission:
  - **Frontmatter:** added the missing closing `---`, and quoted
    `description`, whose "model code: report" is invalid in plain YAML.
    Either fault kept the agent from loading; it was missing from the
    session's agent list. All five project agent headers now parse.
  - **Independence:** "Read first" told the validator to read the modeller's
    hand-off notes in `docs/decisions.md`. Brief section 14, working rule 3,
    and the `CLAUDE.md` hard rule keep the modeller's reasoning and
    calibration numbers from the validator, so it now reads only the `main -`
    and `data -` entries and takes interfaces from the contract.

### 2026-11-13: main - task 4 Elo check design settled before delegation (Josh)
Brief section 7 leaves open how the Elo component check is scored. The main
session checked the data on upstream `ac8be9ca` (2026-11-13 15:35 UTC) before
writing task 4. Josh took all eight recommendations.
- **Evidence:**
  - **2026/27 to date is GW1-10.** All 100 fixtures are finished, and GW11
    starts on 2026-11-21.
  - **Team-fixtures from GW6:** 660 in 2025/26 (GW6-38) and 100 in 2026/27
    (GW6-10), so 760 pooled. GW1-5 holds 100 in each season.
  - **The upstream changes since `b6854dc`** only reorder cup rows in old
    gameweek folders. No result changed.
  - **An independence leak in the reading list:** the validator's agent file
    sends it to every `main -` entry, and two of them ("task 3 review
    decisions" and "task 3 second review", both 2026-11-13) quote the
    modeller's own accuracy numbers.
- **Decisions:**
  1. **Score the next gameweek only.** For each target gameweek g, score GW
     g's fixtures from `elo_goals(season, g−1, "backtest")`, so each
     team-fixture counts once. Trade-off: says nothing about 2-5 gameweeks
     out. Rejected: all five horizon gameweeks (each fixture counted up to 5
     times).
  2. **Pass marks on GW6 onwards of both seasons, pooled** (760
     team-fixtures), with each season reported on its own. Trade-off:
     2025/26 is 87% of the set. Rejected: a 2026/27-only verdict, which
     passes trivially because 100 team-fixtures can't fill a bin to 100.
  3. **Ratings compared at every team-kickoff,** pairing our `elo_before`
     with upstream Elo at the same kickoff (2025/26; GW33's double gives 26
     pairs). Trade-off: a club in a double counts twice that week. Rejected:
     first kickoff per club only, which drops 6 genuine GW33 kickoffs.
  4. **The baseline's league averages come from the Elo goals model's own
     pool** at as-of g−1. Rejected: whole-season averages, which see later
     results.
  5. **Perturbation test** at 2025/26 as-of 5, 20 and 33 and 2026/27 as-of 3
     and 9: corrupt every result after the as-of gameweek (scores, finished
     flags, upstream Elo, xG), keep the schedule (backtests already see the
     final schedule, `docs/known_gaps.md`). Any change in either function's
     output is a fail. A planted-leak test proves the check catches one.
  6. **The validator's reading list:** task 4's message names the
     `decisions.md` entries to read and leaves out the two above; their
     decisions are already in the brief and the contract. **From now on,
     `main -` entries don't quote the modeller's accuracy numbers.** They
     cite its `model -` entry instead.
  7. **The settled points go into brief section 7 before delegating,** and
     the holdout look (2026/27 GW3-10, upstream `ac8be9ca`) is logged here
     when the report comes back.
  8. **Scope:** only the Elo check, written to `backtest/` and its tests,
     TDD, no commits. No `ep_next` baselines and no `latest.json` yet. Task 5
     can run alongside.
- **Code under test:** `190f63f`. The model code is unchanged since
  `42c6809`.
- **Updated:** brief section 7 ("How the check is run").

### 2026-11-13: main - model_version set (Josh)
Task 5 needs `meta.model_version`. The contract's example value was
`0.1.0-elo`, but nothing set it.
- **Decision:** `model_version: "0.1.0-elo"` goes in `config/model.yaml`,
  added by the main session with Josh's permission. `export.py` reads it from
  there, and the modeller bumps it with any change that alters the outputs.
  `meta.csv` carries it for every CSV the run publishes, which is how brief
  section 6's "stamp every output" now reads. Trade-off: a CSV copied out on
  its own loses the version. Rejected: the git commit, which already
  identifies the code but means nothing at a glance in the workbook.
- **No model setting changed.** The file's hash changes, so the task 4
  validator records the commit it ran on.
- **Updated:** `config/model.yaml`, brief section 6, `docs/data_contract.md`
  (the `meta.csv` note).

### 2026-11-14: main - task 4 Elo check: FAIL, and the holdout look
- **Holdout look (brief section 7):** the model-validator's Elo check on
  2026-11-13 read 2026/27 GW1-10 at upstream `ac8be9ca`. Goals and clean
  sheets were scored for GW3-10, and ratings read at as-of 2-10 for the
  stability check. 2026/27 is 100 of the 760 pass-mark team-fixtures.
- **Verdict: FAIL** on goals calibration. In the 1.75+ bin, 103
  team-fixtures had 1.999 goals predicted and 1.718 actual, against a
  tolerance of 0.1. Every other check passes: ratings (lowest Spearman
  0.982), clean sheets, log-loss (1.4461 against the baseline's 1.4688) and
  every leakage check. Report: `backtest/reports/2026-11-13.md`.
- **Rechecked:** the main session's own script, sharing no code with the
  harness, gives the same bin (103, 1.9990, 1.7184) and log-loss. Code
  Review's independent spot check matches too.
- **The gate itself:** simulating a perfectly calibrated model on this run's
  own predictions (20,000 draws), it fails the goals check 57% of the time
  and the clean-sheet check 22%. Put to Josh with the verdict; decision
  pending.
- **Code Review:** approved the harness with non-blocking findings. 31 of 39
  mutants die. The 8 survivors are test gaps in the verdict's leak controls,
  the baseline's call site and the config, and go back to the validator as
  follow-ups.
