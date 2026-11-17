# FPL xP Model

Predicts each Premier League player's expected FPL points (xP) for each of
the next five gameweeks, and turns them into value rankings, transfer
suggestions and an optimal squad over a horizon the user chooses, shown in an
Excel workbook.

## Language

### Gameweeks and time

**Gameweek**:
One FPL scoring round, numbered 1-38, in which a team may play zero, one or
two fixtures.
_Avoid_: round, matchweek

**Deadline**:
The time after which transfers, captain picks and team changes no longer count
for a gameweek: 90 minutes before its first kickoff.
_Avoid_: lock, cutoff

**Fixture**:
A Premier League match in the FPL schedule; it belongs to exactly one
gameweek, which can change if it is rescheduled.
_Avoid_: game, tie

**Match**:
Any competitive game a team plays, in any competition. Only the Premier
League ones are fixtures. A cup or European match belongs to the gameweek
it was played in, the one whose deadline most recently passed before
kickoff, whatever folder upstream files it in.
_Avoid_: fixture (for cup or European games)

**Complete match**:
A finished match whose team xG and player rows (for each of its Premier League
clubs) are present. Only complete matches supply xG and player match stats;
results, for the Elo ratings, come from every finished match. Upstream's
"processed" flags are not used: they stay false on matches whose data is
complete.
_Avoid_: processed match, completed match, played match

**Blank gameweek**:
A gameweek in which a team has no fixture, so its players score 0.
_Avoid_: blank week, free week

**Double gameweek**:
A gameweek in which a team has two fixtures; a player's xP is the sum over
both.
_Avoid_: DGW (in prose), double week

**Next gameweek**:
The first gameweek whose deadline is after the run time, and the first
gameweek of every horizon.
_Avoid_: current gameweek, upcoming gameweek, target week

**Horizon**:
The number of gameweeks, starting at the next gameweek, that xP is summed
over: 1 to 5, chosen by the user for the whole workbook, with a default of 5.
_Avoid_: window, lookahead, planning period

**As-of gameweek**:
The gameweek before the next gameweek: the latest gameweek whose data a run
may use, possibly only part-played.
_Avoid_: current gameweek, latest gameweek

### Points

**xP**:
The model's expected FPL points for a player in one gameweek, summed over
that gameweek's fixtures; 0 in a blank gameweek.
_Avoid_: projected points, EP

**Horizon xP**:
The plain, unweighted sum of a player's xP over the gameweeks in the horizon.
_Avoid_: weighted xP, decayed xP, total xP

### Team strength

**Elo rating**:
The model's own strength rating for a club, updated after every Premier
League result from 2025/26 GW1 on. Each season starts from upstream Elo where
there is one: 2025/26 from each club's GW1 value, and 2026/27 from ClubElo's
end-of-season 2025/26 rating (promoted clubs from their 2026/27 GW1-2 value).
A club with no upstream value carries its own rating into the next season.
_Avoid_: ClubElo, strength, Elo (unqualified)

**Upstream Elo**:
ClubElo's rating at kickoff, as published by upstream. It is a genuine
before-match rating only in 2025/26 GW1-26 and GW33. In GW27-32 it is stuck
at the GW26 value. From GW34 it is ClubElo's end-of-season rating, which
already includes later results. The 2026/27 GW1-2 values repeat that
end-of-season rating, and it is null from 2026/27 GW3. It is used only for
seeds and, where it is a before-match rating, as the target the Elo rating is
tuned and checked against.
_Avoid_: Elo (unqualified), ClubElo rating

**beyondELO rating**:
beyondELO's club rating before and after each Premier League match, pulled
through its API (`ext_beyondelo`). It is an outside check, never a seed or a
model input.
_Avoid_: outside Elo, BE rating, Elo (unqualified)

**Outside-source Elo check**:
Josh's comparison of the **Elo rating** with the **beyondELO rating** on the
matches where **Upstream Elo** can't serve as a check. Predictive log-loss
decides it; ranking agreement is reported as a diagnostic with no pass mark.
The verdict uses every scored match. Figures without matches involving a
**promoted club** are reported alongside, without a verdict of their own.
_Avoid_: beyondELO comparison, Elo comparison

**Promoted club**:
A club in a season's Premier League that wasn't in the previous season's.
beyondELO doesn't rate the Championship, so its **beyondELO rating** starts
from the club's last Premier League spell.
_Avoid_: new club, newly promoted team

**Predictive log-loss**:
How well a rating's before-match gap predicts the result (home win, draw or
away win). Each rating source gets its own ordered logistic fit of result on
the gap (home minus away), so scale and average home advantage drop out.
Numerator: the sum over scored matches of −ln(probability given to the
actual result). Denominator: the number of scored matches. Unit: nats per
match; lower is better. Time window: fitted once per source on 2025/26
GW1-26; scored on 2025/26 GW27-38 and 2026/27 from GW3, reported per window
and pooled. The verdict uses the pooled figure.
The no-skill baseline is the same fit with no gap, which predicts the
league's home, draw and away rates.
_Avoid_: log-loss (unqualified), accuracy

**Ranking agreement**:
Spearman's rank correlation between the **Elo rating** and the **beyondELO
rating** before kickoff, over one gameweek's team-kickoffs (usually 20; a
double gameweek counts each kickoff). No unit, from −1 to 1. Time window:
each gameweek of the scored windows, reported with each window's median and
minimum and its five biggest rank disagreements at the last gameweek. A
diagnostic of the **outside-source Elo check** with no pass mark.
_Avoid_: correlation (unqualified), rating agreement

**Holdout look**:
Any scoring of the model or a component on 2026/27 to date (the holdout).
Each one is approved by Josh and logged in `docs/decisions.md` before it
runs. Its 2026/27 figures go to Josh and the main session only, never to an
agent that builds or tunes the thing scored. The **outside-source Elo
check**'s 2026/27 window is the third look: it runs once, and runs again
only after a **poor Elo rating** and a rebuild.
_Avoid_: test-set peek, validation run

**Poor Elo rating**:
The **outside-source Elo check**'s fail verdict, on the pooled scored
windows. It is reached in either of two ways:
- the mean of the per-match differences (our **predictive log-loss** minus
  the **beyondELO rating**'s) is above zero by more than two standard errors
  (the differences' standard deviation ÷ √matches);
- our **predictive log-loss** isn't below the no-skill baseline's.

It means a separate Elo agent rebuilds the Elo component before phase 2's
Dixon-Coles work starts.
_Avoid_: bad Elo, Elo fail

**Fixture difficulty**:
A team's expected goals for (`lambda_for`), expected goals against
(`lambda_against`) and clean-sheet probability (`p_cs`) in one fixture.
_Avoid_: FDR (FPL's own 1-5 rating), fixture rating

**ep_next**:
FPL's own expected points for a player in the next gameweek; the benchmark
the model must beat.
_Avoid_: EP, FPL xP

### Player metrics (`players.csv`)

Unless stated, every metric covers **season to date**: the current season's
Premier League fixtures up to the as-of gameweek, finished fixtures only.
Per-match stats (xG, xA) use complete matches only.

**Appearance**:
A fixture in which the player played at least one minute.

**Minutes, starts, total points**:
Season-to-date totals from FPL's own per-gameweek figures. Units: minutes,
count, FPL points.

**PPG**:
Total points ÷ appearances, matching FPL's own figure. Unit: points per
appearance.

**xG90 / xA90**:
Σ xG (or xA) ÷ Σ minutes × 90, using the match-data xG and xA that the model
uses, not FPL's `expected_goals`. The minutes are `minutes_played` in the same
complete matches as the xG, not FPL's minutes, so a match whose xG isn't loaded
yet counts in neither. 0 when minutes are 0. Unit: per 90 minutes.

**DC90**:
Σ FPL defensive-contribution count ÷ Σ minutes × 90. The count is CBIT for
defenders and CBIRT for midfielders and forwards; goalkeepers are always 0.
0 when minutes are 0. Unit: actions per 90 minutes.

**Penalty taker**:
True when the player is first on FPL's penalty order.

**Net transfers (GW)**:
FPL transfers in minus transfers out since the last deadline. Unit: managers.

**Price change (GW / start)**:
FPL price change since the last deadline, or since the season started. Unit:
£m to one decimal.

### Operations

**Upstream refresh**:
A new commit to the FPL-Core-Insights data repo; about three a day, at
drifting times.
_Avoid_: upstream update, data drop

**Run**:
One scheduled pass of the update pipeline, at 08:23 or 18:23 UTC daily
(GitHub may start it late or drop it). It publishes only when there is a new upstream refresh and every validation
passes.
_Avoid_: job, build, refresh (in Excel, "refresh" means reloading the CSVs)

**Data age**:
The time since the run that produced the workbook's data: now minus
`meta.run_utc`. Unit: hours. Flagged red above 24.
_Avoid_: freshness, staleness

## Relationships

- Each **Gameweek** has exactly one **Deadline**.
- A team has zero, one or two **Fixtures** in a **Gameweek** (a **Blank**,
  normal or **Double gameweek**).
- Each club has one **Elo rating** before each **Fixture**. The gap between
  the two clubs' ratings, plus home advantage, gives each side's
  **Fixture difficulty**.
- Each **Fixture** has two **Fixture difficulties**, one per team. A
  gameweek's or a horizon's difficulty is the plain sum over its fixtures.
- The **As-of gameweek** is always the **Next gameweek** minus one.
- A run with **As-of gameweek** g also sees cup and European **Matches**
  that kicked off before the GW g+1 **Deadline**, wherever upstream files
  them. It never sees later cup or European ties.
- Only the finished matches of the **As-of gameweek** feed a run. A player's
  gameweek figures count once all their club's fixtures in it are finished,
  and their match stats once each match is a **Complete match**.
- Each **Run** publishes the newest **Upstream refresh** that existed when it
  started, or nothing at all.
- A **Horizon** of h covers the **Next gameweek** and the h - 1 gameweeks
  after it. A horizon of 1 means the **Next gameweek** only.
- Exactly one **Horizon** is in force across the workbook at any time:
  every xP total, value ranking, optimal squad and transfer check uses it.

## Example dialogue

> **Dev:** "It's 18:00 on Saturday and GW11 kicked off at 12:30. What's the
> **next gameweek**?"
> **Domain expert:** "GW12. GW11's **deadline** has passed, so nothing we
> predict for it can change a decision. GW11 is now the **as-of gameweek**,
> and only its finished matches count."

## Flagged ambiguities

- "Current gameweek" (FPL's `is_current`, `meta.current_gw`) means the
  **as-of gameweek**, not the gameweek being predicted.
- "EP" means FPL's **ep_next** only; the model's figure is always **xP**.
- "Elo check" has two meanings. The model-validator's **Elo component
  check** (task 4, brief section 7) tests the Elo rating against ClubElo and
  results, with pass marks. The **outside-source Elo check** compares it with
  the **beyondELO rating**, and its verdict gates phase 2's Dixon-Coles work.
  Name the one you mean.
- Bare "Elo" is ambiguous. Say **Elo rating** for ours and **Upstream Elo**
  for ClubElo's. FPL's own team "strength" ratings are a third, unrelated
  measure.
- The processed table `fact_fixture` holds **matches** from every competition,
  despite its name; only its Premier League rows are **fixtures**.
- There is no weighting or decay across a horizon: a **Horizon xP** of 5
  counts GW+5 the same as the **next gameweek** (decided 2026-11-09).
  "Time decay" in the Dixon-Coles team-goals fit is a different idea: it
  down-weights *past* matches when fitting, and stays.
- Upstream's `is_current` and `is_next` flags are not used to find the
  **next gameweek**: they update only when upstream refreshes, hours after a
  deadline.
