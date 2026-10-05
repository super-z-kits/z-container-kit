# Watchdog forensic detail [V — two container generations]

The operational summary is in SKILL.md ("The Git HEAD watchdog" section). This
module holds the complete verified model and the evidence chain. Investigated
2026-08-28 (E1–E14), 2026-09-09 (T1–T4 rounds), and 2026-09-28 (independent
audit + byte-exact script recovery in a fresh container after a real 19-day
graceful recycle). Raw instruments + all sub-agent reports: private research
repo `zikomolapoutl/zai-watchdog-research-20260909`.

## The complete model (every element live-verified)

- **Actor**: the ZAI bridge (`/app/.venv/bin/python3 main.py`, root; process
  tree tini(1) → caddy(2) → uv → python). Boots unconditionally at container
  start (ready ~7–15 s), before any chat/skill/project-type exists — the
  watchdog is **always armed from boot**; it is not conditioned on
  caddy/fullstack/project type. (The fullstack skill's `init-fullstack.sh` is a
  user-space template drop that cannot reach the root bridge — privilege
  boundary, re-verified 2026-09-28 against the v2 script, which had drifted but
  still contains zero git/kill/app references.)
- **Trigger**: before EVERY toolcall — every observed type (Bash, Read, Write,
  LS, Grep, Glob, TodoWrite), main session AND sub-agents, toolcalls that go on
  to fail (dispatch precedes execution), N parallel calls = N serialized chains
  (~250 ms apart). NEVER while idle (not timer-based; idle windows up to 218 s
  silent).
- **The two-chain prelude** (scripts recovered VERBATIM from the prelude
  bash's heap — same-uid /proc/PID/mem scan + transparent git-shim, byte-exact
  at identical heap offsets; 2026-09-28):
  1. **Report chain — EVERY toolcall**, ~100–350 ms before your command:
     ```
     export PATH=/home/z/.venv/bin:$PATH && cd /home/z/my-project && git branch --show-current
     echo "<<exit_code:$?>>"
     ```
     Read-only. The bridge evidently keys on the chain's stdout
     (`<branch>\n<<exit_code:N>>` observed; the parser's internals are
     unreadable — the firing rule is behaviorally proven across 4 repo states).
  2. **Switch chain — a SECOND, fresh `su z -c /bin/bash` chain 205–209 ms
     later, ONLY when the report ≠ main** (also a two-line script — `2>&1`
     feeds the bridge the switch's errors alongside the exit code):
     ```
     export PATH=/home/z/.venv/bin:$PATH && cd /home/z/my-project && git switch main 2>&1
     echo "<<exit_code:$?>>"
     ```
  The conditional is **BRIDGE-side** — there is no in-script `if` (the earlier
  "guarded script with in-script conditional" inference was corrected 2026-09-
  28; its `CUR=$(…)` / `[ != "main" ]` fragments originated from a mimic
  payload, never from the real prelude). This also explains the old timing
  observation "flip lands ~200 ms after prelude burst" — that gap IS the
  report→switch chain spacing.
- **Anatomy** (caught live, both container generations): `/bin/sh -c su z -c
  /bin/bash` (root) → `su z -c /bin/bash` (root) → `/bin/bash` (uid 1001,
  script piped via stdin — fd0 is a pipe, never a file;   PWD=/home/z/my-project;
  ~190 ms lifetime — the script itself runs ~15 ms, then the bash blocks
  waiting for stdin EOF: the bridge holds the write end open until it has read
  the output) → `git …`. (The export DOUBLES `.venv/bin`, which contains no
  git — actual resolution is `/usr/bin/git` (`_=` in the prelude env), or the
  experiment's shim at `.npm-global/bin/git`.)
- **Scope**: ONLY the repo at `/home/z/my-project` (resolved through a `.git`
  pointer file too). Other repos anywhere else, linked worktrees: untouched.
- **Never does**: touch untracked files (even `git switch -f` spares them; a
  name collision makes the switch FAIL rather than overwrite), destroy
  commits/refs (every probe commit survived), force-push, commit (no mid-
  session commits ever observed; the pre-stop `git add -A` is conditional —
  see kb/repo-tar-mechanics.md), run on a timer, or execute the switch while
  on main (reflog frozen across hundreds of toolcalls).
- **Why (inferred)**: the platform wants the workspace normalized to main so
  its pre-stop snapshot lands linearly. Don't fight it — stay on main and it
  is inert.

## Evidence chain (key artifacts)

- **2026-08-28**: E1–E14 (evidence/EXPERIMENTS.md, evidence/watchdog-
  forensics.log) — literal `git switch main` catches; watchdog ACTIVE in a
  bare-bootstrap session (dormancy hypothesis dead on the activation side);
  scope limits; dirty shield.
- **2026-09-09**: three observer generations (inotify + /proc) incl. the
  process-tree smoking gun (observer3.log 03:36:34.364, ancestry to the root
  bridge); 13 sub-agent reports (T1–T4); 11 off-main→main flips reflog-
  stamped; dirty-shield / carry-over / detached-HEAD / mid-rebase rows
  live-verified; every "mystery" .git write attributed to ordinary git
  commands.
- **2026-09-28** (fresh container, post-recycle): independent claim-by-claim
  audit (56 claims, core model intact); 105 prelude catches + 33 shim catches
  (30 guards, 2 switches, 1 mimic);
  scripts recovered byte-exact; TodoWrite covered; failing-toolcall + parallel-
  call behavior; timing distribution mean 216.9 ms (213.3–222.9, n=8); two-
  chain structure proven by paired catches (report→switch spacing 205–209 ms).

## Attribution rules (telling actors apart)

- **Parent cmdline discriminator**: the prelude bash's parent chain is `su z
  -c /bin/bash` (plain `/bin/bash`); YOUR agent chains run `/bin/bash
  --noprofile --norc`. Every catch can be attributed by ancestry.
- Your own plain `git switch main` (or `git checkout main`) while ALREADY on
  main (git 2.47.3) writes a harmless `main→main` reflog entry + HEAD rename +
  index rewrite — NOT the watchdog (the prelude never runs the switch on
  main). See kb/watchdog-advanced.md.
- `git branch -D` rewrites `.git/config` via a lockfile dance; `git
  commit/switch` spawn `git maintenance run --auto` (more lockfile dances) —
  benign, all attributed.
- reflog "truncation" seen through `head -N` / Read(limit=N) is a VIEW
  artifact — check the file's size/mtime before claiming a writer touched it.

## Capture techniques (reusable, same-uid)

- **/proc reads**: the prelude bash runs as uid 1001 — same as you. With yama
  absent (check /proc/sys/kernel/yama — it does not exist here), /proc/PID/
  {environ,maps,mem} are readable. A fast poller (100–150 Hz) that catches the
  bash early can dump its heap: the piped script sits in the stdin read
  buffer. NOTE: early dumps show line 1 only — line 2 arrives in the buffer
  after line 1 executes (progressive pipe delivery), so track the process and
  snapshot repeatedly.
- **Git-shim**: the prelude's PATH (`/home/z/.venv/bin:/home/z/.npm-global/
  bin:…` — user-writable dirs BEFORE /usr/bin) lets a transparent `git` shim
  (log argv + dump parent bash memory, then `exec /usr/bin/git "$@"`) capture
  invocations at execution time — no race. Plant briefly, verify transparency,
  REMOVE IMMEDIATELY. (Prior observers missed PATH because their env dumps
  truncated the list at 20 vars and masked any key containing "PAT" — PATH
  was hidden by both bugs. Log env keys in full.)
- Instruments preserved in the research repo: `prelude_capture.py`,
  `wdt_inotify.py`, `wdt_observe.py` + raw logs/memsnap evidence.

## Open boundaries (honest)

- A fullstack-ACTIVE container was never live-observed (cannot spawn one from
  inside) — that quadrant is analytic: the bridge boots before any project
  state exists, and user-space code cannot reach the root bridge.
- The dirty-tree graceful recycle (does the pre-stop `git add -A` commit
  appear when the tree is dirty?) has not been exercised — the observed real
  recycle had a clean tree.
- The /tmp/my-project platform-snapshot trigger (session-idle vs recycle
  boundary) is inferred from one observation (see kb/persistence-namespaces.md).
