# FPL Expected Points Model — Project Brief

## Purpose and success criteria

The model predicts expected points (xP) for every Premier League player for the next gameweek and the next five. It ranks players on value, recommends transfers and an optimal squad, and shows all of it in an Excel workbook that refreshes itself from GitHub.

Josh is the first user; anyone given the workbook is the second. Users need Excel desktop for Windows (Microsoft 365 or Excel 2021+) and nothing else: no Python, no Git. Excel for Mac and Excel for the web can't refresh from a web source (section 10).

| Area | Success criterion | Checked by |
| --- | --- | --- |
| Model accuracy | xP beats FPL's own `ep_next` on mean absolute error across the walk-forward backtest | Validator report |
| Calibration | Mean actual points within ±0.3 of mean predicted in every xP bin with ≥200 player-gameweeks | Calibration table in the report |
| Freshness | Each run (08:00 and 18:00 UTC) publishes the newest upstream commit that existed when it started | `meta.upstream_commit` vs upstream's latest commit at run start |
| Reliability | Outputs that fail validation are never published | GitHub Actions run history |
| Optimiser | Returns a legal 15-player squad in under 60 seconds | Unit tests and run log |
| Usability | A new user finds the best-value midfielder under £7.0m for the next 5 GWs in under a minute | Hand test before sign-off |

The thresholds are starting targets. Revisit them after the first backtest.

## Scope

Version 1 delivers an accurate, validated xP model and the six requested sheets. Anything that is a separate modelling problem waits.

**In v1**

- Ingest the 2026/27 season, plus previous seasons for backtesting and priors
- Per-player xP for each of the next 5 gameweeks, with a component breakdown
- One workbook-wide horizon of 1–5 gameweeks, chosen by the user, that every sheet uses at once (`CONTEXT.md`)
- A value-above-replacement metric (section 8)
- Fixture difficulty from the model's own team goal expectations
- An optimal squad from scratch at a range of budgets
- A transfer planner for a squad the user types in
- A captain shortlist (highest next-GW xP among likely starters)
- Six sheets: Dashboard, Player Database, Fixture Analysis, Player Projections, Transfer Planner, Squad Optimisation
- Automated refresh twice a day

**Later (v1.5 and v2)**

- Transfer optimisation for a personal squad loaded from config (v1.5)
- Price-change prediction; v1 shows net transfers and this-GW price change only
- Chip planning: wildcard, free hit, bench boost and triple captain timing
- Points distributions and haul probabilities by simulation
- Bonus from a BPS simulation
- Squad import by FPL team ID
- Team news beyond the FPL status, news and chance-of-playing fields
- Effective ownership and mini-league views

## Architecture

Python does all the computation and Excel only displays it. A scheduled GitHub Action pulls the upstream data, runs the model and optimiser, and commits output CSVs. The workbook reads those CSVs through Power Query.

&#91;embedded content: pipeline architecture · 6 steps, 2 validation checks\]

Either validation check can stop a run. When one does, nothing is published and the workbook keeps the last good data.

**Why not Excel only**

- Excel's built-in Solver is capped at 200 decision variables. The player pool is several times that, so squad optimisation can't run in the workbook.
- The xP model needs Poisson calculations, shrinkage and walk-forward backtests. In formulas these are slow to build, impossible to unit test and hard to version.
- Python code lives in Git with tests. A workbook full of logic does not.

**Delivery to users**

- The output repo is public, so Power Query reads the raw CSV URLs without authentication.
- Each query has "Refresh data when opening the file" turned on, so updates appear when the workbook opens.
- The workbook holds no model logic beyond the Transfer Planner's what-if formulas.
- If the pipeline breaks, the workbook still opens with the last good data, and the Dashboard shows how old it is.
- openpyxl cannot create Power Query connections. The workbook is built on Windows through Excel's object model (xlwings or COM, using `Workbook.Queries.Add`), or the M code is pasted into the Power Query editor by hand.

**Tech stack**

| Layer | Choice |
| --- | --- |
| Language | Python 3.13 |
| Data | pandas, numpy |
| Statistics | scipy (Poisson), statsmodels (regressions) |
| Optimisation | PuLP with the CBC solver |
| Tests | pytest |
| Scheduling | GitHub Actions cron |
| Workbook | Power Query, Excel Tables, XLOOKUP, FILTER, SORTBY, LET, slicers |

## Data source

All data comes from [olbauday/FPL-Core-Insights](https://github.com/olbauday/FPL-Core-Insights). It is CSV only, with the 2026/27 season under `data/2026-2027/`. Upstream commits about three times a day at drifting times. In November 2026 the windows were roughly 02:00–04:00, 13:00–16:00 and 19:00–22:00 UTC.

**Layout**

- **Master files** at `data/{season}/`: `players.csv`, `teams.csv`, `playerstats.csv`, `gameweek_summaries.csv`. These hold the current state.
- **By Gameweek** at `data/{season}/By Gameweek/GW{x}/`: a point-in-time snapshot at the end of each gameweek. It holds `fixtures`, `matches`, `players`, `teams`, `playerstats` (cumulative), `playermatchstats` and `player_gameweek_stats`.
- **By Tournament** at `data/{season}/By Tournament/{tournament}/GW{x}/`: the same files filtered to one competition.

**Files used**

| File | Grain | Used for |
| --- | --- | --- |
| `players.csv` | Player | IDs, names, position, `team_code` |
| `teams.csv` | Team | Team IDs and codes. Its `elo` and `strength` are null for 2026/27 (rule 12) |
| `playerstats.csv` (master) | Player × gameweek | Price, status, news, chance of playing, ownership, set-piece order, `ep_next`, transfers. The latest `gw` row per player is the current state |
| `GW{x}/player_gameweek_stats.csv` | Player × gameweek | Points, minutes, starts, bonus, price at deadline, FPL's defensive contribution counts. This is the model target |
| `GW{x}/playermatchstats.csv` | Player × match | xG, xA, tackles, interceptions, clearances, blocks, recoveries, saves, `minutes_played` |
| `GW{x}/matches.csv` | Match | Team xG, non-penalty xG, scores, Elo at kickoff (null from 2026/27 GW3), processing flags |
| `GW{x}/fixtures.csv` | Match | Gameweek x's fixtures only, with home and away team codes. The next 5 GWs come from folders `GW{next}` to `GW{next+4}` |
| `By Tournament/Premier League/` | Various | Premier League-only filter |

**Data rules**

1. Take per-gameweek stats from `player_gameweek_stats`. Never difference the cumulative `playerstats` yourself.
2. Take per-match minutes from `minutes_played`. `start_min` and `finish_min` are best-effort; deriving minutes from them credits unused subs with a full match. For anything tied to FPL's minute thresholds (appearance points, 60 minutes, `p_60`), use `player_gameweek_stats.minutes`. In 2026/27, `minutes_played` reads 1 minute high for most substituted starters, which wrongly puts 21 of 2,679 player-gameweeks (GW1–9) over the 60-minute line. The two agree exactly in 2025/26.
3. Model points on Premier League matches only. Keep cup and European minutes as rotation and fatigue features.
4. Gameweek 0 is pre-season friendlies. Exclude it from training; it may serve as a minutes prior before GW3.
5. Joins: `players.team_code` → `teams.code`; `fixtures` and `matches` `home_team`/`away_team` → `teams.code`; `playerstats.id` → `players.player_id`; `playermatchstats.match_id` → `matches.match_id`. The match team columns hold team codes, not `teams.id`, in both 2025/26 and 2026/27. Eleven values are valid as both, so a join on `teams.id` mislabels clubs silently. A player's club in a match comes from that gameweek's snapshot `players.team_code`.
6. `player_id` and `teams.id` are season-specific (verified: only 5 of 482 players shared by 2025/26 and 2026/27 keep their id). Join across seasons on `player_code` and `teams.code`, the stable FPL codes.
7. Upstream `now_cost` is already in £m to one decimal (15.8), not tenths. Convert it once, in the cleaning step, to integer tenths with round(`now_cost` × 10). The `cost_change_*` columns are already integer tenths.
8. The snapshot fields in `player_gameweek_stats` (`now_cost`, `selected_by_percent`, `form`) reflect that gameweek's deadline. They are known at prediction time; that gameweek's performance stats are not.
9. Use only matches where `stats_processed` and `player_stats_processed` are both true.
10. Coventry, Hull and Ipswich have no 2026/27 Premier League history at the start. Use Elo and last-season priors for them. Their Elo seeds come from upstream's GW1–2 match rows (rule 12).
11. Credit the upstream repo with a link on the workbook's README sheet, as its author asks.
12. **Elo is computed in-house.** Upstream takes Elo from ClubElo, whose API returned HTTP 502 on 2026-11-08 and 09. The 2026/27 `teams.elo` column is null and match Elo stops after GW2.
    - **Data-engineer:** passes upstream's ClubElo values through unchanged as `upstream_elo`, so every season is available.
    - **Elo component (expected-points-modeller):** computes the model's own Elo ratings over processed Premier League results. Each club is seeded from its last upstream Elo value: GW1–2 match rows for 19 clubs, and 2025/26 for Arsenal. The method is standard Elo with a home advantage and a goal-margin factor; its settings live in `config/model.yaml` and are calibrated by replaying 2025/26, where upstream Elo is complete.
    - **Rejected source:** elofootball.com, which has no API or export, no stated terms of use and no named operator.
13. **Previous seasons:** 2025/26 is complete, with 38 gameweeks and the same columns as 2026/27; 2026/27 adds a few. 2024/25 uses an older layout with no `player_gameweek_stats` or `fixtures`, so it can feed match-level priors only (rule 1 rules out differencing).
14. **Defensive contributions:** in 2026/27, `playermatchstats.tackles` is empty and FPL's tackle count matches `tackles_won`; in 2025/26 it matches `tackles`. Where gameweek grain is enough, use FPL's own counts from `player_gameweek_stats`.
15. **Blank match stats mean zero.** Upstream's 2026/27 `playermatchstats` leaves a count blank when the event didn't happen.
    - **The rule:** in processed matches, for rows with minutes > 0, fill blanks with 0 in these `fact_player_match` columns: `goals`, `assists`, `xg`, `xa`, `pens_scored`, `pens_missed`, `tackles`, `interceptions`, `clearances`, `blocks`, `recoveries`, `saves`.
    - **Evidence (GW1–10, 2,803 rows):** zero-filled goals, saves and missed penalties equal FPL's own counts in every row. FPL's xG is 0 in all 1,459 rows with a blank xG, and a blank xG never sits beside a shot.
    - **Never fill a column that is empty for the whole season.** 2026/27 `tackles` and `defensive_contributions` are like this, so take tackles from `tackles_won`.
    - **Never fill `team_gc_on_pitch`.** In 2025/26 it has 241 genuinely missing values across 83 matches, for players with 1–90 minutes. The data-engineer proposes how to handle them.
    - **Validation fails the run** if a listed column is empty for a whole season, or if a blank xG sits beside `total_shots` > 0.

## Data contract

Every agent builds against these schemas. A change means updating this section and `docs/data_contract.md` first, then telling the agents that depend on it.

**Processed tables** (internal; Parquet in `data/processed/`, not committed)

| Table | Grain | Columns |
| --- | --- | --- |
| `dim_player` | Player, current season | `player_id`, `player_code`, `web_name`, `team_id`, `position`, `price_tenths`, `status`, `chance_next`, `news`, `selected_pct`, `pen_order`, `fk_order`, `corner_order`, `ep_next` |
| `dim_team` | Team | `team_id`, `team_code`, `name`, `short_name`, `upstream_elo` |
| `fact_fixture` | Match, all competitions | `match_id`, `season`, `gw`, `kickoff_utc`, `tournament`, `home_team_id`, `away_team_id`, `home_upstream_elo`, `away_upstream_elo`, `finished`, `home_xg`, `away_xg`, `home_npxg`, `away_npxg`, `home_goals`, `away_goals` |
| `fact_player_match` | Player × match | `player_id`, `team_id`, `match_id`, `minutes`, `goals`, `assists`, `xg`, `xa`, `pens_scored`, `pens_missed`, `tackles`, `interceptions`, `clearances`, `blocks`, `recoveries`, `saves`, `team_gc_on_pitch` |
| `fact_player_gw` | Player × gameweek | `player_id`, `season`, `gw`, `points`, `minutes`, `starts`, `bonus`, `bps`, `yellow`, `red`, `own_goals`, `tackles`, `cbi`, `recoveries`, `defensive_contribution`, `price_tenths`, `selected_pct`, `transfers_in`, `transfers_out` |

The `upstream_elo` columns hold upstream ClubElo exactly as provided (null from 2026/27 GW3). The model's own Elo ratings are the Elo component's output (data rule 12). `home_team_id` and `away_team_id` are null for clubs outside the Premier League. The `fact_player_gw` defensive counts are FPL's own figures. The other source mappings are in `docs/data_contract.md`.

**Published outputs** (CSV in `outputs/`, committed, read by Excel)

| File | Grain | Columns |
| --- | --- | --- |
| `players.csv` | Player | `player_id`, `web_name`, `team`, `position`, `price_m`, `status`, `chance_next`, `news`, `selected_pct`, `minutes`, `starts`, `total_points`, `ppg`, `xg90`, `xa90`, `dc90`, `pen_taker`, `net_transfers_gw`, `price_change_gw`, `price_change_start` |
| `projections.csv` | Player × gameweek (next 5; no row for a blank gameweek) | `player_id`, `gw`, `opponent`, `home`, `exp_minutes`, `p_start`, `p_60`, `xg`, `xa`, `p_cs`, `exp_gc`, `xp_appear`, `xp_goals`, `xp_assists`, `xp_cs`, `xp_gc`, `xp_dc`, `xp_saves`, `xp_bonus`, `xp_cards`, `xp_total`, `low_confidence` |
| `player_summary.csv` | Player × horizon (1–5) | `player_id`, `horizon`, `xp_next`, `xp_horizon`, `replacement_xp`, `xp_above_repl`, `value_per_m`, `xp_per_m`, `ep_next_fpl` |
| `fixture_difficulty.csv` | Team × fixture (gameweeks in the next 5) | `team_id`, `match_id`, `gw`, `opponent_id`, `home`, `lambda_for`, `lambda_against`, `p_cs` |
| `elo_ratings.csv` | Team × Premier League match, 2025/26 and 2026/27 | `team_id`, `match_id`, `season`, `gw`, `kickoff_utc`, `elo_before`, `elo_after` |
| `optimal_squads.csv` | Horizon × budget × player | `horizon`, `budget_m`, `player_id`, `role` (XI or bench), `bench_order`, `is_captain`, `is_vice`, `xp_next`, `xp_horizon` |
| `meta.csv` | One row | `run_utc`, `upstream_commit`, `current_gw`, `next_gw`, `next_deadline_utc`, `model_version`, `max_horizon`, `backtest_mae_model`, `backtest_mae_ep_next`, `status` |

- **`fixture_difficulty.csv`:** a double gameweek has two rows for a team, and a blank gameweek has none. The workbook sums a gameweek's rows and shows a dash where there are none.
- **`projections.csv`:** in a double gameweek, `opponent` lists both opponents.
- **`elo_ratings.csv`:** for Josh's comparison with an outside Elo source. The workbook doesn't load it.
- **`meta.current_gw`** is the as-of gameweek. `max_horizon` is the number of gameweeks projected (5, from `config/model.yaml`), and the workbook's horizon picker offers 1 to `max_horizon`.

**Conventions**

- Column names in snake\_case.
- Published prices in £m to one decimal place (`price_m`). Processed tables hold integer tenths of £m (`price_tenths`, 55 = £5.5m), and code does all price arithmetic in tenths.
- Times in UTC, ISO 8601.
- One row per key, no duplicates.
- Nulls only in `news`, `chance_next`, `value_per_m` (null for minimum-priced players), and `backtest_mae_model` and `backtest_mae_ep_next` (null only until the first backtest).

**Point-in-time loader**

Outside the data-engineer's own code, every agent reads data through `load_as_of(season, as_of_gw, mode)` in `src/fpl/features.py`. It is the main guard against leakage.

- **Backtest mode:** the processed tables as they stood at the end of `GW{as_of_gw}`, built from that snapshot and earlier. It never reads master files and never returns a match after `as_of_gw`.
- **Live mode:** the same, with current status, news, chance of playing and price overlaid from the master files.
- `features.py` also holds generic features such as recent minutes and starts. Model-specific features live in the model components.

**Component hand-offs** (internal to the model)

Each model component exposes a function that takes `season` and `as_of_gw` and returns a DataFrame, per player per fixture unless noted. Every output carries its keys: `player_id` (or `team_id`), `match_id` and `gw`. The model-validator reads `p_60` and `p_cs` from these for its component checks.

| Component | Module | Depends on | Output columns |
| --- | --- | --- | --- |
| Elo | `models/elo.py` | Processed tables (results, `upstream_elo` seeds) | Per team per match: `elo_before`, `elo_after`; writes `elo_ratings.csv` |
| Minutes | `models/minutes.py` | Processed tables | `p_appear`, `p_start`, `p_60`, `exp_minutes` |
| Team goals | `models/team_goals.py` | Processed tables, Elo | Per team per fixture: `lambda_for`, `lambda_against`, `lambda_pen`. The Elo goals model (phase 1) is its fallback and benchmark |
| Attack | `models/attack.py` | Minutes, team goals | `xg`, `xa`, `xp_goals`, `xp_assists` |
| Defence | `models/defence.py` | Minutes, team goals | `p_cs`, `exp_gc`, `xp_cs`, `xp_gc`, `xp_dc`, `xp_saves` |
| Bonus | `models/bonus.py` | Minutes, attack, defence | `xp_bonus` |
| Combine | `xp.py` | All of the above | `xp_appear`, `xp_cards`, `xp_total`; writes `projections.csv` |
| Value | `value.py` | Combine | Per player per horizon (1–5): the `player_summary.csv` columns |

**Canonical copy:** phase 0 copies this section into `docs/data_contract.md`. From then on that file is the contract, and changes are made there first.

## Expected points model

xP is built bottom-up. Each scoring event's probability or expected count is multiplied by its points value, then summed over a player's fixtures in the gameweek.

```latex
xP_{i,g} = \sum_{f \in g} \left( \text{App} + \text{Goals} + \text{Assists} + \text{CS} + \text{GC} + \text{DC} + \text{Saves} + \text{Bonus} + \text{Cards} \right)_{i,f}
```

Expectation is linear, so goals and assists need only expected counts. Thresholds need a full distribution: 60 minutes, a clean sheet, every 2 goals conceded, every 3 saves and the defensive contribution threshold. Those use Poisson probabilities.

All point values live in `config/scoring.yaml`, keyed by position and taken from the official 2026/27 rules. Nothing is hardcoded. Build the components in the order below; each depends on the ones before it.

### 1. Minutes (build first)

Minutes is the largest source of xP error, so it gets the most care.

- **Outputs:** `p_appear`, `p_start`, `p_60` (probability of 60+ minutes) and `exp_minutes`, per fixture.
- **Inputs:** recency-weighted minutes and starts over the last 1, 3 and 6 Premier League matches; `status`; `chance_of_playing_next_round`; `news`; days since the last match; cup and European minutes in the previous 7 days.
- **v1 method:** recency-weighted start rate and minutes-given-start, then an availability override. Status injured, suspended or unavailable sets everything to 0. A chance of playing of 25, 50 or 75 scales the probabilities. A null chance with status available means 100.
- **v2 method:** logistic regression for `p_start`, trained on the backtest seasons.
- **Double gameweeks:** the second fixture gets a rotation discount set in config.

### 2. Team goal expectations

- **Outputs:** `lambda_for` and `lambda_against` per team per fixture.
- **v1 method:** reuse the Dixon-Coles approach from the betting bot. Fit attack and defence ratings on xG-weighted goals with time decay and a home advantage term.
- **Fallback and benchmark:** the Elo goals model, a Poisson model driven by the Elo-rating gap and home advantage. It is built in phase 1, fitted only on results before the as-of gameweek, and supplies `fixture_difficulty.csv` until phase 3.
- **Inputs:** Premier League results and team xG from `matches.csv`, this season and last; the Elo ratings from the Elo component (data rule 12).
- **Gate:** Dixon-Coles work starts only after Josh's own comparison of our Elo ratings with an outside Elo source. If the ratings are poor, a separate Elo agent rebuilds the Elo component first.
- **Promoted teams:** an Elo-based prior until they have about 6 matches.

### 3. Attacking returns

- **Player share:** the player's share of team non-penalty xG and of team xA while on the pitch, weighted by minutes.
- **Shrinkage:** small samples are pulled toward a position-and-team prior, with prior strength `k` (in minutes) set in config.

```latex
\text{share}_i = \frac{\text{npxG}_i + k \cdot \text{prior}_{pos}}{\text{team npxG on pitch}_i + k}
```

**Expected goals in a fixture** is an open-play part plus a penalty part. They are kept separate because open-play chances are spread across the team, while penalties go to one player.

```latex
E[\text{goals}_{i,f}] = \lambda^{np}_{f} \cdot \text{share}_i \cdot \frac{m_{i,f}}{90} \;+\; \lambda^{pen}_{f} \cdot P(\text{on pens}_{i,f})
```

- **Terms:** λ^np is the team's expected non-penalty goals (`lambda_for` × the team's non-penalty fraction). λ^pen is the team's expected penalty goals, from team xG minus non-penalty xG in `matches.csv`, shrunk toward the league average. m is `exp_minutes`.
- **Penalty duty:** for the first-choice taker (`penalties_order` = 1), P(on pens) is his expected share of the match on the pitch, `exp_minutes` / 90. The second-choice taker gets the share of the match when the first choice is off the pitch or out.
- **Why separate:** folded into `share`, penalty xG would inflate a taker's share and be applied to every open-play chance. It would also stay with him after he lost the job, while the new taker got nothing.
- **Stripping penalties from history:** player non-penalty xG = xG − penalty attempts × the provider's penalty xG value. The provider uses 0.7884 per penalty, verified in `shots.csv` for 2025/26 and 2026/27. The value goes in config, not code.
- **Finishing:** use xG, not goals. Finishing skill is shrunk heavily toward average.
- **Points:** expected goals × goal points for the position, plus expected assists × assist points.
- **FPL assists are wider than xA.** They include winning a penalty or direct free-kick that is scored, rebounds from saves, blocks and the woodwork, and deflected shots. "Expected assists" here means expected FPL assists: map xA to FPL assists on history rather than treating the two as equal.

### 4. Clean sheets and goals conceded

- **Clean sheet:** `p_cs` = `p_60` × e^(−`lambda_against`). This assumes the clean-sheet window is the full match.
- **Goals conceded deduction (GK and DEF):** the expected value of floor(N / 2), where N is Poisson with mean `lambda_against` × `exp_minutes` / 90.
- **Midfielders** take the clean-sheet points their position earns.

### 5. Defensive contributions

- **Rate:** the player's per-90 count of qualifying actions. Which actions qualify, and the threshold, differ by position; take both from the official rules.
- **Probability:** P(actions ≥ threshold) from a Poisson with mean rate × `exp_minutes` / 90, times the contribution points.
- **Check:** if the backtest shows variance well above the mean, switch to a negative binomial.
- **v2:** adjust for opponent possession, since dominant opponents force more defensive actions.

### 6. Saves (goalkeepers)

- Expected saves = the keeper's saves per 90, scaled by the opponent's `lambda_for` relative to league average.
- Points = the expected value of floor(saves / 3) under Poisson, times the save points.
- Penalty saves are ignored in v1.

### 7. Bonus

- **v1 method:** a regression of per-match bonus on the predicted components (xG, xA, `p_cs`, defensive contribution, minutes).
- **Same season only.** Fit it walk-forward on matches from the target gameweek's own season. Never use another season's bonus, as training data or as a prior. The BPS changes between seasons: 2026/27 moved bonus away from centre-backs and towards goalkeepers, full-backs and attackers. So in the backtest, 2025/26 predictions use 2025/26 bonus and 2026/27 predictions use 2026/27 bonus.
- **Early-season fallback:** until the season has enough matches (threshold in config), use a rule-based estimate that needs no other season's bonus. For example, share each match's 6 bonus points in proportion to each player's non-bonus xP.
- **v2 method:** a BPS simulation under the current season's BPS rules.

### 8. Appearance, cards and the rest

- **Appearance:** P(1–59 minutes) × the short-appearance points + `p_60` × the full-appearance points.
- **Cards, own goals, missed penalties:** per-90 historical rates, shrunk toward a position prior, × `exp_minutes` / 90 × points.

### Horizon and aggregation

- A gameweek's xP is the sum over its fixtures; a blank gameweek is 0.
- Report xP for each of the next 5 gameweeks (`max_horizon` in config). Horizon xP is a plain sum over the first h gameweeks, with h = 1–5 chosen once for the whole workbook. There is no decay or weighting (decided 2026-11-09).
- **Early season:** blend last season (joined on `player_code`) with this one. The current-season weight is n / (n + k), with n the matches played.
- **New arrivals from outside the league:** use the position-and-team prior and set `low_confidence` to true.
- Stamp every output with `model_version`.

## Validation

The model ships only if it beats FPL's `ep_next` in a walk-forward backtest. The model-validator agent builds and runs the backtest, not the modeller.

**Walk-forward procedure**

1. For each target gameweek g in the test window, build features only from the `GW{g−1}` snapshot and earlier.
2. Refit any learned parameters (team ratings, shrinkage priors, regressions) on data before g.
3. Predict xP for g and compare with actual points from `player_gameweek_stats` for g.
4. Take `ep_next` from the `GW{g−1}` snapshot as the baseline prediction for g.

**Test window:** in two parts. The development window is the full 2025/26 season (confirmed complete: 38 gameweeks, 380 matches); the modeller iterates against it freely. The holdout is 2026/27 to date; it is scored only at phase sign-off, so repeated tweaking can't overfit it. Every look at the holdout is logged in docs/decisions.md. Report GW1–5 of each season separately, because early-season priors behave differently.

**Baselines:** `ep_next`, the last-5-gameweek average, and season points per game.

**Evaluation set:** players with actual minutes > 0, or who started at least one of their team's previous 3 Premier League matches. The rule uses only information known before the deadline and no model's output, so it favours neither the model nor a baseline. Score every model on this identical set. Scoring all \~700 players flatters everyone, because hundreds of non-players score 0 trivially.

| Metric | Answers |
| --- | --- |
| MAE (primary) and RMSE | How far off is xP on average? |
| Spearman rank correlation, per position per gameweek | Does it order players correctly? This drives picks. |
| Top-N hit rate | How many of the predicted top N finish in the actual top N? N set in config |
| Calibration by xP bin (0–1, 1–2 … 8+) | When it says 5, do players average 5? |
| Brier score for `p_60` | Is the minutes model sound? |
| Predicted vs actual clean-sheet rate and goals, by bin | Are the team and attack components sound? |

**Acceptance gate** (starting thresholds)

- Model MAE below `ep_next` MAE on the holdout, and on at least 60% of the holdout's individual gameweeks.
- Mean actual within ±0.3 of mean predicted in every calibration bin with ≥200 observations.
- Every leakage check below passes.

**Elo component check (phase 1, starting thresholds)**

The model-validator judges the Elo component on its own walk-forward test over 2025/26 and 2026/27 to date. Each prediction uses only results from before that fixture.

| Check | Pass mark |
| --- | --- |
| Ratings track upstream Elo (2025/26 replay) | Spearman rank correlation ≥ 0.9 at every gameweek from GW6; the mean rating gap is reported |
| Goals are calibrated | Bins of predicted goals (0–0.75, 0.75–1.25, 1.25–1.75, 1.75+): actual within ±0.1 goals of predicted in every bin with ≥100 team-fixtures |
| Clean sheets are calibrated | Bins of predicted `p_cs` in steps of 0.1: actual rate within ±5 percentage points in every bin with ≥100 team-fixtures |
| Beats a no-skill baseline | Lower Poisson log-loss of goals than league-average home and away goals |
| Early season | GW1–5 of each season reported separately, without pass marks |

- **A fail** returns the Elo component to the modeller with the findings. A second fail is Josh's cue for a separate Elo agent.
- **Beyond GW2 of 2026/27**, where upstream Elo stops, Josh compares our ratings with an outside Elo source himself. The test there is ranking agreement and predictive log-loss, not raw rating levels. His verdict gates the phase 2 Dixon-Coles work.

**Leakage checklist**

- [ ] Features for gameweek g use nothing timestamped after the g deadline
- [ ] Rolling windows exclude the target gameweek
- [ ] Team ratings are refitted per target gameweek, not fitted once on the full season
- [ ] Price, status and ownership come from the `GW{g−1}` snapshot, never the master files
- [ ] Shrinkage priors are computed from training data only

Known limitation: the snapshot is taken at the end of `GW{g−1}`, so team news that breaks before the g deadline is missed. The backtest slightly understates live accuracy.

Known limitation (snapshot timing):
- Upstream keeps rewriting a gameweek folder until the next gameweek becomes current. A `GW{g−1}` snapshot can therefore land up to about 7 hours after the g deadline; this happened in 4 of the first 10 gameweeks of 2026/27.
- All the 2025/26 folders were rewritten on 2026-07-22, so their timing is unknown.
- Price, status, news and `ep_next` in a snapshot may include news from after the deadline. Match data can't leak, because each folder holds only its own gameweek.
- The validator checks whether a post-deadline `ep_next` refers to g or g+1, and reports pre- and post-deadline snapshots separately.

The report goes to `backtest/reports/{date}.md`, and the headline MAEs go into `meta.csv` for the Dashboard.

## Value for money

Value is a player's horizon xP above a replacement-level player in the same position, per £m spent above that position's minimum price. Python computes it for every horizon h = 1–5, and the workbook shows the row for the chosen horizon.

Raw points per £m is the wrong metric. A £4.0m defender who barely plays ranks well because the denominator is tiny. What you are paying for is the points above what a near-free player would score.

```latex
\text{value}_{i,h} = \frac{xP^{(h)}_i - xP^{(h)}_{\text{repl},\,pos}}{\max\left(p_i - p_{\min,\,pos},\ 0.5\right)}
```

- **Replacement level** (`replacement_xp`): the mean horizon xP of the three best players priced within £0.5m of the position's minimum, with `p_start` ≥ 0.7. Both numbers are set in config.
- **Denominator floor:** £0.5m. Without it, a player priced £0.1m above the minimum gets an absurd ratio.
- **Minimum-priced players:** show `xp_above_repl` only and leave `value_per_m` blank.
- **Also published:** raw `xp_per_m`, for familiarity.
- **Default sort:** `value_per_m` within position.

## Optimiser and transfers

Squad selection is an integer program solved in Python with PuLP. The Excel Transfer Planner handles what-ifs with formulas.

### Squad from scratch

This is the wildcard or free-hit view. It is solved for every horizon h = 1–5 and every budget from £95.0m to £110.0m in £0.5m steps: 31 budgets × 5 horizons = 155 solves. The range and step are set in `config/optimiser.yaml`. Managers' budgets drift with their players' prices, so the workbook takes any budget to £0.1m. It shows the squad for the largest solved budget at or below it, and says which: for example, "best squad for £101.5m (your budget £101.7m)".

**Variables:** `x_i` = 1 if player i is in the squad; `s_{i,g}` = 1 if the player starts in gameweek g; `c_{i,g}` = 1 if the player captains in g.

```latex
\max \sum_{g \in \text{horizon}} \sum_{i} xP_{i,g} \left( s_{i,g} + c_{i,g} + \beta \, (x_i - s_{i,g}) \right)
```

Here β is the bench weight (config, for example 0.1). The captain term adds the captain's xP a second time. Gameweeks are not weighted: there is no decay.

**Constraints**

- 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD
- At most 3 players from any club
- Total price ≤ budget
- In each gameweek: 11 starters, each one in the squad; 1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD
- In each gameweek: exactly 1 captain, who must start
- Optional locks (must include) and bans (exclude) from `config/optimiser.yaml`

### Transfers for a personal squad (v1.5)

- **Inputs** from `config/my_team.yaml`: 15 player IDs, purchase prices, bank, free transfers.
- **Selling price:** purchase price plus half of any rise, rounded down to £0.1m. A fall is passed on in full.
- **Variables per gameweek:** transfers in and out; hits = max(0, transfers − free transfers) × hit cost (4 points; `game_rules` in `config/scoring.yaml`).
- **Free-transfer banking:** up to 5 banked (`game_rules` in `config/scoring.yaml`). A Wildcard or Free Hit keeps saved free transfers.
- **Output:** recommended transfers this gameweek, a plan for the horizon, and the net xP gain after hits.

### What Excel does

- Transfer Planner formulas score user-chosen moves.
- A replacement list uses FILTER to check position, price ≤ selling value + bank, and fewer than 3 players from the incoming player's club.

**Runtime:** under 20 minutes for all 155 solves (5 horizons × 31 budgets) on a GitHub runner. This is a starting target, to be confirmed in phase 4.

**Tests:** every output passes `check_squad`, a rules checker written independently of the integer program, so a buggy constraint can't pass its own check. On a small instance the ILP matches a brute-force search, and the objective never falls as the budget rises. `tests/fixtures/rule_cases.csv` holds squads with their expected selling values and legal or illegal verdicts; `check_squad` and the Transfer Planner's formulas are both tested against it, so Python and Excel can't drift apart.

## Excel workbook

The workbook has six user sheets, a README sheet and hidden data sheets. Every number in it comes from the output CSVs, except the Transfer Planner's what-if formulas.

### Workbook-wide standards

- **Version:** Windows Excel 365 or 2021+, for dynamic arrays. Test on Windows Excel 365. Excel for Mac and Excel for the web are not supported. Microsoft's "Power Query data sources in Excel versions" (checked 2026-11-08) lists no Web source for Mac, and only Table/Range and OData as anonymous sources for the web version.
- **Data load:** one Power Query per output CSV, loaded as Excel Tables on hidden `Data_` sheets: `tbl_players`, `tbl_projections`, `tbl_summary`, `tbl_fixtures`, `tbl_squads`, `tbl_meta`.
- **Refresh:** on open, plus Data → Refresh All.
- **Naming:** tables `tbl_*`; named input cells `in_*` (`in_budget`, `in_horizon`, `in_bank`, `in_ft`, `in_hit_cost`).
- **One horizon:** `in_horizon` (1 to `max_horizon`, default 5) is a single workbook-wide picker. Every sheet's xP totals, value, fixture totals, optimal squad and transfer checks use it at once.
- **Inputs vs outputs:** input cells share one fill colour; everything else is protected (no password) against accidental edits.
- **Formats:** price `£0.0"m"`, xP `0.0`, percentages `0%`; header rows frozen.
- **Colour:** a colour-blind-safe scale for xP and difficulty, and the same scale on every sheet.
- **README sheet:** how to refresh, what each sheet does, the data credit with link, and the last-updated time.

### Dashboard

- **Header:** data last updated, current gameweek, next deadline, model version, and a status flag that turns red when data is over 24 hours old.
- **Panels:** top 10 by next-GW xP per position; top 10 value picks; best and worst 5 teams by fixtures over the horizon (attack and defence); captain shortlist (top 5); your squad's projected points next GW and over the horizon against the optimal squad; top 5 transfer opportunities for your squad; latest backtest MAE against `ep_next`.
- **Charts:** your squad's xP by gameweek against the optimal squad (line); xP against price by position (scatter), with value picks highlighted.

### Player Database

- One row per player: `tbl_players` joined to `tbl_summary`.
- **Columns:** name, team, position, price, status, news, chance of playing, ownership, minutes, starts, total points, PPG, xG/90, xA/90, xGI/90, defensive contributions/90, penalty taker, net transfers this GW, price change this GW and since the start, xP next GW, horizon xP, value per £m. Metric definitions are in `CONTEXT.md`.
- **Interaction:** slicers for team, position and status; a price filter; a name search box (FILTER).
- **Formatting:** status colours; data bars on xP.

### Fixture Analysis

- A grid of 20 teams × the gameweeks in the horizon. Each cell shows the opponent's short name and H or A, coloured by difficulty.
- A dropdown (`in_fixture_view`) switches between attack (`lambda_for`) and defence (`p_cs`).
- A total column sums the horizon, and the grid sorts by it.
- Blank gameweeks show a grey dash. Doubles show both opponents and the combined value.
- An optional column shows FPL's own strength ratings for comparison. Upstream's `teams.strength` is null for 2026/27, so this column waits for a source.

### Player Projections

- Player × the gameweeks in the horizon, with the horizon xP.
- Next-GW breakdown: expected minutes, `p_start`, xG, xA, `p_cs`, defensive contribution points, bonus.
- FPL's `ep_next` sits beside the model's next-GW xP.
- **Filters:** position, team, maximum price, minimum `p_start`.
- Low-confidence players are flagged.

### Transfer Planner

**Inputs**

- 15 squad slots, each a dropdown of player names
- Purchase price per slot (optional; defaults to the current price)
- Bank, free transfers and hit cost (default 4). The horizon comes from the workbook-wide `in_horizon`.
- Tick boxes for the starting XI, plus a captain pick

**Calculations**

- Selling value per player (section 9) and total funds available.
- Squad xP per gameweek for the chosen XI and captain, with checks that 11 are picked and the formation is legal.
- Up to 3 planned transfers (out → in). Each is checked for position, budget and the 3-per-club limit, and shows the xP change per gameweek, over the horizon, the hit cost and the net gain.
- **Candidates:** pick an outgoing player, and FILTER lists eligible replacements sorted by horizon xP gain.
- **Price signals:** net transfers and this-GW price change for every squad player and candidate. These are indicators only.

### Squad Optimisation

- `in_budget` takes any budget to £0.1m. The sheet uses the largest solved budget at or below it and shows both figures.
- The optimal squad for that budget and the horizon in `in_horizon`: the XI by formation, the bench in order, captain and vice, cost, bank left, next-GW xP and horizon xP.
- The parameters used (horizon and bench weight).
- Your squad against the optimal: players in common and the xP gap.
- The view is from scratch (wildcard or free hit), and the sheet says so.

## Automation and operations

A GitHub Actions workflow runs the full pipeline at 08:00 and 18:00 UTC. Upstream refreshes about three times a day at drifting times, so each run publishes whatever is newest when it starts; twice a day is enough. It commits only outputs that pass validation. GitHub may start scheduled runs several minutes late, so on days with an 18:00 deadline the evening run lands after the deadline.

**Workflows**

| Workflow | Trigger | Job |
| --- | --- | --- |
| `update.yml` | Cron `0 8 * * *` and `0 18 * * *` (UTC), plus manual run | Full pipeline and publish |
| `backtest.yml` | Weekly, Monday 09:00 UTC, plus manual run | Full backtest; report and headline metrics |
| `ci.yml` | Every push and pull request | Tests and lint |

GitHub cron runs in UTC and so does the upstream schedule, so no summer-time adjustment is needed.

**`update.yml` steps**

1. Check out the repo and set up Python with a pip cache.
2. Sparse-checkout `data/2026-2027/` and `data/2025-2026/` from upstream, and record the commit SHA. The Elo component needs 2025/26 for seeds and calibration.
3. If the upstream SHA matches the last run's, exit without committing.
4. Validate inputs: expected files exist, schemas match the contract, keys are non-null and unique, row counts are within bounds, and the latest gameweek folder is present.
5. Build the processed tables.
6. Run the xP model and value metrics.
7. Run the optimiser for every budget.
8. Validate outputs: schemas match, no NaN, xP per gameweek between −2 and 20, every projected player exists in `players.csv`, and every squad passes the optimiser's `check_squad`.
9. Write `meta.csv`, then commit `outputs/` with the upstream SHA in the message and push. This needs `contents: write` on `GITHUB_TOKEN`; no other secrets are needed.

**When something fails**

- Any failed validation fails the job and nothing is committed. GitHub emails the failure.
- The workbook keeps the last good data, and the Dashboard flags data over 24 hours old.
- An upstream schema change is caught at input validation. Fix the contract first, then the code.

**Tests (pytest, run in `ci.yml`)**

- Scoring: hand-computed xP for synthetic players matches the code.
- Poisson helpers: expected values of floor(N/2), floor(S/3) and threshold probabilities match simulation.
- Joins: no rows lost or duplicated.
- Optimiser: constraints hold; a small instance matches brute force.
- Contract: every output file matches its schema.

## Repo structure

One repo holds the pipeline, the published outputs, the workbook and the agents.

```
fpl-xp-model/
├── .github/workflows/
│   ├── update.yml          # twice-daily pipeline
│   ├── backtest.yml        # weekly backtest
│   └── ci.yml              # tests on push
├── .claude/agents/         # project agents
├── CLAUDE.md               # project rules; points to docs/brief.md
├── config/
│   ├── scoring.yaml        # 2026/27 points rules by position, plus squad and transfer rules
│   ├── pipeline.yaml       # upstream source, input-validation bounds
│   ├── model.yaml          # max horizon, Elo settings, shrinkage k, rotation discount
│   ├── optimiser.yaml      # budgets, bench weight, hit cost, locks, bans
│   └── my_team.yaml        # optional personal squad (v1.5)
├── src/fpl/
│   ├── ingest.py
│   ├── validate.py
│   ├── clean.py
│   ├── features.py
│   ├── models/
│   │   ├── elo.py          # Elo ratings (Elo component)
│   │   ├── minutes.py
│   │   ├── team_goals.py
│   │   ├── attack.py
│   │   ├── defence.py      # clean sheets, goals conceded, DC, saves
│   │   └── bonus.py
│   ├── xp.py               # combines the components
│   ├── value.py
│   ├── optimise.py
│   └── export.py
├── backtest/
│   ├── run_backtest.py
│   └── reports/
├── outputs/                # published CSVs (committed)
├── data/                   # raw and processed cache (gitignored)
├── excel/
│   ├── FPL_Model.xlsx
│   └── queries/            # Power Query M code, one file per query
├── docs/
│   ├── brief.md            # this document
│   ├── data_contract.md
│   └── decisions.md        # dated log of design decisions
└── tests/
```

Keeping the M code as text files in `excel/queries/` means the queries are versioned even though the workbook is binary.

## Build phases

The build runs in six phases, each ending with a review before the next starts. The first is a thin end-to-end slice, so data reaches the workbook before any modelling.

0. **Foundations.** Set up the repo, `CLAUDE.md`, this brief and the data contract in `docs/`. Fill `scoring.yaml` from the official rules and explore upstream to answer the verify list in section 15.
   - Done when: the contract doc is complete and every verify item has an answer.
1. **Data pipeline and thin slice.** The data-engineer builds ingestion, validation, the processed tables and the point-in-time loader. The expected-points-modeller builds the Elo component (ratings and the Elo goals model). Publish `players.csv`, an Elo-based `fixture_difficulty.csv`, `elo_ratings.csv` and `meta.csv`; put `update.yml` live; build the Player Database and Fixture Analysis sheets through Power Query. Plan: `docs/plans/phase-1.md`.
   - Done when: the workbook refreshes from GitHub on open; processed row counts reconcile with upstream after the documented filters; tests pass; two consecutive scheduled runs succeed, each publishing a new upstream commit; and the model-validator's Elo component check (section 7) passes.
2. **xP model v1 and backtest.** Build the components in order: minutes, team goals, attack, defence, bonus, then combine them. The validator builds the backtest harness independently, in parallel.
   - Done when: the acceptance gate in section 7 passes and the report is committed.
3. **Projections and value.** Publish `projections.csv` and `player_summary.csv`, build the Player Projections sheet, and switch Fixture Analysis to the model's goal expectations.
   - Done when: every sheet value reconciles with the CSVs to 0.01.
4. **Optimiser and planner.** Solve the optimal squads for every budget, and build the Squad Optimisation and Transfer Planner sheets.
   - Done when: the constraint tests and brute-force test pass, and the planner blocks illegal moves.
5. **Dashboard and polish.** Build the Dashboard and README sheet, then apply formatting and protection.
   - Done when: QA passes and the usability hand test in section 1 passes.

The model-validator reviews phases 2 and 3. Global QA reviews phases 1, 4 and 5. The agent that did the work never signs off its own phase.

## Agent roster

Five project agents do the work, alongside the global QA and Code Review agents. The main session orchestrates, owns this brief and the data contract, and is the only place a contract change is approved.

| Agent | Owns | Reads | Writes | Must not |
| --- | --- | --- | --- | --- |
| data-engineer | Ingestion, validation, cleaning, processed tables (passing upstream Elo through), the point-in-time loader, workflows | Upstream data; sections 4, 5, 11 | `ingest.py`, `validate.py`, `clean.py`, `features.py`, `config/pipeline.yaml`, `.github/workflows/`; proposed contract changes | Change model logic; touch the workbook |
| expected-points-modeller | The Elo component (ratings and Elo goals model); the minutes, team goals, attack, defence and bonus models; xP combination; value metric | Processed tables, `scoring.yaml`; sections 6, 8 | `src/fpl/models/`, `xp.py`, `value.py`, `config/model.yaml` | Write the backtest or judge its own accuracy; touch the workbook |
| model-validator | Backtest harness, leakage checks, the pass or fail decision | Section 7; model code and outputs (read-only) | `backtest/`, reports | Edit model code |
| optimiser | Squad optimisation, transfer logic, the budget-range solves | `projections.csv`; section 9 | `optimise.py`, `config/optimiser.yaml` | Change xP values |
| excel-builder | The workbook, Power Query M code, all sheets | Output CSV schemas; section 10 | `excel/` | Change outputs or Python |

**Working rules**

1. Agents work in phase order. They run in parallel only when their inputs are frozen; for example, excel-builder can build against sample CSVs that follow the contract while the model is in progress.
2. A contract change is proposed by an agent, approved by the main session, and written into `docs/data_contract.md` (and this brief, if affected) before any code changes.
3. The validator sees code, outputs and this brief, never the modeller's reasoning. The main session never forwards the expected-points-modeller's report to it.
4. Only excel-builder writes to the workbook.
5. Every design decision goes into `docs/decisions.md` with a date and a reason.
6. A phase is done when its acceptance criteria in section 13 are checked by the validator or QA, not by the agent that did the work.
7. The main session owns `config/scoring.yaml`, filled from the official 2026/27 rules with the source cited in `docs/decisions.md`. Filling it needs the web, which no agent has.

## Open decisions and things to verify

These must be settled in phase 0, before any agent writes code that depends on them.

**Verify** (against upstream data or the official FPL rules)

Answered in phase 0 (2026-11-08). Evidence is in `docs/decisions.md`.

- [x] 2026/27 scoring values, including defensive contribution thresholds and which actions count per position. In `config/scoring.yaml`, and they reproduce FPL's official points exactly for GW7–10. Defenders need 10+ CBIT; midfielders and forwards need 12+ CBIRT; 2 points, no stacking; goalkeepers are not eligible.
- [x] Free-transfer banking cap and hit cost for 2026/27: up to 5 banked; 4 points per extra transfer.
- [x] Whether the latest gameweek folder's `fixtures.csv` lists all remaining fixtures or only that gameweek: only that gameweek. All 38 folders exist, so read `GW{next}` to `GW{next+4}`.
- [x] Whether `player_id` is stable across seasons, or only `player_code`: only `player_code`. `teams.id` is season-specific too.
- [x] Price units in `now_cost` (tenths of £m?): already £m to one decimal (data rule 7).
- [x] Which previous seasons exist upstream, and whether their schemas match 2026/27: 2025/26 is complete with matching columns; 2024/25 uses an older layout (data rule 13).
- [x] The penalty xG value the data provider uses: 0.7884.
- [x] Power Query web refresh on Mac Excel and Excel for the web, if other users need them: not supported, so the workbook is Windows-only (section 10).

**Decide** (Josh)

- [ ] Minimum Excel version for users (dynamic arrays need 365 or 2021+)
- [x] Horizon and decay: 5 gameweeks projected; one workbook-wide horizon of 1–5, chosen by the user; no decay (Josh, 2026-11-09)
- [ ] Optimiser bench weight (proposed 0.1)
- [ ] Personal squad optimisation in v1, or v1.5 as planned
- [x] Budget range for the precomputed optimal squads: £95.0m–£110.0m in £0.5m steps, with any typed budget served by the largest solved budget at or below it (Josh, 2026-11-09)
- [x] Whether a public output repo is acceptable: yes, public (Josh, 2026-11-09)

**Sources:** [olbauday/FPL-Core-Insights README](https://github.com/olbauday/FPL-Core-Insights)
