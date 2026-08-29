# Watchdog forensic detail [V]

The operational summary is in SKILL.md ("The Git HEAD watchdog" section).
This module holds the forensic evidence for agents who need to understand
*why* the watchdog behaves the way it does.

## Method

Double-forked observer (the experiment's `wdt_watch.py` — removed from the
shipped kit in v5.1; the forensic rounds are complete and this module +
`evidence/watchdog-forensics.log` hold the results) armed inotify (ctypes) on
`/home/z/my-project/.git` + 4 Hz `/proc` scanning; interleaved bash/Read/
Write toolcalls; markers written into the log for windowing. Raw evidence:
`evidence/watchdog-forensics.log`.

## Verified mechanics

- **Trigger**: EVERY toolcall of every observed type — Bash, Read, Write —
  also observed from within a sub-agent session. Not time-based; nothing
  happens while the session is idle.
- **Actor**: `git switch main` run as user z, cwd `/home/z/my-project`,
  spawned as a child of a prelude chain `/bin/sh -c su z -c /bin/bash`
  that the bridge starts ~200–500 ms before the toolcall's command chain.
- **Write mechanism**: real git (lockfile create/write/rename; new inode
  per reset; file mode 664, owner z:z).
- **Scope**: ONLY the repo at `/home/z/my-project` (resolved through a
  `.git` pointer file too). Other repos anywhere else: untouched. Linked
  worktrees: untouched.
- The watchdog itself commits nothing; UUID-message commits come from the
  platform's own `git add -A` at recycle/pre-stop (not observed mid-session).

## Why it exists (inferred)

The platform wants the workspace on a stable branch so its `git add -A`
snapshot commits land linearly on main. Do not fight it — stay on main and
it is inert.
