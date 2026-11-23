# Phase 2 task messages: drafts for tasks 1 and 4

Drafted 2026-11-18 while Josh runs the hand test. Neither is sent until
"main - phase 1 signed off" is logged in `docs/decisions.md`. Task 1 goes in
two steps, because its contract change has to be approved and written before
any code (CLAUDE.md, "Contract changes").

---

## Task 1, step A (data-engineer): propose the contract change

**Task:** phase 2, task 1, step A. Propose the contract change for FPL goals
and assists, a shots table and each player's on-pitch spells. **Write no code
in this step.** You build it in step B, once the main session has approved
the change and written it into `docs/data_contract.md`.

**Phase:** phase 2 builds xP model v1 and its backtest. Phase 1 is signed off.
The plan is `docs/plans/phase-2.md`. This is its task 1, and you do tasks 2
and 3 later, one at a time.

**Why it's needed:** the attack component (task 7) measures a player's share
of his team's non-penalty xG while he's on the pitch, from shot data. It also
maps xA to FPL assists. It needs three things the processed tables don't have:
1. FPL's own `goals_scored` and `assists` per player per gameweek, from
   `player_gameweek_stats`. `fact_player_match.goals` and `assists` are
   upstream's match-stats counts, not FPL's, and FPL assists are wider than xA
   (brief 6.3, last bullet).
2. A shots table for 2025/26 and 2026/27, from `By Gameweek/GW{x}/shots.csv`.
   It needs each shot's match, minute (with added time), player, team,
   situation and xG. Penalties are identified from `situation`.
3. Each player's on-pitch spells per match, from `start_min` and `finish_min`
   in `playermatchstats`, with FPL minutes ruling out unused substitutes
   (brief data rule 2).

**Read first:**
- `docs/plans/phase-2.md`: point 7 in full, and the task table.
- `docs/brief.md`: section 4 (data rules 2, 5, 6, 9, 13 and 15 especially),
  section 6.3, and section 7's leakage checklist.
- `docs/data_contract.md`, in full.
- `docs/decisions.md`: the `data - ...` and `main - ...` entries.
- Upstream's README and `scripts/clean_playermatchstats.py`, before you trust
  `start_min` and `finish_min`.

**What to do:**
1. **Inspect the real files for both seasons first:** columns, types, nulls,
   row counts and sample rows. Check these rather than assume them:
   - `shots.csv` `player_id` is an integer in 2025/26, and a float (`14.0`)
     with a blank `player_name` in 2026/27. Check that it's FPL's
     `player_id`, and that every shot's player has a `playermatchstats` row
     in that match.
   - A shot at 90+7 is `minute` 90 with `added_time` 7. Check how
     `start_min` and `finish_min` treat added time in both halves, so an
     added-time shot goes to the players who were actually on the pitch.
   - Whether every complete match has a shots file with rows, and how
     `is_home` maps to a team.
2. **Propose the contract change** in your report: new columns, new tables,
   grain, key, source mapping, null rules and drop reasons. Name the FPL
   columns so they can't be confused with `fact_player_match.goals` and
   `assists`.
3. **Propose the build-time checks** from point 7, each with its tolerance
   (in `config/pipeline.yaml`) and every failure counted by reason:
   - shot xG per team per match against `matches.csv` team xG, and
     non-penalty shot xG against team non-penalty xG;
   - on-pitch minutes against FPL minutes, with no spell for an unused
     substitute.
   Run each check on the real data now, in a scratch script outside the repo
   (not committed code). Report the actual spread of differences, so each
   tolerance rests on evidence, and list which matches would fail and why.
4. **Say how the new tables go through `load_as_of`,** so that backtest mode
   never returns a shot or a spell from a match outside the read.

**What your new checks must not break:** the validator's perturbation test.
`backtest/perturb.py` corrupts scores, finished flags, upstream Elo and xG in
`matches.csv` and `fixtures.csv` after an as-of gameweek. It expects every
read to succeed and the Elo outputs to stay the same. A shot-xG
reconciliation over the whole season would fail on that corrupted copy. Say
how your checks avoid this.

**Holdout rules:** data checks on 2026/27 data are fine. Never compute or
report model or baseline scores on 2026/27. Don't open
`backtest/reports/*-beyondelo.md`. Don't pull the upstream checkout (it's at
`ac8be9c`); the main session decides when it moves.

**Done means:** your usual report, with a "Proposed contract changes" section
specific enough for the main session to write `docs/data_contract.md` from
it, and the check results on real data. No changes to `src/`, `tests/` or
config, and no commit.

---

## Task 1, step B (data-engineer, by `SendMessage`): build it

*Filled in once the contract change is approved. It names the decisions
entry and any change from the agent's proposal.*

**Task:** phase 2, task 1, step B. Build the approved contract change, which is
now in `docs/data_contract.md` (decisions entry "YYYY-MM-DD: main - task 1
contract change"). Changes from your proposal: ...

**Red-green-refactor** (you can't run `/tdd`, so here it is):
1. Red: for each behaviour, write one failing test first. Run it and see it
   fail for the right reason.
2. Green: write the least code that makes it pass.
3. Refactor: tidy up with the tests green. Then the next behaviour.

Use small samples cut from real upstream files, kept in `tests/fixtures/`.

**Tests must prove:**
- row counts before and after every join;
- each check fails on a planted mismatch and passes on the real data;
- backtest mode never returns a shot or spell from a match outside the read
  (extend the loader leakage tests);
- an unused substitute has no spell;
- the Elo check's perturbation tests still pass (`tests/test_elo_check_perturb.py`
  and the others that use `backtest/perturb.py`).

**Files in scope:** `src/fpl/ingest.py`, `validate.py`, `clean.py` and
`features.py` (plus a new module under `src/fpl/` if a file would take on a
second job), `config/pipeline.yaml`, `tests/`, and a `data - ...` entry in
`docs/decisions.md`. Out of scope: `src/fpl/models/`, `backtest/`, `excel/`,
`outputs/`, `config/model.yaml` and `config/scoring.yaml`.

**Runs:**
- `.venv/Scripts/python -m fpl.run_pipeline` on the local checkout, unpulled;
- `.venv/Scripts/python -m pytest --cov`, the full suite (7-10 minutes; run
  it in the background and read the log before calling a stop a failure);
- `.venv/Scripts/ruff check .`.

**Done means:**
- built for both seasons;
- the point 7 checks pass on real data, with every failure counted by reason;
- the full suite is green and ruff is clean;
- a `data - ...` decisions entry;
- your report gives row counts per new table and per drop reason.

Don't commit: the main session commits after Code Review.

---

## Task 4 (model-validator): the backtest harness

**Task:** phase 2, task 4. Build the walk-forward backtest harness,
`backtest/run_backtest.py`, against a stub model, and run it with the
baselines only on the 2025/26 development window.

**Phase:** phase 2 builds xP model v1 and its backtest. Phase 1 is signed off.
The plan is `docs/plans/phase-2.md`. This task runs alongside the
data-engineer's task 1 and the modeller's minutes work. No model component
beyond phase 1's Elo exists yet, so build against the data contract's
Component hand-offs.

**Read first:**
- `docs/brief.md`: section 7 in full, section 5 for the output columns, and
  section 6 only for what each component says it outputs.
- `docs/data_contract.md`, especially "Point-in-time loader" and "Component
  hand-offs".
- `docs/plans/phase-2.md`: points 1, 2 and 6, and the task table.
- `CONTEXT.md`: **Development window**, **Holdout look**, **ep_next**,
  **As-of gameweek** and **Next gameweek**.
- `docs/decisions.md`: the `main - ...` and `data - ...` entries only.

**Build:**
1. **The walk-forward procedure** (section 7). For each target gameweek g of
   2025/26, predict g from `load_as_of(season, g − 1, "backtest")` alone, and
   score it against `fact_player_gw` points for g. Runs are deterministic and
   record the git commit, `model_version`, the upstream SHA and a hash of
   `config/model.yaml` (reuse `backtest/provenance.py`).
2. **The evaluation set,** exactly as section 7 defines it, identical for
   every predictor. Section 7 says the rule uses only what's known before the
   deadline, but its first clause (actual minutes > 0 in g) doesn't. Build it
   as written: it uses no model's output, so it's still fair to every
   predictor.
3. **The three baselines:** `ep_next` from the GW g − 1 snapshot
   (`dim_player.ep_next` at as-of g − 1), the last-5-gameweek average, and
   season points per game. Define each one precisely in the report, including
   how a blank or double gameweek counts.
4. **Every metric in section 7's table,** with GW1-5 of the season reported
   separately. Compute the acceptance gate too, labelled as a dry run: it is
   decided only on the holdout.
5. **Snapshot timing** (section 7, "Known limitation"): check whether each
   2025/26 snapshot's `ep_next` refers to g or g + 1. Choose and state the
   method, and report the late snapshots separately.
6. **Component diagnostics, with no pass mark** (point 1). Build them against
   the hand-off interfaces, so they run as each component lands. The first is
   the Brier score for `p_60` from `models/minutes.py`, against a simple
   baseline of your choice that uses only what was known before the
   deadline. Split it by clubs in Europe that season and the rest (point 2).
   The clean-sheet and goals bins follow with team goals and defence.
7. **Leakage checks:**
   - section 7's checklist;
   - a planted-leak test: a deliberately leaky stub that the checks must
     fail;
   - the perturbation test, extended to every file the model can read.
     Today `backtest/perturb.py` corrupts results in `matches.csv` and
     `fixtures.csv` only. xP also reads `player_gameweek_stats`,
     `playermatchstats`, `playerstats` and, after task 1, `shots.csv`.
     Extend it without breaking the Elo check's use of it.

**The model interface:** the contract fixes each component's output columns
and its `(season, as_of_gw, mode)` signature. It doesn't fix `xp.py`'s
function name, or whether it returns rows per fixture or per gameweek. Build
against a stub. If the harness needs something the contract doesn't fix,
propose it under "Proposed contract changes" rather than block. The modeller
then builds to what the main session approves.

**Holdout rules:**
- This task never reads 2026/27. The harness refuses to score 2026/27 unless
  it is given an explicit holdout switch, and a test proves it. The holdout
  look is task 11, approved by Josh and logged beforehand.
- For 2026/27, status, chance of playing, price and `ep_next` will come from
  task 3's pre-deadline view, not the snapshot. Keep the place where the
  harness reads them in one spot, so that the view can replace it.
- You don't need `backtest/reports/*-beyondelo.md`, so don't open it.

**Red-green-refactor** (you can't run `/tdd`, so here it is):
1. Red: for each behaviour, write one failing test first. Run it and see it
   fail for the right reason.
2. Green: write the least code that makes it pass.
3. Refactor: tidy up with the tests green. Then the next behaviour.

**Files in scope:** `backtest/` (`run_backtest.py` as the entry point, plus
new modules as needed), `backtest/config.yaml` (the evaluation and metric
settings, such as top-N and the calibration bins), harness tests in `tests/`,
and the new report in `backtest/reports/`. Out of scope: `src/`,
`config/model.yaml`, `config/scoring.yaml`, `docs/data_contract.md`, `excel/`,
`outputs/` and `CLAUDE.md` (put the run command in your report, and the main
session adds it).

**Runs:**
- the harness, with the baselines only, on 2025/26. Write the report to
  `backtest/reports/{YYYY-MM-DD}-baselines.md`. Don't write `latest.json`,
  because phase 2 publishes nothing new;
- `.venv/Scripts/python -m pytest --cov`, the full suite (7-10 minutes; run
  it in the background and read the log before calling a stop a failure);
- `.venv/Scripts/ruff check .`.

**Done means:**
- the harness tests pass, including the planted leak and the extended
  perturbation test;
- a baselines-only report on 2025/26 with every section 7 metric for the
  three baselines;
- the full suite is green and ruff is clean;
- your usual report (Verdict: "none, harness build"), stating the model
  interface you built against.

Don't commit: the main session commits after Code Review.
