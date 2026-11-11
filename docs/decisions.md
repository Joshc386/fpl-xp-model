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
