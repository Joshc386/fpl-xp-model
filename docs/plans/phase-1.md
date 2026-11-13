# Phase 1 plan: data pipeline and thin slice

Status: reviewed with `/grill-with-docs` on 2026-11-09. Ready for Josh's
go-ahead. Terms are defined in `CONTEXT.md`; decisions are logged in
`docs/decisions.md`.

**Goal (brief section 13):** data reaches the workbook before any modelling
beyond Elo. Phase 1 builds:
- the data-engineer's ingestion, validation, processed tables and
  point-in-time loader;
- the expected-points-modeller's Elo component (ratings and the Elo goals
  model);
- the published `players.csv`, `fixture_difficulty.csv`, `elo_ratings.csv`
  and `meta.csv`;
- `update.yml`, live;
- the Player Database and Fixture Analysis sheets, with the workbook-wide
  horizon picker.

**Done when:**
- the workbook refreshes from GitHub on open;
- processed row counts reconcile with upstream after the documented filters,
  with every dropped row counted by reason;
- tests pass, with at least 80% coverage on new code;
- two consecutive scheduled runs succeed, each publishing a new upstream
  commit;
- the model-validator's Elo component check (brief section 7) passes.

QA checks the first four and the model-validator checks the Elo component.
Neither is the agent that did the work.

## Tasks, in order

Each task is one subagent call. It writes tests first, runs `pytest` and
reports back. Then the Code Review agent reviews it, and only then is it
committed to `main` and pushed. Josh approved pushes for phase 1 on
2026-11-09.

| # | Owner | Task | Needs | Done means |
| --- | --- | --- | --- | --- |
| 1 | data-engineer | **Ingestion and processed tables.** Python 3.13 project setup with pinned dependencies, `config/pipeline.yaml`, `ingest.py` (2025/26 and 2026/27, recording the upstream commit), `validate.py` input checks (brief section 11, step 4, plus the rule 15 guards), and `clean.py` building the five processed tables with every phase 0 rule. Upstream Elo passes through as `upstream_elo`. | None | Tables built for both seasons. Row counts reconcile. Tests cover schemas, join row counts and each cleaning rule. |
| 2 | data-engineer | **Point-in-time loader.** `load_as_of(season, as_of_gw, mode)` in backtest and live modes; the next-gameweek and as-of-gameweek logic from the deadline clock; generic features (recent minutes and starts). | 1 | Leakage tests prove three things: no match after `as_of_gw`; master files are never opened in backtest mode; the two modes are identical apart from the overlaid fields. Deadline-boundary tests cover the cases either side of a deadline. |
| 3 | expected-points-modeller | **Elo component.** `models/elo.py` (from 2025/26 GW1, each season seeded from upstream Elo, settings in `config/model.yaml`, tuned on 2025/26 where upstream Elo is a before-match rating) and the Elo goals model in `models/team_goals.py` (Poisson on the rating gap plus home advantage, fitted only on results up to the as-of gameweek). Both return DataFrames; `export.py` writes the CSVs in task 5. Data is read through `load_as_of`. | 2 | Tests pass. The modeller reports its own calibration numbers, which go to Josh, never to the validator. |
| 4 | model-validator | **Elo component check.** An independent walk-forward test against brief section 7's Elo pass marks. Report in `backtest/reports/`. | 3 | Pass or fail with numbers. A fail returns to task 3. Can run alongside task 5. |
| 5 | data-engineer | **Thin-slice outputs.** `export.py` writes `players.csv` (metrics as defined in `CONTEXT.md`), `fixture_difficulty.csv` (team × fixture, from the Elo goals model), `elo_ratings.csv` and `meta.csv`, plus the output checks from brief section 11, step 8. | 3 | Outputs match the contract and pass validation on the latest snapshot. |
| 6 | data-engineer | **Workflows.** `update.yml` (08:00 and 18:00 UTC plus manual runs; checks out 2025/26 and 2026/27; skips if the upstream commit hasn't changed; publishes `outputs/` only after validation passes) and `ci.yml` (tests and lint). | 5 | A manual run on `main` passes and publishes. |
| 7 | excel-builder | **Workbook.** Power Query M for `players`, `fixture_difficulty` and `meta`, reading raw GitHub URLs on `main` with refresh on open. The `in_horizon` picker (1 to `max_horizon`). The Player Database and Fixture Analysis sheets, plus `build_workbook.py` (COM). | 6 (real CSVs on `main`) | The workbook builds on Windows, and the sheets reconcile with the CSVs. |
| 8 | QA, then Josh | **Phase review.** QA checks every done-when item and test coverage. Josh hand-tests refresh-on-open in Windows Excel. | 1-7 | QA passes. |
| 9 | main session | **Go-live check.** Confirm two consecutive scheduled runs each published a new upstream commit. | 6 | Both runs green. |

**In parallel, outside the gates:** once `elo_ratings.csv` is published
(task 5), Josh compares our Elo ratings with an outside Elo source:
beyondELO's per-match ratings, pulled through its API by a small
data-engineer task (decided 2026-11-13). His verdict gates only the phase 2
Dixon-Coles work. The minutes model can start
as soon as phase 1 is signed off.

## Settled in the plan review (2026-11-09)

1. **Gameweeks:** the next gameweek comes from the deadline clock. A
   gameweek whose deadline has passed never appears in the outputs.
2. **Horizon:** 5 gameweeks are projected, and one workbook-wide picker
   chooses 1-5. Python precomputes value and optimal squads for every
   horizon. There is no decay.
3. **`meta.csv`:** ships in phase 1 with `max_horizon` and without `decay`.
   The backtest MAEs stay blank until the first backtest.
4. **`fixture_difficulty.csv`:** team × fixture. Blank gameweeks have no row,
   and doubles have two.
5. **`players.csv` metrics:** as defined in `CONTEXT.md`.
6. **Runs:** 08:00 and 18:00 UTC. Each publishes the newest upstream commit.
   The 1-hour freshness target is dropped.
7. **Elo:** the expected-points-modeller owns the ratings and the goals model.
   The model-validator judges them, and Josh adds his own outside-source
   comparison.
8. **Git:** each reviewed task is committed straight to `main` and pushed.

## Decided by the main session (say if you disagree)

- **Seasons:** 2025/26 and 2026/27 only. 2024/25 waits until a component
  needs its match-level priors.
- **`backtest.yml`:** waits for phase 2.
- **Player Database:** shows only the `players.csv` columns in phase 1. The
  xP and value columns arrive in phase 3.
- **Review standards from the roster, given to every agent up front:**
  - 80% test coverage on new code;
  - functions under 50 lines and files under 300 lines;
  - logging, not `print`;
  - imports in stdlib, third-party, local order.
- **Agent-file conflicts:** `optimiser.md` mentions decay, and
  `expected-points-modeller.md` lists `xp_horizon_weighted` and decay. The
  brief wins, and both agents are told in their task messages.

## Steps for Josh
- Task 7 needs Windows Excel on this machine.
- Hand-test refresh-on-open in task 8.
- Create a free beyondELO API key (it goes in an environment variable, never
  in code), and run the outside-source Elo comparison once `elo_ratings.csv`
  is published.
