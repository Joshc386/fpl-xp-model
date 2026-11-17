# Task 6 plan: the workflows

Status: done (2026-11-16). The first manual run published `4f8fa36`, and the second skipped as it should; see docs/decisions.md. Terms are as in `CONTEXT.md`.

**Spec:** `docs/plans/phase-1.md` task 6, and brief section 11 ("Workflows",
"`update.yml` steps", "When something fails", "Tests").

**Done means (phase 1 plan):** a manual run of `update.yml` on `main` passes
and publishes. Task 7 then builds against those CSVs, and task 9 needs two
consecutive scheduled runs that each publish a new upstream refresh.

## What the code already does

- **`fpl.export` doesn't read the processed tables.** It reads upstream
  through `load_as_of` in live mode, which runs the input checks
  (`validate_inputs`, `validate_tables`). Then it runs the output checks, and
  writes nothing if any check fails.
- **`fpl.run_pipeline` is the only full input check of both seasons.** It
  reads every gameweek of 2025/26 and 2026/27, and it's the only place the
  cross-season match-id check runs. Its tables in `data/processed/` are a
  cache that nothing else reads.
- **The real-data tests skip themselves** when there's no upstream checkout
  (`pytest.mark.skipif` on the folder): five whole test files, and one test
  in `test_elo_check_provenance.py`.
- **Repo settings (checked 2026-11-16):**
  - The repo is public and Actions is enabled.
  - `main` has no branch protection, so the workflow can push to it.
  - The default token is read-only, so `update.yml` has to ask for
    `contents: write` itself.

## `update.yml`

| Item | Plan |
| --- | --- |
| Triggers | Cron `23 8 * * *` and `23 18 * * *` (UTC; `0 8` and `0 18` until 2026-11-17), plus manual runs (`workflow_dispatch`). |
| Permissions | `contents: write` for this workflow only, and nothing else. No secrets. |
| Concurrency | One group, `update`, with `cancel-in-progress: false`, so a manual run queues behind a scheduled one rather than overlapping. |
| Timeout | 15 minutes. |
| Python | 3.13 on `ubuntu-latest`, with the pip cache keyed on `requirements.txt`. It installs `requirements.txt` and `-e .`, not the dev tools. |
| Our checkout | `main`'s tip when the job starts (`ref: main`, not the commit the run was queued at), at depth 1, without keeping the token on disk. |
| Upstream checkout | `olbauday/FPL-Core-Insights` into `data/raw/upstream/repo` (already gitignored). Sparse, cone mode, on `data/2025-2026/By Gameweek` and `data/2026-2027/By Gameweek`, which also brings each season's master files. Depth 1, blobless. This leaves out `By Tournament` and 2024/25. `read_upstream_commit` records the SHA. |
| Skip rule | If the checked-out SHA equals `upstream_commit` in `outputs/meta.csv` on `main`, the run ends green without committing. If there's no `meta.csv` (the first run), it publishes. A small tested Python function makes the decision, not a shell line. |
| Build | `python -m fpl.run_pipeline` (brief steps 4 and 5: input checks for both seasons), then `python -m fpl.export --out-dir $RUNNER_TEMP/outputs` (steps 8 and 9: output checks, then `meta.csv`). Steps 6 and 7, the xP model and the optimiser, join in later phases. |
| Publish | Only after both commands exit 0: copy the files into `outputs/` and commit `outputs/` alone. |
| Commit | Author `github-actions[bot]`. Message `chore: publish outputs for upstream <short sha>`, with the full SHA, `run_utc` and the run's URL in the body. Before pushing, it rebases onto `origin/main` and retries once, aborting a failed rebase first. Runs never overlap and each starts from `main`'s tip, so only code pushes can move `main` during a run, and they never touch `outputs/`. Only the commit step gets the token. |
| Failure | Any non-zero exit fails the job before the commit step, so nothing is published. GitHub emails the failure. |

**Why a rebase rather than failing on a race:** if the main session pushes
code while a run is going, the bot's push is rejected. Failing would email
Josh about something harmless. The cost is that, for one run, the published
outputs come from the code just before the push. The next run catches up.

## `ci.yml`

| Item | Plan |
| --- | --- |
| Triggers | Push to `main`, and pull requests. The bot's publish commits don't trigger it, because pushes made with `GITHUB_TOKEN` never start workflows. |
| Permissions | `contents: read`. |
| Concurrency | Per branch, with `cancel-in-progress: true`. |
| Timeout | 30 minutes. |
| Jobs | Install `requirements-dev.txt` and `-e .` (pywin32 skips itself on Linux), then `ruff check .` and `pytest`. |
| Upstream data | None, so the real-data tests skip (decision 1). |

## Decisions for Josh

1. **CI runs without the upstream data, so the real-data tests skip
   there.** Approved by Josh, 2026-11-16.
   - **Why:**
     - CI stays quick, and doesn't depend on upstream being reachable.
     - The real-data tests still run locally before every commit, which
       the project rules require.
     - `update.yml` reads the real data, with every check, twice a day.
   - **Trade-off:** a change that breaks only on real data isn't caught by
     CI. It's caught at the local run, or at the next `update.yml` run,
     which fails without publishing.
   - **The alternative:** CI checks out upstream at a fixed SHA, so the real
     tests run there too. That costs a large checkout on every push, and
     several minutes on top of the suite. It also means bumping the pinned
     SHA whenever those tests change. Testing against the newest upstream
     instead would fail CI whenever upstream changes, because those tests
     pin row counts.
2. **The first manual run.** After the reviewed workflows are pushed, I
   start the first run on `main` (`gh workflow run update.yml`). It commits
   to the public repo, so I'll ask you before I start it.

## Decided by the main session (say if you disagree)

- **Keep the brief's skip rule as it is:** skip when the upstream SHA hasn't
  changed.
  - **The edge case:** if upstream stops refreshing across a deadline, the
    outputs keep showing the passed gameweek as the next one until upstream
    refreshes. Publishing anyway on a passed deadline would fix that.
  - **Why not fix it:** it would also reset `run_utc`, so the data age would
    look fresh while upstream is stuck. The data age is the signal that
    something upstream is wrong. Upstream refreshes about three times a day,
    so the case is rare.
  - **Next step:** log it in `docs/known_gaps.md`.
- **Pin third-party actions to full commit SHAs,** with the version in a
  comment. `update.yml` can push to `main`, so a moved tag mustn't be able to
  change what runs.
- **Run `fpl.run_pipeline` in `update.yml`, even though export doesn't read
  its tables.** It's the brief's input check of both seasons, and it adds
  seconds.
- **No "force publish" input for manual runs yet.** It's only needed when
  code changes the outputs while upstream hasn't moved, and then the next
  upstream refresh publishes within about half a day. It goes in when phase 2
  first needs it.
- **No coverage gate in CI.** QA checks the 80% target on new code, locally
  and with the real-data tests.

## Order of work

1. **Josh approves this plan,** with decision 1.
2. **Data-engineer, one task.** Tests first for the skip-rule function, then
   `update.yml` and `ci.yml`. Local `pytest` and `ruff`. If `actionlint` is
   available, it lints the YAML. No push.
3. **Review:** Code Review, and `/security-review` on the two workflows
   (Josh's rule for anything that takes outside input and pushes).
4. **Main session:** I read the YAML myself, commit and push. `ci.yml` runs
   on that push and must be green. If a test fails only on Linux, it goes
   back to the agent that owns it; the data-engineer doesn't fix other
   agents' tests.
5. **First manual run,** on your yes (decision 2).
6. **Main session check:**
   - the run is green;
   - the bot's commit holds only `outputs/`, with the upstream SHA in its
     message;
   - `meta.csv`'s values are right for that run;
   - the raw GitHub URLs serve the four CSVs;
   - a second manual run with upstream unchanged ends green with
     `publish=false` and no commit (added after Code Review, 2026-11-16);
   - a local `fpl.export` at the same upstream SHA and `run_utc` gives the
     same files, to within float noise.
7. **Then:** task 7 (the workbook) starts, and task 9 watches the scheduled
   runs.

## Risks and things left for later

- **Late or dropped runs:** GitHub can start a scheduled run late, or drop
  it under load, especially on the hour. Task 9 counts only runs that
  actually happened. The crons moved off the hour, to 08:23 and 18:23 UTC,
  on 2026-11-17, after one run started 7 h 43 min late and the next hadn't
  started 5 hours on.
- **The off-season:** GitHub turns off scheduled workflows in a public repo
  after 60 days without activity. The bot's commits count as activity, but
  in the summer, when upstream stops, the schedule could switch itself off.
  To check before the 2027/28 season.
- **Upstream content is data, never code.** The workflow only reads CSVs
  from upstream with pandas, and the input checks bound them. Power Query
  loads values rather than formulas, so text in a CSV can't run in the
  workbook.

## Steps for Josh

- Approve the plan, or change it, with decision 1.
- Check that GitHub emails you when a workflow fails: Settings, then
  Notifications, then Actions.
- Later, the yes for the first manual run (decision 2).
