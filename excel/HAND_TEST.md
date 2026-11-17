# Hand test: the workbook in Windows Excel 365 (task 8)

Run this on Windows with Excel 365. Time needed: about 30 minutes, plus a wait of more than
5 minutes after a publish. Tick a box for each step: `[x]` pass, `[F]` fail, and write what you
saw next to any fail.

**Run it after task 9's first scheduled publish**, so the workbook pulls a real update rather
than the data it was saved with.

**Rules for the whole test**

- Open the workbook, never the raw CSV files, in Excel. The CSVs carry free text from upstream,
  and Excel can run a cell that starts with `=`, `+`, `-` or `@`. To look at a CSV, use GitHub in
  the browser (links below).
- GitHub's raw files are cached for 5 minutes. Always wait **more than 5 minutes** after a
  publish before comparing the workbook with `main`, or you may see the old files, or a mix.

**Where to read the truth on GitHub (the browser, not Excel)**

| What | Where |
| --- | --- |
| Publish times | <https://github.com/Joshc386/fpl-xp-model/commits/main/outputs>. A publish is a commit "chore: publish outputs for upstream ..." by `github-actions`. Its time is the earliest you can expect to see it. |
| `run_utc` | <https://github.com/Joshc386/fpl-xp-model/blob/main/outputs/meta.csv>. Open the page, find the first column of the one data row. (Use the Code view if GitHub shows a table.) |
| `tbl_players` row count | <https://github.com/Joshc386/fpl-xp-model/blob/main/outputs/players.csv>. The page header shows the number of lines. It counts the header line, so players = lines - 1 (672 at `4f8fa36`). |

## A. A stale copy refreshes on open

This is the main pass mark: a copy saved before a newer publish, opened **without pressing
Refresh All**, shows the new `run_utc` and the new row count.

1. Before a scheduled publish (08:00 or 18:00 UTC; runs can be hours late), download
   `FPL_Model.xlsx` from GitHub with your browser (`excel/FPL_Model.xlsx` in the repo, the
   Download raw file button) and save it as `stale_copy.xlsx`. A browser download marks the file
   as from the internet, which is what a new user gets. Don't open it yet.
   - [ ] Done. Note the time you saved it: ____________
2. Wait for the next publish (see the commits link above), then wait **more than 5 minutes**.
   - [ ] Publish commit time: ____________ ; now is more than 5 minutes later.
3. On GitHub, note `run_utc` from `meta.csv` and the line count of `players.csv` (minus 1).
   - `run_utc` on `main`: ____________ ; players rows on `main`: ____________
4. Open `stale_copy.xlsx`. It opens in **Protected View** (a yellow bar). Before clicking
   anything, look at the README sheet: it shows the data the file was saved with.
   - [ ] README "Last updated" is older than the `run_utc` from step 3. Value: ____________
5. Click **Enable Editing**, then **Enable Content** if a Security Warning bar appears, and
   answer the web prompt (section B). Wait for the status bar to finish. Do not press Refresh All.
   - [ ] README "Last updated" now equals `run_utc` from step 3 (to the minute).
   - [ ] Player Database shows "Showing N of N players", where both N equal the players row
     count from step 3. (The second N is the `tbl_players` row count.)

## B. First-open prompts (a new user sees these)

Use a copy that has never been opened. This machine already holds the Anonymous permission
for the web source from earlier use, so **clear it first**, or the third prompt won't appear:

1. In Excel, open any workbook, then Data, Get Data, Data Source Settings.
2. Choose **Global permissions**, select `https://raw.githubusercontent.com/...` (the
   raw.githubusercontent.com entry), and click **Clear Permissions**, then Close.
   - [ ] Done. (If the entry isn't listed, the permission is already clear.)
3. Now open the new copy and go through the three prompts below.

| # | Prompt | What to do | Pass |
| --- | --- | --- | --- |
| 1 | **Protected View**: yellow bar "PROTECTED VIEW ... be careful" on a downloaded copy | Click Enable Editing. Nothing refreshes until you do. | [ ] |
| 2 | **External data warning**: a Security Warning bar about external data connections being disabled | Click Enable Content | [ ] |
| 3 | **Anonymous access**: a dialog asking how to connect to `raw.githubusercontent.com` | Choose **Anonymous**, then Connect. No sign-in is needed. | [ ] |

- [ ] The wording on README ("The first time you open it") matches what you saw. Write any
  difference here: ____________________________________________
- [ ] After the three prompts, the workbook refreshes with no error message.

## C. Offline

1. With the workbook refreshed (end of A), save it and close it.
2. Turn the network off (airplane mode, or unplug).
3. Open the workbook and enable editing and content.
   - [ ] Excel reports that a refresh failed (write the message): ____________
   - [ ] README still shows the last good "Last updated" and gameweek, not blanks or errors.
   - [ ] Player Database still lists all players and filters still work.
   - [ ] Fixture Analysis still shows the grid, and the View switch still works.
   - [ ] No sheet shows `#REF!`, `#N/A`, `#VALUE!`, `#NAME?` or `#SPILL!` anywhere.
4. Turn the network back on and press Data, then Refresh All.
   - [ ] It refreshes with no error.

## D. README

- [ ] "Last updated", "Current gameweek", "Next deadline" and "Model version" match
  `meta.csv` on GitHub (times are UTC).
- [ ] The data credit links to <https://github.com/olbauday/FPL-Core-Insights> and the link opens.
- [ ] The README says to use the workbook, not the raw CSVs.
- [ ] "What each sheet does" lists Player Database and Fixture Analysis, and the sheet names
  are links that jump to those sheets.

## E. The horizon picker (README, yellow cell next to "Horizon (gameweeks)")

Default is 5.

- [ ] Type 6: Excel rejects it with a message. Type 0: rejected. Type 2.5: rejected.
- [ ] Type 3: accepted. Go to Fixture Analysis: three gameweek columns show.
- [ ] Put it back to 5.

## F. Player Database

1. Pick team **ARS** in the Team cell.
   - [ ] "Showing 29 of N players" (29 was the ARS count at `4f8fa36`; after a later publish
     check it against `players.csv` on GitHub, filtered by team ARS). N is the row count from
     section A.
2. Also pick position **MID** and type **6** in Max price.
   - [ ] "Showing 7 of N players" (same caveat). Every row is ARS, MID and £6.0m or less.
3. Delete the three cells (Delete key).
   - [ ] "Showing N of N players" and the full list returns.
4. Type `zzzz` in Search name.
   - [ ] The table goes blank, with "Showing 0 of N players" and no error. Clear it.
5. Type `SA` in Search name.
   - [ ] Names containing "sa" in any case appear. Clear it.
6. Pick status **i**.
   - [ ] Only injured players show, each with an orange Status cell. Clear it.
7. Look at a player with news and one without.
   - [ ] News shows for the first. For the second, News is empty (not `0`).
   - [ ] Chance of playing: a player whose chance is **blank** (FPL sets no flag; most
     available players) shows an empty cell, not `0.0%`. A player with chance 0 (for example
     one who has left the club) correctly shows `0.0%`, and one with 75 shows `75.0%`.
8. Click a locked cell (a player's name) and type.
   - [ ] Excel says the cell is protected. (There is no password.)

## G. Fixture Analysis

1. Open the sheet with View = **Attack** and horizon 5.
   - [ ] 20 clubs, one row each. Columns GW(next) to GW(next+4), then nothing past the horizon.
   - [ ] Each cell shows an opponent's short name and H or A, for example `MCI (H)`.
   - [ ] The Total column is highest at the top and falls going down. Total is the sum of the
     club's goals-expected (`lambda_for`) over the horizon.
   - [ ] Blue means better for you, orange means worse, and the Total column uses the same colours.
2. Switch View to **Defence**.
   - [ ] The note under the title changes to clean-sheet chance. The cells and Total change.
   - [ ] The order of clubs changes, still highest Total first (Total is the sum of `p_cs`).
3. Set the horizon to 1 on README, then return to this sheet.
   - [ ] Only one gameweek column shows, and Total equals that column's value.
4. Set the horizon back to 5.
5. Look for a dash or a `+` in the grid (a blank or a double gameweek).
   - [ ] If one exists: a dash is grey, a double shows both opponents and `= x.xx`. If neither
     exists this time, write N/A. (The build was tested on a sample with both.)
6. Click the "Horizon" link at the top left.
   - [ ] It jumps to the README horizon cell.

## H. Refresh All

- [ ] Data, then Refresh All finishes with no error, and the numbers stay the same or move
  with a new publish.

---

Result: [ ] all pass &nbsp;&nbsp; [ ] failures (list the step numbers): ____________

Tested by ____________ on ____________ (Excel build: File, Account, About Excel) ____________
