# STATE.md's head names the ticket. Start there.

`STATE.md` opens with a YAML head. **`next_action` names the issue that is up now** — go straight
to it. Do not read the issue list and decide for yourself what's important; the owner has already
decided, and that is what the field is for. When no ticket is up, it holds a quoted reason
instead, such as `next_action: "none: idle"` or `next_action: "none: no ticket is ready-for-agent"`
(unquoted, `none: idle` is not valid YAML). An accept never leaves it `""`; only a freshly
bootstrapped repo starts there. Below the head, STATE.md is a thin snapshot: what's mid-flight,
how to run/verify, and the gotchas that have already bitten. The full build archive and
per-feature detail live in `docs/HISTORY.md`.

**The work queue is GitHub Issues** (`gh issue list`). The `ready-for-agent` label means the issue
has its four template sections filled in **and** the owner has green-lit it — that's the eligible
pool. `next_action` picks one out of it. A ticket also isn't ready unless it is **buildable in one
fresh session** inside the lean-window target — too big means split it before green-lighting.
Anything unlabeled still needs owner confirmation before starting. Reference issues in commits
(`refs #N`).

# One ticket = two sessions

Planning and building do not share a window. A context that has read the issue, explored the code,
and written a plan is a **poor context to then write the code in** — so the plan goes to a file and
a fresh session builds from it.

- **`/plan-ticket [#N]`** — read the ticket, write `docs/superpowers/plans/YYYY-MM-DD-issue-N.md`,
  stop. No code. The owner reads the plan (**gate 1** — cheap; nothing is built yet).
- `/clear`
- **`/build-ticket [#N]`** — build from the plan file, run the suite, **paste the real output**,
  stop before landing anything on main. Multi-task plans build on a ticket branch with one commit
  per approved task; single-task plans stay uncommitted in the working tree. The owner reads the
  diff (**gate 2**). Optional pre-reads the owner may run first: `/gate2-review [#N]` (does the
  diff meet the repo's standards, and does it implement the ticket and its plan) and
  `blast-radius` (what the change could break outside the diff). Both are aids to the owner's
  read and never replace it.
- On the owner's accept: land the code (merge the branch, or commit the working tree), then a
  docs commit; push both together, close the issue, `/clear`.

**Or run the whole ticket from one thread: `/run-ticket [#N]`** (alias `/rt`). It runs
`/plan-ticket` in a fresh `rt-planner` subagent, and after the owner says go at gate 1,
`/build-ticket` in a fresh `rt-builder` subagent; both run Opus 5.5 at high effort with only the
tools their command needs (agent files in skillbook's `agents/`, linked at `~/.claude/agents`).
The thread relays each subagent's closing word for word and stops at
gate 1, at gate 2, and after the accept. The owner's notes at a gate go back to the same subagent.
Planning and building still do not share a window, because each subagent starts with an empty one.
Every run works in its own git worktree on branch `issue-N`, branched from local main, so two
tickets can run at once in one repo; at accept the work lands on main from the main folder, and
the owner's push line also removes the worktree and deletes the branch. This is an extra option
for now; the manual path above stays.

The closing message at each of the three seams — the end of `/plan-ticket`, the gate 2 stop, and
the after-accept stop — is written under the `wait-what` skill's rules from the start (global
CLAUDE.md, section 8). The rule covers the summary only: build output, test output, and diffs
stay raw at gate 2, because the owner's read depends on seeing the real output.

Planning and reviewing spend judgment; building from an approved plan mostly spends execution.
The build session may therefore run a cheaper model — start it with `claude --model opus` and
save Fable's weekly budget for `/plan-ticket` and the gates. The plan's constraints are what keep
a cheaper builder in bounds; a build that keeps failing gate 2 means the plan was under-specified
first, the builder too weak second. A non-Claude builder (Codex / GPT-5.6 Sol) slots in the same
way — it reads `AGENTS.md` and the plan file — paste-in prompt to be added here if adopted.

# STATE.md is written exactly once per ticket

**In the accept-time docs commit, after the owner accepts. Never mid-session.**

Continuous updates are what makes this file drift and bloat, because a session writes it from a
context already full of its own work, and it ends up recording things the owner never accepted.
One write, at the seam:

- **Mid-session discoveries never touch STATE.md** → `gh issue create` immediately. The issue queue
  is the capture buffer (write anytime, cheap); STATE.md is the accepted-state snapshot (write once).
  Nothing is lost if a session dies — the plan file, the branch, and the issue all outlive it.
- **Acceptance lands as code commits + one docs commit, pushed together**: the code first — the
  ticket branch's per-task commits merged, or a single `type(scope)` commit for single-task
  tickets — then one docs commit carrying `STATE.md` (Now cleared of the finished item,
  `next_action` set to the ticket or `none:` reason the owner's accept confirmed or named, from
  gate 2's list of eligible tickets, `last_worked_on` bumped) and the feature's section in
  `docs/HISTORY.md`. Then close the issue.
- **"Now" holds unaccepted work only.** The moment the owner accepts something it moves to
  `docs/HISTORY.md`. Keep "Now" under ~6 lines. Gotchas stay in STATE.md — they're the memory that
  earns its place — but a gotcha lives there only while it would still bite an agent working today.

# Session hygiene — keep the window lean

Target **≤140k tokens of working context per session.** This works because state lives
OUTSIDE the conversation: `STATE.md` (snapshot), GitHub Issues (queue), `docs/HISTORY.md`
(archive). Suggest a fresh window at natural seams — phase acceptance, plan approval, deploy —
rather than letting a session balloon; a decision that lives only in conversation memory doesn't
exist, so write it to the right file the moment it's made.

# Verification scope

- **While iterating, test only what you touched** (`python3 -m unittest tests.test_<module>`). The full suite (`python3 -m unittest`) runs once, at the end of
  `/build-ticket` — not after every change.
- **At most one dev server and one test run per worktree, on a free port, stopped by whoever
  started it.** The session that builds the ticket may start them (under `/rt`, that is the build
  subagent); helper subagents it spawns may not.
- **Stop what you started.** Kill any dev server, build server, or tunnel you launched before
  ending the session.

# Visual rule

Anything visual gets 3 single-file HTML variants first; the owner picks; the winner gets wired in.
Three variants means three shapes — a second flavor of the first shape doesn't count. Variants go
in `<folder, e.g. mockups/ or design-directions/>`; the winner is wired into
`<where, e.g. the page or component it replaces>`, and the losing variants are `<kept or deleted>`.

# Commit format

`#N short summary` (as in PR #8). Trailers: the harness default. A commit hook, if one exists, is named here too.

# The ticket commands are global

`/plan-ticket`, `/build-ticket`, `/run-ticket`, `/pt`, `/bt`, `/rt` live once, in skillbook's
`commands/`, which `~/.claude/commands` links to. They carry the protocol; this file carries what
differs per repo.
If a repo's `CLAUDE.md` does not import this file, the commands read it themselves. Three H1
sections above are the ones the commands **quote**, so they are found by heading — the text up to
the first ` (` or ` —`, so `# Verification scope (owner rule, 2026-07-28)` still matches:

- `# Verification scope` — the focused check, the full check, and any forms for reading their
  output. `/plan-ticket` quotes the full check into the plan's last step; `/build-ticket` runs it
  and pastes the output. Missing: the commands fall back to STATE.md's `## Run / verify` and say so.
- `# Visual rule` — where variants go and how the winner is wired in. Missing: the generic rule
  applies and the plan names the folder it chose as a gate 1 decision.
- `# Commit format` — the commit form and trailer policy. Missing: `type(scope): summary (refs #N)`.

Everything else in this file is a standing instruction the commands honor without quoting. Any
other line a repo wants the commands to obey goes here as ordinary text, not in a local command.

**Precedence.** When a personal command (`~/.claude/commands`) and a project command
(`.claude/commands`) share a name, Claude Code runs the personal one (code.claude.com, "Resolve
skills that share a name": enterprise over personal, personal over project). So a
`.claude/commands/plan-ticket.md` left in a repo is inert from the moment the global set exists —
delete it. The leftover does not show in the `/` menu either: only the personal command is listed,
marked `(user)` (checked in skillbook, 2026-09-29).

**Closing issues.** Close with `gh issue close N --comment "<one-line result>"`, never with the
button on github.com: the cmux workspace-description hook refreshes the description when an agent
runs `gh issue close`, and a close on github.com leaves it stale (skillbook #43).

# Question tickets — mapping decisions (opt-in)

Most tickets are work orders: the deciding already happened before `ready-for-agent` went on.
Some projects stall earlier than that — too many open decisions, each waiting on another, and
no way to see which one can be made today. For those projects only, add a decision layer in
front of the work queue:

- **A pinned map issue** names the destination and holds the decision list — one line per
  answered question — plus a **Fog** section: decisions the owner can see coming but can't
  phrase as a question yet. Fog costs one line to park and, unlike a premature ticket, has
  nothing to go stale.
- **The `question` label** marks a ticket that holds one open decision, not work. Its body
  says what the question is and what answering it unblocks. Question tickets are exempt from
  the four-section agent-task template.
- **`Blocked by #N`** as the first body line of any ticket — question or work — that waits on
  an open question. The frontier, what the owner can take today, is every open ticket with no
  open blockers. Answering a question closes its ticket, adds a line to the map, and usually
  turns some fog into new question tickets.
- **One question per session**, same rhythm as build tickets. The answer and its reasoning are
  written on the ticket at close — the ticket does for a decision what the plan file does for
  code.
- **Regenerate the map when a ticket closes** — question or work, either kind:
  `node ~/Developer/tools/decision-map/decision-map.mjs <owner/repo> --out docs/decision-map.html`.
  Read-only (it only reads `gh issue list`) and it writes one self-contained HTML file, so it
  rides along in the accept-time docs commit and the picture in the repo never lags the queue.

Work tickets and `next_action` behave exactly as above; this layer feeds them. A project with
a short queue and fast decisions gets nothing from it — the owner's `next_action` pointer
already does that job. Skip it there.
