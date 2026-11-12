# Data contract

The canonical schema for every processed table and published output. Copied
from section 5 of docs/brief.md in phase 0 (2026-11-08) and amended on
2026-11-09 with the phase 0 findings and the phase 1 plan review (see
docs/decisions.md). From now on this
file is the contract: it overrides section 5 of the brief, and changes are
made here first.

**Changing the contract:** an agent proposes the change in its report; the
main session approves or rejects it; on approval this file (and the brief, if
affected) is updated and the change logged in docs/decisions.md before any
code changes; dependent agents are told in their next task message.

## Processed tables

Internal; Parquet in `data/processed/{season}/`, one set per season, not
committed. `player_id` and `team_id` are season-specific (brief data rule 6),
so a table never mixes seasons.

| Table | Grain | Columns |
| --- | --- | --- |
| `dim_player` | Player, current season | `player_id`, `player_code`, `web_name`, `team_id`, `position`, `price_tenths`, `status`, `chance_next`, `news`, `selected_pct`, `pen_order`, `fk_order`, `corner_order`, `ep_next` |
| `dim_team` | Team | `team_id`, `team_code`, `name`, `short_name`, `upstream_elo` |
| `fact_fixture` | Match, all competitions | `match_id`, `season`, `gw`, `kickoff_utc`, `tournament`, `home_team_id`, `away_team_id`, `home_upstream_elo`, `away_upstream_elo`, `finished`, `stats_complete`, `home_xg`, `away_xg`, `home_npxg`, `away_npxg`, `home_goals`, `away_goals` |
| `fact_player_match` | Player × match | `player_id`, `team_id`, `match_id`, `minutes`, `goals`, `assists`, `xg`, `xa`, `pens_scored`, `pens_missed`, `tackles`, `interceptions`, `clearances`, `blocks`, `recoveries`, `saves` |
| `fact_player_gw` | Player × gameweek | `player_id`, `team_id`, `season`, `gw`, `points`, `minutes`, `starts`, `bonus`, `bps`, `yellow`, `red`, `own_goals`, `goals_conceded`, `tackles`, `cbi`, `recoveries`, `defensive_contribution`, `price_tenths`, `selected_pct`, `transfers_in`, `transfers_out` |

### Source notes

The non-obvious mappings, verified on upstream commit 66e73ea in phase 0.
Brief section 4 lists the data rules.

- **Team keys:** in `matches.csv` and `fixtures.csv`, `home_team` and
  `away_team` are team **codes**. Map them through `teams.code` to get
  `home_team_id` and `away_team_id`. These are null for clubs outside the
  Premier League.
- **`fact_player_match.team_id`:** the player's `team_code` in the snapshot
  `players.csv` of the match's `gw`, mapped to `teams.id`. For a cup or
  European match that is the gameweek it was played in, not the folder that
  holds it; a GW0 match uses the GW1 snapshot. Don't use the master
  `team_history.csv`, because backtest mode never reads master files.
  - A row whose club isn't one of the match's clubs is dropped and counted
    under `club_not_in_match`, and validation checks this. Example: upstream
    id errors such as Bailey in Kairat v Arsenal.
  - The `club_not_in_match` and `player_not_in_snapshot` drops are capped
    per season in `config/pipeline.yaml`, so a club-mapping regression
    fails the run instead of silently emptying the table.
  - Why: upstream filed Palace's October 2025 Conference League tie in the
    GW30 folder, and that folder's snapshot put Guéhi at Man City.
- **Prices:** upstream `now_cost` is £m. Processed tables store
  `price_tenths` = round(`now_cost` × 10), as an integer. Published outputs
  store `price_m` = `price_tenths` / 10, to one decimal.
- **Positions:** take each season's own `players.position` and map
  Goalkeeper, Defender, Midfielder and Forward to GKP, DEF, MID and FWD.
  Positions change between seasons; 11 players were reclassified for 2026/27.
- **`dim_player.chance_next`:** `chance_of_playing_next_round`. Null means no
  concern.
- **`dim_player.ep_next`:** from the snapshot being loaded, never from master
  history in backtest mode.
- **`dim_player.fk_order` and `corner_order`:** `direct_freekicks_order` and
  `corners_and_indirect_freekicks_order`.
- **Upstream Elo:** Premier League matches only.
  - `home_upstream_elo` and `away_upstream_elo` are `home_team_elo` and
    `away_team_elo`, the ClubElo rating at kickoff, on Premier League rows.
    They are null on cup and European rows.
  - `dim_team.upstream_elo` is each club's most recent non-null Premier
    League kickoff value among the finished matches in the read, by kickoff
    time, and null if there is none.
  - These are upstream ClubElo exactly as provided: no filling, null from
    2026/27 GW3.
  - **Frozen stretches** (checked 2026-11-12, brief data rule 12): in
    2025/26 the kickoff values move at every gameweek up to GW26, are frozen
    in GW27-32, move in GW33-34 and are frozen from GW35. The 2026/27 GW1-2
    values repeat each club's 2025/26 GW38 kickoff value. The Elo component
    uses them only as seeds and, where they move, as its tuning target.
  - The model's own Elo ratings are the Elo component's output, not a
    processed-table column (brief data rule 12).
  - **Why not cup rows:** in 2025/26 their Elo isn't the kickoff rating.
    Bournemouth's 26 August 2025 EFL Cup tie shows 1871.97, which it reached
    only at Premier League kickoffs in GW34-38, against 1804-1808 at its
    GW1-2 kickoffs.
  - **Why not `teams.elo`:** in 2025/26 its value in folders GW1-25 equals
    clubs' GW26-30 kickoff Elo. Either source would leak into early
    backtests.
- **`fact_fixture.gw`:** for a Premier League fixture, upstream's gameweek
  (its folder). For a cup or European match, the gameweek it was played in:
  the latest gameweek whose deadline is at or before kickoff, or 0 before
  the GW1 deadline, with deadlines derived as in the loader section.
  - Why: upstream files these in a later folder, one later throughout
    2026/27 and up to 26 later in 2025/26. Using the folder would break
    "gameweek up to as-of" for cup rows.
- **`fact_fixture`:** `kickoff_utc` comes from `kickoff_time`. That is UTC,
  naive in 2026/27 and offset-stamped in 2025/26, so normalise to ISO 8601
  with `Z`. `home_xg` is `home_expected_goals_xg`, `home_npxg` is
  `home_non_penalty_xg` and `home_goals` is `home_score`; the same applies to
  away.
- **`fact_fixture.finished` and `stats_complete`:** `finished` is upstream's
  `finished`. `stats_complete` marks a complete match: finished, with both
  team xG values present, and with `playermatchstats` rows for each club that
  has a Premier League `team_id` (brief data rule 9). Upstream's
  `stats_processed` and `player_stats_processed` flags aren't used.
  - `home_goals` and `away_goals` are kept for every finished match, and
    null otherwise, even if upstream shows a part-played score.
  - The xG and npxG columns are kept only for complete matches.
  - Unfinished matches stay in the table, because fixture difficulty needs
    future fixtures.
- **`fact_fixture` dropped rows:** matches with no `kickoff_time` are dropped
  and counted under that reason. All 40 at upstream `0206600` are 2025/26
  cup and European matches (36 played), which the model doesn't need.
  Validation fails if a Premier League match has no kickoff time.
- **`fact_player_match.minutes`:** `minutes_played`.
- **`fact_player_match.tackles`:** FPL's tackle measure. That is
  `tackles_won` in 2026/27, where total `tackles` is null, and `tackles` in
  2025/26.
- **`fact_player_match` other columns:** `pens_scored` and `pens_missed` come
  from `penalties_scored` and `penalties_missed`.
- **`fact_player_match` rows:** complete matches only; rows from a finished
  match that isn't complete are dropped and counted. A row whose player is
  missing from that gameweek's snapshot `players.csv` is dropped and counted
  under `player_not_in_snapshot`.
- **`fact_player_match` blanks:** blanks mean zero (brief data rule 15). In
  complete matches, blanks in `goals`, `assists`, `xg`, `xa`, `pens_scored`,
  `pens_missed`, `tackles`, `interceptions`, `clearances`, `blocks`,
  `recoveries` and `saves` are filled with 0. This includes 0-minute rows
  (unused substitutes), which are kept.
- **Goals conceded:** upstream's `team_goals_conceded` and goalkeeper-only
  `goals_conceded` in `playermatchstats` aren't used. `team_goals_conceded`
  is the whole-match figure for unused substitutes and for most 2025/26
  GW1-25 substitutes, and has 241 genuine gaps in 2025/26. Use
  `fact_player_gw.goals_conceded` instead.
- **`fact_player_gw` minutes:** `minutes` is FPL's own value from
  `player_gameweek_stats`, which sets the 60-minute threshold. It is not
  `minutes_played`.
- **`fact_player_gw` other columns:** `points` is `event_points`, and `yellow`
  and `red` are `yellow_cards` and `red_cards`. `tackles`, `cbi`
  (`clearances_blocks_interceptions`), `recoveries` and
  `defensive_contribution` are FPL's own counts. `goals_conceded` is FPL's
  own goals conceded while on the pitch. `transfers_in` and `transfers_out`
  are `transfers_in_event` and `transfers_out_event`.
- **`fact_player_gw` snapshot columns:** `price_tenths`, `selected_pct`,
  `transfers_in` and `transfers_out` describe the run-up to the *next*
  gameweek's deadline (brief data rule 8). Row g is known when predicting
  g+1, never g. `transfers_in` and `transfers_out` count transfers made for
  g+1.
- **`fact_player_gw.team_id`:** the player's `team_code` in that gameweek's
  snapshot `players.csv`, mapped to `teams.id`, the same club the row gate
  uses. It is null for a player missing from that snapshot.
- **`fact_player_gw` rows:** a player's gameweek row is kept only once every
  Premier League fixture their club has in that gameweek is finished. The
  club comes from that gameweek's snapshot `players.csv`. Other rows are
  dropped and counted under `club_fixture_not_finished`, and reappear once
  the fixtures finish. A club with no fixture in the gameweek (a blank
  gameweek) keeps its rows. A player missing from that gameweek's snapshot
  has no club, so his row is held until every Premier League fixture in the
  gameweek is finished (players added to FPL mid-gameweek).
  - Why: FPL publishes a row for every player while a gameweek is being
    played. A player whose match is still to come would read as 0 minutes
    and 0 points.
  - The gate is `finished`, because FPL's own figures don't depend on
    upstream's match stats.
  - A released row can still be provisional for some hours: FPL keeps
    adjusting bonus, BPS and occasionally points. The next run corrects it,
    and backtests read final folders.
- **`dim_player`:** the latest snapshot of the season's players, so fact
  tables may hold a `player_id` that isn't in it (players who left). A player
  with no `playerstats` row is dropped and counted under
  `no_playerstats_row`.
- **`season`:** upstream's folder name, for example `2025-2026`.

## Published outputs

CSV in `outputs/`, committed, read by Excel.

| File | Grain | Columns |
| --- | --- | --- |
| `players.csv` | Player | `player_id`, `web_name`, `team`, `position`, `price_m`, `status`, `chance_next`, `news`, `selected_pct`, `minutes`, `starts`, `total_points`, `ppg`, `xg90`, `xa90`, `dc90`, `pen_taker`, `net_transfers_gw`, `price_change_gw`, `price_change_start` |
| `projections.csv` | Player × gameweek (next 5; no row for a blank gameweek) | `player_id`, `gw`, `opponent`, `home`, `exp_minutes`, `p_start`, `p_60`, `xg`, `xa`, `p_cs`, `exp_gc`, `xp_appear`, `xp_goals`, `xp_assists`, `xp_cs`, `xp_gc`, `xp_dc`, `xp_saves`, `xp_bonus`, `xp_cards`, `xp_total`, `low_confidence` |
| `player_summary.csv` | Player × horizon (1–5) | `player_id`, `horizon`, `xp_next`, `xp_horizon`, `replacement_xp`, `xp_above_repl`, `value_per_m`, `xp_per_m`, `ep_next_fpl` |
| `fixture_difficulty.csv` | Team × fixture (gameweeks in the next 5) | `team_id`, `match_id`, `gw`, `opponent_id`, `home`, `lambda_for`, `lambda_against`, `p_cs` |
| `elo_ratings.csv` | Team × Premier League match, 2025/26 and 2026/27 | `team_id`, `match_id`, `season`, `gw`, `kickoff_utc`, `elo_before`, `elo_after` |
| `optimal_squads.csv` | Horizon × budget × player | `horizon`, `budget_m`, `player_id`, `role` (XI or bench), `bench_order`, `is_captain`, `is_vice`, `xp_next`, `xp_horizon` |
| `meta.csv` | One row | `run_utc`, `upstream_commit`, `current_gw`, `next_gw`, `next_deadline_utc`, `model_version`, `max_horizon`, `backtest_mae_model`, `backtest_mae_ep_next`, `status` |

- **`fixture_difficulty.csv`:** a double gameweek has two rows for a team, and
  a blank gameweek has none. The workbook sums a gameweek's rows and shows a
  dash where there are none.
- **`projections.csv`:** in a double gameweek, `opponent` lists both
  opponents.
- **`elo_ratings.csv`:** an analysis output for Josh's comparison with an
  outside Elo source. The workbook doesn't load it. It holds finished Premier
  League matches only, from the Elo component's one continuous run across
  both seasons, and `export.py` writes it.
- **`fixture_difficulty.csv`** comes from the Elo goals model in phase 1, and
  `export.py` writes it.
- **`meta.csv`:** `current_gw` is the as-of gameweek. `max_horizon` is the
  number of gameweeks projected (5, from `config/model.yaml`).
  `model_version` is filled from phase 1, for example `0.1.0-elo`.
- **Gameweeks:** the next gameweek is the first gameweek whose deadline is
  after the run time. A gameweek whose deadline has passed never appears in
  the outputs (`CONTEXT.md`).

## Conventions

- Column names in snake_case.
- Published prices in £m to one decimal place (`price_m`). Processed tables
  hold integer tenths of £m (`price_tenths`, 55 = £5.5m), and code does all
  price arithmetic in tenths.
- Times in UTC, ISO 8601.
- One row per key, no duplicates.
- In published outputs, nulls only in `news`, `chance_next`, `value_per_m`
  (null for minimum-priced players), and `backtest_mae_model` and
  `backtest_mae_ep_next` (null only until the first backtest).
- Processed tables may also be null in `home_team_id` and `away_team_id`
  (non-Premier League clubs), and in the `upstream_elo` columns.
  - `fact_fixture`: `home_goals` and `away_goals` may be null when `finished`
    is false; `home_xg`, `away_xg`, `home_npxg` and `away_npxg` when
    `stats_complete` is false. `home_npxg` and `away_npxg` may also be null
    on complete cup and European matches (five 2025/26 EFL Cup matches). A
    complete Premier League match without npxG fails validation.
  - `dim_player`: `chance_next`, `news`, `pen_order`, `fk_order`,
    `corner_order` and `ep_next` may be null. A null order means the player
    isn't on that order.
  - `fact_player_gw`: `team_id` may be null for a player missing from that
    gameweek's snapshot.

## Point-in-time loader

Outside the data-engineer's own code, every agent reads data through
`load_as_of(season, as_of_gw, mode)` in `src/fpl/features.py`. It is the main
guard against leakage.

- **Signature:** `load_as_of(season, as_of_gw, mode, *, cfg=None,
  root=ROOT)`, with `mode` either `"backtest"` or `"live"`.
- **Returns** the five processed tables, keyed by table name, with the
  columns above.
- **What an as-of read holds:** a read at as-of g holds every match with
  `gw` up to g, in any competition.
  - Because a cup or European match's `gw` is the gameweek it was played
    in, this includes every cup match that kicked off before the GW g+1
    deadline, whichever folder upstream filed it in.
  - Upstream files a midweek tie in the next gameweek's folder (all of
    2026/27 so far), and the minutes model needs those minutes.
  - **The deadline:** GW g+1's deadline is its first Premier League kickoff
    minus `deadline_offset_minutes` (90, in `config/pipeline.yaml`). This
    matches FPL's `deadline_time` for all 76 gameweeks of 2025/26 and 2026/27
    and needs no master file. At as-of 38, every match counts.
    - **A gameweek with no Premier League fixture** (wholly postponed, as
      in 2022/23 GW7) takes the previous gameweek's last Premier League
      kickoff as its deadline. That is never later than FPL's, so a cup tie
      can only be dated late, never early. Its folder may hold no matches
      without failing validation, as long as the season's Premier League
      count is within bounds.
    - Validation fails if the derived deadlines don't strictly increase.
- **Backtest mode:** the processed tables as they stood at the end of
  `GW{as_of_gw}`, built from that snapshot and the folders it needs.
  - It never reads master files.
  - It never returns a result, xG, upstream Elo or player row from a match
    outside the read.
  - **Later Premier League fixtures** appear in `fact_fixture` as **schedule
    only**: `finished` and `stats_complete` false, and results, xG and
    upstream Elo null. Fixture difficulty needs them. Their gameweek and
    kickoff come from the final folders, so a backtest knows about
    rescheduled fixtures earlier than a manager would (`docs/known_gaps.md`).
  - **Later cup and European matches are left out.** In a knockout cup a
    future tie reveals who won the earlier rounds.
- **Live mode:** the same, with current status, news, chance of playing and
  price overlaid from the master files.
  - **Overlay rules:** the master row with the highest `gw` wins. A cleared
    concern clears the snapshot value. A player with no master row keeps his
    snapshot values. Rows are matched by `player_id`, never by position, and
    `team_id` is not overlaid.
  - **Between a deadline and upstream's first write** of that gameweek,
    `as_of_gw` may be ahead of the newest folder with player figures; the
    loader then returns what exists. Finished cup and European matches
    already in that folder are normal, not an error.
- **As-of 0:** `fact_fixture` is the Premier League schedule with nothing
  finished, plus any cup or European match played before the GW1 deadline
  (none in either season so far), `dim_team` has no `upstream_elo`, and `dim_player` and the player
  fact tables are empty (`docs/known_gaps.md`). A live run at as-of 1 before
  upstream has written GW1 returns the same.
- **Live gameweeks:** `live_gameweeks(season, run_utc)` returns the next and
  as-of gameweeks.
- **Next and as-of gameweek (live only):** the next gameweek is the first
  whose `deadline_time` in the master `gameweek_summaries.csv` is strictly
  after the run time. A run at the exact deadline treats it as passed. The
  as-of gameweek is the next gameweek minus 1, so it is 0 before the GW1
  deadline. After the GW38 deadline there is no next gameweek in the
  season, and the run fails with a clear error.
- `features.py` also holds generic features. Model-specific features live in
  the model components.
  - **Recent minutes and starts:** `recent_minutes(tables, as_of_gw,
    windows)`. For each player and each window N given by the caller, it
    returns the totals of FPL `minutes` and `starts` over the last N
    gameweeks up to `as_of_gw` in which his club had a Premier League
    fixture, plus `fixtures`, the club's fixture count in those gameweeks.
    It returns long rows: `player_id`, `window`, `minutes`, `starts` and
    `fixtures`. A double gameweek counts as one gameweek. The club is
    `fact_player_gw.team_id` for each gameweek.

## Component hand-offs

Internal to the model. Each model component exposes a function that takes
`season`, `as_of_gw` and `mode` (passed to `load_as_of`) and returns a
DataFrame, per player per fixture unless noted. Every output carries its keys:
`player_id` (or `team_id`), `match_id` and `gw`. The model-validator reads
`p_60` and `p_cs` from these for its component checks. Components return
DataFrames only; in phase 1, `export.py` writes `elo_ratings.csv` and
`fixture_difficulty.csv` from them.

| Component | Module | Depends on | Output columns |
| --- | --- | --- | --- |
| Elo | `models/elo.py` | Processed tables (results, `upstream_elo` seeds) | Per team per finished Premier League match, 2025/26 onwards in one run: `elo_before`, `elo_after` (the `elo_ratings.csv` rows) |
| Minutes | `models/minutes.py` | Processed tables | `p_appear`, `p_start`, `p_60`, `exp_minutes` |
| Team goals | `models/team_goals.py` | Processed tables, Elo | Per team per fixture: `lambda_for`, `lambda_against`, `lambda_pen`. The phase 1 Elo goals model is its fallback and benchmark, and supplies `fixture_difficulty.csv` until phase 3. It returns `lambda_for`, `lambda_against` and `p_cs` (e^(−`lambda_against`)) for each team's Premier League fixtures in the next `max_horizon` gameweeks; `lambda_pen` comes with the phase 2 team goals model |
| Attack | `models/attack.py` | Minutes, team goals | `xg`, `xa`, `xp_goals`, `xp_assists` |
| Defence | `models/defence.py` | Minutes, team goals | `p_cs`, `exp_gc`, `xp_cs`, `xp_gc`, `xp_dc`, `xp_saves` |
| Bonus | `models/bonus.py` | Minutes, attack, defence | `xp_bonus` |
| Combine | `xp.py` | All of the above | `xp_appear`, `xp_cards`, `xp_total`; writes `projections.csv` |
| Value | `value.py` | Combine | Per player per horizon (1–5): the `player_summary.csv` columns |

- **Elo seeds are point-in-time.** A club entering the Elo run (every club at
  2025/26 GW1, and clubs promoted later) is seeded from its first non-null
  Premier League kickoff Elo in the read. If a club needs a rating and has no
  seed in the read, the Elo component raises an error. That happens at
  2025/26 as-of 0 and 2026/27 as-of 0-1 (`docs/known_gaps.md`).
- Clubs are matched across seasons on `team_code`, never `team_id` (brief
  data rule 6).
