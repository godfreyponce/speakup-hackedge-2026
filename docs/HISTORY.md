# Hackedge-2026 — Build History

Accepted-work archive. One section per accepted ticket, appended at the accept-time docs commit.
Newest first.

## #78 Agree and Disagree save onto the try the card shows (2026-11-15)

- Found by #56's reviewer. `/verify` and `/practice/verify` saved the call onto the try the session was on at the moment of the post. A press on an old card in a second tab could land on another word.
- Each half of the question card now posts a hidden `i`, the try the card shows (the word index on the SLP view, the turn on the practice page), and the server saves the call onto try `i`. A try that does not exist or has no recording saves nothing and gives 400 with the existing wording. A post with no `i` still saves onto the current try; only tests and direct model calls post that way.
- The first review said FIX: a card from an earlier session (another child) could save onto the new session's word `i`. The card now also posts `started`, the session's or practice's start time, and a card whose `started` does not match is refused the same way. Fixed in dbf0872 before the merge.
- A late call on an older practice try changes that try's call but not the level, because Next already set the level.
- Tests: `tests/test_server_slp.py`, six new tests, all failing on main. Full check at the head: Ran 529 tests, OK (skipped=3). The reviewer's run with #81 merged in: 531, OK (skipped=3).
- Open follow-up, not blocking: a tab rendered by the old code and open since before the update posts no `i`, so its next press still falls back to the current word, once per such tab. Closing it means dropping the no-`i` fallback.
- Not built, owner's call: a word recorded again keeps its index, so a call from a card that shows the first recording lands on the second; and Next and the box choice on a stale card still act on the current word.
- Board steps (PR #80) are still to run on the board.
- PR #80, commits 4743ea7, dbf0872; merge b811759.

## #77 A worker that dies during the recording check no longer shows Recording failed (2026-11-15)

- Found by #53's reviewer. When an analysis worker died during a try's recording check, the try was saved but the page showed "Recording failed".
- `take()` in `speakup/server.py` now gets the check through `check_of()`. If the worker died during the check, the check runs again in the server process, and the page shows the try's real recording card. The issue asked for the no-check card instead, but that card says "laptop test mode", which is false on the board. No new wording.
- Tests: `tests/test_server.py`, two new tests: a real worker exits during the check, and the pool plus its rebuild both refuse jobs so `later()` runs them in the server process (the in-process fallback from #53 had no test). Full check at the head: Ran 525 tests, OK (skipped=3).
- Open follow-up, not blocking, older than #77: in the same crash the try's sound analysis also fails, and `analysis_of` keeps no result for that clip. That try's Sound picture card can be missing on the SLP view.
- Board steps (PR #81) are still to run on the board. Step 2 in the PR body uses `pkill -9 -f multiprocessing`, which may kill no worker, because forked workers share the server's command line. Run these instead:
  1. Pull main on the board and run `python3 -m unittest tests.test_server`.
  2. Start the app as usual and note the server's PID. Record one word, press Stop, and at once kill one worker by a PID from `pgrep -P <server pid>` (`kill -9 <worker pid>`). The page shows the try with its recording card, not "Recording failed", and the next Record works.
- PR #81, commit d67d1bb; merge e5857e5.

## #60 llama.cpp runs take turns, so the bank fill and the note never share the cores (2026-11-14)

- Found by the fresh-eyes review. The start-up bank fill (2 llama.cpp calls) and the end-screen notes (3 calls) ran in separate threads with nothing to keep them apart. On the board a note takes about 107 s against a 240 s timeout, so two runs at once could push the note past it and the end screen fell back to the fixed note.
- `speakup/llm.py` now holds one re-entrant lock, `TURN`, around each llama.cpp run, at module level so a second `load()` shares it. The 240 s timeout does not count the wait for the lock. `bank.fill` takes the lock before it starts its clock, so the `bank: <level> took N s` line is the bank's own run time.
- The cost: a note can wait up to 480 s for both bank calls, and all three notes up to 1200 s.
- The first review said FIX: the bank's timing line counted the wait for a turn, and the PR body gave too short a wait for the note. Both were fixed in 753ffb9 before the merge.
- Tests: `tests/test_llm.py`, two threads take turns, and the bank time leaves out the wait. Full check on the branch with main merged in: Ran 521 tests, OK (skipped=3). The reviewer's run on the merge with the latest main: 523, OK (skipped=3).
- Open follow-up, not blocking, not filed (owner's call): a note thread from an abandoned session still runs one SLP call (up to 240 s) before it checks that its session is current, so it can delay the current note. The waste is older than #60; the lock turned it into a delay.
- Board steps (PR #64) are still to run on the board, including the bank's own `bank:` times for `docs/model-timing.md`.
- PR #64, commits c4497f8, 7ab37a4 (main merged in), 753ffb9; merge 19fa731.

## #55 The Qwen label follows each line: only a line Qwen wrote says so (2026-11-14)

- Found by the fresh-eyes review. Once Qwen kept any practice line, the practice page labelled every phrase and sentence line "Line written by Qwen on the board.", including lines from `practice_lines.csv`.
- `Bank` now keeps the (word, level) keys Qwen wrote, and `Bank.by_qwen(word, level, line)` is true only when the key is Qwen's and the line on screen is Qwen's text. The line is taken at Next, so a fixed line shown before the bank fill ends stays unlabelled. `server.qwen_lines` is gone; `WordView.qwen_line` replaces `qwen_lines`.
- Tests: `tests/test_bank.py` and `tests/test_server.py`, one new test each. Full check at the head: Ran 514 tests, OK; the reviewer's run on the merge with main: 521, OK (skipped=3).
- The branch clashed with main in `speakup/server.py`; the merge of main resolved it.
- Board steps (PR #70) are still to run on the board.
- PR #70, commits 17e2f16, 015095c (main merged in); merge 806a723.

## #57 The end screen no longer says the note takes about a minute (2026-11-14)

- Found by the fresh-eyes review. The waiting line said Qwen writes the note in "about a minute", a number nobody measured.
- The line in `speakup/pages.py` now reads "Qwen, a small language model on the board, is writing a note on these results." One test in `tests/test_server.py` now checks that "minute" does not show.
- Full check at the head: Ran 512 tests, OK; the reviewer's run on the merge with main: 519, OK (skipped=3).
- The branch clashed with main in `speakup/pages.py`. The merge commit 0d53b55 keeps git's "# Conflicts:" lines after the trailer (not blocking). The PR said "Refs #57", so #57 was closed by hand.
- No board steps.
- PR #71, commits 64fbef0, 0d53b55 (main merged in); merge 5cf03bb.

## #53 A dead analysis worker no longer breaks every later recording (2026-11-14)

- Found by the fresh-eyes review. With 3 analysis workers (`--arecord` and `--replay`), one dead worker broke the process pool for good, and every later Record failed until a restart.
- `later()` in `speakup/server.py` now catches the broken pool on submit, shuts it down without waiting, starts a new pool of the same size and submits again. If that fails too, the work runs in the main process, as with 0 workers. Each step writes one line to stderr.
- Tests: `tests/test_server.py`, a test that kills the only worker of a real pool and records again. Full check on the branch: Ran 492 tests, OK (skipped=3).
- Open follow-ups, not blocking: a worker that dies during a check still makes that one try show "Recording failed" although the try was saved (filed as #77); the in-process fallback has no test (also in #77).
- Board steps (PR #69) are still to run on the board.
- PR #69, commit b071320; merge 4fb6b55.

## #56 Agree and Disagree post the call the card shows (2026-11-14)

- Found by the fresh-eyes review. Agree and Disagree posted "agree" or "disagree", and the server turned that into a call against Arti's answer at the moment of the post. If the try was recorded again under the page, Agree on an "off" card could save "correct".
- `_question_card` in `speakup/pages.py` now posts the call each half shows (`correct` or `wrong`), for `/verify` and `/practice/verify`. The server still accepts agree and disagree.
- Tests: `tests/test_server_slp.py`, two new tests (each half posts its call, and Agree on a stale card saves the call it showed). Full check on the branch: Ran 493 tests, OK (skipped=3).
- Open follow-up, not blocking: `/verify` saves onto the session's current word, so a press on an old card in a second tab can land on a different word. This is older than #56; filed as #78.
- Board steps (PR #65) are still to run on the board.
- PR #65, commit 44b94d7; merge 78443c0.

## #54 Starting a practice or a screening keeps the other one's clips (2026-11-14)

- Found by the fresh-eyes review. Starting a practice wiped the open screening's try info: `/word` said there was no clip, Listen again was off and the clip's audio link gave 404. Starting a screening did the same to an open practice.
- `reset_try_state` in `speakup/server.py` now drops only the info of the one being started. It copies the info items before it filters them, so a request in another thread cannot break the loop.
- Tests: `tests/test_server_slp.py`, one test each way. Full check on the branch: Ran 493 tests, OK (skipped=3).
- Board steps (PR #67) are still to run on the board.
- PR #67, commits ccd7172, b5335d0; merge 3166bd3.

## #58 Start-up refuses --rate under 16000 (2026-11-14)

- Found by the fresh-eyes review. `--arecord --rate 8000` started, then every try failed inside Arti and the SLP saw "Model gave a bad result".
- `speakup/__main__.py` now stops at start-up when `--rate` is under 16000, the rate Arti and the sound analysis need, as it does for a bad `--silence`.
- Tests: `tests/test_main.py`, the repo's first start-up test. Full check on the branch: Ran 492 tests, OK (skipped=3).
- Reviewer notes, not blocking: the PR body quotes the message's older wording; the check also stops a laptop start that has no `--arecord`, which does no harm.
- No board steps; the board's default rate is 48000.
- PR #66, commits ba99a02, 9a348ae; merge 2ef0249.

## #59 /compare/data reads age_months with isdecimal (2026-11-14)

- Found by the fresh-eyes review. `/compare/data?age_months=²` dropped the connection: "²" passes `isdigit()`, but `int()` refuses it.
- `compare_data` in `speakup/server.py` now uses `isdecimal()`; any other value counts as no age.
- Tests: `tests/test_compare.py`, one new test. Full check on the branch: Ran 492 tests, OK (skipped=3).
- Open follow-up, not blocking, not filed (owner's call): an `age_months` value of 4301 or more digits still drops the connection, because `int()` refuses numbers that long (Python's 4300-digit limit). The old line had the same gap.
- No board steps.
- PR #62, commit c2e591c; merge a2086dc.

## #61 Docs: date of birth, what shows without Qwen, no middle dots (2026-11-14)

- Found by the fresh-eyes review. README said to enter an age of 8 or older (the start page asks for a date of birth, and errors flag from 7 years). README said the end screen shows the tally only without the model (it also shows the fixed family notes). The demo script used a middle dot in 5 headings.
- README, the `--llm-model` help and the start-up message in `speakup/__main__.py` now name the tally and the fixed family notes. The 5 headings use a comma. No test; text only.
- The reviewer found one more stale line, "tally only" in `docs/model-timing.md`; it is fixed in #79.
- The PR said "Refs #61", so #61 was closed by hand. No board steps.
- PR #72, commit 22541d4; merge 1086a33.

## #73 Replay: a new session starts every word at its first clip (2026-11-14)

- Found by #51's reviewer. Under `--replay`, the clip order was set once at start-up and never reset, so the next session's first try played the word's second clip, not the order the team rehearsed.
- `ReplayRecorder.rewind()` in `speakup/replay.py` puts every word back at its first clip. `reset_try_state` in `speakup/server.py` calls it on every start of a screening or a practice, when the recorder has it, so live mode is unchanged.
- One recorder serves both, so starting a practice also rewinds an open screening's clips, and the reverse. This follows from the design; the team should know it before a rehearsal.
- Tests: `tests/test_replay.py`, two new tests (a new session starts at the first clip; tries in one session step through the clips). Full check at the head: Ran 502 tests, OK; the reviewer's run on the merge with main: 512, OK (skipped=3).
- Board steps (PR #76) are still to run on the board.
- PR #76, commit 897302f; merge 22a21d7.

## #50 Note checks: every word flagged for age, the session's sound, the copied listen line (2026-11-14)

- Fixes #39's reviewer follow-ups. Measured first with Qwen2.5-0.5B on the laptop, on made-up sessions: 52 SLP notes, 33 of which pass today, and 74 family notes in English and Spanish.
- Built: the SLP check now rejects a note that leaves out a word flagged for age, and the note falls back to the fixed one. None of the 33 passing notes left one out.
- Built: the family count sentence names the session's sound (`{sound}` in `speakup/data/family_notes.json`), not a fixed "r sound". The r text is unchanged in both languages.
- Built: the SLP check also accepts the listen line in the form Qwen writes, "SLP please listen: w1, w2.", where every word must be inside the unsure band and none may repeat.
- Not built, proposals: requiring every word with an error, not only words flagged for age (1 of the 33 notes would then fall back); and item 4, a list word used as plain English (none of the 74 family notes fell back for it, and a new sentence form would reopen gaps #39 closed).
- Open follow-up, not blocking: with listen words in the facts, Qwen gave a listen word an error it did not have in 11 of 41 notes, and the check rejects those. So once `UNSURE_BAND` is set, most SLP notes that have listen words will fall back. A mixed r and s session would read "the r, s sound" in the fixed family note; that wording is Lexi's call.
- Tests: `tests/test_summary.py` and `tests/test_family.py`, five new tests. Full check on the branch with main merged in: Ran 500 tests, OK (skipped=3). The reviewer's run on the merge with the latest main: 510, OK (skipped=3).
- Board steps (PR #75) are still to run on the board.
- PR #75, commits 5191ae3, a23555a (main merged in), ce29475; merge d0bf9b3.

## #49 Proof bar: ignore -nan speeds, take "5." as 5, Watts tile no taller (2026-11-14)

- Fixes #38's and #45's reviewer follow-ups. A llama.cpp speed of `-nan` or `inf` emptied the Qwen tile, the watts box refused "5.", and a typed watts value made the bar taller.
- `speakup/proof.py`: a call whose speed is not a real number is ignored, and the tile keeps both numbers of the last real call. "5." is stored as 5. The watts form is as tall as a value line, and a typed value becomes a tile only when another tile is on; alone, it stays in the quiet "not measured yet" line.
- Tests: `tests/test_proof.py`, six new tests. Full check on the branch with main merged in: Ran 505 tests, OK (skipped=3).
- Commit 99468fa added three screenshots of the bar (no child data); the next commit removed them, but they stay in the history.
- Board steps (PR #74) are still to run on the board.
- PR #74, commits a9bb601, 1960c78, 99468fa, 55867e0, 54fbcab (main merged in); merge 3420049.

## #51 Replay: practice walks only words with a clip, a plain error for a non-UTF-8 manifest, Replay tag on end pages (2026-11-14)

- Fixes #40's reviewer follow-ups. Under `--replay`, practice got stuck at the first word with no saved clip, a manifest that was not UTF-8 gave a raw `UnicodeDecodeError`, and the end pages had no Replay tag.
- Coordinator pick: under replay, practice walks only the words that have a saved clip, in list order. No "skip word" button. Live practice still walks every word.
- A manifest that is not UTF-8 now stops start-up with one `--replay:` line. The summary, the practice summary and the sound analysis page show the Replay tag.
- Tests: `tests/test_replay.py`, five new tests. Full check at the head: Ran 496 tests, OK; the reviewer's run on the merge with main: 500, OK (skipped=3).
- The reviewer found that the clip order carried over into the next session; filed and fixed as #73.
- Board steps (PR #68) are still to run on the board, with the 6 demo clips.
- PR #68, commit 45bd3e7; merge 3c2ddc4.

## #52 Store: column upgrades are safe against a second connection (2026-11-14)

- Fixes #37's reviewer follow-up. When two connections opened an old database at the same moment, both could try to add a missing column, and the second failed with "duplicate column". The older column upgrade had the same race.
- `_connect` in `speakup/store.py` takes the write lock when a column is missing, reads the columns again and adds only those still missing. The old `+slp` backfill runs in the same transaction. A database that is already upgraded opens without the lock.
- Tests: `tests/test_store.py`, `UpgradeRaceTest`, four tests. Full check: Ran 495 tests, OK (skipped=3). The PR's own check (8 threads, 50 rounds) failed 274 opens on the old code and none on the new; the reviewer's 8-process run saw no errors.
- No board steps.
- PR #63, commit a59671b; merge 471fb60.

## #45 SLP word page and proof bar polish (2026-11-14)

- The owner said the SLP word page (`/word`) looked generic: every panel had the same weight, the middle column was mostly empty before Record, "Finish with N of 10" floated under the word list, and on a laptop the proof bar took about a sixth of the screen with 4 of 5 tiles saying "not measured yet".
- Owner decisions: three mockups first (`mockups/round3-word-polish/`: stage, list-led, mirror). The owner picked none of them; they stay as a record. The live page was then hill-climbed instead: a written score list (lead, empty space, labels, Finish, bar on the laptop, bar on the board, nothing covered), one change per round, a screenshot and a score after each. Scope: `/word` and the proof bar it shares with practice.
- Five rounds, score 3 of 14 to 14 of 14: the proof bar folds every value not measured yet into one quiet line and keeps measured values as tiles; `.wide` was defined twice in the SLP CSS, so Finish, Next word and End practice were squashed (fixed); the word card leads with a soft shadow and the context column is plain text under thin rules, headings in sentence case; on the board the tile values no longer take the big-button padding, and an upright iPad shows 2 rows of tiles, not 3; before Record, the help text sits in a dashed slot where the result will land. The "quiet for 3 s" wording (#33) is untouched.
- A script checked every round that no button, link or input sits under the bar, for both bars at both widths. With the bar's padding removed it does find one, so the check works.
- `speakup/pages.py` changes are CSS only. While merging main, the end screen's `.listen` rule from #39 also styled the word page's Listen circle (8 px shift, bold); it is now `p.listen`, and `ListenStyleTest` in `tests/test_server_slp.py` fails on the old rule.
- Tests: full check on the branch with main merged in: Ran 491 tests, OK (skipped=3).
- Open follow-ups, not blocking: once a watts value is typed, the Watts tile turns on, and a reviewer saw the bar grow to about 150 px in a laptop screenshot. The folded bar drops its top border with `:has()`; an older browser keeps it.
- Board steps (PR #46) are still to run on the board.
- PR #46, commits e1e482e, e914a0c, 49e2188, f3e0388, fdd61e7, b38cc84, 78cb9ac (main merged in), fafcec2; merge 7510568.

## #39 Checked end-screen notes, with a family note in English and Spanish (2026-11-14)

- SLP note: a green check, "✓ every number checked by code", shows under Qwen's note. The note reaches the screen only after `summary.check_reply` passes. A note that fails is hidden, not shown without the check, and the reason goes to the log (`summary note skipped: ...`).
- Owner decision: the family note is written live by Qwen and checked by code, with a fixed note as the fallback. `speakup/family.py`: after the SLP note, Qwen writes a short practice note in English, then in Spanish, from code-built facts (the sound, the number of words tried, and the words to practice). Code checks numbers (each must match its fact; numbers written as words fail), the sound name, the word names (only practice words, none left out, none repeated), banned words in both languages (diagnose, disorder, pass, refer, fail and the Spanish forms), the language, and a reply cut off mid-sentence.
- Fallback: if a family note fails its check, or Qwen is off or times out, the fixed note shows, labelled "fixed note filled in by code". Its English and Spanish text is in one file for Lexi, `speakup/data/family_notes.json`, and a test runs it through the same check. After an `LlmError`, Qwen is not asked again that session.
- The SLP checker is stricter. Each digit must match its fact ("N words" is the count tried, "X yr Y mo" is the age), and it bans the same words as the family note. Review rounds kept finding new false claims in open wording, so each SLP note sentence must now be one of a short allowed list (count, age, no errors, a word with its error and verdict, a listen word). PR #42 reports that a replay of 66 real and fixed notes through the final checker rejected none. The merge reviewer found 43 notes in the samples file and checked those, and all were accepted; the 66 is not verified.
- SLP please listen: `summary.listen_words` lists each word whose Arti p(wrong) is inside `calibration.UNSURE_BAND`. These show as "SLP please listen: ..." on the end screen and go into the SLP note's facts. While the band is None the list is empty.
- The tally shows at once; the SLP note, the English family note and the Spanish family note each appear as they arrive (3 s refresh, as in #29).
- `scripts/note_samples.py OUT.txt [--llm-model PATH]` writes 10 made-up sessions (no child, no audio) with the verdict line, the fixed family note and, with the model, Qwen's notes, their check result and time. The output stays outside git. Laptop run with Qwen2.5-0.5B: 9 of 10 SLP notes passed (the failure was a clean session where Qwen copied the example's word, as before), 14 of 16 family notes passed (2 repeated a word and fell back).
- Tests: `tests/test_family.py` new, new cases in `tests/test_summary.py` and `tests/test_server.py`. Full check on the branch: Ran 488 tests, OK (skipped=3).
- Open follow-ups, not blocking: an SLP note may leave out a word with an error, but it can make no false claim; the family count sentence says "r sound" in fixed text, which needs a seam once /s/ words arrive; the listen sentence form rarely matches what Qwen writes word for word; a correct list word used as plain English ("did very well") makes a family note fall back. Known and deliberate: the #28 rule checks a correctly said word only as a sentence's subject.
- Board steps (PR #42) are still to run on the board, including the board time for both notes.
- PR #42, commits dfd5ab5, 1e359fa, d175351, dbbd96c (main merged in), 5e6c929, 64a7323, 8c589b2, 9c6a77b, 4fcf531, 9cae489, adfcc28, dad25ae, 2326ea7; merge b801861.

## #37 SLP view: agree, disagree and listen again with A, D and L (2026-11-14)

- The SLP watches on a laptop or iPad over the local network; the kid view stays on the HDMI monitor at `/kid`. Both follow one session from separate browsers.
- Owner decision: mockup C, the question card (`mockups/round3-slp-view/c-question-card.html`), with the evidence fold open by default and no 100vh. The card asks one question: does the SLP agree with Arti? Mockups A and B stay in that folder.
- On `/word` and `/practice`, `A` agrees, `D` disagrees and `L` plays the clip again, each with a large touch target for an iPad. The keys do nothing while typing in a field, with ctrl, cmd or alt held, on a held key, or while the full sound view is open.
- Two calls saved apart: `Attempt.arti` and `Attempt.slp`, and new `arti_call` and `slp_call` columns in SQLite. An old database gains the columns when it opens, in one transaction, and its old `+slp` rows become `slp_call`. The `+slp` model suffix is gone.
- Unsure seam: `speakup/calibration.py` has `UNSURE_BAND = None` and `unsure(p_wrong) -> bool`, always False while the band is None. `UNSURE_BAND` is Raf's to set from his calibration; our code never sets it and never moves the 0.5 threshold. When `unsure()` is True, the card shows "Unsure, SLP please listen".
- If the SLP moves the box after a check and Arti's answer changes, the card says "Arti changed its answer after you moved the box." The SLP's call stays.
- Checked by eye on a desktop, an iPad Air and an iPad mini (768 px): the keys save or play, the correct half lights, and `/kid` shows the same word.
- Tests: route tests for agree, disagree, Unsure and two screens, plus the two saved calls, an old database opening, and `unsure()` with and without a band. Full check on the branch with main merged in: Ran 455 tests, OK (skipped=3).
- Open follow-ups, not blocking: until Raf sets `UNSURE_BAND`, "Unsure, SLP please listen" never shows. A first open of an old database on two connections at the same moment can fail with "duplicate column" (the older column upgrade has the same race). No test runs the key script, so the keys are a board step by hand. The commit that brought main into the branch (12b1ad6) kept the text git writes on its own, so it names no issue and has no Co-Authored-By line.
- Board steps (PR #44) are still to run on the board.
- PR #44, commits d7d98d7, 11e67b7, b3c432d, 8d7d0da, 3bb8b30, 12b1ad6 (main merged in), b65326e; merge 3902d1a.

## #38 Proof tile bar: Arti ms, Qwen tokens/s, memory, network, typed watts (2026-11-14)

- Owner decision: shape C, the tile bar, fixed to the bottom of every SLP page that has the header (word, practice, both summaries, the full analysis page), with bottom space kept so it never covers a button. Not on the start page, the child screen, the 404 page or the embedded analysis. Mockups A (strip) and B (side card) stay in `mockups/round3-proof-banner/`.
- Every number is measured on the machine or typed by a person from a meter; anything not measured yet says "not measured yet". `speakup/proof.py` holds the parsers and the live values.
- Arti: time around the real model call, last word and session median; fake and demo models are never timed; clears when a session starts. Qwen: generation tokens/s (and prompt tokens/s) parsed from llama.cpp's own timing lines, last successful call; both the newer `common_perf_print` and older `llama_perf_context_print` forms. Memory: MemTotal minus MemAvailable from `/proc/meminfo`, plus the app's peak RSS (main process only). Network: a working default route in `/proc/net/route` or `/proc/net/ipv6_route` is Online; with no `/proc`, the tile says so. Watts: typed from the USB-C meter (POST `/proof/watts`), blank until typed, never filled by code.
- Overhead measured on the laptop: the Arti timer 0.73 µs per word; building the bar 4.4 µs per page load (no `/proc` on the Mac); the llama.cpp parse 6.6 µs per call. The board's `/proc` reads still need a measurement.
- Tests: parsers on fixed sample text and the "not measured yet" states. Full check on the branch with main merged in: Ran 431 tests, OK (skipped=2).
- Open follow-ups, not blocking: when llama.cpp prints its speed as `-nan` or `inf`, the Qwen tile goes back to its empty state; the watts box refuses a number that ends in a point, such as "5.".
- Board steps (PR #43) are still to run on the board, including the bar's cost per page load.
- PR #43, commits 296eedb, 4eaa35e, d97ddd9, bf157cb, 5db1161 (main merged in); merge 2d769a6.

## #40 --replay: saved clips scored live by Arti, the demo's backup (2026-11-14)

- If the mic or the room fails at the demo, `python3 -m speakup --replay <folder> --arti models/arti-v0.onnx` runs the normal screening flow, and each Record takes the next saved clip for the word on screen. The real Arti scores it live; replay never shows a scripted answer. A second Record on a word takes that word's next clip, and wraps after the last.
- The folder holds the WAV clips (mono, 16-bit, 16 kHz or faster) and a `manifest.csv` with the header `file,word`. Each word must be in `speakup/words.csv`. The clips stay outside git.
- `--replay` needs `--arti` and refuses `--arecord` and `--sample-clip`. At start-up the app checks the folder, the manifest, each clip and each word, and stops with a clear `--replay:` line before Arti loads.
- The SLP word and practice pages show "Mode: Replay: saved clips from <folder>, not the mic" in the banner. A Record on a word with no clip names the words that have clips and the way out.
- New code is in `speakup/replay.py`; `server.py`, `pages.py` and `__main__.py` changed a few lines each. `--demo` and `--arecord` behave as before. Replay uses the same 3 analysis workers as `--arecord`, so the demo's timing matches a live run. README's "Run the app" names the flag.
- Tests: `tests/test_replay.py`, 16 tests (manifest checks, clip order, the no-clip error, the flow through the real server with a stand-in model, the flag checks). Full check with numpy: Ran 399 tests, OK (skipped=3).
- Open follow-ups, not blocking: practice walks all 10 words in order with no skip, so with the 6 demo clips practice under replay gets stuck at the first word that has no saved clip, and only End practice gets out (a clip per practice word, or a "skip word" feature, is the owner's call). A manifest that is not UTF-8 gives a raw `UnicodeDecodeError`. The end pages and the sound analysis page have no Replay tag.
- Board steps (PR #41) are still to run on the board, including where the 6 de-identified clips go.
- PR #41, commits 7689091, 2610792; merge 2b016e5.

## #28 check_reply: name a word only where it names an error, folds #27 (2026-11-10)

- `check_reply` in `speakup/summary.py` no longer rejects a true note because a correctly said list word appears as plain English ("Truck had gliding (heard w), which is very clearly flagged for age." passes for the `--demo` session at 96 months). The owner picked option 2 on #28: the prompt is unchanged.
- The naming rule: a sentence's subject is its first word, or the word after a leading "on". A session word with an error counts as named anywhere in the sentence. A correctly said word, or an example word (rope, bird), counts only as the subject.
- #27: a sentence that makes a claim (an error phrase, or "flagged", "normal", "keep an eye") must have a session word with an error as its subject, else `ValueError("makes a claim about <subject>, which is not a word with an error: ...")`. "Giraffe had gliding ..." for a session without giraffe is now rejected.
- Every earlier accept and reject case gives the same result with the same message as before (old and new `check_reply` run side by side in the build).
- Known costs: true notes shaped "The r sounded off in rabbit, ...", "Very clearly, truck had ...", "Keep an eye on rabbit." or a bare "Flagged for age." are now dropped (the end screen shows the tally only). A false note shaped "Rabbit and carrot had gliding ..." (carrot said correctly), or with an example word in that place, was rejected before and now passes (gate 2 review finding).
- Tests: `tests/test_summary.py`, one new accept line (`DEMO_VERY_AT_96`) and four new reject cases (word not in the session, correct word as subject, second word has a different error, claim with no word). Full check in the worktree: Ran 153 tests, OK (skipped=1). Full check on main after the merge: Ran 153 tests, OK (skipped=1).
- Deferred from review: the reject cases check only that `ValueError` is raised, not its message.
- Commit: e09236a. Closes #28 and #27.

## #30 PERCEPT-R license from its sources, 2022 citation (2026-11-10)

- The ticket said no source backs CC BY-ND 4.0. The planner found one: `PERCEPT-R 2.2.2py/README.txt`, the only text file in `PERCEPT-R.zip`, says the 2.2.2py release is CC BY-ND 4.0. No web page says so. BY-ND stays, now with its source.
- `docs/test-set.md` has a `## License` section that quotes the README, TalkBank's Ground Rules (CC BY-NC-SA 4.0 "except where otherwise indicated"; media not on the web without the contributor's permission), the corpus page, the contributor's form ("None") and Benway et al. 2023 ("noncommercial use through PhonBank"). Open: which terms govern this release, and whether a trained model is adapted material.
- The reason nothing from the corpus is committed is now the media rule and the repo's no-child-data rule for clips, and the open adapted-material question for files made from the corpus. BY-ND alone never stopped sharing unchanged clips.
- `docs/model-timing.md` names the terms in one sentence and links `test-set.md#license`. Both docs cite Benway et al. 2022 (Interspeech, doi:10.21437/Interspeech.2022-10785).
- Left as they are: the BY-ND lines in `scripts/train_arti.py` and `scripts/pick_test_set.py` (agree with the README; no code change), and the 2026-11-03 plan files (records). "No model file is in git" in `docs/model-timing.md` is still false until #25.
- Tests: no new test (docs only). Full check in the worktree: Ran 153 tests, OK (skipped=1). Full check on main after the merge: Ran 153 tests, OK (skipped=1).
- Commit: beaa4fd.

## #19 Arti masking experiment: time and frequency masks on validation speakers (2026-11-10)

- Validation only, nothing deployed. Baseline, a time mask (one band per training clip, 0 to 5 frames) and a frequency mask (one band per clip, 0 to 2 mel bins), each filled with the clip's mean log-mel, each trained with seeds 2026, 2027 and 2028. Everything else fixed: frontend, 4 blocks, 20 epochs, Adam 0.001, batch 256, class weights, threshold 0.5, speaker split seed 2026 (106 train, 12 val, 55 held out and unused).
- `scripts/train_arti.py`: `train(..., *, seed=SEED, order=None, augment=None)` returns `(body, best_epoch, val_pred)`. `augment` sees the float32 CPU training batch only. With defaults the CLI trains the same model as before: state dicts and stdout equal to main's `train()` on CPU, and `--help` identical.
- `scripts/experiment_arti.py`: `stream_seeds` (init, order and mask seeds from `numpy.random.SeedSequence`), `mask`, `augmenter`, `run_one`, `summarize` (rank by mean balanced accuracy, baseline first on an exact tie), `main` (`--out-dir`, `--device auto|cpu|mps`). Writes `results.json` after every run and each run's best-epoch weights to `data/percept-r/arti-masking/`. It never imports `score`, `export` or `session` and never reads `test-set.csv`.
- Result, 9 runs on MPS (about 150 s each), validation balanced accuracy mean over 3 seeds: time 0.8638 (sd 0.0027), frequency 0.8631 (sd 0.0060), baseline 0.8556 (sd 0.0021). All 3 paired differences are positive for both masks, and the gain is larger than the seed spread. Time and frequency differ by 0.0007, less than their spread. Selected candidate: the time mask. Report: `docs/arti-masking-experiment.md`.
- `models/arti-v0.onnx` and the mel cache in `arti-cache/` are unchanged (sha256 before and after the run).
- Ruling: the test module's skip guard wraps only the third-party imports, so a broken `experiment_arti` fails instead of skipping.
- Tests: `tests/test_arti_experiment.py` 20 (5 train, 6 mask, 3 summary, 6 end to end; skipped as one test without torch). Full check in the worktree: Ran 149 tests, OK (skipped=1). Full check on main after the merge: Ran 153 tests, OK (skipped=1) (main holds #29's tests too).
- Deferred from review: a rerun that stops early leaves old `.pt` files beside the new partial `results.json` (the report says to use only the runs `results.json` lists); `run_one` recomputes balanced accuracy instead of importing it; the `score`/`export` patches in the end-to-end test cannot fire (the `hasattr` asserts and the missing `test-set.csv` are the real guards); the paired-seed test checks seeds from one function; `results.json` is not written atomically.
- Follow-ups not filed yet: held-out scoring of the selected run, its ONNX export, live-mic checks, board timing.
- Commits: b63724b, f054953, 8c09fb3; merge 4d807e9.

## #29 End screen: tally at once, note when it arrives (2026-11-10)

- Raf's board timing (#26): the end screen took 40.3 s, because `/next` waited on Qwen's note before it saved and showed `/summary`. Now the last Next saves the session and shows the tally and the pass, watch or refer line at once; the note is written in a daemon thread.
- `speakup/server.py`: `SpeakUpServer.start_note` marks the note pending and starts one thread per finished session (`note_thread`); `write_note` moved from `Handler` to the server and writes its note only when `server.session` is still the session it was written for, so an old note never shows on a new session and never clears a new session's pending line. `note_lock` guards session, note and `note_pending` in `/start`, the thread's write and the `/summary` read (`note_state`). `note_pending` is cleared in a `finally`, so an error that is not `LlmError` or `ValueError` cannot leave the page reloading forever. With no model (`generate` is None) nothing starts and the page is as before.
- `speakup/pages.py`: `_page` takes `head`; `summary_page` takes `note_pending`. While pending, the note paragraph reads `Summary note: being written on the board.` and the head has `<meta http-equiv="refresh" content="3; url=/summary">` (3 s is a guess; `url=/summary` is needed because the failed-save page is the body of POST /next). No JavaScript; no new style.
- The note is still not stored, and `summary.py` and the practice pages are untouched. #9's deferred "a hung llama.cpp blocks the one-request server for up to 120 s" no longer holds.
- Laptop run with real Qwen2.5-0.5B and `--demo` at 8 yr 0 mo: right after the last Next, `/summary` showed the tally, the pending line and the refresh tag; 6 s later it showed the note; the session was saved.
- Ruling: on the old code the three gated tests hang inside POST /next instead of failing (http.client has no timeout); RED was shown on the six other note tests, and no client timeout was added.
- Review fix: `test_old_note_leaves_new_pending_line`, shown red on a mutant that clears `note_pending` for any session.
- Tests: `tests/test_server.py` 4 new (`test_end_screen_shows_tally_while_note_is_written`, `test_old_note_dropped_on_new_session`, `test_old_note_leaves_new_pending_line`, `test_unexpected_note_error_clears_pending_line`), 6 changed; `NoteModel` takes a `gate`. Full check in the worktree: Ran 152 tests, OK. Full check on main after the merge: Ran 152 tests, OK.
- Deferred from review: a regression that puts `generate` back on the request hangs the gated tests instead of failing them; `start_note` clears `note`, which `/start` already did.
- Owner step outside the Done when: on the board, the end screen shows the pending line at once and the note (or the tally only) about 40 s later with no click.
- Commit: acf6e3f.

## #21 Practice coach, part 1: levels, startup bank, line check (2026-11-04)

- Lexi's Nov 3 answer: levels are good for screening; this is a leveled screen and practice tracker, not therapy. Gate 1 Decision 1 kept word, phrase, sentence (phoneme is out because Arti scores words; multisyllable is out because it needs new words). The UI says "practice" and "Screening aid, not a diagnosis. The therapist always decides."
- `speakup/bank.py`: `LEVELS`, `KID_WORDS` (det, adj, who, noun, verb; no word has an r and none is a Lexi word), `INTENSIFIERS = {"very"}`. `check_line` raises with the first reason: `not a word: X`, `target missing` / `target twice`, `another r word: X`, `r in the wrong position`. A word is real when it is a Lexi word or a kid word; there is no CMUdict (Decision 4). `Bank.line(word, level)` gives the word itself at the word level.
- `speakup/practice_lines.csv`: the fixed fallback bank, one phrase and one sentence per Lexi word. `load_fallback` checks every line and needs both lines for every word in `words.csv`.
- Startup bank: `bank.grammar` builds GBNF for one JSON object keyed by Lexi's words in order, each value locked to a part-of-speech shape (Decision 3). `bank.build_prompt` is ChatML with the format in words and 3 example lines per level. `bank.fill` makes one llama.cpp call per level (`n_predict=400`) and keeps the fallback line for any word whose line is not passed. It logs each drop to stderr as `bank: dropped <level> line for <word>: '<line>' (<reason>)`, and each call as `bank: <level> took <s> s, kept <k> of <n> lines`. `__main__` runs it in a daemon thread and swaps `server.bank` when it is done, so start-up never waits; the deadline is `llm.TIMEOUT_S` per call.
- `speakup/llm.py`: `generate(prompt, grammar=None, n_predict=96)`; `--grammar <text>` when a grammar is given; `-c 1024` (was 512). The note still calls `generate(prompt)`. One laptop run with real Qwen2.5-0.5B during the build: phrase 1.3 s, sentence 1.6 s, 10 of 10 lines kept for each.
- `speakup/practice.py`: `next_level` moves one step up on a right r and one step down on a miss, and stops at word and at sentence. `Practice` goes through Lexi's words round and round. Record again replaces the try. Next moves the level from the current try's result. `Attempt` gains `level` and `line` (default None).
- `speakup/store.py`: `results` gains nullable `level` and `line`, added with `ALTER TABLE` on open, so an old board database gains them too. Screen rows keep NULL. The log pages did not change; a practice shows there as a session of its tries.
- Pages and routes: a Practice button on the start form; `/practice`, `/practice/record`, `/practice/next`, `/practice/end`, `/practice/summary`, `/practice/save`. The end page shows the pass/refer line, the tally and a Try, Level, Line, Heard, Flagged table, with no model note. End with no try goes home and saves nothing. The screen's routes and page output did not change; `pages._result` and `pages._flagged_cell` were extracted for reuse.
- Rulings: `load_fallback` reads only the rows for the given words. The fake llama in `tests/test_llm.py` gained an `args` mode, because the plan's "existing argument test" did not exist. `practice_ended` on the server stops a second save after End. On the practice footer, the model name goes on a second line, and the end page top bar says "Practice done".
- Review fix: when `practice_lines.csv` lacks a line for a `words.csv` word, the server prints `practice off: <reason>`, hides the Practice button, and runs the screen as usual. It does not exit (`test_missing_practice_lines_turn_practice_off_not_the_screen`).
- Tests: `tests/test_bank.py` 17 new, `tests/test_practice.py` 9 new, `tests/test_llm.py` 1 new, `tests/test_store.py` 3 new, `tests/test_server.py` 12 new. Full check in the worktree: Ran 148 tests, OK. Full check on main after the merge: Ran 148 tests, OK.
- Deferred from review: `summary.Generate` is still `Callable[[str], str]`, though `llm.load`'s generate now also takes `grammar` and `n_predict`. A JSON dict with a non-str value is logged as "reply is not a JSON object". A duplicate row in `practice_lines.csv` overwrites the earlier row without a message, and a misspelled level is stored and never used. The shared CSS gained `.word.line` and a fifth start-grid column.
- Owner steps still open on #21: the phrase and sentence check through Arti on the board (step 2), the board's `bank:` timing lines into `docs/model-timing.md` (step 3), and `python3 -m unittest` on the board (step 4).
- Commits: 17c1b9c, 99666cd, bf1ad9b, a81a0bc, ecf5539, 2db6bed; merge d9bea9c.

## #24 Age rule: Lexi's bands, keep an eye on it at 5 to 6, flag from 7 (2026-11-04)

- Lexi's Nov 3 text: ASHA cites Crowe and McLeod (r acquired by 5.5 years) and says gliding should be remediated by 6 to 7. Every r error (gliding, distortion, `off`) is normal for age under 60 months, keep an eye on it from 60 to 83, flagged from 84. Distortion and `off` moved from 96 to 84. Owner and Lexi confirmed the bands at gate 1.
- `speakup/age_norms.py`: `AgeNorm` has `watch_from_months` and `flag_from_months`, one comment above `AGE_NORMS` names the sources; `should_watch()` beside `should_flag()`, both through one `_norm()` lookup. `Attempt.watched` in `speakup/session.py`.
- `speakup/summary.py`: `pass_or_refer` returns `Watch: k of n words to keep an eye on for age ...` when nothing is flagged and something is watched. The facts line ends `keep an eye on it`; the worked example is a 5 yr 6 mo child; `check_reply` checks all three verdict words in one loop. Planning measured Qwen2.5-0.5B with the new example: right verdict on 7 of 7 sessions with errors; clean sessions copy the example and fall back to the tally only (they were flaky before too).
- `speakup/pages.py`: text only. Word page `Keep an eye on it for age ...`; summary cell `no, keep an eye on it`; child page legend `wrong, not flagged for age`. A watched word keeps the amber of "normal for age"; no new colour. `docs/result-format.md` names the 60 and 84 months.
- Saved sessions are judged on read (`SavedSession.is_flagged`), so old distortion or `off` sessions at 84 to 95 months in the log now show a flag.
- Tests: `tests/test_age_norms.py` 3 edge tests replaced by `test_band_edges`, `should_watch` added to 3 tests; `tests/test_session.py` 1 new, `test_tally` changed; `tests/test_summary.py` 3 new, 1 replaced (`test_pass_line_with_no_model` by `test_watch_line_with_no_model`), 3 new reject cases, 2 new accept cases, 2 expectations changed; `tests/test_server.py` 1 new, 2 changed. Full check in the worktree: Ran 106 tests, OK. Full check on main after the merge: Ran 106 tests, OK.
- Deferred from review: `check_reply`'s loop variable `verdict` reuses the name of the earlier regex match; its docstring still says the note sits under a Refer line; a watched word described in other words ("worth watching") slips past the check (the gap predates this ticket).
- #10 landed on main during gate 2; main was merged into `issue-24` (84ae1f4). One conflict in `tests/test_summary.py`: #10's truck reply and #24's two new replies sat on the same lines; both kept.
- Commits: 595fcad, eef53a4, fb0c44c, 84ae1f4 (main merged in); merge d968123.

## #10 Practice word list: Lexi's r words (2026-11-04)

- `speakup/words.csv` is Lexi's list (Nov 3, by text to Godfrey): the stand-in list with very for cherry and truck for giraffe, because "ch" and "j" are also late-developing sounds. Ten words in position order: rabbit, rain, ring, rocket, truck (start); carrot, very (middle); car, door, bear (end). The header and `speakup/words.py` did not change. `speakup/__main__.py` already reads the list through `load_words()` (since #5).
- Gate 1 Decision 1: truck is `start` (its r is in the "tr" cluster at the front). There is no fourth `cluster` position; if Lexi says clusters count apart, that is a new ticket.
- `--demo` (`speakup/demo_model.py`): truck takes giraffe's result (`gliding`, "twuck"), very takes cherry's (`None`). There are still three scripted errors, so README's "8 years or older" line holds. truck now comes 5th, not 7th, so the second gliding word comes earlier in the demo than it did with giraffe.
- `tests/test_summary.py`: `DEMO_AT_96` is the real Qwen2.5-0.5B reply re-measured at planning with truck in the list (Mac, Homebrew `llama-completion` build 11960). With truck in the list, the 62-month reply is now correct, so `DEMO_AT_62` stays the old giraffe-list reply with the word swapped, and a comment says so. At planning, `--demo` at 5 yr 2 mo gave a reply that `check_reply` accepts, so the end screen now shows the note there (#9 recorded tally only).
- Old records keep cherry and giraffe: `mockups/issue-5/c3-bubble.html`, `mockups/issue-6/c-chart.html`, and the #5 section below.
- Plan deviation: Step 7's grep for giraffe/cherry finds the two comments that Steps 1 and 5 asked for (the CSV header comment and the fixture comment). No code or data row names the old words.
- Tests: no new test (gate 1 Decision 6). Full check in the worktree: Ran 103 tests, OK. Full check on main after the merge: Ran 103 tests, OK.
- Deferred from review: "very" is an everyday adverb, and `check_reply` rejects a correct reply that uses it that way (#28).
- Filed while building: #27 (`check_reply` passes a sentence that names a word not in the session; the old "Giraffe" fixture passed against the new list), #28.
- Commit: f89fd15; merge: a fast-forward, so no merge commit.

## #1 Board bring-up: Linux, SSH, mic, served page (2026-11-03)

- SK-AM62B (PCB label) boots TI Processor SDK Linux AM62x 12.01.00.05.03 (Arago 2026.04, kernel 6.18.38-ti) from a 32 GB microSD.
- Flashing: balenaEtcher failed three times ("writer process ended unexpectedly") on two cards and two computers; unpacking the `.wic.xz` and writing the `.img` with Raspberry Pi Imager worked.
- Serial console on J15 (first of four FTDI COM ports, 115200 8-N-1), power on J11. Login `root`, no password until `passwd`.
- Python 3.14.5, pip 26.0.1, numpy and tflite_runtime preinstalled. 1.3 GiB memory free after boot, no swap; root fills the card (17 GB free).
- USB mic (ATR2100-USB) is ALSA card 0; 16 kHz mono recording works, peak 3350 at Mic capture 90%; plays back clearly on the laptop.
- One Ethernet cable laptop to board: both sides self-assign 169.254.x.x; SSH (Dropbear), scp, and `python3 -m http.server 8000` all work from the laptop.
- HDMI: the board fell back to 1024x768 and the portable monitor showed nothing; forcing 1920x1080 in `/etc/xdg/weston/weston.ini` fixed it. TI's demo menu uses about 500 MB of memory.
- Not done: RTC module (clock is wrong after every boot).
- Guide: `docs/board-setup.md`. Code commit: 5b5e261.

## #9 Summary on the board: llama.cpp and the end screen's model note (2026-11-03)

- `speakup/summary.py`: `build_prompt` is ChatML (the chat format of Qwen2.5 and SmolLM2) with one worked example (age 7 yr 6 mo, rope gliding flagged, bird distortion normal), and lists only the words with an error plus the count of words. `check_reply` keeps a reply off the screen when it is empty; says pass, refer or diagnose; has a number not in the facts; has `not` or `n't` in any sentence; says `no` or `none` in a session with an error; or has a sentence that names a word with no error, an example word, a flagged word as normal, a normal word as flagged, or the wrong error phrase. `note()` replaced `summarize()`.
- `speakup/llm.py`: `load(binary, model)` gives #7's `Generate` from `llama-completion` (`-n 96 --temp 0 -t 4 -c 512 -ngl 0 -no-cnv --no-display-prompt`, prompt in a UTF-8 temp file, 120 s timeout, a guess until #17). A missing model file or binary raises `LlmError` at load; a timeout, a non-zero exit or any `OSError` raises `LlmError` per call.
- End screen: a "Model note:" paragraph under the Refer or Pass bubble, made once when the last Next is pressed, kept across a refresh and on the failed-save page, cleared by a new start. `python3 -m speakup --llm-bin PATH --llm-model PATH`; the model is off without `--llm-model`. A missing file or binary prints `--llm-model: ... The end screen shows the tally only.` at start; a failed or rejected reply prints `summary note skipped: <reason>` and the screen shows the tally only.
- `docs/model-timing.md` "On the board": the `time_model.py --llm` line uses `$HOME/llama.cpp/build/bin/llama-completion` and `-c 512`; new subsection with the pack, `which cmake make g++`, build (`-DLLAMA_OPENSSL=OFF`, target `llama-completion`) and app commands. README Board bullet names the two flags.
- Measured on the Mac, Homebrew `llama-completion` build 11960, Qwen2.5-0.5B Q4_K_M: at planning the prompt was right on 5 of 6 sessions, and the check rejects the sixth (`--demo` at 5 yr 2 mo). At build, through the app with `--demo`: 8 yr 0 mo showed the note; 5 yr 2 mo showed the tally only (`summary note skipped: calls a word flagged that is normal for age`).
- Gate 1 Decision 9: the board items (llama.cpp built and run on the AM62x, the note on the board's end screen, the real board time for the 120 s guess) are the owner's steps the night of Nov 3.
- Plan deviations: no `build_prompt` import in `tests/test_server.py` (unused); the README "Demo:" line is unchanged (the plan gave it no text). Review fixes beyond the plan: the negation and `no`/`none` rules in `check_reply`, and the temp file inside the `OSError` catch, so a full `/tmp` cannot drop the last Next before the save.
- Tests: `tests/test_llm.py` 6, `tests/test_summary.py` 10 (4 new, 3 rewritten, 1 deleted), `tests/test_server.py` 6 new. Full check in the worktree: Ran 103 tests, OK. Full check on main after the merge: Ran 103 tests, OK.
- Deferred from review: plurals ("carrots") and spelled-out numbers ("ten words") slip past `check_reply`; no test presses Save again after a note; `--llm-bin` without `--llm-model` is ignored with no message; a hung llama.cpp blocks the one-request server for up to 120 s.
- Commits: 8c67026, adff399, c4b1fbd, 29a7326, aadbe2d; merge 59f582a.

## #2 Arti: the board's r model, trained, scored and timed on the laptop (2026-11-03)

- The Nov 3 decision: the model answers right or wrong only. `speakup/result.py` has `ERROR_WORDS` (`gliding`, `distortion`, `off` → "the r sounded off") and `ERROR_TYPES = tuple(ERROR_WORDS)`. `("r", "off")` in `AGE_NORMS` flags from 96 months, with the same consonant-age-of-acquisition source as distortion; Lexi confirms. The word page, the summary page's tally and the #7 prompt show "the r sounded off", never "off". `fake_model` and `demo_model` keep gliding and distortion.
- `speakup/arti.py`: `read_wav` (16 kHz mono 16-bit only; any other format is a `ValueError` naming it, shown on the word page), `prepare` (the loudest 1.5 s by 10 ms frame energy, padded at the end, scaled to a peak of 1.0, silence stays zeros), `to_result` (`p_wrong` of 0.5 or more is `off` with `heard_phone` null; model `arti-v0`), `load` (ONNX Runtime, 4 threads; `onnxruntime` and `numpy` imported inside, so the app and tests stay standard library). `python3 -m speakup.arti MODEL WAV WORD` prints one #3 result. `python3 -m speakup --arti PATH` runs it in the app and needs `--arecord`; it refuses `--demo`. `.gitignore` has `models/`.
- `scripts/train_arti.py` (laptop, through `uv run --managed-python`): 42,350 clear-label child clips from non-test speakers (12,203 correct, 30,147 wrong), split by speaker, seed 2026: 106 train, 12 val, 55 test, asserted disjoint before any audio is read. Log-mel frontend inside the ONNX graph (Conv1d DFT and a mel matrix), 4 conv blocks, 60,706 parameters, every setting a labeled guess. Kept epoch 4 of 20, val balanced accuracy 0.844; val swung 0.64 to 0.84 between epochs. Export opset 18, `audio [1, N]` (N of 2800 or more) → `p_wrong [1]`; torch and ONNX Runtime agree within 2.5e-07. On the #14 test set: 259 of 300 (start-r correct 69/75, start-r wrong 59/75, end-r correct 68/75, end-r wrong 63/75). The model rebuilt later on Nov 3 scores 258 of 300 (start-r correct 70/75, start-r wrong 59/75, end-r correct 69/75, end-r wrong 60/75); 258 is the number to quote. The mel cache is beside the zip; no model file is committed.
- `scripts/time_model.py` (onnxruntime and numpy only; runs on the board as is) and `scripts/export_wav2vec2.py`. Laptop, M3 Pro, 4 threads: Arti 1.0 MB, 64 MB peak, 0.0019 s per 1 s clip through the app path (`--prepare`; the model alone is 0.0003 s, a 3 s clip is 0.0033 s). wav2vec2 fp32 1267 MB, 1401 MB, 0.112 s; int8 (MatMul only) 358 MB, 626 MB, 0.059 s. Qwen2.5-0.5B Q4_K_M summary with Arti loaded, llama.cpp b11146 `llama-completion -ngl 0`: 1.56 s, 1125 MB (1187 MB with Arti); with `-c 256`, 1.22 s, 844 MB (905 MB).
- `docs/model-timing.md`: the table (board rows "not run yet (#1)"), the pick (Arti), how it was trained, rebuild commands, laptop and board commands. `docs/test-set.md` has a Result line.
- Gate 1 Decision 1: #2 closes on laptop numbers. The board run is #17 (`Blocked by #1`).
- Plan deviations: uv runs with `--managed-python` (the Python.org 3.12 leaks an old protobuf and breaks `import onnx`); the ONNX time axis starts at 2800 samples (torch.export needs a floor for the four pools); wav2vec2 int8 quantizes MatMul only (the weight-normed positional Conv fails `quantize_dynamic`); the summary runs `llama-completion`, not `llama-cli`, which this llama.cpp build moved one-shot text to; an extra `-c 256` row; `time_model.py` prints `llm_reply` and has `--prepare`.
- Found while building: the summary model, on the raw #7 prompt with no chat template, listed errors over and over and made one up ("carrot: the r sounded off", carrot was correct). Recorded in `docs/model-timing.md` for #9.
- Tests: `tests/test_arti.py` 5, plus 4 new and 1 extended across age_norms, result, session, summary and server. Full check in the worktree: Ran 86 tests, OK. Full check on main after the merge: Ran 86 tests, OK.
- Deferred from review: the mel cache is reused when the clip list matches even if the frontend settings changed; `wave.Error`, `EOFError`, `TypeError` and onnxruntime errors from a bad clip are not `ValueError`, so they skip the word page's error line; the tally reads "gliding 0, distortion 0, the r sounded off N" under Arti; `--arti` without onnxruntime gives an `ImportError` traceback; "(pairwise disjoint)" is a fixed string printed after the assert.
- Filed while building: #17 (run #2's timing on the board, `Blocked by #1`), #18 (rabbit vs wabbit on the team's recordings).
- Commits: f785aac, ab852ad, e5959e2, 04076f9, d2e768f, 8e2c2e9; merge 0f76867.

## #6 Session log: what the therapist sees later (2026-11-03)

- `speakup/store.py`: SQLite on the board, standard library `sqlite3`. `save_session` writes one `sessions` row (child ID, age in months, `started_at`) and one `results` row per word (#3's fields, in order) in one transaction; `load_sessions` reads every session or one child's, oldest first by `sessions.id`. A fresh connection per call, closed when done; each call creates `data/` and the tables if missing. The file is `data/speakup.db`; `.gitignore` now also has `*.db`.
- The session is saved once, when the last Next finishes it. A session left halfway is not saved. Record again replaces the word's result, so each word is saved once; a second Next on the summary does not save again.
- Flags are worked out when a page is read (`SavedSession.is_flagged` calls `should_flag` with the stored age), not stored. If a norm changes, old sessions show the new answer.
- Pages: `GET /sessions` (big session count, totals, then every session newest first: date, child ID linked to its page, age, flags) and `GET /child/<id>` (flags in the last session against the first, an inline SVG line of flags per session, then one row per session oldest first with every word as a green, amber or red chip). An ID that fails `parse_child_id`, or has no sessions, gives 404. The start page links to Past sessions.
- Look: the owner picked c-chart (`mockups/issue-6/c-chart.html`) from three shapes of the child page (table, GFTA-style grid, chart), after asking for a light take on a dashboard reference. Light panels, one deep-red accent, #5's chip colors. The log pages have their own `LOG_CSS`; #5's pages keep theirs.
- At the owner's request, ages show as `7 yr 4 mo` on every page and in the summary prompt, not `7;4`. `summary._age` is gone; it uses `session.format_age` (closes #5's deferred note). Dates on the log pages show as `Nov 3, 2026` with the time beside.
- Tests: store 4, server 18 (4 new, 1 extended), session test asserts `started_at` has an offset. Full check in the worktree: Ran 68 tests, OK. Full check on main after the merge: Ran 77 tests, OK.
- Deferred from review: a failed save (SD card full or read-only) drops the connection after the session has moved to done, so a retry shows the summary unsaved; chart labels collide at about 8 or more sessions for one child; `_connect` leaks a connection if the file is not a database (GC closes it); `GET /sessions` creates `data/` and an empty database on a read.
- Filed while building: #15 (`self.fail` in `tests/test_server.py` shadows `TestCase.fail`, so a failing assert shows as `TypeError`).
- Board risk, not fixed here: the Yocto image may ship Python without `sqlite3` (`python3-sqlite3` package); add `python3 -c "import sqlite3"` to #13's checklist.
- Commits: 11bdd6e, eaafd31, 928c49d, a6c3c56, 3f3794b; merge 8844379.

## #14 PERCEPT-R test set: 300 start-r and end-r clips, held out by speaker (2026-11-03)

- `python3 -I scripts/pick_test_set.py data/percept-r/PERCEPT-R.zip` reads the zip in place and writes `test-set.csv` (columns `zip_path, speaker, age_months, word, position, label, listener_says`) and `test-speakers.txt` beside the zip, in `data/percept-r/` (gitignored). Standard library only, no imports from the repo. Labels and ages are read with `pickletools.genops`; the script never imports `pickle`.
- Rules: children only (age 144 months or less); a label of 0.25 or less is wrong, 0.75 or more is correct, the rest stay out; 75 clips per cell (start-r and end-r, correct and wrong); whole speakers held out, walked in an order shuffled with seed 2026 until every cell can be filled; one clip per speaker per word, picked at random before it is sorted into a cell. Word lists are constants: start rabbit, rain, ring, rocket, red, rock, run, rug, rose; end car, door, bear, star, chair, floor, hair, pear, deer.
- Real run on `PERCEPT-R 2.2.2py`: 55 of 173 children held out, ages 72 to 143 months; 75 clips in each cell; 13 label pickles skipped (not one float); 0 speakers skipped; training pool 105,647 clips, 21,639 removed by the hold-out, 84,008 left. Two runs gave byte-identical files. The numbers match the planner's dry run.
- `docs/test-set.md`: counts table, held-out speakers and age range, rules, the rule for #2 (train on no clip from any held-out speaker), how to rebuild, citation. No speaker IDs, file names, or labels.
- Plan deviation: `Picked` gained a `test_ages` field, because the printed age range covers every held-out speaker and a held-out speaker can have no clip in the set.
- Tests: 9 in `tests/test_pick_test_set.py` on a fake zip (label rule, age filter, word lists, hold-out, one clip per speaker per word over 50 seeds, a code-running label pickle skipped and never run, byte-identical runs, a short cell raises). Full check in the worktree: Ran 69 tests, OK. Full check on main after the merge: Ran 69 tests, OK.
- Deferred from review: labels are not range-checked to 0..1 and ages have no lower bound; a non-numeric speaker folder with a valid age would exit with a bare `int()` error; a failed run leaves an earlier run's files beside the zip; `main`'s exit-1 path has no test. None of these can happen on the current corpus.
- Commits: d906d08; merge: fast-forward, no merge commit.

## #5 App skeleton: session flow with the fake model (2026-11-03)

- `python3 -m speakup` serves the session on port 8000: start (child ID and age in years and months), one page per word (Record, what was heard, flagged or normal for age), and a summary (tally, a table of every word, and #7's pass or refer line). Standard library `http.server`, plain HTML forms that redirect (303), no JavaScript, nothing loaded from off the board.
- Look: the owner picked the speech-bubble strip (`mockups/issue-5/c3-bubble.html`) from three shapes and then four takes on the strip: word chips across the top that fill in green, amber or red; the word in a speech bubble; the Refer line in a red bubble. Rounded system font, no downloaded fonts.
- `speakup/session.py`: input checks (ID is letters, digits and hyphens, because it goes into the clip's file name; months 0 to 11 or blank), `should_flag` from #4 on age in months, Record again replaces the word's result, Next only after a result, and `tally`.
- Pass or refer comes from #7's `speakup.summary.pass_or_refer`, which landed first; #5 does not have a second copy. Its copy replaced the plan's, so "The therapist decides on a full assessment." is not on the page.
- `speakup/recorder.py`: `--arecord` runs `arecord` at 16 kHz mono into `recordings/` (gitignored) as `<child_id>-<time>-<word>.wav`; `--device` and `--seconds` (3, a guess) tune it on the board. The laptop uses a fake recorder that writes nothing. A failed recording or a bad model record shows its error on the word page (500), and Record works again.
- `--demo`: results come from a script keyed by word (`speakup/demo_model.py`: rabbit and giraffe glide, carrot is distorted); the server refuses to start if a word in `words.csv` has no line.
- Tests: session 7, recorder 4 (a stub `arecord` script), server 14, demo 3. Full check in the worktree: Ran 60 tests, OK. Full check on main after the merge: Ran 60 tests, OK.
- Deferred from review: a query string (`/word?x=1`) gives 404; a bad request body or a non-`ValueError` from a future model still drops the connection; the start line prints `http://0.0.0.0:8000`; `summary._age` duplicates `session.format_age`; no length cap on the child ID (a very long one fails the recording on the board).
- Not checked on the board yet (#1): #13.
- Commits: 56a71c9, 84cc7c3, 1e17f14, d5d75ef, 4c1898e, 25faaae, e67d767; merge 20e3813.

## #7 Session summary: the function and prompt, with a fake model (2026-11-02)

- `speakup/summary.py`: `pass_or_refer(results, age_months)` gives the decision line, `build_prompt(results, age_months)` gives the facts prompt, and `summarize(results, age_months, generate)` puts the code's line first and the model's stripped reply below it. `Generate = Callable[[str], str]` is the seam #9 points at llama.cpp; it is a required argument, so no fake can stand in by accident.
- The code decides: refer when any one word is flagged by `should_flag` (#4), pass when none is. Copy: `Pass: 0 of 5 words flagged for age 6;8.` and `Refer: 2 of 5 words flagged for age 7;6 (rabbit, mirror).` Age shows as years;months. Every try counts as one word.
- The prompt lists the age, the words tried, and one line per error (`(heard X)` only when `heard_phone` is set, then `flagged for age` or `normal for age`), or `Errors heard: none`. It tells the model not to say pass or refer and not to diagnose. No name is in it.
- An empty session raises `ValueError` before the model runs.
- Tests: `tests/test_summary.py`, 6 tests, with a fake model in the test file. Full check on main after the merge: Ran 32 tests, OK.
- Deferred from review: no test asserts `normal for age` in the prompt for a child under 84 months; an empty model reply leaves a trailing newline (#9 sees real replies).
- Code commit: 1ddd8dc.

## #3 Result format: what the model hands to the app (2026-11-02)

- `speakup/result.py`: the `Result` dataclass (word, target_sound, expected_phone, heard_phone, error_type, confidence, model, recorded_at) and `check(d)`, which returns a `Result` or raises `ValueError` naming every bad field. Unknown fields are rejected, so a child's name or an audio path can't ride along. A correct word must have `heard_phone` equal to `expected_phone` or null; `recorded_at` needs a UTC offset.
- `speakup/fake_model.py`: `fake_listen(word, rng)` returns correct, gliding or distortion at random, with `model: "fake"`. The app uses it until #2 lands.
- `docs/result-format.md`: each field with a correct and a wrong example, plus two whole records.
- Tests: `tests/test_result.py`, 16 tests. Full check on main after the merge: Ran 22 tests, OK.
- Review answers (Raf): the board model gives a confidence (softmax); null stays allowed. Board clock: an external RTC module, tracked in #1. Raf prefers a small classifier (Arti) over wav2vec2 phoneme transcription; the format fits both.
- Open, decided in #2: PERCEPT-R labels are rhotic vs derhotic only, and `error_type` has no value for "wrong, type unknown".
- Merged as PR #8 (code commit 7d2cbd5, merge a4b4b34).

## #4 Age rule: drop errors that are normal for the child's age (2026-10-30)

- `speakup/age_norms.py`: `AGE_NORMS` maps `(sound, error_type)` to an `AgeNorm` (the age in months from which the error flags, and its ASHA source URL). `should_flag(error_type, sound, age_months)` returns `False` for a correct sound (`error_type is None`), raises `ValueError` for an unknown pair, and otherwise flags when `age_months >= flag_from_months`.
- Rows: r gliding flags from 84 months (7;0), from ASHA's selected phonological processes. r distortion flags from 96 months (8;0), the top of the /ɹ/ 90% range in Crowe & McLeod (2020), Table 2. The 96 is a proposal that waits on Lexi.
- Tests: `tests/test_age_norms.py`, 6 tests (edges at 83/84 and 95/96, a correct sound never flags, unknown error type and unknown sound raise, every row cites asha.org). Full check: Ran 6 tests, OK.
- The function takes age in months. A caller that passes years (for example `7`) gets `False` with no error; #5 or #6 owns the conversion.
- Code commit: 856e12d.
