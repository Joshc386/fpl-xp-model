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

### 2026-11-13: data - task 5 thin-slice outputs (export.py)
`python -m fpl.export --out-dir DIR [--run-utc ISO]` writes `players.csv`,
`fixture_difficulty.csv`, `elo_ratings.csv` and `meta.csv`. About 5 s on the latest
snapshot (upstream `ac8be9ca`). Every check runs before anything is written; a failed
check raises `ValidationError` (non-zero exit) and leaves `DIR` untouched. Files are
written under temporary names and renamed together.

- **Code:** `export.py` (reads, orchestration, writes), `player_metrics.py` (pure
  players.csv), `output_checks.py` and `output_checks_model.py` (step 8 checks),
  `output_schema.py` (the four schemas). `features.py` gains `live_deadlines`, which
  `live_gameweeks` now uses. `schema.check_table_schema` delegates to a new
  `check_schema(df, name, spec)`. `config/pipeline.yaml` gains `current_season` and
  `output_validation` (Elo rating range, `lambda_max`, float tolerance).
- **One read per season:** `load_history` once, then `run_elo` and `goals_from_history`
  (the pure cores). `players.csv` uses the same live read of the current season. A real-data
  test counts the loader calls (2025/26 backtest at 38 and 2026/27 live at as-of: two) and
  asserts the outputs equal `elo_ratings` and `elo_goals` exactly.
- **Metric rules (CONTEXT.md, plus the points it leaves open):**
  - `minutes`, `starts`, `total_points`: sums of `fact_player_gw` up to the as-of gameweek.
  - `ppg` appearances = complete Premier League matches with `minutes` > 0 in
    `fact_player_match`, not gameweeks. Evidence: 2025/26 GW38, which has doubles, gives 1
    mismatch of 841 against FPL's `points_per_game` by match and 112 by gameweek.
    Fallback: `max(match appearances, gameweeks with minutes > 0)`. Reason: 7 player-match
    rows are dropped as `player_not_in_snapshot` (Mfuni, J.Angulo, Tutierov at GW10), which
    left 19 points over 0 appearances. A double gameweek can only raise the match count.
  - `xg90`, `xa90`: Σ xG (xA) ÷ Σ `minutes_played` over the same complete Premier League
    matches, so numerator and denominator cover the same matches. `dc90`: FPL's
    `defensive_contribution` ÷ FPL `minutes`, both from `fact_player_gw`. All are 0 at 0
    minutes. Players whose rows were dropped (above) have xG 0.
  - `pen_taker`: `pen_order` = 1. `price_m`: `dim_player.price_tenths` / 10, which in live
    mode is the master price.
  - `net_transfers_gw`: row g's `transfers_in` - `transfers_out` (rule 8: row g is the run-up
    to g+1). `price_change_gw`: `dim_player.price_tenths` less row g-1's `price_tenths`
    (the price at GW g's deadline). Null for a player missing the row it needs (a club's
    gameweek not finished, or a player new that gameweek).
  - `team` is `dim_team.name`.
- **Left out:** `price_change_start`. No processed table holds the start-of-season price.
- **Checks:** schema and dtypes against the contract; unique keys; no NaN or infinity outside
  the null-by-design columns; `lambda_for`/`lambda_against` in (0, `lambda_max`);
  `p_cs` = exp(-`lambda_against`) and in [0, 1]; fixture_difficulty gameweeks inside
  next..next+`max_horizon`-1, each with a deadline after `run_utc`; its rows equal
  `fact_fixture`'s Premier League fixtures in that range (one per side, so a double has two
  rows and a blank none) with matching gw, opponent and home, and mirrored lambdas; every
  team id in that season's `dim_team`; Elo rows two per match, zero-sum, in range, covering
  exactly each season's finished Premier League matches, none after the as-of gameweek, none
  kicking off after `run_utc`; players set equals `dim_player`, price, position, team,
  percentage and non-negative checks; meta values equal the context (`current_gw` = next - 1,
  deadline from the master file and after `run_utc`, commit hash, `max_horizon`).
- **`meta.status`:** `ok` is the only value, because a run that fails a check publishes
  nothing (brief section 11). Proposal, not in the contract.
- **Effect downstream:** the workflows (task 6) call the one command with `--out-dir`. The
  `kickoff_utc <= run_utc` check means a run pinned in the past is valid only while the data
  on disk is not newer than the pin; a pin just before the next deadline is fine.
- **Real-data reconciliation (GW10, 672 players):** `total_points`, `minutes` and `starts`
  equal FPL's `playerstats` for all; `net_transfers_gw` equals `transfers_in_event` -
  `transfers_out_event` for all; `price_change_gw` equals `cost_change_event` / 10 for all
  670 non-null; `price_m` equals `now_cost`; `ppg` is within FPL's 0.1 rounding;
  `dc90` x minutes / 90 equals FPL's `defensive_contribution`.

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

### 2026-11-14: main - task 5 contract changes (Josh)
From the data-engineer's task 5 report. Josh approved three of its
proposals, and the contract changes go in before the fix round's code.
- **Four FPL fields in `dim_player`:** `price_change_start_tenths`,
  `price_change_gw_tenths`, `transfers_in_gw` and `transfers_out_gw`, from
  upstream's `cost_change_start`, `cost_change_event`, `transfers_in_event`
  and `transfers_out_event`, overlaid in live mode.
  - Why: `players.csv` can publish `price_change_start`, and
    `net_transfers_gw` and `price_change_gw` are never null. Until now they
    came from `fact_player_gw`, whose rows are held back until a club's
    fixtures finish, so mid-gameweek runs would have published blanks. The
    export's computed values already match these fields wherever both exist
    (GW10).
  - Trade-off: four more columns in a processed table. Rejected: allowing
    nulls in the two columns.
- **`team` and `opponent` in `fixture_difficulty.csv`:** the clubs' short
  names, so the workbook needs no join. Trade-off: names repeat across rows.
  Rejected: a separate `teams.csv`.
- **`meta.status` is always `ok`:** a failed run publishes nothing (brief
  section 11), and the Dashboard's warning comes from data age.
- **Also in the contract:** `live_deadlines(season)` in the loader section
  (Code Review).
- **Code Review of task 5: changes required.** `ppg` takes its points from
  released gameweek rows and its appearances from complete matches, so it
  is wrong in a half-played double gameweek and when a match is finished
  but not yet complete. The main session reproduced both cases. No 2026/27
  output is affected yet, because there have been no doubles. The other
  findings are a real-data test that breaks once GW11 prices land, seven
  untested checks, no goalkeeper `dc90` guard, renames that aren't atomic on
  Windows, and small fixes. All go to the data-engineer's fix round.
- **Updated:** `docs/data_contract.md` (`dim_player` and its source note,
  live mode, live gameweeks, and the `fixture_difficulty.csv`, `players.csv`
  and `meta.csv` notes) and brief section 5.

### 2026-11-14: data - task 5 fix round
Applied the three approved contract changes (commit `37b6824`) and the Code Review findings.

- **`dim_player` carries four more columns** (`price_change_start_tenths`,
  `price_change_gw_tenths`, `transfers_in_gw`, `transfers_out_gw`) from upstream
  `cost_change_start`, `cost_change_event`, `transfers_in_event` and `transfers_out_event`.
  Schema, cleaning (`to_int`, so a null or fractional value fails the build), the raw-column
  requirement and the live overlay (all four are in `OVERLAID`; a null in a player's latest
  master row raises `ValidationError`) are updated. Loader tests check the snapshot values in
  backtest mode and the poisoned master values in live mode.
- **`players.csv`:** `price_change_start` added. `net_transfers_gw`, `price_change_gw` and
  `price_change_start` come from `dim_player` and are never null; the null checks are strict
  again and the `fact_player_gw` route is gone.
- **`fixture_difficulty.csv`:** `team` and `opponent` (`dim_team.short_name`) added by checked
  joins; a check compares them with the ids.
- **`ppg` (blocking finding):** appearances are now counted only in gameweeks that have a
  released `fact_player_gw` row, the same window as the points. Per gameweek the larger of
  complete-match appearances and 1 if FPL minutes > 0, summed. This gives 18 / 4 for the
  shipped fixture (a finished match that is not complete), 16 / 3 for a half-played double
  gameweek, and counts both matches of a complete double. Mutants "gameweek appearances
  only" and "match appearances only" now fail a test each.
- **Checks added or tightened:** `dc90` is 0 for every goalkeeper; every message is asserted
  exactly. Tests now kill these mutants: finished filter dropped from the Elo cover check,
  `>` to `>=` on the meta deadline, the `current_gw` = `next_gw` - 1 check dropped, the
  exact-deadline boundary, the lambda bounds made inclusive, the lambda upper bound dropped,
  and the previously unrun players checks.
- **`publish`:** the renames are atomic per file, not as a set. A failed rename now removes
  the temporary files and raises; the docstring says what really happens. A test forces the
  third rename to fail.
- **Small:** `run_export` reads the deadlines once and derives the next and as-of gameweeks
  with `clock.next_gameweek` and `clock.as_of_gameweek` (what `live_gameweeks` does).
  `output_problems`' docstring now says it raises only on malformed input.
  The real-data tests compare current-state columns with the master file, and derive row
  counts from the fixtures, so the next pull does not break them.
- **`players.csv` `team` is `dim_team.short_name`** (approved 2026-11-14), like
  `fixture_difficulty.csv`. The check compares each player's `team` with the short name of his
  own `dim_player.team_id`, not just any club.
- **Another data copy:** `fpl.features.use_data_copy(data_dir)` is a context manager (a
  `ContextVar`, so exception-safe and per thread or task). `data_dir` is the folder holding the
  season folders. Inside it `load_as_of`, `live_deadlines` and `live_gameweeks` read from it
  when called with no `root` or `cfg`, including inside `elo_ratings` and `elo_goals`. An
  explicit `root` or `cfg` wins. The loader functions' `root` default changed from `ROOT` to
  `None` (same behaviour). `features._config` is untouched and still patchable, which a test
  confirms. Tests: `tests/test_data_copy.py` (recorders: inside, outside, after an exception,
  nested, explicit root or cfg, patched `_config`) and `tests/test_data_copy_real.py` (a copy
  with one GW10 score changed to 9-0; `elo_ratings` inside the block shows the copy, outside
  it equals the checkout).
- **Not changed:** the `xg90`/`xa90` denominator stays `minutes_played` over the same
  complete matches (undecided when this round started; Josh settled it on 2026-11-14, see
  "main - task 4 verdict decisions").

### 2026-11-14: main - task 4 verdict decisions (Josh)
Josh took the six remaining recommendations from the task 4 verdict and the
task 5 review. The numbers are the ones he answered.
1. **The FAIL stands.** The Elo goals model (`src/fpl/models/team_goals.py`)
   goes back to the modeller with the findings. This is fail one of two. The
   ratings passed and aren't changed.
2. **The calibration tolerance accounts for sample size, from the re-check
   on.** A goals or clean-sheet bin fails only if it misses by more than
   both the written tolerance (0.1 goals, 5 percentage points) and two
   standard errors of the bin mean under the model's own rates.
   - Why: a perfectly calibrated model failed the original goals rule 57% of
     the time and the clean-sheet rule 22%, so a second fail, which triggers
     a rebuild, would often be chance. The first check fails under both
     rules (miss 0.281, limit 0.279), so the change doesn't rescue it.
   - Trade-off: a real bias of about 0.25 goals in a 100-fixture bin can
     pass. Rejected: a higher minimum count, which would excuse the failing
     bin after the fact.
   - The xP gate's calibration rule (±0.3 in bins of at least 200) should be
     checked the same way before phase 3. It isn't changed now.
3. **The modeller works on 2025/26 only.** Its task carries the 2025/26
   findings, not the 2026/27 breakdowns, and it doesn't read
   `backtest/reports/`. The public signatures and output columns stay the
   same, and the fix bumps `model_version`.
4. **A supported way to point the loader at another data copy,** so the
   harness stops patching `fpl.features._config`. It is added to task 5's
   fix round, and the validator switches to it in the re-check.
8. **xG90 and xA90 divide by `minutes_played` in the same complete matches**
   (`CONTEXT.md`). Trade-off: 2026/27's `minutes_played` reads about 1
   minute high for substituted starters, so the rates run about 1% low.
   Rejected: FPL minutes, which count matches whose xG isn't loaded yet.
9. **`team` in `players.csv` is the short name,** as in
   `fixture_difficulty.csv`, so one column name means one thing. Trade-off:
   the Player Database shows "ARS", not "Arsenal".
- **Updated:** brief section 7 (the goals and clean-sheet pass marks, and
  why), `docs/data_contract.md` (the `players.csv` note and the loader
  section) and `CONTEXT.md` (xG90 / xA90).

### 2026-11-14: main - Elo goals fix: log-linear form plus priors (Josh)
The modeller's fix round proposed two changes to the Elo goals model:
priors on the gap and home coefficients, and a new form with a fixed
expected total per match. Its evidence and numbers are in its
`model - Elo goals fix round` entry, and the main session reproduced them
on 2025/26.
- **Decision (Josh): keep the log-linear form and add the priors.**
  - Why: the priors address the main cause the modeller found. One season
    can't separate flat match totals from the log-linear form's modest rise
    with the rating gap, and betting markets price higher totals for bigger
    mismatches. It is also the smaller change, and it stays in the same
    family as the phase 2 Dixon-Coles model it benchmarks.
  - Trade-off: on 2025/26 it scores slightly worse than the fixed-total
    form, within noise.
  - Rejected: the fixed-total form.
- **Caveat for the re-check:** most of the pooled pass-mark set (GW6 on,
  both seasons) is 2025/26, the development window the fix was tuned on.
  Only 2026/27's team-fixtures are out of sample, so the main session reads
  them on their own as well.
- **Also:** `docs/data_contract.md` (the `meta.csv` version example, and
  `use_data_copy` not reaching worker threads) and `docs/known_gaps.md`
  (transfer columns just after a deadline, `ppg` in a double gameweek with
  one match still loading, players missing from a snapshot).

### 2026-11-14: data - task 5 review follow-ups
Code Review's second pass on `eb5a9bd`; all non-blocking.
- **No copied model values in tests:** `test_export_build.py` builds its model settings from
  `config/model.yaml`, overriding only `model_version` (a test value) and
  `goals_model.min_matches` (the synthetic season has 4 matches). `test_export_real.py` and
  `export_outputs.py` read `model_version` from the config. The export tests pass with HEAD's
  model files and with the modeller's uncommitted ones (`0.1.1-elo`, the prior settings).
- **`ppg` docstring:** now says the "1 if FPL minutes > 0" fallback covers a single finished
  match that is not complete or a dropped row, and undercounts a double gameweek with both
  matches finished but one complete (4.5 against 3.6) until the second match's stats load.
  Accepted as transient.
- **`use_data_copy` docstring:** says the setting is per thread or task, so a worker thread
  started inside the block reads the real checkout.
- **`run_export`** calls `live_deadlines(season)` without `cfg`, so its deadlines follow
  `use_data_copy` like the tables (test added).
- **Stale docstrings** in `features.py` (module and `load_as_of`) now list all the overlaid
  fields; `output_checks.py` and `output_checks_model.py` say what they raise on.

### 2026-11-14: model - Elo goals fix round
Task 4 failed the Elo goals model on goals calibration (fail one of two). Worked on 2025/26
only, at upstream `ac8be9ca`; nothing in 2026/27 was fitted, scored or looked at, and
`backtest/reports/` was not read. The Elo ratings are unchanged. `model_version` is now
`0.1.1-elo`.
- **Scoring (my own, walk-forward as in brief section 7):** each 2025/26 GW g fixture
  (GW6-38, 660 team-fixtures) is scored once, from `elo_goals("2025-2026", g-1, "backtest")`.
  The before numbers reproduce the validator's exactly.
- **Diagnosis: two causes of about equal size behind the top bin's -0.280.**
  1. **Small-pool noise in the coefficients.** 2025/26 has no earlier season in its pool, so
     the fits up to GW20 see 50-200 matches. Through mid-season they have a steeper gap
     (0.20 per 100 points at as-of 5, 0.16 at as-of 12) and a bigger home term (0.26-0.36)
     than the full-season fit (0.143, 0.224), which over-predicts strong home sides. The
     calibration slope (Poisson regression of actual goals on log predicted) is 0.811 (se
     0.129) walk-forward against 0.957 in-sample. Scoring the walk-forward fixtures with
     full-season coefficients (a leak, as a diagnostic only) gives a slope of 0.956 and moves
     the top bin from -0.280 to -0.148. The rating spread is flat all season (std 94-101), so
     the ratings aren't widening.
  2. **The log-linear form.** log lambda = a + b gap + h home makes a fixture's expected total
     e^a (e^(h + b gap) + e^(-b gap)) rise with the gap. In 2025/26 actual match totals are
     flat in |gap|: a Poisson slope of -0.013 (se 0.038) per 100 points, where the fitted model
     implies +0.030. The split of goals between the two sides is modelled well at every gap.
     Even in-sample (full-season fit, GW6+), the top bin misses by -0.149. Half of that is
     Liverpool and Aston Villa, whose ratings ran ahead of their results (rating error, out of
     scope). Without them the old form still over-predicts both tails: favourites -0.082
     (65 team-fixtures, lambda 1.75+) and underdogs -0.085 (55, lambda below 1.0).
  - The early weeks also run low (GW6-12: predicted 1.311, actual 1.443), because GW1-5 of
    2025/26 scored 2.48 goals a match against about 2.78 later. Without an earlier season in
    the pool, nothing driven by the gap and home can fix this. It drives most of the
    middle-bin shortfall and the 2-4 point clean-sheet over-prediction.
- **Changed (still brief 6.2: Poisson goals driven by the Elo gap and home advantage):**
  - **Form:** lambda_for = 2 exp(a) x sigmoid(b x gap + h x side), with side +1 at home and
    -1 away. A fixture's expected total is 2 exp(a) whatever the ratings, and the gap and home
    advantage set the split. Equal clubs on neutral ground each expect exp(a). There are still
    three coefficients. Why: it matches the flat totals, and in-sample it brings the tails to
    favourites -0.012 and underdogs -0.009 (without Liverpool and Villa), with a better
    log-likelihood than the old form (1.4393 against 1.4405 per team-fixture, GW6+).
  - **Priors:** zero-centred Gaussian priors on b and h, both sd 0.2 on the share's logit
    scale (b per 100 rating points). The fit is penalised maximum likelihood by Fisher
    scoring, still numpy only. The intercept has no prior, so the fitted total always equals
    the pool's. Why: the priors pull a small pool towards league-average goals, and their pull
    fades as the pool grows. At 370 matches (as-of 37) they shrink b from 0.310 to 0.293 per
    100 points and h from 0.230 to 0.207. With 2026/27's two-season pool they matter less
    still.
  - **Tuning:** one value for both priors, by walk-forward log-loss on 2025/26 GW6-38, over
    sd 0.05, 0.075, 0.1, 0.15, 0.2 and 0.3 (log-loss 1.4569, 1.4501, 1.4468, 1.4445, 1.4441
    and 1.4443). It is flat from 0.15 to 0.3, and splitting the two (0.3 and 0.2, or 0.2 and
    0.3) gives 1.4442 and 1.4441. In-sample for the development window, like the Elo settings.
  - **Fitted on real data (2025/26):**

    | As-of | Matches | Total 2e^a | b per 100 | h | Equal clubs, home v away | +300 home side v opponent (old form) |
    | --- | --- | --- | --- | --- | --- | --- |
    | 5 | 50 | 2.480 | 0.269 | 0.142 | 1.328 v 1.152 | 1.788 v 0.692 (2.476 v 0.569) |
    | 10 | 100 | 2.660 | 0.302 | 0.243 | 1.491 v 1.169 | 2.019 v 0.641 (2.514 v 0.650) |
    | 20 | 200 | 2.780 | 0.298 | 0.248 | 1.561 v 1.219 | 2.107 v 0.673 (2.416 v 0.750) |
    | 37 | 370 | 2.754 | 0.293 | 0.207 | 1.519 v 1.235 | 2.059 v 0.695 (2.313 v 0.776) |

- **Before and after, 2025/26 GW6-38 (660 team-fixtures):**

  | Predicted goals bin | Before: n, predicted, actual | After: n, predicted, actual |
  | --- | --- | --- |
  | 0-0.75 | 13, 0.697, 0.769 (+0.072) | 12, 0.674, 0.833 (+0.159) |
  | 0.75-1.25 | 253, 1.060, 1.146 (+0.086) | 225, 1.062, 1.076 (+0.013) |
  | 1.25-1.75 | 300, 1.461, 1.527 (+0.066) | 349, 1.477, 1.550 (+0.073) |
  | 1.75+ | 94, 1.992, 1.713 (-0.280) | 74, 1.883, 1.703 (-0.180) |

  | `p_cs` bin | Before: n, predicted, actual | After: n, predicted, actual |
  | --- | --- | --- |
  | 0.0-0.1 | 12, 0.085, 0.000 | none |
  | 0.1-0.2 | 141, 0.164, 0.156 | 146, 0.169, 0.151 |
  | 0.2-0.3 | 277, 0.252, 0.220 | 307, 0.247, 0.208 |
  | 0.3-0.4 | 185, 0.346, 0.324 | 161, 0.342, 0.323 |
  | 0.4-0.5 | 39, 0.439, 0.410 | 38, 0.434, 0.500 |
  | 0.5-0.6 | 6, 0.515, 0.333 | 8, 0.525, 0.500 |

  - Log-loss 1.4463 before and 1.4441 after, against 1.4705 for the league-average home and
    away baseline. Calibration slope 0.811 (se 0.129) before and 0.930 (se 0.149) after.
  - **How strong the evidence is:** every log-loss gain here is within about one paired
    standard error (the chosen model: -0.0022 ± 0.0023 per team-fixture, paired by match).
    A two-fold split of the season with fixed coefficients is mixed: the old form wins one
    fold and the new form two, all by under 0.002. One season can't separate these models
    on log-loss. The change rests on the two mechanisms above, not on the score.
- **Rejected (walk-forward log-loss; top-bin miss):**
  - A gap-squared term (1.4463; -0.140) or an |gap| term (1.4463; -0.185) in the log-linear
    model: a fourth coefficient, with in-sample likelihood-ratio statistics of 1.6 and 1.4.
  - A home x gap interaction (1.4472; -0.179): worse.
  - The new form with a total that varies with |gap| (1.4466; -0.244): the fourth coefficient
    costs more than it gains.
  - A fixed multiplier on the fitted gap coefficient (0.8: 1.4460; -0.107): a post-fit
    constant that doesn't fade with pool size, so it would keep shrinking in 2026/27's large
    pools, where the noise is small. At 0.6 it is worse (1.4485).
  - The priors alone, keeping the log-linear form (sd 0.15 per 100 points and per home:
    1.4456, slope 0.904; -0.222): fixes the noise, not the form. This is the main
    alternative if a fixed total is unwanted.
  - The new form without priors (1.4452, slope 0.799; -0.230): fixes the form, not the noise.
  - Loading 2024/25 results as a prior pool: a new input that would also need 2024/25 ratings.
  - Changing the Elo ratings, for example a higher K so Liverpool's decline shows sooner: out
    of scope, and the ratings passed.
- **Inputs:** unchanged (our `elo_before`, home flag and goals of finished Premier League
  matches in the pool).
- **Outputs:** unchanged columns and keys. `lambda_for` + `lambda_against` is now the same for
  every fixture in a read: 2 exp(intercept), the pool's goals per match.
- **Code:** `models/team_goals.py`: `goal_rates` (the link and its Jacobian) and
  `fit_coefficients` (penalised Fisher scoring) replace `poisson_fit`. `GoalsSettings` gains
  `prior_sd_gap` and `prior_sd_home` and a `precision` property, and rejects a prior sd that
  isn't positive. `GoalsFit` keeps its fields: `intercept` is log goals for equal clubs on
  neutral ground, and `gap` and `home` are share-logit coefficients (gap per rating point).
  `elo_goals`, `goals_from_history` and `elo_ratings` keep their signatures and outputs.
- **Config keys added:** `goals_model.prior_sd_gap` (0.002 per rating point) and
  `goals_model.prior_sd_home` (0.2). `model_version` is `0.1.1-elo`.
- **Tests:** a new `tests/test_goals_fit.py` covers the link, a hand-computed MLE (two gap
  cells: home logit ln 1.5 and ln 5, total 11/4), stationarity of the penalised likelihood by
  finite differences, monotone shrinkage with the total kept, an overwhelming prior giving the
  pool mean, a prior making an unidentified fit possible, and the error paths.
  `tests/test_team_goals.py` adds config and constant-total tests. The known-answer
  regression in `tests/test_elo_regression.py` has new goals-model values, changed on purpose
  for this form and checked by hand (total 26/10 = 2.6, lambda 2.6 x 0.517344 = 1.345094).
  The rating values are unchanged.
- **Assumptions and known weaknesses:**
  - **A fixed expected total per fixture.** 2025/26 supports it (slope -0.013 ± 0.038 per 100
    points), but it can't rule out the old form's +0.030. Betting markets usually price
    higher totals in big mismatches, partly because strong sides attack well, and a single
    rating can't tell attack from defence. Dixon-Coles (phase 2), with separate attack and
    defence ratings, can vary the total.
  - **The home prior is centred on no home advantage,** so it trims a large pool's home term
    a little (0.230 to 0.207 at 370 matches, about -0.015 goals for an equal home side).
    Walk-forward, home sides now run 0.036 under (1.509 predicted, 1.545 actual; before:
    1.542, 1.545), within noise (se about 0.07).
  - **The early-season level** (above) remains, as does the 2-4 point clean-sheet
    over-prediction it causes. Goals are slightly underdispersed (variance/mean 0.94), so
    exp(-lambda) runs about 1 point high even in-sample (0.266 against 0.257).
  - **Rating error dominates what's left of the top bin:** Liverpool -0.63 over 10
    team-fixtures. Without Liverpool and Villa the after top bin is -0.092 (57).
  - Raising reads are unchanged: `MissingSeedError` at 2025/26 as-of 0 and 2026/27 as-of
    0-1, and `InsufficientSampleError` at 2025/26 as-of 1-2.
- **Revision (same day): log-linear form plus priors (Josh's choice).** Per "main - Elo goals
  fix: log-linear form plus priors (Josh)", the fixed-total form is rejected. The model keeps
  v1's form, log lambda = intercept + gap x gap + home x is_home, and adds the priors. This
  revision supersedes the "Changed", "Code", "Config keys", before-and-after and tests points
  above, and the two weaknesses specific to the fixed total. The diagnosis, scoring and the
  rest of the rejected list stand.
  - **Final form and settings:** zero-centred Gaussian priors on the gap and home
    coefficients (log goals), with none on the intercept, fitted by penalised Newton.
    `goals_model.prior_sd_gap` 0.00175 per rating point (0.175 per 100 points) and
    `goals_model.prior_sd_home` 0.175. `model_version` stays `0.1.1-elo`.
  - **Re-tuned the same way:** one value for both, by walk-forward log-loss on 2025/26 GW6-38
    only. sd none, 0.4, 0.3, 0.25, 0.2, 0.175, 0.15, 0.125, 0.1 and 0.075 gave 1.44625,
    1.44596, 1.44582, 1.44572, 1.44562, 1.44559, 1.44560, 1.44572, 1.44611 and 1.44714.
    0.175 is the minimum, on a flat stretch from 0.15 to 0.2. Sensitivity only, not adopted
    (a second knob tuned on one season): a tighter gap prior with a looser home prior does a
    little better (gap 0.125 and home 0.2: 1.44528; gap 0.15 and home 0.3: 1.44541).
  - **Fitted on real data (2025/26), with the unpenalised fit in brackets:**

    | As-of | Matches | Intercept | Gap per 100 | Home | Equal clubs, home v away | +300 home side v opponent |
    | --- | --- | --- | --- | --- | --- | --- |
    | 5 | 50 | 0.124 | 0.173 (0.201) | 0.125 (0.262) | 1.283 v 1.132 | 2.154 v 0.674 (2.476 v 0.569) |
    | 10 | 100 | 0.148 | 0.160 (0.171) | 0.217 (0.326) | 1.441 v 1.160 | 2.325 v 0.718 (2.514 v 0.650) |
    | 20 | 200 | 0.194 | 0.146 (0.151) | 0.214 (0.266) | 1.505 v 1.215 | 2.334 v 0.783 (2.416 v 0.750) |
    | 37 | 370 | 0.196 | 0.143 (0.145) | 0.196 (0.222) | 1.481 v 1.217 | 2.272 v 0.793 (2.313 v 0.776) |

  - **Final against v1, 2025/26 GW6-38 (660 team-fixtures),** through the public
    `elo_goals`, scored as above:

    | Predicted goals bin | v1: n, predicted, actual | Final: n, predicted, actual |
    | --- | --- | --- |
    | 0-0.75 | 13, 0.697, 0.769 (+0.072) | 3, 0.697, 1.000 (+0.303) |
    | 0.75-1.25 | 253, 1.060, 1.146 (+0.086) | 254, 1.066, 1.114 (+0.048) |
    | 1.25-1.75 | 300, 1.461, 1.527 (+0.066) | 320, 1.460, 1.528 (+0.068) |
    | 1.75+ | 94, 1.992, 1.713 (-0.280) | 83, 1.956, 1.735 (-0.221) |

    | `p_cs` bin | v1: n, predicted, actual | Final: n, predicted, actual |
    | --- | --- | --- |
    | 0.0-0.1 | 12, 0.085, 0.000 | 6, 0.085, 0.000 |
    | 0.1-0.2 | 141, 0.164, 0.156 | 132, 0.164, 0.152 |
    | 0.2-0.3 | 277, 0.252, 0.220 | 300, 0.250, 0.210 |
    | 0.3-0.4 | 185, 0.346, 0.324 | 190, 0.343, 0.337 |
    | 0.4-0.5 | 39, 0.439, 0.410 | 31, 0.439, 0.452 |
    | 0.5-0.6 | 6, 0.515, 0.333 | 1, 0.500, 0.000 |

    - Log-loss 1.4463 (v1) and 1.4456 (final), against the baseline's 1.4705. The paired
      difference is -0.0007 ± 0.0017 per team-fixture.
    - Calibration slope 0.811 (se 0.129) for v1 and 0.884 (se 0.141) final.
  - **Tried and rejected: the fixed-total form** (lambda_for = 2 exp(a) x sigmoid(b x gap +
    h x side), with priors sd 0.2): log-loss 1.4441, slope 0.930, top bin 74 team-fixtures at
    -0.180, with middle bins at +0.013 and +0.073. Josh's reasons are in the main entry. The
    final form gives up about 0.0015 of log-loss to it on 2025/26, within noise.
  - **Code:** v1's `poisson_fit(x, y, precision, tol, max_iter)` gains the prior precisions:
    they are added to the Hessian, and `precision x beta` is taken from the score.
    `GoalsSettings` gains `prior_sd_gap`, `prior_sd_home` and a `precision` property, and
    rejects a prior sd that isn't positive. `GoalsFit` and the outputs are as in v1.
  - **Tests:** `tests/test_goals_fit.py` covers v1's known answers without a prior (log-linear
    cell means, and the intercept-only log mean), stationarity of the penalised likelihood by
    finite differences, monotone shrinkage with the total kept, an overwhelming prior giving
    the pool mean, a prior making an unidentified fit possible, and the error paths. The
    regression values in `tests/test_elo_regression.py` changed on purpose, checked by hand
    (exp(0.246907 + 0.00100247 x 42.5618 + 0.021331) = 1.36466).
  - **Weaknesses, final version:**
    - **The home prior does most of the shrinking.** The gap is well identified, so it
      barely moves (0.145 to 0.143 at 370 matches). Home goes from 0.222 to 0.196, about
      -0.04 goals for an equal home side. Walk-forward, home sides now run 0.044 under (1.501
      predicted, 1.545 actual; v1 1.542) and away sides 0.006 under (1.233 against 1.239;
      v1 1.194). This is within noise (se about 0.07) but has a direction. The split grid
      above points the same way.
    - The early-season level, the clean-sheet over-prediction it causes and Liverpool's
      rating error (all above) remain. The validator's log-linear claims check holds again.

### 2026-11-14: main - Elo goals fix reviewed and committed
- **Committed as `eed7c22`:** the log-linear Elo goals model with priors on
  the gap and home coefficients, as Josh chose. The main session reproduced
  the modeller's 2025/26 numbers, and the fix passes with the committed
  harness.
- **Code Review:** approved with non-blocking findings. Its own fitter
  matches the model's coefficients on 2025/26, and every code mutant dies.
  - **Follow-up, after the re-check:** the prior-sd search isn't in the repo,
    so the setting can't be re-tuned from it, and a units slip in
    `goals_model.prior_sd_gap` (per 100 points instead of per point) would go
    unnoticed. The modeller adds a tuning command, like `elo_tune`, and a
    guard. Both wait until after the re-check, so that `config/model.yaml`
    doesn't change while the validator runs.
  - **Logged in `docs/known_gaps.md`:** the zero-centred home prior shrinks
    home advantage towards zero in small pools. The as-of 1 note in the
    `min_matches` entry is updated for the priors.
- **Two leakage self-checks become verdict criteria** in the harness: the
  planted leak must be caught (`planted_leak_caught`), and both functions
  must read the corrupted copy (`copy_reached`). If either fails, the
  leakage checks can't be trusted, so under brief section 7's "every leakage
  check passes" the verdict is FAIL.

### 2026-11-14: main - task 4 re-check: PASS, and the second holdout look
- **Holdout look (brief section 7):** the validator's re-check on 2026-11-14
  read 2026/27 GW1-10 at upstream `ac8be9ca`, on `ff6d43d` (`model_version`
  `0.1.1-elo`). The main session's recompute read the same data, with the
  same model, to verify it. Report: `backtest/reports/2026-11-14.md`.
- **Verdict: PASS** on every criterion: ratings (lowest Spearman 0.982),
  goals and clean-sheet calibration, log-loss (1.4456 against the
  baseline's 1.4688), and every leakage check, including the planted leak
  and the copy control. The main session's own script, sharing no code
  with the harness, reproduces every pass-marked bin and the log-loss.
- **Caveats for sign-off:**
  - **The bin that failed last time carries no mark this time.** The 1.75+
    goals bin shrank from 103 to 91 team-fixtures, below the 100 that carry
    a mark. It would still pass the two-standard-error rule (miss 0.231,
    limit 0.294), but it would fail the original ±0.1.
  - **On the holdout alone,** 2026/27 GW6-10 with 100 team-fixtures, the
    model beats the baseline by 0.0124, against 0.0132 for v1. The fix's
    gain is on the season it was tuned on, and the holdout difference is
    within noise.
  - **Clean sheets run slightly high** in every scored bin. The closest to
    its limit is 0.2-0.3, at −0.034 against 0.050.
- **This is the phase 1 Elo component check** (plan, task 4). Josh signs
  it off.

### 2026-11-15: main - task 4 signed off (Josh)
Josh took the three recommendations from the re-check.
1. **Task 4 is signed off.** The Elo component check passes on `ff6d43d`
   (`backtest/reports/2026-11-14.md`) under the rule set before the
   re-check, so phase 1's Elo done-when item is met. The three caveats
   logged on 2026-11-14 stand: the old failing bin now carries no mark, the
   holdout gain is within noise, and clean sheets run slightly high. They
   are part of why the phase 2 Dixon-Coles model, and Josh's beyondELO
   comparison, still matter.
2. **Two small follow-up rounds run before task 6:**
   - the modeller adds a committed tuning command for the goals priors (like
     `elo_tune`), plus a guard against a units slip in
     `goals_model.prior_sd_gap`;
   - the validator fixes Code Review's four low findings from the harness's
     third pass.

   Neither changes the verdict.
3. **Task 6 (the workflows) gets an explicit plan before delegation.**
   `update.yml` commits `outputs/` to `main` from GitHub Actions, and Josh's
   rules ask for a plan before any deployment or infrastructure work. It
   starts in a fresh session after the handoff.

### 2026-11-15: main - beyondELO key, goals-prior tuner and the task 8 hand test (Josh)
Josh answered the main session's review of his open items.
1. **beyondELO key:** it lives in the user environment variable
   `BEYONDELO_API_KEY`, set through Windows' account settings. Never in
   code, a command line or the repo. The pull is a one-off local
   data-engineer task, so GitHub needs no secret.
   - **API facts** (developer page, checked 2026-11-15): the key goes in the
     `X-API-Key` header. A key allows 10 requests a minute and 100 a day,
     reset at midnight UTC. `GET /v1/matches` gives each side's rating
     before and after a match and needs a `competition`, `season` or `club`
     filter. The page doesn't list the Premier League's competition code, so
     the data-engineer confirms it first.
   - **Rejected:** the keyless `club-elo-history` CSV. It holds ratings by
     date, after each match, so the before-match ratings would have to be
     derived.
2. **The goals-prior tuner is a separate command,**
   `python -m fpl.models.goals_tune`, with its grid under
   `goals_model.tuning` in `config/model.yaml`. `fpl.models.elo_tune` stays
   the ratings tuner. Why: each tuner covers one model. Trade-off: one more
   command.
3. **Task 8's hand test:** the excel-builder writes a checklist as part of
   task 7. Josh runs it after task 9's first scheduled publish, so the
   workbook pulls a real update rather than the data it was saved with.
   Pass marks:
   - a copy saved before a newer publish, opened without pressing Refresh
     All, shows `meta`'s `run_utc` and a `tbl_players` row count that match
     the CSVs on `main`;
   - opened offline, it shows the last good data and no sheet breaks;
   - the test waits more than 5 minutes after a publish:
     raw.githubusercontent.com caches each file for 5 minutes
     (`Cache-Control: max-age=300`, checked 2026-11-15), so an earlier
     refresh can show old files, or old and new ones mixed.
   - **For the task 7 message:** the README sheet's "how to refresh" lists
     the first-open prompts each new user sees: Protected View on a
     downloaded copy, the external-data warning, and Anonymous access for
     the web source.
   - **Still open:** pywin32 as a Windows-only dev dependency for
     `build_workbook.py`.

### 2026-11-15: model - goals-prior tuner and units guard
Phase 1 follow-up before task 6 (approved by Josh on 2026-11-15). Worked on 2025/26 only, at
upstream `ac8be9ca`; nothing in 2026/27 was read, fitted or scored, and `backtest/reports/` was
not read. No `model_version` bump: `prior_sd_gap` and `prior_sd_home` keep their values, and
the goals model's output is unchanged (checked exactly against HEAD's `team_goals.py` and
`config/model.yaml` at 2025/26 as-of 5, 20 and 37).
- **Built:** `python -m fpl.models.goals_tune` (`src/fpl/models/goals_tune.py`), the search
  behind the goals priors, now in the repo; and a units guard on `goals_model.prior_sd_gap` in
  `GoalsSettings.from_config`.
- **Method, tuner:** the search in "model - Elo goals fix round" (its "Re-tuned the same way"
  revision). One shared sd per grid point sets `prior_sd_home` = sd and `prior_sd_gap` = sd /
  `gap_points` per rating point. Each 2025/26 GW g team-fixture, g = 6..38, is predicted once
  by `goals_from_history` (the pure core of `elo_goals`) on `load_history("2025-2026", g - 1,
  "backtest")`, and scored by Poisson log-loss (-ln P(goals), with the ln goals! term) against
  the goals in the as-of 38 read.
  - Each read is loaded once, and all ten fits (the nine grid values and the no-prior
    reference, sd inf) run on it.
  - Reads go through `fpl.models.elo.load_history`, so the module holds no `load_as_of`
    reference of its own.
  - Before reading anything it refuses a tuning season other than the Elo run's first season
    (`elo.start_season`), or that season if it is the newest or the current one. It also
    refuses scored gameweeks outside the season.
  - Every grid point is built through `GoalsSettings.from_config`, so the units guard checks
    each one.
  - It logs the curve, the minimum over the grid and whether `config/model.yaml` holds it. It
    writes nothing.
- **Real run, 2025/26 GW6-38 (660 team-fixtures), 58 s:**

  | Shared sd | none | 0.4 | 0.3 | 0.25 | 0.2 | 0.175 | 0.15 | 0.125 | 0.1 | 0.075 |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | Log-loss | 1.44625 | 1.44596 | 1.44582 | 1.44572 | 1.44562 | 1.44559 | 1.44560 | 1.44572 | 1.44611 | 1.44714 |

  The minimum is 0.175, the configured value, and the curve is the fix round's to 5 decimal
  places. A scratch loop with its own join and log-loss gave the same curve, and found every GW
  g fixture in the as-of g-1 read has the same `match_id` and `gw` as in the as-of 38 read.
- **Method, guard:** `prior_sd_gap` must be below `goals_model.prior_sd_gap_max`, 0.01 per
  rating point (1.0 log goals per 100 points). The error says the setting is per rating point
  and asks whether the value is per 100 points.
  - Why 0.01: there the gap prior is practically off. With the home prior off, it shrinks the
    gap coefficient by 0.4% at as-of 5 (50 matches: 0.20123 to 0.20033 per 100 points) and by
    0.05% at as-of 37. So no useful setting is that large. The grid tops out at 0.004 (2.7%
    shrinkage at as-of 5), 2.5 times below the bound.
  - Slips: a per-100 value from the grid lands at 0.075 or above, 7.5 times above the bound;
    Code Review's mutant M20 (0.175) is 17.5 times above. At 0.175 the fit equals the
    unpenalised one to 5 decimal places, which is why the slip was silent.
- **Inputs:** unchanged (`fact_fixture` and `dim_team` through `load_history`).
- **Outputs:** none; the tuner logs only. `elo_goals`, `goals_from_history` and the published
  outputs are unchanged.
- **Config keys added:** `goals_model.prior_sd_gap_max` (0.01) and `goals_model.tuning`:
  `season` "2025-2026", `scored_gameweeks` [6, 38], `gap_points` 100 and `shared_sd_grid` [0.4,
  0.3, 0.25, 0.2, 0.175, 0.15, 0.125, 0.1, 0.075]. The `goals_model` comment points at the
  command.
- **Tests:**
  - `tests/test_goals_tune.py`:
    - a known-output curve on a fixed synthetic season (six clubs, 30 matches, GW4-10 scored,
      42 team-fixtures), with expected values from a separate loop;
    - the log-loss against hand values;
    - the grid mapping, and that a grid value the guard rejects stops the tuner;
    - the curve's refusals (a missing prediction, a missing result, a duplicate);
    - the season and gameweek guards, which load nothing;
    - the logged report, with both config-check outcomes.
  - `tests/test_team_goals.py`: 0.175 and the bound itself are rejected (each fails if the guard
    is removed), and the bound is read from config.
  - A real-data test of the full curve would take about 60 s, twice the 30 s budget, so there
    is none; the real run is above.
- **Assumptions and known weaknesses:**
  - As before, the curve is in-sample for the development window: the same 660 team-fixtures
    choose the priors and score them.
  - The bound catches a per-100 slip, not every wrong value. A per-point value between 0.004
    and 0.01 passes, and so does a value 100 times too small.
  - The tuner raises if a predicted fixture has no result in the as-of 38 read or a scored
    fixture has no prediction. That never happens in 2025/26, but a postponed match in a future
    tuning season would need a rule.
  - To score through `elo_goals`'s own core, each grid point re-runs the Elo ratings (13 ms), about
    4 s of the 58. The rest is the 34 reads, about 2 s each.
  - The loader logs two INFO lines per read (68 lines before the report), as `elo_tune` does for
    its one read.

### 2026-11-16: main - the two follow-up rounds reviewed and committed
- **Harness low findings, committed as `ae809e3`:** all four are fixed, and
  mutants P10 and P07 now die. The new caller guard found
  `fpl.models.elo_tune` missing from `CALLERS`. The `backtest/` changes
  are wording and docstrings only: no verdict rule or report number changed.
  - **Code Review:** approve with non-blocking findings. 18 mutants run,
    12 die; of the 6 that survive, one is equivalent. The guard runs on
    every `synth_point` entry.
  - **Follow-ups for the validator:** the guard looks by name, so an
    aliased import, a module reference (`features.load_as_of(...)`) or a
    default argument gets past it. Compare by identity, and make
    `fpl.features.load_as_of` raise inside `synth_point`. Also plant a
    caller under `fpl` as well as `backtest`; assert `run_check`'s default
    directly; make `run_leakage`'s dead `point` default required; and test
    the refit row's `pairs > 0`.
- **Goals-prior tuner, committed as `c3ca7c7`:** `python -m
  fpl.models.goals_tune` and the units guard
  (`goals_model.prior_sd_gap_max`). The main session ran the tuner, and
  scored the committed priors with its own script; both reproduce the
  recorded search. Outputs are unchanged; `model_version` stays
  `0.1.1-elo`.
  - **Code Review:** approve with non-blocking findings. Its own fitter
    reproduces the whole curve. `elo_goals` is identical to `ddac026` at
    seven as-of reads, and 38 of 42 mutants die.
  - **Follow-ups for the modeller:** tests for the logged minimum and for
    the config-match check (the two surviving code mutants), and rejecting
    duplicate grid values.
  - **Accepted:** no real-data test pins the config grid (about 70 s a
    run). The tuner's own "matches/DIFFERS" line shows a drift whenever it
    runs.
- **Full suite** with both rounds: 750 passed, 99% coverage of `fpl`, lint
  clean.
- **Conflict found (brief wins, not resolved here):** brief section 7 says
  every leakage check passes, and its checklist includes "Team ratings are
  refitted per target gameweek". But the harness's `criteria()` has no
  refit entry, so that row can FAIL while the verdict says PASS. On the
  2026-11-14 run it showed 42 of 42, so that PASS stands. Put to Josh, with
  the validator's two proposals: a refit rule that allows an unchanged pool
  (a wholly postponed gameweek), and a Concern when `home_above` falls
  below 0.9.
- **Settled since 2026-11-15:** pywin32 312 is a Windows-only dev
  dependency (`ddac026`). `BEYONDELO_API_KEY` is set, and Josh rotated
  the key after it was shared in a chat.

### 2026-11-16: main - refit criterion and home-share Concern (Josh)
- **Modeller follow-ups, committed as `6cf1b42`:** tests now pin the
  tuner's logged minimum and its config-match check, and a duplicate value
  in `goals_model.tuning.shared_sd_grid` stops the run before any data is
  read. The tuner's curve on 2025/26 is unchanged. The main session read
  the diff: 43 tests pass, lint clean.
- **Approved: the refit row counts towards the verdict.** This resolves the
  conflict logged above in the brief's favour. Between consecutive as-of
  reads of `elo_goals`, the fitted coefficients must change when the
  fitting pool (finished Premier League results of this season and last, up
  to the as-of, as brief section 7 defines the baseline pool) gained a
  result, and must not change when the pool is identical, as after a wholly
  postponed gameweek. A change smaller than a configured tolerance counts
  as no change, since the implied coefficients are refitted on a different
  horizon at each read. The row also needs at least one pair, and the
  ratings reads must hold no rows after their as-of.
  - **Why:** the old rule (a change at every pair) would fail a correct
    model on a postponed gameweek, and it never counted. The new rule is
    stricter too: a fit that changes with no new result is reading
    something it shouldn't.
  - **Effect on past runs:** none. Every pair in the 2026-11-14 run gained
    results and changed (42 of 42), so its PASS stands. Nothing re-reads
    2026/27 for this.
- **Approved: a Concern when the home share is low.** The report lists a
  Concern when the lowest `home_above` share falls below 0.9 (a new report
  threshold in `backtest/config.yaml`). It doesn't fail the gate. It
  watches the known gap where the home prior pulls home advantage towards
  zero on a small sample. On the 2026-11-14 run the lowest share was 1.000.
- **Next:** one validator round covering both, plus the five Code Review
  follow-ups logged above. Brief section 7 gains the refit rule under "How
  the check is run".

### 2026-11-16: main - refit round reviewed and committed
- **Committed as `6f26524`:** the `refit` criterion, the home-share Concern
  and Code Review's five follow-ups on `ae809e3`. Nothing read 2026/27, so
  there is no holdout look to log.
- **Tolerance 1e-9:** on 2025/26, refitting one read on different horizon
  subsets moves the coefficients by at most 5.4e-15 (Code Review: 3.1e-15).
  The smallest real step between consecutive reads is 2.7e-3, and all 34
  pairs changed both their pool and their coefficients.
- **The 2026-11-14 PASS stands.** Every pair in that run gained results.
  The 8 pairs that touch 2026/27 are known only to have changed above zero,
  but real refit steps are about 1e-3, so a re-run (a holdout look) isn't
  worth it.
- **Code Review:** approve with non-blocking findings; 30 of 40 mutants die,
  two of the survivors equivalent. The harness's pool equals the model's own
  fitting pool at every 2025/26 as-of from 3 to 37. The verdict and the
  checklist row can't disagree.
- **Brief:** the refit bullet now says the pool "changed (in practice, it
  gained a finished result)" and names `refit_tolerance` (the validator's
  proposal). **Known gap logged:** the refit check assumes the goals model's
  log-linear form.
- **Full suite:** 786 passed, 99% coverage of `fpl`, lint clean.
- **Follow-ups for the validator,** one more small round:
  1. Test `run_check`'s refit wiring end to end: a synthetic gameweek with
     its league matches postponed and a cup tie kept. Mutants R15-R17
     (unfiltered fixtures, pool length 1, the wrong tolerance) survive.
  2. Render a run with no goal-check rows instead of crashing (predates
     this round).
  3. Patch `fpl.features._resolve` inside `synth_point`, so reaching the
     real loader without the synthetic config raises, however a caller
     holds it (closes the container, partial and closure gaps).
  4. Pin the three new report numbers (L04-L06).
  5. The home-share Concern: assert the "of K reads" count, and test a
     non-default threshold (H02, H03).
  6. Bring `tests/test_elo_check_run.py` (320 lines) under 300.
  7. Count a non-finite coefficient difference as a fail.
  8. Correct the config comment: 1e-9 is about 5.3 orders above the noise
     and 6.4 below the smallest step.
  9. Check that the backtest's pool settings match the model's (the
     season order against `elo.start_season`, `baseline_pool_seasons`
     against `goals_model.pool_seasons`); nothing does today.

### 2026-11-16: main - task 6 plan: CI skips the real-data tests (Josh)
- **Decision 1 of `docs/plans/task-6-workflows.md`, approved:** `ci.yml`
  runs without the upstream checkout, so the real-data tests skip there.
  - **Why:** CI stays quick and doesn't depend on upstream being
    reachable. The real-data tests still run locally before every commit,
    and `update.yml` runs every check on the real data twice a day.
  - **Trade-off accepted:** a change that breaks only on real data isn't
    caught by CI. It's caught at the local run, or at the next `update.yml`
    run, which then fails without publishing.
  - **Rejected:** a pinned upstream checkout in CI (a large checkout and
    several extra minutes on every push, and a SHA to bump whenever those
    tests change), and the newest upstream (it fails CI whenever upstream
    changes, because the real tests pin row counts).
- **Still open:** the rest of the plan. Nothing is delegated yet.

### 2026-11-16: main - task 6 plan approved (Josh)
- **Approved:** the rest of `docs/plans/task-6-workflows.md`, including the
  items the main session decided:
  - the brief's skip rule is kept as it is;
  - third-party actions are pinned to full commit SHAs;
  - `fpl.run_pipeline` runs before `fpl.export` in `update.yml`;
  - no force-publish input yet, and no coverage gate in CI.
- **Known gap logged:** a stalled upstream across a deadline.
- **Next:** the data-engineer builds the skip-rule function and both
  workflows, then Code Review and `/security-review`. The main session
  asks Josh before the first manual run.

### 2026-11-16: main - refit follow-ups reviewed and committed
- **Committed as `f4ff5cc`:** the nine follow-ups logged above, then a
  second pass on Code Review's findings. Nothing read 2026/27, so there is
  no holdout look to log.
- **Code Review:** approve with non-blocking findings. 33 mutants run, 29
  die: R08 and R09 are equivalent, L06 was closed in the second pass, and
  G11 was stricter. The moved tests were compared by syntax tree, and none
  was lost or weakened. The session fixture leaks no state between tests.
  - **Second pass, checked by the main session, not re-reviewed:** L06
    pinned; the postponed scenario checks its own cup tie; a non-finite
    pair is reported as "not finite"; the synthetic swap raises on any read
    that resolves to the real checkout; the season order comes from
    `pipeline.yaml`; the comment-reading test deleted.
- **New rules, approved by the main session:**
  - a NaN or infinite coefficient difference fails the refit pair (added
    to brief section 7);
  - `check_pool_settings` stops the run, before any read, unless the
    backtest seasons start the Elo run (`pipeline.yaml`'s seasons from
    `elo.start_season` on) and `baseline_pool_seasons` equals
    `goals_model.pool_seasons`. A prefix is enough: a pipeline season the
    backtest doesn't cover yet doesn't stop the check.
- **Full suite:** 853 passed, 99% coverage of `fpl`, lint clean.

### 2026-11-16: main - task 6 reviewed and committed
- **Committed:** `aabff75` (`read_upstream_commit` refuses a folder that
  isn't its own clone) and `68d19f5` (`update.yml`, `ci.yml` and
  `fpl.publish_decision`).
- **Code Review:** request changes, all fixed before the commit:
  - bare `pytest` in CI couldn't import `backtest`, so it's now `python -m
    pytest`;
  - a run queued behind another started from the queued commit and its
    rebase conflicted, so the checkout is now `ref: main` and a failed
    rebase is aborted before the retry;
  - stale files could stay in `outputs/`, so the folder is now cleared
    before the copy;
  - the token stayed on disk for the whole job, so it now reaches only the
    commit step, through a credential helper;
  - `read_upstream_commit` fell through to our repo;
  - two tests were added for the publish decision (mutants M15 and M27).
  The plan's line "a rebase can't conflict" is corrected.
- **`/security-review`:** no vulnerabilities found. Upstream content is only
  read, never run. The only `${{ }}` in a step is the token in `env:`.
  `ci.yml` uses `pull_request`, not `pull_request_target`.
- **Brief section 11** brought in line with the approved plan: CI runs on
  pushes to `main` and on pull requests, and the upstream checkout takes
  each season's master files and `By Gameweek` folders.
- **For task 7 (excel-builder):** the CSVs publish free text from upstream
  (`news`, names) unscreened. Power Query loads values, which is safe, but
  opening a raw CSV straight in Excel could evaluate a cell starting `=`,
  `+`, `-` or `@`. The README sheet should say to use the workbook.
- **Not yet tested on GitHub itself:**
  - the credential helper and the rebase retry;
  - the pinned wheels on Linux;
  - workflow syntax (actionlint isn't installed).
  The first CI run and the first manual run test these. Step 6 of the plan
  now includes a second manual run with upstream unchanged, which must skip.

### 2026-11-16: main - task 6 done: the first manual runs (Josh approved)
- **First run** ([43902048007](https://github.com/Joshc386/fpl-xp-model/actions/runs/43902048007),
  52 s, green):
  - It published `4f8fa36` as `github-actions[bot]`. The commit holds only
    the four `outputs/` files, and its message gives upstream `fa67c136` and
    `run_utc` 2026-11-16T15:57:50Z.
  - Rows: `players` 672, `fixture_difficulty` 100, `elo_ratings` 960,
    `meta` 1.
  - `meta`: `current_gw` 10, `next_gw` 11, next deadline
    2026-11-21T11:00:00Z, `model_version` 0.1.1-elo, status ok.
  - The credential helper and the push worked.
  - All four raw GitHub URLs serve the files (HTTP 200).
- **Second run** ([43902361860](https://github.com/Joshc386/fpl-xp-model/actions/runs/43902361860),
  29 s, green): upstream was still at `fa67c136`, so the publish decision
  skipped. The build, export and commit steps were skipped, and `main`
  didn't move. This shows the skip rule reads the published `meta.csv`.
- **Local rebuild,** by the main session at the same upstream commit and
  `run_utc`, on Windows:
  - `meta`, `players` and `elo_ratings` are byte-identical to the published
    blobs.
  - In `fixture_difficulty`, 8 lines differ in the last bit of a float
    (largest difference 2.2e-16), from Linux and Windows maths.
  - The published blobs use LF. The local working-tree copies show CRLF
    only because of git's `core.autocrlf` on checkout, which Power Query
    never sees.
- **Task 6's done-means is met:** a manual run on `main` passes and
  publishes. Next:
  - task 7 (the workbook) can start against these CSVs;
  - task 9 watches the scheduled runs, from 18:00 UTC today. A scheduled
    run with no new upstream commit skips and doesn't count towards task
    9's two publishing runs.

### 2026-11-16: excel - task 7 part 1: the workbook foundation
Built on `19ee8e5`. Real outputs from `4f8fa36`, read from the raw GitHub URLs.
- **Queries** (`excel/queries/*.pq`): `BasePath` (the one parameter, release URL by default),
  `GetCsv` (a function: `Web.Contents` for an `https://` base, `File.Contents` otherwise),
  and `players`, `fixture_difficulty`, `meta`. Types are set explicitly with culture `en-US`.
  The two `_utc` columns load as UTC date-times. Tables: `tbl_players` (672 rows),
  `tbl_fixtures` (100), `tbl_meta` (1), on hidden `Data_Players`, `Data_Fixtures`,
  `Data_Meta`. Refresh on open is on, with background refresh off.
- **`in_horizon` lives on the README sheet** (cell C5, whole number from 1 to
  `meta_max_horizon`, default 5, input fill). Why: README is the only user sheet in phase 1,
  and parts 2 and 3 refer to the name, not the cell. Trade-off: a user on another sheet must
  jump to README to change it, so each sheet should show the current value with a link. It
  can move to the Dashboard in a later phase by changing one `Names.Add`.
- **Colour scale** (`wb_style.py`): orange `#F1A340`, near-white `#F7F7F7`, blue `#67A9CF`
  (ColorBrewer PuOr family, colour-blind safe). Blue is always good for the manager (high xP,
  easy fixture, likely clean sheet). Inputs: fill `#FFF2CC`, blue font, unlocked.
- **Protection:** no password on user sheets. The `Data_` sheets are hidden and not protected,
  because a protected sheet blocks the table resizing a refresh needs.
- **Build:** `excel/build_workbook.py` starts its own Excel with `DispatchEx`, builds to
  `excel/build/FPL_Model.new.xlsx`, refreshes and checks it, then replaces `FPL_Model.xlsx`.
  A local `--base-path` build never replaces it. Excel only exits when every COM reference is
  dropped, so `ExcelSession` releases ours, then waits and stops only its own pid if needed.
- **Checks:** every cell of the three tables is compared with its CSV (13,440 + 1,000 + 10
  values, tolerance 0.01, times to 1 second); no error values on any sheet.
- **For parts 2 and 3:** `players.csv` `selected_pct` and `chance_next` are in percentage
  points (47.6, 75), not fractions, so the `0%` format would show 4760%. Use
  `wb_style.PCT_POINTS_FMT` (`0.0"%"`) unless the contract changes them to fractions.
- **Not tested:** the first-open prompts a new user sees. This machine already had the
  Anonymous credential, so no prompt appeared. The README wording for them is from Microsoft's
  documented behaviour and is for the task 8 hand test to confirm, as is the offline line.

### 2026-11-17: main - task 7 part 1 accepted; two display choices
- **Part 1 (the workbook foundation) accepted** for review at the end of
  task 7. It builds from the raw GitHub URLs in about 30 s, and all three
  queries refresh. It reconciles every value with the CSVs (14,450, none
  off) and shows no error values. 876 tests pass, and lint is clean.
- **`in_horizon` stays on the README sheet (`README!C5`)** in phase 1.
  README is the only user sheet so far, and every formula refers to the
  name, not the cell, so it can move to the Dashboard in phase 5 by
  changing one name. Each later sheet shows the current value with a link
  back.
- **Percentage-point columns show one decimal place with a literal `%`**
  (`0.0"%"`). `selected_pct` and `chance_next` are published as points
  (47.6, 75), so the brief's `0%` would show 4760%. A whole-number format
  would also show 0.3% ownership as 0%. Brief section 10's formats line is
  updated. No contract change: the CSVs stay in points.
- **The 18:00 UTC scheduled run of 2026-11-16 started 7 h 43 min late**
  (created 01:43 UTC on 2026-11-17). It was green and published upstream
  `6df7a43` as `4ec7fba`, the first scheduled publish. Watching whether
  lateness recurs before moving the cron off the hour.

### 2026-11-17: excel - task 7 part 2: the Player Database sheet
Built on part 1, uncommitted. Built and refreshed from the raw GitHub URLs (upstream `6df7a43`).
- **Interaction: dropdown and text inputs feeding one filter, not slicers.** Inputs (all `in_*`
  named, input fill, unlocked): `in_search` (name contains, case-insensitive, no wildcards),
  `in_team`, `in_position`, `in_status` (lists from `tbl_players` through spill ranges on the
  hidden `Data_Lists` sheet) and `in_max_price` (a price cap in £m). An empty cell means no
  filter, so the sheet starts with all 672 players. Why not slicers: a slicer acts on an Excel
  Table, and the only table holding these rows is `tbl_players` on a hidden sheet that a refresh
  resizes, so it can be neither protected nor shown; a FILTER spill can't carry a slicer. A
  visible copy of the table would need a hand-built slicer, would have no name search, and
  would break the protection rule. Trade-offs: one value per control (slicers allow several),
  and a dropdown shows the status letter. No manual steps, no `MANUAL_STEPS.md`.
- **How it works:** named formulas `pd_keep` (the filter), `pd_count` and `pd_rows` (matching
  row positions, highest total points first, ties in CSV order). Each of the 19 columns is one
  `INDEX(tbl_players[col], pd_rows)` spill, so column order is mine and no column is found by
  position. A blank `news` shows empty, and a blank `chance_next` shows empty rather than 0
  (FILTER and INDEX turn a blank into 0, so each is tested explicitly). `pen_taker` shows Yes
  or empty. No match shows empty cells and "Showing 0 of 672 players". No IFERROR anywhere.
  The sort by total points is my choice; the brief names no order.
- **Left out until a later phase:** xGI/90, xP next GW, horizon xP and value per £m, because no
  CSV holds them. Proposal: add `xgi90` to `players.csv` (see the report) rather than add
  `xg90 + xa90` in Excel.
- **Formats:** price `£0.0"m"`; `selected_pct` and `chance_next` `0.0"%"`; `ppg` 0.0; per-90
  0.00; price changes signed `+£0.1m`; net transfers signed with thousands separators. Status
  fills from the shared palette: a blue, d pale orange, i and s orange, u grey. The letter
  stays in the cell. Header row and name column frozen, sheet protected with no password.
- **Checks in the build** (`check_players.py`): eight scenarios set the inputs, recalculate,
  and compare the spill with an independent pandas filter of the CSV (row count and every
  displayed value, 32,376 in all); error values are scanned after each; inputs are cleared
  before saving. The horizon is not shown on this sheet because phase 1 has no horizon-based
  column here; Fixture Analysis will show it with a link.
- **Bug fixed from part 1:** pywin32 ignores the named `After=` and `Before=` arguments of
  `Worksheets.Add`, so part 1's README was the last sheet, after the hidden ones. They are now
  passed positionally and README is first. A test checks the order.

### 2026-11-17: main - task 7 part 2: two calls on the Player Database
- **Part 2 accepted** for review at the end of task 7.
  - The sheet shows `players.csv`'s 19 columns.
  - Eight filtered views match counts from the CSV: no filter 672, ARS 29,
    MID 299, injured 59, at most £6.0m 608, ARS + MID + £6.0m 7, a name
    search 30, and no match 0.
  - All 32,376 displayed values compared match the CSV.
  - There are no error values, and lint is clean.
- **Departure from brief section 10, put to Josh:** the brief asks for
  slicers for team, position and status. The sheet uses dropdown `in_*`
  cells (`in_team`, `in_position`, `in_status`, `in_max_price`,
  `in_search`) feeding one FILTER.
  - **Why:** a slicer needs an Excel Table. The only one holding these rows
    is the hidden `tbl_players`, which a refresh resizes, and a FILTER spill
    can't carry a slicer.
  - **Trade-off:** one value per control, where a slicer allows several.
  - The brief is updated only if Josh accepts.
- **Contract proposal, deferred to phase 3:** `xgi90` (xG/90 + xA/90) in
  `players.csv`. It belongs with phase 3's other Player Database columns
  (xP next GW, horizon xP, value per £m). Adding it now would take a
  data-engineer change, a publish, then a second workbook pass for one
  column.
- **Process note:** the excel-builder ran `ruff format` over `tests/`, then
  reverted it with `git checkout -- tests`. The main session confirmed that
  only formatting was reverted and no uncommitted work was lost; only
  `tests/test_workbook.py` is new. The full suite is re-run before the
  commit.

### 2026-11-17: excel - task 7 part 3: the Fixture Analysis sheet and the hand-test checklist
Built on part 2, uncommitted. Built and refreshed from the raw GitHub URLs.
- **Club list:** `SORT(UNIQUE(tbl_players[team]))`. `tbl_fixtures` can't be the source, because a
  club with no fixture in the horizon would lose its row. `players.csv` `team` is the same
  short name as in `fixture_difficulty.csv` (contract note), and all 20 clubs have players.
- **Grid:** 20 clubs by up to 5 gameweeks (`GRID_GWS`, the model's `max_horizon`; a message
  shows on the sheet if `max_horizon` ever exceeds the grid, and the workbook must be rebuilt).
  Gameweeks run from `tbl_meta[next_gw]` for `in_horizon` gameweeks; columns past the horizon
  are empty. Each cell shows `OPP (H)`; a blank gameweek shows a grey dash; a double shows
  `OPP (H) + OPP (A) = x.xx`, the sum of the two rows, as the contract says. Columns: Club,
  Total, then the gameweeks (Total sits beside Club so a short horizon leaves no gap).
- **Lookups live on a hidden, protected `Data_Grid` sheet** (formulas only, no model logic):
  SUMIFS and COUNTIFS on `tbl_fixtures` by table and column name, TEXTJOIN over FILTER for the
  text. A blank `in_fixture_view` shows Attack; only the exact value `Defence` switches.
- **View switch:** `in_fixture_view`, a dropdown of Attack (`lambda_for`) or Defence (`p_cs`),
  default Attack.
- **Sort:** by the horizon total, **highest first in both views**: more goals expected for the
  club (Attack) or a higher clean-sheet chance (Defence) is better for the manager. Ties stay
  A-Z. A club with a blank gameweek has a smaller total, as in FPL's own fixture totals. In a
  double the sum of two `p_cs` can exceed what one match gives, which is the contract's rule.
- **Colour follows the view:** the shared scale, blue good and orange bad, on both views. The
  Total column uses Excel's colour scale. A colour-scale rule can't colour a text cell by a
  number elsewhere, so the grid cells take a 10-step version of the same three colours
  (`wb_style.scale_colour`), from the cell's number on `Data_Grid` between the grid's lowest and
  highest value in the current view and horizon. The middle step is the scale's near-white.
  Doubles carry a summed value, so in a view with doubles they sit at the blue end.
- **Names:** `in_horizon` is now defined before any sheet uses it (`wb_readme.define_names`),
  at the fixed cell `README!C5`.
- **Sample data:** `excel/sample_outputs/` (a copy of `players.csv` and `meta.csv`, and
  `fixture_difficulty.csv` with the Chelsea v Crystal Palace match moved from GW13 to GW12).
  So CHE and CRY each have a double in GW12 and a blank in GW13 (a match always involves two
  clubs, so blanks and doubles come in pairs here). It follows the contract: one row per team
  and match, two rows per match. Build from it with `--base-path`; that never replaces
  `FPL_Model.xlsx`.
- **Checks in the build** (`check_fixtures.py`): both views at horizons 1, 3 and 5 against an
  independent pandas build of the grid (club order, every cell's text, every total, every number
  on `Data_Grid`), the colour Excel shows on the highest, lowest and a dash cell, and no error
  values.
- **Hand test:** `excel/HAND_TEST.md`, sections A to H, from the 2026-11-15 pass marks.
- **Part 2 still stands:** the dropdown design is unchanged; no `xgi90`.

### 2026-11-17: main - Player Database filters: dropdowns accepted (Josh)
- **Josh accepted** dropdown filters in place of the brief's slicers:
  `in_team`, `in_position`, `in_status`, `in_max_price` and `in_search`
  feed one FILTER, and an empty cell means no filter. Brief section 10's
  Player Database interaction line is updated.
  - **Why:** a slicer needs a visible Excel Table, and the only one holding
    these rows is the hidden `tbl_players`, which a refresh resizes. A
    FILTER spill can't carry a slicer.
  - **Trade-off accepted:** each filter takes one value, where a slicer
    allows several.
- **Scheduled runs:** the 08:00 UTC run of 2026-11-17 hadn't started by
  10:40 UTC. Together with the 18:00 run of 2026-11-16 starting 7 h 43 min
  late, this is put to Josh as a reason to move the cron off the hour.

### 2026-11-17: excel - task 7 review fixes (Code Review, approved with findings)
Dropdown design unchanged (Josh accepted it). Items by the review's numbers.
- **1. Independent checks.** The build check (`check_players.py`, `check_fixtures.py`) and the
  tests now hold hand-written (header, source column, number format) rows, the dropdown lists
  and the gameweek headers, instead of reading back the builder's own constants. The build
  checks: each header and number format on the saved sheet; `lst_team`, `lst_position` and
  `lst_status` against the CSV's unique values, and each input's validation formula; Fixture
  Analysis headers against `GW {next_gw + k}` at every horizon. Refresh on open (and
  foreground refresh) moved into `check_workbook.check`, so every build enforces it. Mutants M1,
  M9, M19, M22 and M23 are each caught by the build check, and by a pure test (M19 through
  `wb_data.REFRESH_ON_OPEN`); results in the report.
- **2. Colour.** A cell is coloured by its **per-match average** (a double's text still shows the
  sum). Why this over setting the range from singles and capping doubles: no special case, and
  the same colour then means the same difficulty of one match in every cell; a cap would hide a
  genuinely hard or easy double. Cost: a double is not shown as better because it has two
  matches (its Total still counts both). The Total column's colour scale now has its middle at
  the arithmetic middle of its lowest and highest value (a formula midpoint), not the 50th
  percentile, which matches the grid's steps. `wb_style.apply_scale` does this for any sheet.
- **3. Process handle.** `ExcelSession` opens one process handle (terminate and synchronise
  rights) right after `DispatchEx`, waits on it, terminates through it if Excel hasn't exited
  after 15 s, then closes it. Holding it stops Windows reusing the pid, so a fallback can't hit
  Josh's own Excel.
- **4. `HAND_TEST.md`:** blank `chance_next` versus 0 (0 correctly shows `0.0%`); "Showing N of
  N"; section B starts with how to clear the Anonymous permission.
- **5. Personal information.** Before saving, `RemovePersonalInformation` is on and the
  author, last author, company and manager properties are cleared. After saving, `personal_info_hits`
  searches every part of the .xlsx, and the query package inside `customXml` (base64 then zip),
  for "Josh", "Cohen", "joshc", "C:\Users" and email addresses, and fails the build on a hit. The
  public repository URLs are excluded on purpose, because they carry the owner's login. A
  development build also excludes its own local base path. The pre-fix `FPL_Model.xlsx` had
  `Josh Cohen` in `docProps/core.xml`, and `Josh`, `joshc` and `C:\Users` in `xl/workbook.xml`
  (the saved folder path); the rebuilt file has none. A test scans the committed workbook.
- **6. `--base-path`:** a relative folder becomes absolute; the release URL with or without its
  trailing slash is the release URL; a locked `FPL_Model.xlsx` gives a plain message, before the
  build and again at the replace.
- **7.** The Excel tests compare with the CSV's row counts, not 672 and 100.
- **8. Guard messages** on Fixture Analysis (and the README note): a cleared horizon, a horizon
  outside 1 to `max_horizon` or a decimal (`horizon_problem`), `max_horizon` above the grid's 5
  gameweeks, and more than 20 clubs in `tbl_players[team]`. The build check exercises the first
  three.
- **9.** `FIXED(num,2,TRUE)` replaces `TEXT(num,"0.00")`.
- **10. Standards:** `tests/test_workbook.py` split into `test_workbook_queries.py`,
  `test_workbook_sheets.py`, `test_workbook_excel.py` and `workbook_helpers.py`, each under 300
  lines; docstrings and the `expected_grid` return type added; `define_names` runs once;
  `LAST_COL` derived; unused arguments removed.
- **11.** README says "twice a day, around 08:00 and 18:00 UTC" and that GitHub can start a
  scheduled run late, sometimes by hours.
- **12.** `pyproject.toml` `[tool.ruff]` `src` now includes `excel`; nothing else there changed.

### 2026-11-17: main - task 7 reviewed and committed
- **Committed as `5831836`:** the workbook, its build code, queries, sample
  outputs, tests and `excel/HAND_TEST.md`.
- **Code Review:** approve with non-blocking findings. It dumped all 424
  formulas: no IFERROR, INDIRECT or OFFSET, every data reference by table
  and column, and no model logic beyond the contract's double-gameweek and
  horizon sums. 19 of its 23 mutants were caught. All findings were fixed
  before the commit:
  - the four survivors (a header label, the gameweek headers, the
    ownership format, a dropdown list) are now checked against independent,
    hand-written expectations;
  - refresh on open is enforced by every build;
  - a double gameweek is coloured by its per-match average, so it no longer
    washes out the grid;
  - the Excel process is stopped only through a handle held since launch;
  - three false-fail steps in `HAND_TEST.md` are fixed;
  - personal information is removed. The creator "Josh Cohen" and a local
    build path were in the file. Every build now scans for them and fails
    on a hit, and the main session's own scan of the committed file found
    only the public repo URL.
- **Main session's check:** full suite 902 passed, 99% coverage of `fpl`;
  lint clean. `excel/` isn't in the coverage source, and its Excel tests
  skip on Linux.
- **Known gaps logged:** the name search ignores accents, and a failed
  refresh can leave tables from different runs. Brief section 10's tech
  stack line no longer lists slicers.
- **Task 8's hand test** runs after the next publish, so the committed
  workbook (data from `4ec7fba`) pulls newer data on open.

### 2026-11-17: main - beyondELO pull, run times and the task 8-9 calls (Josh)
Josh took all eight of the main session's recommendations on the handoff.
1. **The beyondELO pull is capped at 20 requests.** About 6-9 are expected:
   1 for `/competitions`, 4 for 2025/26 and 1-4 for 2026/27, at 100 matches
   a page. It keeps under 10 a minute, stops on a 429 or at the cap without
   retrying, and caches every raw response, so a re-run spends nothing.
   Trade-off: if the paging differs, the pull finishes the next day.
2. **Both full seasons are pulled,** not just the scored windows. The
   windows stay as decided on 2026-11-13: 2025/26 GW27-38 and 2026/27 from
   GW3. The earlier matches give the comparison something to fit on outside
   them.
3. **The comparison's 2026/27 window is a holdout look** (brief section 7).
   It is logged as the third look when it runs, and its result feeds the
   phase 2 Dixon-Coles call, not a retune of our Elo. The pull isn't a look.
4. **Promoted clubs are flagged, and results are reported with and without
   them.** A club is promoted if it isn't among the previous season's
   Premier League teams in upstream's teams files (2024-2025 for 2025/26,
   2025-2026 for 2026/27). beyondELO doesn't rate the Championship, so their
   ratings carry over from their last Premier League spell.
5. **Two tasks.** The data-engineer pulls now. The comparison is a script by
   the model-validator, which didn't build the Elo model, with its report in
   `backtest/reports/` carrying the credit "beyondELO
   (https://beyondelo.com)" (CC BY 4.0). Its method is settled with
   `/grill-with-docs`, and its measures defined in `CONTEXT.md`, before it
   is delegated. Josh gives the verdict.
   - **Caveat:** beyondELO learns a home advantage per club, but the API
     gives only ratings, so the comparison tests its ratings, not its full
     predictions.
   - **New table `ext_beyondelo`** (data contract, processed tables), kept
     in `data/external/beyondelo/`, apart from the season folders, because
     it's an outside source the pipeline doesn't build.
   - **Read path (main session; flagged to Josh):** the project rule is that
     data outside the data-engineer's code is read only through
     `load_as_of`. `ext_beyondelo` is read through the data-engineer's own
     reader in `fpl.beyondelo` instead. Why: it is a check, never a model
     input, and each row's before-match rating was fixed when the match was
     played, so there is no as-of to apply.
6. **Scheduled runs move to 08:23 and 18:23 UTC.** GitHub's documentation
   says scheduled runs are most likely to be delayed or dropped at the start
   of each hour, and advises another minute. So far the 11-16 18:00 run
   started 7 h 43 min late, and the 11-17 08:00 run hadn't started by
   13:37 UTC. Josh doubts it will make much difference; it is a two-line
   change, and task 9's log will show.
   - The workbook's README sheet ("around 08:00 and 18:00 UTC", and that
     runs can be late) stays, so the committed workbook isn't rebuilt
     before the hand test.
   - Updated: brief sections 1 and 11, `CONTEXT.md` "Run",
     `docs/plans/phase-1.md`, `docs/plans/task-6-workflows.md` and
     `excel/HAND_TEST.md` (by the excel-builder).
   - **Code Review:** approve with three low findings, all stale times (the
     two plans' tables and `HAND_TEST.md`), fixed before the commit.
7. **A dropped run doesn't break "consecutive".** Task 9 counts the
   scheduled runs that started and logs every dropped one, because a drop is
   GitHub's scheduler, not our workflow failing. Trade-off: a looser reading
   of the done-when item.
8. **QA (task 8) runs once the pull and run-time commits land,** so it never
   tests a tree another agent is editing. It measures `excel/` and
   `backtest/` coverage locally with extra `--cov` flags, and changes no
   config.

### 2026-11-17: data - beyondELO pull built
- **What:** `python -m fpl.beyondelo` pulls beyondELO's Premier League matches for 2025-2026 and
  2026-2027 and builds `ext_beyondelo` into `data/external/beyondelo/{season}.parquet`, with
  `reconciliation.csv` beside it. Three modules: `beyondelo_api.py` (client, cache, paging),
  `beyondelo_build.py` (pure build and reconciliation), `beyondelo.py` (config, I/O, `load_beyondelo`).
  No real request was made; the HTTP layer is faked in the tests.
- **Evidence for the keys:** upstream's `code` is stable across seasons and `id` is not (Chelsea:
  code 8, team id 6 in 2024-25 and 7 in 2025-26). `promoted` is therefore `team_code` not in the
  previous season's `code` set (2025/26: Leeds, Sunderland, Burnley; 2026/27: Coventry, Hull,
  Ipswich). The 2024-2025 file is `teams/teams.csv`; later seasons have `teams.csv`.
- **Cleaning and checks:**
  - Premier League competition code is not in config: it is the one England tier-1 entry in
    `/competitions` (country "England", tier 1); none or several stops before any
    `/matches` call. Why: the code is undocumented, and a configured guess would be wrong silently.
  - Join on home club, away club and exact UTC date. No +-1 day tolerance: our Premier League
    kickoffs are 11:00-20:00 UTC in both seasons, so none crosses midnight in either source.
  - Club names match `dim_team.name` exactly plus `beyondelo.club_aliases` (empty to start). An
    unmapped name fails the build and every one is listed. No fuzzy matching.
  - Fail: a finished match of ours with no played partner, a score that differs, a duplicate
    home/away/date on either side, a missing field, a `season` other than the one asked for, a
    played match without all four ratings, an unreadable date.
  - Counted, not failed (`reconciliation.csv`, columns season, source, reason, matches): ours
    `matched`, `finished_without_partner`, `not_finished`; beyondELO `matched`, `unplayed`,
    `not_in_our_fixtures`, `same_clubs_other_date`, `played_not_finished_in_ours`.
  - Budget: cap 20 requests per run checked before each, 6.5 s between requests, no retry on a
    429 or any non-200, no redirects followed (urllib would resend the key header), https only.
    Each response is saved to `raw/` once it parses as JSON, before field checks, so a field
    problem is fixed and re-run from the cache at no cost.
  - `beyondelo_match_id` is stored as a string, whatever type beyondELO's `id` has.
- **Effect downstream:** none. `ext_beyondelo` is outside the pipeline and `load_as_of`; the
  model-validator reads it through `load_beyondelo(season)`.
- **Fix round (after Code Review):**
  - The usage line no longer shows the key; the `--help` text says the key is set in the
    environment, never on the command line.
  - After page 1 the pull stops if the pages `meta.total` implies exceed the requests left, or if
    a record's `season` is not the one asked for. Only `season` is checked: whether a record's
    `competition` holds a code or a name is unknown until the first real response. The cap message
    now says to check the cached responses.
  - Build fails if a played, decided match does not raise the winner's rating and lower the
    loser's (catches a before/after or home/away mix-up), listing the first five ids.
  - Errors name the cache files to delete (`raw/matches_{season}_p*.json`); the body of a non-2xx
    response is logged (300 characters, key replaced by `***`); the request sends
    `User-Agent: fpl-model`; the cache is written through a temp file and `replace`; a corrupt
    cache file raises an error naming it.
  - `load_beyondelo` reads `beyondelo.external_dir` from config.
  - Trimmed: season-coverage narrowing of the competition code, a bare-list response, the "eng"
    country spelling, three unreachable checks, and the unused JSON fixture. Team ids now come from
    `add_team_ids` (which fails on unmapped names), and `build_season` casts them to int, so it
    cannot silently drop an unmapped club without its own name check. The run-level check lists
    names across both seasons.
  - The fix-round code was written before its tests, against the TDD rule; the tests were then
    added, and not seen failing first.
- **Second fix round (after Code Review's second pass), tests written and seen failing first:**
  - `run` passes each season's Premier League fixture count (all scheduled, from `fact_fixture`)
    to the pull, which stops after page 1 if `meta.total` is above it, as well as if the pages
    exceed the requests left.
  - Nothing is logged for a 401 or 403 body. For other statuses the key, its percent-encoded and
    plus-encoded forms and its JSON-escaped form are redacted before the 300-character cut.
  - The "delete `raw/matches_{season}_p*.json`" hint is on the "finished without partner" failure
    only (`BuildError.refresh`); a re-pull returns the same data for the other failures.
  - The winner check fails only above `beyondelo.max_wrong_direction_share` (0.5) of played,
    decided matches, and otherwise logs the count, share and first five ids (WARNING if any).
    A margin-based Elo can lower a narrow-winning favourite; a label mix-up makes nearly all wrong.
  - `matches_frame` no longer checks `season` (the pull checks every page). The unmapped-name check
    kept is the run-level one, which lists names across both seasons; `add_team_ids` has none and
    `build_season` fails on a missing team id.
  - `tests/test_beyondelo_api.py` split into client and paging files.
- **First real response:** `/competitions` gave string tiers ("domestic_league", "continental_club"), not
  numbers, and the Premier League's code is `eng.1`. `find_premier_league_code` now selects country
  "England" and tier "domestic_league"; none or several still stops.

### 2026-11-17: main - Liverpool v Man Utd score corrected, and the two own-goal flags (Josh)
The first beyondELO build stopped on one score that differs between the
sources. Josh's calls follow.
1. **The score is corrected to beyondELO's 1–2.** 2025/26 GW8 Liverpool v
   Man Utd (`25-26-prem-liverpool-vs-manchester-united`, 19 October 2025).
   - **Evidence:**
     - upstream's `matches.csv` and `fixtures.csv` both say 0–1;
     - upstream's own player stats give Liverpool one scorer and Man Utd two;
     - beyondELO says 1–2;
     - beyondELO agrees with our score on the other 379 2025/26 matches and
       all 100 of 2026/27.
   - **How:** brief data rule 16, a cited `score_corrections` entry applied
     by `clean.py`. The build fails if upstream's score stops being 0–1, so
     an upstream fix shows up and the entry is removed.
   - **Effect:**
     - **Elo:** ratings don't change. The update uses only the result and
       `max(1, |goal difference|)`, and both are the same at 0–1 and 1–2.
     - **Goals model and clean-sheet data:** one team-fixture in 760
       changes. Man Utd lose a false clean sheet, and `fixture_difficulty`
       shifts slightly at the next publish.
     - **Task 4:** its sign-off stands.
   - **Process:** the main session updated the brief (data rule 16) and the
     data contract before any code change.
2. **The two own-goal flags were checked: neither match had an own goal.**
   The main session's check had counted own goals by gameweek.
   - **Newcastle 1–2 Bournemouth** (2025/26 GW33): the flag was a false
     positive. Upstream's incidents give Tavernier (32'), Osula (68') and
     Truffert (85'). Bournemouth had a double gameweek 33, and Hill's own
     goal (68') came in their other match, Bournemouth 2–2 Leeds.
   - **Coventry 4–1 Newcastle** (2026/27 GW6): `shots.csv` gives Rudoni (6',
     penalty), Cherif (48'), Simms (81') and Mfuni (86') for Coventry, and
     Botman (70') for Newcastle. Mfuni has no `playermatchstats` row in this
     match, so `fact_player_match` misses his goal. The 2026-11-13 known
     gap "Players missing from a snapshot" now carries the recheck:
     8 player-gameweeks with no per-match row.
3. **QA (task 8) runs once the score correction is reviewed and committed.**

### 2026-11-17: data - score correction (data rule 16)
- **What changed:** `config/pipeline.yaml` has a `score_corrections` list with one entry,
  2025/26 GW8 Liverpool v Man Utd, upstream `[0, 1]` corrected to `[1, 2]`. The new
  `src/fpl/corrections.py` (`apply_score_corrections`, pure) is called from `build_season`
  in `clean.py` right after `build_fact_fixture`. It is in its own module to keep `clean.py`
  under 300 lines.
- **Evidence:** real rebuild, `data/processed/2025-2026/fact_fixture.parquet`, match
  `25-26-prem-liverpool-vs-manchester-united`: `home_goals, away_goals` now 1, 2 (was 0, 1);
  `finished` True, xG 2.75 / 1.34 unchanged. `reconciliation.csv` is identical to before the
  change (2025/26 fact_fixture 485 rows, fact_player_match 14589, fact_player_gw 29978).
- **Cleaning rule:** replaces `home_goals` and `away_goals` only. Fails with `CleanError` if a
  listed match is not in that season's fixtures exactly once, is not finished, or has an
  upstream score other than `upstream`; the last message says to remove or update the entry.
  Entries for another season are ignored. Each application is logged at INFO. Not counted in
  `reconciliation.csv` (no dropped rows, and an info line fits poorly), so log only.
- **Judgement call, as-of reads:** ingest blanks Premier League matches after `as_of_gw` to
  schedule only, so on an as-of read before GW8 the listed match is legitimately unfinished.
  Failing there would break every 2025/26 backtest read before GW8. So `build_season` passes
  `raw.as_of_gw`, and an unfinished listed match whose gameweek is after `as_of_gw` is left
  alone; at or before `as_of_gw` (and on full reads) unfinished still fails.
- **Effect downstream:** `fact_fixture` goals for that one match only. `fact_player_match` and
  `fact_player_gw` already gave 1-2. Elo unchanged; the goals model loses Man Utd's false
  clean sheet (see the entry above).
- **Fix round (code review F2-F6):**
  - F2: `tests/test_score_corrections_real.py` (real checkout: 1-2 at as-of 8 and 38, null
    and unfinished at 7, live read at 20) and `tests/test_score_corrections_config.py` (CI:
    entries well formed). With the `build_season` call switched off, the three correcting
    real-data tests fail. The `conftest.py` docstring now names what covers the correction.
  - F3: one-sided mismatches (0-2, 1-1, 1-3, 2-1) are tested.
  - F4/F5: the config test requires a configured season id and the Premier League tag in the
    `match_id`; the config comment says entries are Premier League only, because ingest leaves
    cup and European matches out of as-of reads.
  - F6: the mismatch message prints scores as "1-3".

### 2026-11-17: validator - harness keeps score-corrected matches
- **Problem:** with data rule 16, the cleaning step raises `CleanError` when upstream's score for a
  listed match isn't the entry's `upstream` score. The Elo check's control (`corrupt_up_to` in
  `after_as_of_case`) corrupts every Premier League score up to the as-of gameweek, so it changed
  2025/26 GW8 Liverpool v Man Utd and every case from 2025/26 as-of 8 on crashed
  `python -m backtest.elo_check` before a report was written. The planted leak at a 2025/26
  as-of 7 case, or a within-gameweek case at GW8, would have crashed the same way.
- **Change:** `backtest.perturb.Corruption` has a `keep` set of match ids that no corruption
  touches (`_rewrite` drops them from every selection, in `matches.csv` and `fixtures.csv`).
  `backtest.elo_check.corruption` builds the `Corruption` and fills `keep` from
  `config/pipeline.yaml` `score_corrections`. The real-data test no longer patches the loader's
  config to an empty `score_corrections`; it goes through the keep set.
- **Trade-off (accepted by the main session):** a listed match is never perturbed, so a leak of
  only that match's result would go unseen. Every other match is still corrupted. Today one
  match is listed.
- **Tests:** new `tests/test_elo_check_keep.py`. Under `corrupt_up_to`, `corrupt_after` and
  `corrupt_within` the listed match keeps its results in both files, every other match in the
  selection is still corrupted, the default keeps nothing, and `keep` comes from the config.
  The four keep tests failed first, and so did the real test without the workaround
  (`CleanError ... upstream now has 3-8`). `tests/test_elo_check*.py`: 203 passed. Ruff clean.
  `python -m backtest.elo_check` was not run (holdout).
- **Fix (Code Review's second-pass finding):** the keep test's `fixtures.csv` check now compares scores. Its copy of the synthetic season gives each `fixtures.csv` its `matches.csv` scores, and the helper fails if a file has no scores to compare. A mutant whose `fixtures.csv` ignores `keep` now fails 3 of the 6 keep tests. `tests/test_elo_check*.py`: 203 passed. Ruff clean.

### 2026-11-17: main - score correction and harness fix reviewed and committed; beyondELO table built
- **Committed as `de950d6`:** data rule 16 in `clean.py` (`src/fpl/corrections.py`) and the Elo check harness's keep set (`backtest/perturb.py`, `backtest/elo_check.py`), with their tests.
- **Code Review's first pass:** approve with findings.
  - **F1 (high):** the harness's control reads corrupt every score up to the as-of gameweek, so the next `python -m backtest.elo_check` run would have crashed at 2025/26 as-of 20 and 33.
  - **The fix, by the model-validator:** the harness never corrupts a listed match.
  - **The trade-off, accepted by the main session:** a leak of that one match's result alone would go unseen. Every other match is still corrupted.
  - **F2-F6, by the data-engineer:** a real-data loader test (1-2 at as-of 8, 38 and live 20, null at as-of 7), a CI check of the config entries' shape (Premier League only), one-sided mismatch tests, and a readable error message.
- **Second pass:** approve. With the correction switched off, 3 of the 4 real-data tests fail. One low finding is left: the keep test's `fixtures.csv` comparison checks no columns, because the synthetic file has none to compare. It goes to the model-validator after task 8.
- **Main session's check:** full suite 1036 passed, 99% coverage of `fpl`, and 100% of `corrections.py`. Lint is clean. The rebuilt 2025/26 `fact_fixture` has the match at 1-2, with row counts unchanged.
- **beyondELO table built** from the cache, with no further requests. 6 of the day's 100 were used in all.
  - **2025/26:** 380 of 380 matches matched in both directions.
  - **2026/27:** 100 of 100 matched; our 280 unplayed fixtures are counted, not failed.
  - **Ratings:** in every decided match both ratings moved the right way (276 and 73 matches).
  - **Promoted:** Burnley, Leeds and Sunderland in 2025/26; Coventry, Hull and Ipswich in 2026/27.
  - **Committed earlier:** `7cdc31a` (the pull) and `4114e73` (the string tiers and the 10 club aliases).
  - **Next:** settle the comparison method with `/grill-with-docs` before the model-validator builds the script.
- **Task 9 log:**
  - the 2026-11-17 08:00 UTC scheduled run never started (nothing by 17:08 UTC), so it counts as dropped;
  - the crons moved to 08:23 and 18:23 UTC at 13:46 UTC (`d4e34fa`), so 18:23 tonight is the first run at the new time.

### 2026-11-17: qa - phase 1 review (task 8)
Tested `546687e` on `main` (clean tree). QA didn't build any of this code. Overall verdict:
**pass with findings**, with one condition: `excel/` coverage must be measured with Excel
(item 3).
- **1. The workbook refreshes from GitHub on open: static part PASS; the live part is Josh's
  hand test.**
  - `excel/HAND_TEST.md` covers the 2026-11-15 pass marks: A (a stale copy opened without
    Refresh All shows the new `run_utc` and the `tbl_players` row count from `main`), C
    (offline: last good data, no error values), the wait of more than 5 minutes (the rules
    and A2), and B (the three first-open prompts).
  - Read as a zip, never opened in Excel: `xl/connections.xml` has 3 Power Query connections
    (`players`, `fixture_difficulty`, `meta`), each `refreshOnLoad="1"`. The 3 query tables
    are `refreshOnLoad="1"` and `backgroundRefresh="0"`. The embedded `Section1.m` has
    `BasePath` = `https://raw.githubusercontent.com/Joshc386/fpl-xp-model/main/outputs/`, read
    through `Web.Contents`.
- **2. Processed row counts reconcile with upstream: PASS.**
  - QA's own script (it doesn't import `fpl`) recomputed every table from the raw files of
    the local checkout at `ac8be9c`. That is the HEAD of `data/raw/upstream/repo` and the
    `upstream_commit` in both manifests (built 2026-11-17T15:06:07Z).
  - Every count matches `reconciliation.csv`, and in = kept + dropped holds for all 10
    tables.
    - 2025/26: `fact_fixture` 525 = 485 + 40 `no_kickoff_time` (all cup and European, 36
      of them played); `fact_player_match` 15,340 = 14,589 + 749 `match_has_no_kickoff_time`
      + 2 `club_not_in_match`; `fact_player_gw` 29,978; `dim_player` 841; `dim_team` 20.
    - 2026/27: `fact_fixture` 484, with 319 unfinished kept; `fact_player_match` 5,530 =
      5,517 + 7 `player_not_in_snapshot` + 6 `club_not_in_match`; `fact_player_gw` 6,596;
      `dim_player` 672 (GW10); `dim_team` 20.
  - The key sets equal QA's in all five tables, and so do `gw`, `finished`, `stats_complete`
    and `fact_player_match.team_id`. There are no duplicate keys.
  - Rechecked a second way: upstream line counts (`wc -l`) and the Parquet row metadata.
- **3. Tests pass, with at least 80% coverage on new code: PASS for `fpl` and `backtest`;
  OPEN for `excel/`.**
  - QA's run: 1,028 passed in 734 s, with no skips. QA left out
    `tests/test_workbook_excel.py` (8 tests), because those tests start Excel and QA may not.
    That accounts for the main session's 1,036. CI on `546687e`: 979 passed, 57 skipped.
  - Coverage (statements, missed, covered): `fpl` 2,035, 20, 99.0%; `backtest` 803, 25,
    96.9%; `excel` 1,025, 648, 36.8% without the Excel tests; all 3,863, 693, 82.1%, or
    80.2% without the beyondELO modules.
    - In `fpl`, every phase 1 module is at 97.6% or more, except `export.py` (88.0%).
    - In `backtest`, every module is at 91.0% or more.
    - The `excel/` builders and checks run only in the Excel tests.
  - **To close:** the main session runs `.venv/Scripts/python -m pytest --cov=excel
    --cov-report=term-missing tests/test_workbook_*.py` on Windows with Excel. Below 80%,
    item 3 fails for `excel/`.
  - **Standards** (51 files in `src/fpl/`, `backtest/` and `excel/*.py`):
    - no function of 50 lines or more;
    - no file of 300 lines or more (the largest is `backtest/elo_data.py`, 298);
    - imports in order (checked through the syntax tree, and ruff is clean);
    - one `print`, at `publish_decision.py:77`.
  - **CI doesn't cover:**
    - the 8 Excel tests (no Excel on Linux);
    - 49 real-data tests (no upstream checkout, accepted 2026-11-16);
    - coverage, which it doesn't measure.
- **4. Two consecutive scheduled runs:** main session (task 9).
- **5. The Elo component check:** signed off on 2026-11-15 (main, task 4). Not re-run.
- **Outputs on `main`** (`4ec7fba`, upstream `6df7a43`): 0 problems against the contract.
  - Columns and order are exact, all snake_case.
  - Prices are in £m to one decimal (3.9-15.8). Times are ISO 8601 with `Z`.
  - Nulls appear only in `news`, `chance_next` and the two MAEs.
  - `fixture_difficulty`: 100 rows, GW11-15. Each match has two mirrored rows, and `p_cs` is
    within 5.6e-17 of e^(−`lambda_against`).
  - `elo_ratings`: 960 rows (380 + 100 matches), zero-sum per match, continuous within each
    season.
- **Findings, most severe first:**
  1. **Medium, `excel/` (coverage 36.8% without Excel):** nothing automatic builds the
     workbook. The Excel tests skip in CI, and QA can't run them. A change to `wb_*.py` or
     `check_*.py` passes CI green, and the committed workbook can drift from its code
     unseen. **Fix:** the Excel coverage run above, and a full suite with Excel before any
     commit that touches `excel/`.
  2. **Low, `docs/known_gaps.md` ("Players missing from a snapshot"):** the entry is stale.
     It says the 7 `player_not_in_snapshot` rows are Premier League rows of Mfuni, J.Angulo
     and Tutierov. At `ac8be9c` they are 6 EFL Cup rows and 1 Champions League row, for 7
     players added to FPL later (Bentley, Zepa, Wright, Fredrick, Balcombe, Subuloye,
     Cissé). So the effect is lost cup minutes, not a low xG90. **Fix:** reword the entry.
  3. **Low, `excel/HAND_TEST.md` A5:** the row count can't show that `tbl_players`
     refreshed when the count doesn't change (672 at both publishes). With the logged gap
     that one failed query keeps its old rows, A5 could pass on stale players. **Fix:** add
     one value that changes each publish, such as a player's `selected_pct` against
     `players.csv` on GitHub.
  4. **Low, `src/fpl/export.py:131-134, 167-173`:** two paths have no test: the clean-up
     after a failed write, and `main()`, which `update.yml` calls on every run. A broken
     flag would show only as a failed scheduled run. That failure is safe, since nothing
     publishes, but the publish is lost. **Fix:** one test of `export.main([...])` with a
     pinned `--run-utc`.
  5. **Low, `src/fpl/publish_decision.py:77`:** `print` breaks the logging standard. It is
     the CLI's documented output, so either log it or record the exception.
  6. **Low, `docs/data_contract.md`:** the `fact_player_match` source notes don't list the
     `match_has_no_kickoff_time` reason (749 rows in 2025/26). **Fix:** add one line.
- **Notes, not findings:**
  - `main`'s `fixture_difficulty.csv` predates the score correction: its goals pool still
    has upstream's 0-1. `elo_ratings.csv` doesn't change, because the margin is 1 either
    way. The next publish brings both in line.
  - In `fpl` and `backtest`, 41 public functions are tested only through their callers.
    All but two are fully covered.
  - The tests use seeded RNGs and fake HTTP, and make no network calls.
  - `update.yml`'s rebase retry has still never run.

### 2026-11-17: main - task 8 QA part: pass with findings
- **QA's verdict:** pass with findings, on `546687e`.
  - **Item 1, refresh on open:** the static checks pass. All three connections and query tables refresh on load, from the raw GitHub URL on `main`, and `HAND_TEST.md` covers every 2026-11-15 pass mark. The live test is Josh's hand test.
  - **Item 2, row counts:** pass, by QA's own script at upstream `ac8be9c`. Rows in = kept + dropped holds for all 10 tables, and every drop has a reason.
  - **Item 3, tests and coverage:** pass. `fpl` 99.0% and `backtest` 96.9%.
  - **Item 4, the scheduled runs:** the main session's (task 9).
  - **Item 5, the Elo check:** signed off on 2026-11-15.
- **QA's open condition, closed by the main session:**
  - **Why:** QA wasn't allowed to start Excel, so it measured `excel/` at 36.8% without the 8 Excel tests.
  - **The main session's run with Excel:** `pytest --cov=excel tests/test_workbook_*.py` gave 49 passed and `excel/` at 91% (`build_workbook.py` 64%, mostly the replace path; the rest 89-100%).
  - **The 1,028 against 1,036 gap:** exactly the 8 Excel tests QA left out.
- **Local checkout:** QA's reconciliation, the main session's checks and today's rebuilt tables all describe upstream `ac8be9c` (2026-11-13), the local checkout's HEAD. Upstream itself is at `32ac4d7`, and the workflow checks out the newest commit on every run.
- **Fixed now by the main session (docs):**
  - `docs/known_gaps.md` "Players missing from a snapshot" was wrong. Its 7 dropped rows are cup and Champions League rows of other players (ids 623, 626, 660, 661, 667, 670 and 672), checked with QA's script. Mfuni, J.Angulo and Tutierov's missing per-match rows are now their own entry, "Players with no per-match rows".
  - `docs/data_contract.md` now lists the `match_has_no_kickoff_time` drop reason (749 rows in 2025/26).
- **Open, for Josh:**
  - the medium finding: nothing automatic builds the workbook, so an `excel/` change can pass CI unbuilt;
  - three low findings: `HAND_TEST.md` step A5, the untested `export.main`, and the `print` in `publish_decision.py`;
  - the model-validator's low finding on the keep test.

### 2026-11-17: main - QA's remaining findings (Josh)
Josh took all three recommendations.
1. **Three small fixes run now, in parallel:**
   - `HAND_TEST.md` step A5 also checks a value that changes every publish (excel-builder);
   - a test of `export.main`, the command `update.yml` runs (data-engineer);
   - the keep test's `fixtures.csv` comparison must compare at least one column (model-validator).

   They touch only tests and the checklist, so the main session reviews them itself instead of a Code Review pass.
2. **The `print` at `src/fpl/publish_decision.py:77` is an accepted exception** to the logging rule. It is the command's documented output (`publish=true` or `publish=false`), which `update.yml` reads.
3. **New `CLAUDE.md` convention:** run the full suite on Windows with Excel before committing anything under `excel/`, because CI skips the 8 Excel tests. This answers QA's medium finding.

### 2026-11-17: excel - hand test step A5 checks a changing value
- **Gap:** step A5 checked only the "Showing N of N players" count, which was 672 at both publishes, so it passed on stale player data (known gap: one failed query can keep old rows).
- **Chosen value:** Haaland's (`player_id` 411) `net_transfers_gw`, read on GitHub's CSV view and in Player Database ("Net transfers this GW"). It was -27,513 in `outputs/players.csv` at `4ec7fba`.
- **Why not `selected_pct`:** it is rounded to 0.1 and Haaland's was 78.8 at both publishes (`4f8fa36` and `4ec7fba`), so it can't tell old from new. `net_transfers_gw` moved from -27,307 to -27,513 between them.
- **Edits:** step 3 notes the value; step 4 (Protected View) checks it differs from the saved copy, with a fallback (wait, or use another player such as Salah); step 5 checks it equals the step 3 value. Markdown only.

### 2026-11-17: data - export.main tests
- **Added** `tests/test_export_main.py` (4 tests, tests only; no source file changed):
  - `main` with `--out-dir` and a pinned `--run-utc` writes the four outputs, and `meta.csv`'s `run_utc` is `2026-09-03T20:00:00Z`. `run_export` runs for real; only its reads (config, deadlines, upstream commit, `load_history`) are stubbed with the synthetic season, so it needs no `data/` and no Excel.
  - Both flags reach `run_export` (a pinned time with an offset, and no `--run-utc` giving `None`).
  - A missing `--out-dir` exits with code 2 and names the flag.
  - A write that fails part-way (the third `to_csv`) leaves no `.tmp` files and no partial outputs, and an existing `players.csv` is untouched.
- **Evidence the tests catch faults** (each fault applied temporarily, then `export.py` restored byte for byte): `run_export(args.out_dir, None)` fails tests 1 and 2; `out_dir / "sub"` fails tests 1 and 2; `required=False` fails the argparse test; removing the `unlink` calls in the clean-up fails the clean-up test; `--run-utc` parsed as a string fails the flag-wiring test.
- **Effect:** none on tables or outputs. `export.py` coverage 88% to 99% (only the `if __name__ == "__main__"` line is left).

### 2026-11-17: main - QA's three small fixes reviewed and committed
- **Reviewed by the main session**, as Josh decided, not by a Code Review pass:
  - **`HAND_TEST.md` A3-A5:** the steps note and check Haaland's (`player_id` 411) `net_transfers_gw`. It was -27,307 at `4f8fa36` and -27,513 at `4ec7fba`, while his `selected_pct` was 78.8 at both.
  - **`tests/test_export_main.py`:** 4 tests, each seen catching a deliberate fault. `export.py` goes from 88% to 99%.
  - **The keep test:** it now compares scores in `fixtures.csv`, and a mutant that ignores `keep` there fails 3 of the 6 keep tests.
- **Full suite with Excel:** 1040 passed, 99% coverage of `fpl`. Lint is clean.

### 2026-11-17: main - outside-source Elo check method settled (Josh, /grill-with-docs)
Josh took the main session's recommendation on all eight questions. The terms are in `CONTEXT.md`: **beyondELO rating**, **Outside-source Elo check**, **Predictive log-loss**, **Ranking agreement**, **Poor Elo rating**, **Promoted club** and **Holdout look**.
1. **Predictive log-loss decides the verdict.** Ranking agreement is a diagnostic with no pass mark. beyondELO isn't the truth: when the rankings disagree, only results can say which is wrong.
2. **"Predictive" means the match result** (home, draw or away).
   - Each source gets its own ordered logistic fit of the result on the before-match gap (home minus away). Three parameters absorb scale, home advantage and the draw rate.
   - The no-skill baseline is the same fit with no gap.
   - **Rejected:** Poisson goals through our Elo goals model. Its priors were tuned on our own gaps, which would favour our ratings.
3. **Windows:** each source is fitted once on 2025/26 GW1-26 (261 matches: GW26 is a double gameweek with 11; corrected on 2026-11-18 from 260, an arithmetic slip). Both are scored on 2025/26 GW27-38 (119) and 2026/27 from GW3 (80 to date), reported per window and pooled. The verdict uses the pooled figure.
   - **Rejected:** a walk-forward refit, which means about 20 refits for little gain with 3 parameters.
4. **A poor Elo rating** means either of these, on the pooled windows:
   - the mean per-match difference (ours minus beyondELO's) is above zero by more than two standard errors (sd ÷ √n), the same floor the Elo component check adopted on 2026-11-14;
   - our log-loss isn't below the no-skill baseline's.
   - **Trade-off:** with 199 matches, only a clear deficit fails. That suits a check for broken ratings.
5. **Ranking agreement:** per-gameweek Spearman over the team-kickoffs, paired as in the Elo component check. It's reported per gameweek, with each window's median and minimum and its five biggest rank disagreements at the last gameweek.
6. **Promoted clubs:** the verdict uses every scored match, and figures without matches involving a promoted club are reported alongside. Why: each system's promoted-club handling is part of the rating. Ours starts from ClubElo, which rates the Championship; beyondELO's starts from the club's last Premier League spell.
7. **Holdout:**
   - the 2026/27 window is the third look, and runs once, now, on GW3-10, logged before the run;
   - it runs again only after a poor verdict and a rebuild tuned on 2025/26 only, as the fourth look with Josh's approval;
   - the 2026/27 figures go to Josh and the main session only, and builders get the verdict and the 2025/26 figures.
8. **Build and report:**
   - **Builder:** the model-validator builds `backtest/beyondelo_check.py` (`python -m backtest.beyondelo_check`) test first, with a known-output regression test.
   - **Inputs:** `outputs/elo_ratings.csv`, `load_beyondelo` and results through `load_as_of`.
   - **Report:** `backtest/reports/{date}-beyondelo.md`, committed, with the credit "beyondELO (https://beyondelo.com)" (CC BY 4.0).
   - **Process:** Code Review reviews the script, Josh approves the run, and the analysis-verifier recomputes the headline numbers before they reach him.
   - Builders' task messages tell them not to open `*-beyondelo.md` reports.
- **Updated:** `CONTEXT.md` (seven terms and one flagged ambiguity, "Elo check"), and brief sections 2 (the gate) and 7 (the outside-source paragraph).
- **Builder confirmed (Josh):** Josh asked whether the expected-points-modeller should build the check instead. It stays with the model-validator, for three reasons: the modeller's agent file rules out backtest code and accuracy verdicts; the agent that did the work doesn't judge it; and the **Holdout look** rule keeps 2026/27 figures from whoever builds the Elo.

### 2026-11-17: validator - outside-source Elo check build
- **What:** `python -m backtest.beyondelo_check` (brief section 7, `CONTEXT.md` **Outside-source Elo check**), built test first. Not run with the configured windows: its 2026/27 window is the third holdout look, which the main session runs after Code Review and Josh's approval.
  - `backtest/beyondelo_fit.py`: `fit_ordered` (the ordered logistic fit), `match_nll` and `poor_elo_verdict`.
  - `backtest/beyondelo_data.py`: `window_table` (one row per match with both gaps and the result, plus the partner counts), `ranking_by_gameweek` and `rank_disagreements`.
  - `backtest/beyondelo_report.py`: `render`.
  - `backtest/beyondelo_check.py`: `read_inputs`, `run_check`, `run` and `main`.
  - `backtest/config.yaml`: a new `beyondelo_check` section holding the windows, file paths, fit tolerance, iteration cap, SE multiple, rounding and top-five count.
- **Fit method:** Newton-Raphson in numpy, with an analytic gradient and Hessian, so scipy isn't needed.
  - It starts from the baseline's exact fit (cut-points at the logits of the cumulative away and draw shares, slope 0) and halves a step until the log-likelihood doesn't fall. The ordered logit's log-likelihood is concave in (cut-points, slope).
  - **Convergence:** it stops when the Newton decrement's half square, the log-likelihood a full step is predicted to gain, is at most `fit_tolerance` = 1e-12 nats in total. It fails after `max_iterations` = 50. The real 2025/26 fits took 4 iterations.
  - The decrement is invariant to the gap's scale, so an affine copy of our ratings gets the same fit and the same log-losses, to 1e-12 in the tests.
- **No finite fit stops the run before Newton-Raphson.** It stops if an outcome never occurs in the fit window, or if the gaps, grouped by outcome, are sorted with ties allowed in either direction. In that case the slope can grow without bound; with all three outcomes present, this is exactly when no finite, unique maximum exists.
  - Why a pre-check: with the pre-check removed, Newton-Raphson silently "converged" on separated test data, because the likelihood flattens towards its supremum. A test showed it.
- **Verdict:**
  - SE is the per-match differences' sd (ddof 1) ÷ √n.
  - Condition 1 fires when the mean is above `se_multiple` × SE. Condition 2 fires when our pooled log-loss is at or above the baseline's.
  - Both comparisons are made after rounding to `compare_decimals` = 9, as in the Elo component check. So an exact tie on the two-SE line is not poor, sd = 0 with a zero mean is not poor, and sd = 0 with a positive mean is poor. Without the rounding, the affine-copy case's 1e-15 noise could fire condition 1.
  - With fewer than 2 matches, the verdict stops.
- **Partners:**
  - A match is in a window if any of the three sources places it there by its own `season` and `gw`. "Our rating" and "beyondELO rating" each mean exactly two rated rows, one per club of the fixture. A finished result means `finished` with both scores.
  - Any match lacking a partner, in the fit window or a scored window, stops the run with the counts per window and the match ids. No report is written.
  - Results are read through `load_as_of(season, last window gameweek, "backtest")`, so later results never reach the check. Our and beyondELO's rows are also cut to the window by `gw`, so data past 2026/27 GW10 leaves the GW3-10 window unchanged.
- **Promoted clubs:** the figures without promoted-club matches reuse the same fits, fitted on every fit-window match. Only the scoring drops matches with `promoted` true for either club. A club is flagged only in the season beyondELO flags it.
- **Read path:**
  - `elo_ratings.csv` holds both seasons in one file, so `read_inputs` reads it whole and drops the seasons no window names straight away. A 2025/26-only run computes nothing from 2026/27 rows.
  - `read_inputs` looks `fpl.features.load_as_of` up at each call, rather than holding it as a default argument. Holding it made the Elo check's synthetic guard (`tests/elo_check_synth.py`, `stray_callers`) fail 61 existing tests.
- **Provenance:** `run_info`, plus the sha256 of `outputs/elo_ratings.csv` and of each parquet read, and `outputs/meta.csv`'s `upstream_commit`, labelled as the publish the ratings came from. The report's `upstream_commit` is the local checkout's, from which the results are read. Today these differ (`6df7a43` against `ac8be9c`); the report shows both.
- **Tests:** 70 in 9 new test files (`tests/test_beyondelo_check_*.py`), with two helpers (`beyondelo_check_frames.py`, `beyondelo_check_synth.py`). Among them:
  - the known-output regression test, a seeded synthetic world with parameters and log-losses to 1e-9;
  - a finite-difference check that the fit is a maximum, written independently of the module;
  - the real 2025/26 test: fit GW1-26 and score GW27-38, with its report in `tmp_path`. Its loaders fail if any season but 2025/26 is asked for.
  - Mutants checked: removing the separation pre-check, freezing the slope, removing the rounding and using `>=` for `>`. Each fails at least one test.
- **2025/26 real-data figures (development data, not the holdout):**
  - Counts: fit 261, scored GW27-38 119, all complete.
  - Log-loss on GW27-38, in nats per match: ours 1.0398, beyondELO 1.0315, baseline 1.0830.
  - Mean difference 0.0083, against a two-SE threshold of 0.0184 (sd 0.1004, n 119).
  - Without promoted-club matches (85): 1.0323, 1.0289, 1.0662.
  - Ranking agreement: median 0.963, minimum 0.947.
  - These are not the check's verdict, which pools in the 2026/27 window.

### 2026-11-18: main - outside-source Elo check: Code Review approved with findings (Josh)
- **Code Review** (roster role) reviewed the uncommitted build: approve with findings, none of them a must-fix before the holdout run.
  - It re-derived the gap sign, the outcome coding and the fit's gradient and Hessian, and found them right.
  - The separation pre-check is complete: of 20,000 random small datasets, it rejected none that could be fitted.
  - The verdict arithmetic and the GW3-10 pinning are right.
  - It broke the code 15 ways; the tests caught all but one (finding 2).
- **Main-session check:** an independent fit (Nelder-Mead, not Newton) reproduced the validator's 2025/26 counts, log-losses and mean difference to 4 decimals.
  - A local rebuild of `elo_ratings.csv` from upstream `ac8be9c` equals the published file (from `6df7a43`) in all 960 rows. So the validator's commit-mismatch flag doesn't affect the check, and the checkout needn't be pulled before the holdout run.
- **Findings:**
  1. The method entry said 260 fit-window matches; 261 is right. Fixed in point 3 (main session).
  2. The line search is never tested: neither the step-halving nor its "no improvement" `FitError`. Its cap of 60 halvings is hardcoded. To the validator.
  3. `python -m backtest.beyondelo_check` was missing from CLAUDE.md's Commands. Added, with the holdout warning (main session).
  4. `main()` catches only `CheckError` and `FitError`, so three cases show a traceback instead of a plain message: a missing parquet, a promoted club missing from `dim_team`, and n < 2 in the verdict. None of them leaks 2026/27 figures. To the validator.
  5. `meta.csv` is read without `dtype=str`. To the validator.
  6. Style: the report's `inp: object` annotation, `.name` attribute access on a DataFrame, no docstring on `_line_search`, test helpers without type hints, and `print()` in the real-data test. To the validator.
- **Josh's decision:** commit the reviewed build now, and send findings 2 and 4-6 to the validator before the holdout run, so the run uses the final code. The fix's diff gets a re-review.
- **Not added:** the validator's optional guard against a scored window overlapping the fit window. It was left out on the main session's recommendation, because the windows are fixed in reviewed config.
- **Full suite:** 1110 pass, 99% coverage of `fpl`, ruff clean.

### 2026-11-18: main - task 9: second counted run, done when met
- **The run:** the 2026-11-17 18:23 UTC scheduled run started at 01:02 UTC on 2026-11-18, 6 hours 39 minutes late, and succeeded in 38 seconds (run 44212656708).
  - It published upstream `648ec21` as `60b04a9`, changing `players.csv`, `fixture_difficulty.csv` and `meta.csv`.
  - `elo_ratings.csv` didn't change, as expected after the Liverpool v Man Utd score correction (same result and margin).
- **Counted runs:** 2026-11-16 18:00, which started 2026-11-17 01:43 and published upstream `6df7a43` as `4ec7fba`, and this one. The only scheduled run between them, 2026-11-17 08:00, was dropped, and a drop doesn't break "consecutive" (2026-11-17, point 7).
- **Result:** task 9's done-when is met: two consecutive scheduled runs are green, each publishing a new upstream commit. Phase 1 sign-off still waits on Josh's hand test (task 8), which can run now.
- **Freshness:** the counted runs started 7 hours 43 minutes and 6 hours 39 minutes late. Still to raise as a product problem once there are more runs.

### 2026-11-18: validator - outside-source Elo check review fixes
- **Finding 2 (line search untested):** the halving cap is `beyondelo_check.max_halvings` (60) in `backtest/config.yaml`, passed through `fit_ordered` to `_line_search`, which now has a docstring. New tests call `_line_search` directly: one where a 40-times Newton step overshoots and is halved to the first step that doesn't fall, and one where a downhill step stops with "no improvement after 5 halvings". A third checks that the configured cap reaches the line search. The reviewer's `if True:` mutant now fails 2 tests. On real 2025/26 data all 8 Newton steps were taken in full, so the figures don't move.
- **Finding 4 (tracebacks from `main`):** each case now raises `CheckError` where it starts, so `main` logs a plain message, returns 1 and writes no report. The cases are a missing `ext_beyondelo` parquet (`read_inputs` wraps `load_beyondelo`'s `FileNotFoundError`; a missing `elo_ratings.csv` or `meta.csv` does the same), a promoted club with no `dim_team` name (`_promoted`), and scored windows holding fewer than 2 matches (`run_check`, before the verdict). There is one unit test each, and one `main` test parametrised over all of them and the missing-partner case.
- **Finding 5 (`meta.csv` dtype):** read with `dtype=str, keep_default_na=False`, as `fpl.publish_decision` does. An empty `upstream_commit` reads as `""` and shows as "(empty)" in the provenance, never "nan". Two tests.
- **Finding 6 (style):** `beyondelo_report` types `inp` as `Inputs` (imported under `TYPE_CHECKING`); `read_inputs` uses `["name"]`; the test helpers, the `spoil` parameter and the `checked` and `report` fixture arguments have type hints; the real-data test logs its figures instead of printing them.
- **2025/26 figures unchanged:** checked to full precision. On GW27-38, ours is 1.039763, beyondELO's 1.031509 and the baseline 1.082970, with a mean difference of 0.008254 against a two-SE threshold of 0.018415. The fits are identical.

### 2026-11-18: main - outside-source Elo check review fixes: re-review approved
- **Code Review re-review:** approve. All four fixes do what the entry above says, and nothing else changed behaviour. Re-run against the 2025/26-only real test, the 3d1fe8c modules and the fixed ones give bit-identical verdict figures, fits and ranking median and minimum.
- **Full suite:** 1123 pass, 99% coverage of `fpl`, ruff clean.
- **Three optional points, open for Josh:**
  1. Two stops fire after the scored windows' log-losses are computed: fewer than 2 scored matches, and a promoted club with no `dim_team` name. They show and write nothing, so nothing leaks. Neither can fire on the real data: the six promoted clubs all have names, and 199 matches are scored.
  2. The exact halving count isn't tested: `range(max_halvings)` for `range(max_halvings + 1)` survives.
  3. The fewer-than-2 stop is tested with 0 matches only, so `< 1` for `< 2` survives.

### 2026-11-18: main - outside-source Elo check: third holdout look approved (Josh)
- **Approved by Josh** before the run: the outside-source Elo check (`python -m backtest.beyondelo_check`) scores 2026/27 GW3-10, 80 matches. This is the third holdout look (brief section 7, `CONTEXT.md` **Holdout look**).
- **Code:** `980f1a3`. Ratings come from `outputs/elo_ratings.csv`, published from upstream `648ec21` and identical to a rebuild from `ac8be9c`. Results come from the local upstream checkout at `ac8be9c`, and beyondELO's ratings from `ext_beyondelo` as pulled on 2026-11-17.
- **The three optional re-review points** go to `docs/known_gaps.md` and aren't fixed first (Josh). Neither late stop can fire on this data.
- **Who sees the figures:** the 2026/27 and pooled figures go in the report and to Josh only. This log gets the verdict and the 2025/26 figures, because builders read it. The report is `backtest/reports/2026-11-18-beyondelo.md`, which builders don't open.
- **No re-run:** it runs again only after a **Poor Elo rating** and a rebuild tuned on 2025/26 only, as a fourth look with Josh's approval.

### 2026-11-18: main - outside-source Elo check: third holdout look run, not a poor Elo rating
- **The run:** 08:58 UTC on `11f1a6c` (check code `980f1a3`), clean tree. The report is `backtest/reports/2026-11-18-beyondelo.md`, which builders don't open. All 261 fit-window and 199 scored matches were complete. This was the third holdout look.
- **The check's verdict:** not a **Poor Elo rating**. Neither condition fires on the pooled scored matches.
- **2025/26 GW27-38 (development data):** log-loss is 1.0398 for ours, 1.0315 for beyondELO's and 1.0830 for the baseline, in nats per match, over 119 matches. The 2026/27 and pooled figures are in the report and went to Josh only.
- **Verified:** the analysis-verifier shares no code with `backtest/`. It recomputed every count, log-loss, verdict figure, fit, ranking figure and promoted-club list, and all hold to the report's precision.
  - Its own checks: the joins are one to one, home and away agree with beyondELO's flag in all 480 matches, and the windows are exact. The fit window's last kickoff (2026-02-18) comes before the first scored one (2026-02-21). Every `elo_before` equals the club's previous `elo_after`.
- **How to read it:** "not poor" means no evidence that ours is worse. It doesn't mean the two ratings are level. Condition 1 fails only a clear deficit, as accepted in the method's point 4.
- **Not like-for-like on inputs:** beyondELO's rating moves between Premier League matches in 147 of 920 cases, 102 of them around a European or EFL Cup match. So it uses results ours doesn't. The check is a fair test of predictive quality, but this favours beyondELO.
- **Minor:** the report's "five biggest rank disagreements" list cuts ties alphabetically. Added to the check's entry in `docs/known_gaps.md`.
- **Next:** Josh's verdict. If he accepts "not poor", the Elo isn't rebuilt and the 2026/27 window isn't run again. Phase 2's Dixon-Coles work then isn't blocked by the Elo.

### 2026-11-18: main - outside-source Elo check: Josh's verdict, not a poor Elo rating (Josh)
- **Verdict (Josh):** accepted, not a poor Elo rating. In his words, the differences are very small. The Elo rating is important, but not as vital as the main session had treated it.
- **So:** the Elo component isn't rebuilt, and the check's 2026/27 window isn't run again. Phase 2's Dixon-Coles work is no longer gated on the Elo.
- **Proportion:** weigh further Elo work against its effect on xP, not as a gate in its own right. The check's known gap (`docs/known_gaps.md`) waits for the check's next change.

### 2026-11-18: main - phase 2 plan settled (Josh, /grill-with-docs)
Josh took the main session's recommendation on points 1, 2, 5 and 6. On points 3 and 4 he added the outside checks, and on point 7 he chose the harder, better-quality option. The plan is `docs/plans/phase-2.md`, and Josh approved it and pushes to `main` after each reviewed task.
1. **Only the end-to-end gate decides.** No component has a pass mark of its own. The model-validator reports diagnostics on the development window as each component lands, and the holdout is scored once, at sign-off.
2. **Minutes v1 stays lean:** recent starts and minutes, then the availability override. `news`, days since the last match, and cup and European minutes wait for v2 (brief 6.1 updated).
3. **2024/25 is loaded as 2025/26's prior season,** so the early-season blend's k can be tuned on the development window.
4. **The 2024/25 load is checked three ways:**
   - scores against beyondELO and upstream's player goals;
   - internal rules on the player rows;
   - season totals against FPL's API, pulled only after Josh approves the request count and terms.
5. **Team goals v1 is the Elo goals model plus `lambda_pen`.** Dixon-Coles moves to v2, built only if the first full backtest points at team goals (brief 6.2 updated).
6. **The holdout gets a rebuilt pre-deadline view.** Player fields come from upstream's last commit before each 2026/27 deadline. Why: in 4 of the first 10 gameweeks the snapshot landed after the deadline, when FPL's "next round" fields had moved on (brief section 7 updated).
7. **Attack measures on-pitch team xG from shot data,** with penalties taken from each shot's situation. 2024/25 has no shots, so it uses match xG × minutes ÷ 90 (brief 6.3 updated).
- **Main-session choices** (in the plan, unchallenged):
  - the xA-to-FPL-assists mapping pools two seasons only if the assist rules match;
  - the modeller builds one component at a time;
  - phase 2 publishes nothing new.
- **`CONTEXT.md`:** adds **Development window**. The "Elo check" ambiguity now notes that the gate on Dixon-Coles has passed.
- **Starts:** after phase 1 is signed off, which waits on Josh's hand test.
