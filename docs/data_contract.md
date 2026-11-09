# Data contract

The canonical schema for every processed table and published output. Copied
from section 5 of docs/brief.md in phase 0 (2026-11-08) and amended on
2026-11-09 with the phase 0 findings (see docs/decisions.md). From now on this
file is the contract: it overrides section 5 of the brief, and changes are
made here first.

**Changing the contract:** an agent proposes the change in its report; the
main session approves or rejects it; on approval this file (and the brief, if
affected) is updated and the change logged in docs/decisions.md before any
code changes; dependent agents are told in their next task message.

## Processed tables

Internal; Parquet in `data/processed/`, not committed.

| Table | Grain | Columns |
| --- | --- | --- |
| `dim_player` | Player, current season | `player_id`, `player_code`, `web_name`, `team_id`, `position`, `price_tenths`, `status`, `chance_next`, `news`, `selected_pct`, `pen_order`, `fk_order`, `corner_order`, `ep_next` |
| `dim_team` | Team | `team_id`, `team_code`, `name`, `short_name`, `elo` |
| `fact_fixture` | Match, all competitions | `match_id`, `season`, `gw`, `kickoff_utc`, `tournament`, `home_team_id`, `away_team_id`, `home_elo`, `away_elo`, `finished`, `home_xg`, `away_xg`, `home_npxg`, `away_npxg`, `home_goals`, `away_goals` |
| `fact_player_match` | Player × match | `player_id`, `team_id`, `match_id`, `minutes`, `goals`, `assists`, `xg`, `xa`, `pens_scored`, `pens_missed`, `tackles`, `interceptions`, `clearances`, `blocks`, `recoveries`, `saves`, `team_gc_on_pitch` |
| `fact_player_gw` | Player × gameweek | `player_id`, `season`, `gw`, `points`, `minutes`, `starts`, `bonus`, `bps`, `yellow`, `red`, `own_goals`, `tackles`, `cbi`, `recoveries`, `defensive_contribution`, `price_tenths`, `selected_pct`, `transfers_in`, `transfers_out` |

### Source notes

The non-obvious mappings, verified on upstream commit 66e73ea in phase 0.
Brief section 4 lists the data rules.

- **Team keys:** in `matches.csv` and `fixtures.csv`, `home_team` and
  `away_team` are team **codes**. Map them through `teams.code` to get
  `home_team_id` and `away_team_id`. These are null for clubs outside the
  Premier League.
- **`fact_player_match.team_id`:** the player's `team_code` in that
  gameweek's snapshot `players.csv`, mapped to `teams.id`. Don't use the
  master `team_history.csv`, because backtest mode never reads master files.
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
- **Elo:** `dim_team.elo`, `home_elo` and `away_elo` are the in-house Elo
  (brief data rule 12). `home_elo` and `away_elo` are the ratings before
  kickoff; `dim_team.elo` is the rating at the snapshot.
- **`fact_fixture`:** `kickoff_utc` comes from `kickoff_time`. That is UTC,
  naive in 2026/27 and offset-stamped in 2025/26, so normalise to ISO 8601
  with `Z`. `home_xg` is `home_expected_goals_xg`, `home_npxg` is
  `home_non_penalty_xg` and `home_goals` is `home_score`; the same applies to
  away.
- **`fact_player_match.minutes`:** `minutes_played`.
- **`fact_player_match.tackles`:** FPL's tackle measure. That is
  `tackles_won` in 2026/27, where total `tackles` is null, and `tackles` in
  2025/26.
- **`fact_player_match` other columns:** `pens_scored` and `pens_missed` come
  from `penalties_scored` and `penalties_missed`. `team_gc_on_pitch` comes
  from `team_goals_conceded`.
- **`fact_player_match` blanks:** blanks mean zero (brief data rule 15). In
  processed matches with minutes > 0, blanks in `goals`, `assists`, `xg`,
  `xa`, `pens_scored`, `pens_missed`, `tackles`, `interceptions`,
  `clearances`, `blocks`, `recoveries` and `saves` are filled with 0.
  `team_gc_on_pitch` is never filled. Upstream's goalkeeper-only
  `goals_conceded` column isn't used.
- **`fact_player_gw` minutes:** `minutes` is FPL's own value from
  `player_gameweek_stats`, which sets the 60-minute threshold. It is not
  `minutes_played`.
- **`fact_player_gw` other columns:** `points` is `event_points`, and `yellow`
  and `red` are `yellow_cards` and `red_cards`. `tackles`, `cbi`
  (`clearances_blocks_interceptions`), `recoveries` and
  `defensive_contribution` are FPL's own counts. `transfers_in` and
  `transfers_out` are `transfers_in_event` and `transfers_out_event`.

## Published outputs

CSV in `outputs/`, committed, read by Excel.

| File | Grain | Columns |
| --- | --- | --- |
| `players.csv` | Player | `player_id`, `web_name`, `team`, `position`, `price_m`, `status`, `chance_next`, `news`, `selected_pct`, `minutes`, `starts`, `total_points`, `ppg`, `xg90`, `xa90`, `dc90`, `pen_taker`, `net_transfers_gw`, `price_change_gw`, `price_change_start` |
| `projections.csv` | Player × gameweek (next 5) | `player_id`, `gw`, `opponent`, `home`, `exp_minutes`, `p_start`, `p_60`, `xg`, `xa`, `p_cs`, `exp_gc`, `xp_appear`, `xp_goals`, `xp_assists`, `xp_cs`, `xp_gc`, `xp_dc`, `xp_saves`, `xp_bonus`, `xp_cards`, `xp_total`, `low_confidence` |
| `player_summary.csv` | Player | `player_id`, `xp_next`, `xp_horizon`, `xp_horizon_weighted`, `replacement_xp`, `xp_above_repl`, `value_per_m`, `xp_per_m`, `ep_next_fpl` |
| `fixture_difficulty.csv` | Team × gameweek | `team_id`, `gw`, `opponent_id`, `home`, `lambda_for`, `lambda_against`, `p_cs`, `is_blank`, `is_double` |
| `optimal_squads.csv` | Budget × player | `budget_m`, `player_id`, `role` (XI or bench), `bench_order`, `is_captain`, `is_vice`, `xp_next`, `xp_horizon` |
| `meta.csv` | One row | `run_utc`, `upstream_commit`, `current_gw`, `next_gw`, `next_deadline_utc`, `model_version`, `horizon`, `decay`, `backtest_mae_model`, `backtest_mae_ep_next`, `status` |

## Conventions

- Column names in snake_case.
- Published prices in £m to one decimal place (`price_m`). Processed tables
  hold integer tenths of £m (`price_tenths`, 55 = £5.5m), and code does all
  price arithmetic in tenths.
- Times in UTC, ISO 8601.
- One row per key, no duplicates.
- In published outputs, nulls only in `news`, `chance_next`, `opponent`
  (null for a blank gameweek) and `value_per_m` (null for minimum-priced
  players). Processed tables may also be null in `home_team_id` and
  `away_team_id` (non-Premier League clubs) and in the source-dependent stats.

## Point-in-time loader

Outside the data-engineer's own code, every agent reads data through
`load_as_of(season, as_of_gw, mode)` in `src/fpl/features.py`. It is the main
guard against leakage.

- **Backtest mode:** the processed tables as they stood at the end of
  `GW{as_of_gw}`, built from that snapshot and earlier. It never reads master
  files and never returns a match after `as_of_gw`.
- **Live mode:** the same, with current status, news, chance of playing and
  price overlaid from the master files.
- `features.py` also holds generic features such as recent minutes and starts.
  Model-specific features live in the model components.

## Component hand-offs

Internal to the model. Each model component exposes a function that takes
`season` and `as_of_gw` and returns a DataFrame, per player per fixture unless
noted. Every output carries its keys: `player_id` (or `team_id`), `match_id`
and `gw`. The model-validator reads `p_60` and `p_cs` from these for its
component checks.

| Component | Module | Depends on | Output columns |
| --- | --- | --- | --- |
| Minutes | `models/minutes.py` | Processed tables | `p_appear`, `p_start`, `p_60`, `exp_minutes` |
| Team goals | `models/team_goals.py` | Processed tables | Per team per fixture: `lambda_for`, `lambda_against`, `lambda_pen` |
| Attack | `models/attack.py` | Minutes, team goals | `xg`, `xa`, `xp_goals`, `xp_assists` |
| Defence | `models/defence.py` | Minutes, team goals | `p_cs`, `exp_gc`, `xp_cs`, `xp_gc`, `xp_dc`, `xp_saves` |
| Bonus | `models/bonus.py` | Minutes, attack, defence | `xp_bonus` |
| Combine | `xp.py` | All of the above | `xp_appear`, `xp_cards`, `xp_total`; writes `projections.csv` |
| Value | `value.py` | Combine | Per player: the `player_summary.csv` columns |
