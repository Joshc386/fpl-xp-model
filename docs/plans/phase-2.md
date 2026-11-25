# Phase 2 plan: xP model v1 and backtest

Status: reviewed with `/grill-with-docs` and approved by Josh on 2026-11-18;
started on 2026-11-19. Terms are defined in `CONTEXT.md`; decisions are
logged in `docs/decisions.md`.

**Goal (brief section 13):** the expected-points-modeller builds the xP
components in order: minutes, team goals, attack, defence, bonus, then the
combined xP. The model-validator builds the walk-forward backtest harness in
parallel.

**Done when:** the acceptance gate in brief section 7 passes on the holdout,
and the report is committed. The model-validator signs off.

**Started:** on 2026-11-19, when phase 1 was signed off after Josh's hand
test. The Elo gate on the Dixon-Coles work passed on 2026-11-18 (Josh's verdict:
not a poor Elo rating).

## Tasks, in order

Each task is one subagent call. It writes tests first, runs `pytest` and
reports back. Then the Code Review agent reviews it, and only then is it
committed to `main` and pushed. Every contract change is approved by the main
session and written to `docs/data_contract.md` before its code. The
data-engineer's tasks run one at a time, because they share `clean.py` and
the contract; so do the modeller's.

| # | Owner | Task | Needs | Done means |
| --- | --- | --- | --- | --- |
| 1 | data-engineer | **FPL goals and assists, and shots.** Adds FPL `goals_scored` and `assists` (from `player_gameweek_stats`) to `fact_player_gw`, for the attack's xA-to-FPL-assists mapping. Builds a shots table and each player's on-pitch spells for 2025/26 and 2026/27 (point 7). | Phase 1 signed off | Built for both seasons. The point 7 checks pass, with every failure counted by reason. |
| 2 | data-engineer | **2024/25 prior season.** Match-level tables joined on `player_code` and `team_code` (point 3). It feeds player priors only, never the Elo or team goals. | 1 | All three point 4 checks pass, or each failure has a cited correction. The FPL API pull runs only after Josh approves its request count and terms. |
| 3 | data-engineer | **Pre-deadline view for both seasons.** Player fields from upstream's last commit before each deadline of 2025/26 and 2026/27 (point 6; 2025/26 added on 2026-11-24), including GW1 if that commit has players. That would close the "can't predict GW1" gap. | 1 | Tests prove that no field comes from after its deadline, and that each value equals what a live run would have read at that commit. |
| 4 | model-validator | **Backtest harness.** `backtest/run_backtest.py`: the walk-forward procedure, evaluation set, three baselines, section 7's metrics and leakage checks (a planted leak and the perturbation test included). It's built against a stub model and the hand-off interfaces. Component diagnostics run as each component lands, with no pass mark (point 1). It never reads 2026/27 before task 11. | Phase 1 signed off | Harness tests pass, with a baselines-only report on 2025/26. Runs alongside tasks 1-10. |
| 5 | expected-points-modeller | **Minutes v1** (point 2), with the double-gameweek rotation discount. The early-season blend is added once task 2 lands. | Phase 1 signed off | Tests pass. The validator's minutes diagnostics on 2025/26 are reported to the main session. |
| 6 | expected-points-modeller | **Team goals v1:** the Elo goals model plus `lambda_pen` (point 5). | Phase 1 signed off (runs after 5) | Tests pass. `lambda_pen` reconciles with team penalty xG on 2025/26. |
| 7 | expected-points-modeller | **Attack:** shot-based shares with shrinkage, penalties apart, and expected FPL assists (brief 6.3). | 1, 5, 6 (2 for the prior) | Tests pass, with validator diagnostics. |
| 8 | expected-points-modeller | **Defence:** clean sheets, goals conceded, defensive contributions and saves (brief 6.4-6.6). | 5, 6 | Tests pass, with validator diagnostics. |
| 9 | expected-points-modeller | **Bonus:** same season only, with the early-season fallback (brief 6.7). | 7, 8 | Tests pass. |
| 10 | expected-points-modeller | **Combine:** `xp.py`, covering appearance, cards, the horizon sum, `low_confidence` and `model_version` (brief 6.8). | 9 | Tests pass. xP for every player in every gameweek of 2025/26. |
| 11 | model-validator | **Phase 2 verdict.** The full backtest on the development window first, then the holdout look, approved by Josh and logged beforehand. | 3, 4, 10 | Pass or fail against section 7's gate, with the report committed. A fail goes back to the modeller, with development-window figures only. |

**Main-session choices in drafting** (flag any you disagree with):
- **The xA-to-FPL-assists mapping** is fitted on this season and last only
  if the official 2025/26 and 2026/27 assist rules match. The main session
  checks before task 7. Otherwise it's fitted on the same season only, as
  bonus is.
- **Before task 11,** the main session runs `/grill-with-docs` on whether the
  gate's calibration rule (±0.3 per bin) should be judged on the evaluation set,
  whose first clause uses gameweek g's actual minutes (brief section 7). Every
  baseline misses the 0-1 bin by more than 1 point on 2025/26 (decided
  2026-11-25).
- **Attack and defence run one after the other,** not in parallel. They
  share the modeller's shrinkage helpers and `config/model.yaml`.
- **Phase 2 publishes nothing new.** `projections.csv`, `player_summary.csv`
  and the backtest MAEs in `meta.csv` come in phase 3 (brief section 13).

## Settled in the plan review (2026-11-18)

1. **Only the end-to-end gate decides (Josh).**
   - No component gets a pass mark of its own.
   - The modeller iterates freely on the development window (2025/26).
   - As each component lands, the model-validator reports diagnostics on
     the development window only, with no pass mark, for example the Brier
     score for `p_60` against a simple baseline.
   - The holdout (2026/27) is scored once, at phase sign-off: one holdout
     look.
   - Why: it matches brief section 7 and Josh's steer to keep component work
     in proportion. Component pass marks proved hard to set in phase 1.
   - The risk: a weak component is flagged, not stopped, so the main session
     must act on a poor diagnostic.
2. **Minutes v1 stays lean (Josh).**
   - **Inputs:** recency-weighted starts and minutes from `recent_minutes`
     (weights in config), then the availability override from `status` and
     the chance of playing (brief section 6.1).
   - **Outputs:** `p_start` is the weighted start rate. `p_appear` adds the
     bench-appearance rate. `p_60` comes from how often a start reaches 60,
     and `exp_minutes` from minutes given a start or a bench appearance.
   - **Deferred to v2:** the `news` text, days since the last match, and cup
     and European minutes. Brief section 6.1 now says which inputs are v1.
   - The risk: v1 misses rotation around European weeks. The validator's
     minutes diagnostics are split by clubs in Europe and the rest, to show
     whether it matters.
3. **2024/25 is loaded as 2025/26's prior season, checked against a source
   when loaded (Josh).**
   - Why: the early-season blend's k (brief section 6, "Horizon and
     aggregation") can't be tuned on 2026/27, which is the holdout. With
     2024/25 as 2025/26's prior, k is tuned on 2025/26's early weeks, which
     face the same position as the holdout's.
   - **What exists:** upstream's 2024/25 is match-level only (data rule 13):
     per-match minutes, start times, xG and xA, players with `player_code`,
     and team xG and non-penalty xG. It has no FPL gameweek points, bonus or
     fixtures file.
   - **How:** a data-engineer task early in phase 2, with a contract change
     for the new table. Minutes v1 doesn't wait for it; the blend is added
     when it lands.
   - **Checked when loaded:** the 2025/26 Liverpool v Man Utd score was
     wrong upstream (data rule 16), so the load is checked against an
     outside source before anything uses it (point 4).
4. **What the 2024/25 load is checked against (Josh): all three, and any
   breach fails the build.**
   - **Scores against beyondELO:** its 2024/25 Premier League matches
     (about 4 requests through the existing client, cached, CC BY 4.0), and
     against upstream's own player goals. A mismatch needs a cited
     `score_corrections` entry, as in data rule 16.
   - **Internal rules on player rows:** 11 starters per club per match;
     minutes in range; players' xG summing to the team's within a tolerance;
     each player's club one of the match's two clubs.
   - **Season totals against FPL's API:** minutes, goals and assists for
     players still in FPL, against the sums of upstream's per-match rows.
     The data-engineer reports the request count and FPL's terms of use
     first, and Josh approves before anything is pulled.
5. **Team goals v1 is the Elo goals model, plus `lambda_pen` (Josh).**
   - `lambda_pen` is the team's expected penalty goals: team xG minus
     non-penalty xG, shrunk toward the league average (brief section 6.2).
   - Dixon-Coles becomes the v2 method. It's built only if the first full
     backtest's weakest areas point at team goals, with that backtest as its
     regression test.
   - Why: naive but correct first. It gets an end-to-end xP and backtest
     soonest, fits Josh's steer on proportion, and defers scipy.
   - The cost: v1's team goals use results, not xG, and keep the known gap
     on home advantage early in a season.
6. **The holdout gets a rebuilt pre-deadline view of each player (Josh).**
   - **The problem:** in 4 of 2026/27's first 10 gameweeks, the GW{g−1}
     snapshot was written after the g deadline. By then FPL's "next round"
     fields describe g+1, so `chance_next` misleads the minutes model and
     `ep_next` may be FPL's projection for g+1. Status can also include
     injuries from GW g's own matches.
   - **The fix:** for each 2026/27 gameweek g, status, chance of playing,
     news, price and `ep_next` come from upstream's `playerstats.csv` at its
     last commit before the g deadline, which is what a live run would have
     seen. The model and the `ep_next` baseline both use it, so every
     holdout gameweek counts in the gate. The upstream checkout has the full
     history: 306 commits since 2026-08-01, about three a day.
   - **How:** a data-engineer task with a contract change. It must land
     before the holdout look.
   - **Extended to 2025/26 (Josh, 2026-11-24).** The model-validator's
     snapshot-timing audit (task 4) found that upstream's git history keeps
     a version of every 2025/26 snapshot from before its deadline. Today's
     files were rewritten later: GW1's on 2025-12-13, so its `ep_next` is for
     GW16, and GW2-10's on 2025-11-19, with most available players at a
     chance of 0. So the development window gets the same pre-deadline view,
     and the modeller tunes on what a live run would have seen.
7. **Attack measures on-pitch team xG from shot data (Josh).**
   - **How:** upstream's `shots.csv` (2025/26 and 2026/27) gives each shot's
     match, minute, player, situation and xG. Each player's on-pitch spells
     come from `incidents.csv` in 2025/26 and from his start and finish
     minutes in 2026/27. (Changed on 2026-11-23: 2025/26's start and finish
     minutes hold no substitution times in 157 of 380 matches.) A player's
     share uses his team's non-penalty xG during his spells (brief section
     6.3).
   - **Penalties** are identified from each shot's situation, so penalty xG
     comes from the shots themselves, not from penalty attempts × 0.7884.
   - **Checks when built**, in line with point 4: penalty shot xG
     reconciles tightly with `matches.csv` team xG minus non-penalty xG, and
     total shot xG loosely with team xG, because the two files carry
     different xG measures. On-pitch minutes agree with FPL minutes, so
     unused substitutes get no spell (brief data rule 2). The full list is in
     `docs/data_contract.md` (decided 2026-11-23).
   - **Limit:** in 2026/27 about one shot in nine has no player id
     (`docs/known_gaps.md`).
   - **Limit:** 2024/25 has no shot data, so its prior-season shares use the
     match xG × minutes ÷ 90 approximation. That affects only 2025/26's early
     weeks; 2026/27's prior is 2025/26, which has shots.
   - Why: Josh chose the best-quality measure over the quicker one.
