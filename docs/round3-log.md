# Round 3 decisions

The decisions made during the round 3 build on Saturday, Nov 14, 2026 (times are CST), with the reason for each. What each ticket built is in `docs/HISTORY.md`.

- **9:01 PM. Round 3 is four tickets:** #37 (SLP view with A, D and L keys), #38 (proof banner), #39 (checked notes and a family note), #40 (replay). Each one has a place in `docs/round3-demo-script.md`: a beat, the setup checklist, or the backup plan.
- **9:01 PM. #22 (practice coach, part 2) waits** until #37, #38 and #39 are merged and run on the board, by Mon Nov 16. New practice work should sit on a base the board has checked.
- **9:01 PM. The family note is written live by Qwen, with a checked fixed note as the fallback.** Qwen can fail a check, time out or be off; the fixed note always shows something true, and its text sits in one file Lexi can check.
- **9:01 PM. The SLP view and the proof banner each get three mockups first, and the owner picks.** Both are visual, so the repo's visual rule applies.
- **9:01 PM. A PR merges only after a separate reviewer says MERGE for its exact head commit,** and the merge is pinned to that commit (`--match-head-commit`). What was reviewed is what lands.
- **9:06 PM. SLP view: the question card (mockup C),** with the evidence open by default. It asks the SLP one question, agree or disagree with Arti, which fits one key per answer.
- **9:21 PM. Proof banner: the tile bar (mockup C), fixed to the bottom,** with space kept under the page so it never covers the SLP's buttons.
- **9:22 PM. The app may use numpy; no new dependency.** Main's app code already imported numpy, so "standard library only" in STATE.md was stale. The docs fix went into the round 3 docs ticket (#47), not a ticket of its own.
- **9:24 PM. #40 merged with practice under replay left as it is.** In practice, a word that has no saved clip blocks the way to the next word; a "skip word" button would be a new feature, so it is the owner's call.
- **9:35 PM. A pushed branch is brought up to date by merging main into it, never by a rebase or a force push.** A force push would change commits a reviewer already read.
- **9:35 PM. #38 merged with two small gaps left as follow-ups:** if llama.cpp reports its speed as `-nan`, the Qwen tile empties again, and the watts box refuses a number with a trailing point such as "5.". Neither shows a wrong number.
- **9:42 PM. #37 merged with the first-open database race left as a follow-up.** The older column upgrade has the same race, so it was not new.
- **9:42 PM. When main is merged into a branch, the merge commit gets the message `#N merge origin/main` and the Co-Authored-By trailer.** #44's merge of main kept git's own text, which names no issue; this rule makes every commit on a branch point back to its ticket.
- **10:10 PM. The owner asked for a polish of the SLP word page, opened as #45.** Scope: `/word` and the proof bar. The bar folds the values not measured yet into one quiet line, because four "not measured yet" tiles read as broken. Until #39 merged, the polish changed only styles and added functions of its own, so it could not clash with #39's edits to the same files.
- **10:25 PM. The owner picked none of the three #45 mockups.** Instead, the live page was improved in scored rounds, one change at a time, against a written list.
- **10:25 PM. The SLP note's sentences became an allowed list.** Review after review found new false claims in open wording; a short list of allowed sentence forms closes the whole class, at the cost of Qwen notes failing a little more often (the end screen then shows the tally without a note).
- **10:40 PM. #39 merged with the reviewer's last notes left as follow-ups.** None of them lets a note make a false claim: a note may leave out an error word, the family count sentence names the r sound in fixed text, and the listen sentence rarely matches Qwen's wording.
- **10:40 PM. #45 waited for one more fix before merging.** #39's style for the end screen's listen line also moved the word page's Listen circle; the rule now matches only the end screen, with a test.
- **10:50 PM. The round 3 docs ticket (#47).** `next_action` stays #9: the board runs come next, and #22 waits on them.

## After the round 3 docs (#48)

- **11:03 PM. A fresh-eyes review of main after #48, in four areas:** the server and screens, the scoring path, the language model and notes, and the docs against the code. Each bug it finds gets its own issue and its own small fix PR. Raf's and Lexi's parts get findings only, never a fix.
- **11:09 PM. Board steps are Raf's.** The owner cannot reach the board; Raf has it. Every "## Board steps" list, old and new, now waits on Raf.
- **11:09 PM. `UNSURE_BAND` stays Raf's to set,** and the note that tells him so goes in a PR body, not in code.
- **11:09 PM. The reviewer follow-ups from round 3 are filed and fixed now,** as #49 (proof bar), #50 (note checks), #51 (replay) and #52 (column upgrade race). None of them blocked a merge, but each one is a small, known gap.
- **11:09 PM. Under #51, practice under replay walks only the words that have a saved clip.** It fixes the stuck practice without a new "skip word" button.
- **11:09 PM. Under #50, measure before building.** A rule that makes the checker stricter is built only if real notes still pass it.
- **11:12 PM. The fresh-eyes review files its bugs as #53 to #61,** one issue and one fix PR each, and leaves #49 to #52 alone.
- **11:19 PM. #50 builds the missing-word rule for words flagged for age only.** None of 33 real notes fell back under it. A rule for every error word would drop 1 of 33, so it stays a proposal.
- **11:19 PM. #50's item 4 (a list word used as plain English) is not built.** None of 74 real family notes fell back for that reason, and a new sentence form would reopen gaps #39 closed. It stays a proposal.
- **11:24 PM. #51's reviewer found that the replay clip order carries over into the next session; filed as #73.** A new session now starts every word at its first clip.
- **11:38 PM. The nine fresh-eyes fix PRs** (#62, #64, #65, #66, #67, #69, #70, #71, #72, for issues #53 to #61) **each get their own reviewer and merge one at a time on the new main.** #70 and #71 clashed with main and were sent back for a merge of main first.
- **11:44 PM. #64 went back once before it merged.** Its timing line counted the wait for a turn as the run's own time, and its PR body gave too short a wait for the note.
- **12:27 AM, Sun Nov 15. Two reviewer findings become fix tickets:** #77 (a worker that dies during a check shows "Recording failed" although the try was saved, from #69's review) and #78 (Agree or Disagree on an old card in a second tab saves onto another word, from #65's review).
- **12:27 AM. Two smaller reviewer findings are logged, not fixed:** an `age_months` value of 4301 or more digits still drops the connection, and an abandoned session's note thread still runs one SLP call before the current note. The owner chose to record them in `docs/HISTORY.md` instead of fixing them now.
- **12:27 AM. The round docs ticket (#79)** also fixes the two stale doc lines (numpy, and "tally only" without llama.cpp). `next_action` stays #9.

## After the round docs (#79)

- **12:38 AM. #78 went back once before it merged.** A card from an earlier session could save onto the same word of the new session, which is another child's. The card now sends the session's start time, and a card from another session saves nothing.
- **12:38 AM. Two more stale-tab ideas from #78 are not built:** a word recorded again keeps its index, and Next and the box choice still act on the current word. The owner chose to leave both.
- **12:41 AM. #77 runs the check again in the server process** instead of showing the no-check card the issue named. That card says "laptop test mode", which is false on the board.
- **12:46 AM. #77 merged with one follow-up left:** after the crash, that try's sound analysis stays empty, so its Sound picture card can be missing.
- **12:51 AM. #78 merged with one follow-up left:** a tab open from before the update still saves onto the current word once.
- **12:52 AM. The docs ticket for #77 and #78 (#83)** also corrects PR #81's board step 2 in `docs/HISTORY.md`: kill a worker by its PID, because `pkill -9 -f multiprocessing` may kill no worker. `next_action` stays #9.
