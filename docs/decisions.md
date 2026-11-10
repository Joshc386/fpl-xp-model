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
