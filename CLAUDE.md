# FPL xP Model

A Python pipeline that predicts FPL expected points (xP) for every Premier
League player over the next 5 gameweeks, recommends transfers and optimal
squads, and publishes the results as CSVs that an Excel workbook reads
through Power Query. Data comes from the upstream FPL-Core-Insights repo,
which refreshes twice daily.

## Sources of truth

* **docs/brief.md** is the spec. Read the sections relevant to your task
before starting.
* **docs/data\_contract.md** defines every table and output schema. Once it
exists, it overrides section 5 of the brief.
* **docs/decisions.md** is the dated log of design decisions and component
hand-off notes.
* If code, an agent file and the brief disagree, the brief wins. Flag the
conflict; never resolve it silently.

## How work is organised

The main session orchestrates. It plans, writes each subagent's task,
reads every report, and is the only place a contract change is approved.

**Agents:** data-engineer, expected-points-modeller, model-validator, optimiser,
excel-builder. The global QA and Code Review agents handle review.

**Delegating:**

* One task per subagent call. Subagents start without this conversation,
so every task message states: the task, the phase, the brief sections to
read, the files in scope, and what "done" means.
* Work in the phase order in brief section 13. A phase starts only after
the previous phase's acceptance criteria are checked, by the
model-validator for phases 2 and 3 and by QA for phases 1, 4 and 5.
* The agent that did the work never signs off its own phase.

**Hard rules:**

* Never forward the expected-points-modeller's report or reasoning to the
model-validator. Give the validator only its task, the commit to test and
the brief.
* Only the excel-builder writes to excel/.
* The main session owns config/scoring.yaml. Fill it from the official
2026/27 FPL rules and cite the source in docs/decisions.md.

## Contract changes

1. An agent proposes the change in its report.
2. The main session approves or rejects it.
3. On approval, update docs/data\_contract.md (and the brief, if affected)
and log it in docs/decisions.md, before any code changes.
4. Tell the dependent agents in their next task message.

## Conventions

* Python 3.13, pandas, pytest. Run `pytest` before reporting a task done.
* No hardcoded constants. Points values go in config/scoring.yaml, model
settings in config/model.yaml, optimiser settings in
config/optimiser.yaml.
* Money is handled in units of £0.1m internally, and output in £m to
one decimal place.
* Times are UTC, ISO 8601. Column names are snake\_case.
* Outside the data-engineer's own code, data is read only through
`load\_as\_of` in src/fpl/features.py.
* Never write to outputs/ by hand; only the workflow publishes. Never commit
data/.
* Keep commits small, one task each, with a message saying what changed and
why.

## Commands

Update this list as each piece is built.

* `pytest`: run all tests
* Full pipeline locally: to be added by the data-engineer in phase 1
* `python backtest/run\_backtest.py`: run the backtest
* `python excel/build\_workbook.py`: build the workbook (Windows, Excel installed)

## Working with Josh

Keep updates short and lead with the result. Raise problems plainly, and if
you think the brief is wrong, say so and say why.

