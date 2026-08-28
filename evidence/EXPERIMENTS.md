# Experiment Log — 2026-08-28 forensic session (UTC)

All experiments run live in the container by the main agent, using
`scripts/wdt_watch.py` (double-forked inotify + /proc observer; raw log:
`evidence/watchdog-forensics.log`). Container: booted 03:08 UTC, chat's first
session, bare bootstrap repo (single "Initial commit", no remote).

## E1 — Watchdog existence & signature
- Set `tmp/wdt-baseline` in toolcall N; observed `main` in toolcall N+1.
- `.git/HEAD` inode changed on every real reset (first observed change:
  134861 -> 134867 at 03:54:45.891; likewise on every subsequent reset) → the
  file is replaced, not truncated. Lockfile event sequence observed each
  time: `HEAD.lock` CREATE → MODIFY → CLOSE_WRITE → MOVED_FROM(HEAD.lock) +
  MOVED_TO(HEAD) with matching cookie → standard git lockfile-rename protocol.
- **Caught the culprit three times, literally (byte-exact log lines):**
  - `03:57:19.956 SPAWN pid=1471 cmd='git switch main'`
  - `03:59:05.829 SPAWN pid=1514 cmd='git switch main'` (this attempt FAILED — dirty shield, E5)
  - `04:00:24.762 SPAWN pid=1613 cmd='git switch main'`
  - Running as user z (reset file owner 1001:1001), inside a prelude chain
    `/bin/sh -c su z -c /bin/bash` (command chains run
    `/bin/bash --noprofile --norc`; the prelude chain does not).
- Sampling caveat: chain-to-command attribution comes from a 4 Hz /proc scan;
  short-lived chains can be missed or misattributed (one window at 03:54:45.766
  shows a prelude-signature chain apparently "owning" a branch-SETTING write —
  most plausibly the real command chain was simply not sampled). The hard
  evidence is the three literal `git switch main` catches plus event ordering,
  not chain signatures.

## E2 — Timing: prelude, not "between toolcalls"
- Watcher heartbeat during idle (no toolcall running) shows HEAD unchanged for
  minutes (e.g. 03:54:47 heartbeat: still `tmp/wdt-baseline` 1.7 s after chain
  exit; repeated 10 s heartbeats).
- Reset fires ~200–500 ms BEFORE the toolcall's own command chain appears
  (03:54:49.819 prelude chain → 49.858 reset → 50.068 command chain). The
  offset estimate rests on few clean samples — order of magnitude only; the
  reliable fact is the ORDER: prelude first, then the command chain.
- Operational consequence: any git sequence works inside ONE bash toolcall;
  across toolcalls the prelude always normalizes first. A bash check can never
  observe a surviving non-main HEAD — the reset precedes the check.

## E3 — Non-bash toolcalls trigger it too
- Read toolcall at 03:56:23.918: prelude chain spawned; no lockfile events —
  HEAD was already main (`git switch main` on main = no-op, no HEAD write).
- Write toolcall at 03:57:19 with HEAD on `tmp/wdt-baseline`: two chains
  spawned; `git switch main` executed (E1) and reset HEAD before the write
  completed the toolcall window.
- Conclusion: the prelude is per-TOOLCALL (observed for Bash, Read, Write),
  not per-bash-command. Sub-agent toolcalls go through the same bridge.

## E4 — Working-tree revert (the "confusing revert")
- Branch `tmp/wdt-file`, committed new file `hello-branch.txt` (306cdc0).
  End of toolcall: file present, on branch.
- Next toolcall: branch=`main`, `hello-branch.txt` GONE from the working tree,
  commit still on `refs/heads/tmp/wdt-file`.
- Conclusion: the prelude is a FULL `git switch main` — a real checkout that
  reverts the tree to main's content. v1's claim "resets only the branch
  pointer, not files" is WRONG (v1 was presumably tested with branches whose
  tips equaled main's, making the switch content-neutral).

## E5 — Dirty shield (switch failure mode)
- On `tmp/wdt-file`, appended an uncommitted edit to `hello-branch.txt`
  (a file that differs between branch and main).
- Next toolcall: HEAD STILL on `tmp/wdt-file`, dirty edit intact, watcher shows
  prelude chains ran but no HEADCHANGE — the switch failed silently and the
  platform did not escalate.
- Corollary: non-conflicting uncommitted changes are carried over onto main by
  a successful switch (standard git-switch semantics).

## E6 — Scope: only /home/z/my-project
- Repos created on `test-branch` at `/tmp/my-project/wdt-repo` (PolarFS),
  `/home/z/wdt-repo` (overlay), `/home/sync/wdt-repo` (ossfs): HEADs survived
  every subsequent toolcall untouched.
- `git worktree add` worktree HEAD (`.git/worktrees/<n>/HEAD`): untouched.

## E7 — gitdir-pointer relocation does NOT evade
- Moved real `.git` to `/tmp/my-project/gitdirs/myproj.git`, left
  `.git` pointer file. `git status` worked; set branch via pointer.
- Next toolcall: real HEAD (on PolarFS) was reset to main by
  `git switch main` (caught: pid 1613) — git resolves the pointer file.
- Conclusion: relocation is a persistence hardening (history on PolarFS
  survives force-kill), NOT a watchdog evasion.
- Method note: the inotify watcher went blind once `.git` became a file
  (read errors `<err20>` in the raw log), so the real HEAD's reset was
  verified by a post-hoc bash check in the following toolcall, not by the
  watcher itself.

## E8 — Process culling & double-fork survival
- `wdt_watch.py` (double-forked) survived 10+ minutes and 30+ toolcalls,
  logging continuously; heartbeats every 10 s prove liveness across chains.
- Re-verified 2026-08-28 by two independent review agents: `nohup ... &`
  counter dead within one toolcall; daemonize.py-launched counter alive 14+
  ticks later (PPID 1). Also independently re-verified: watchdog scope
  (scratch repos + worktree untouched across 18+ toolcalls), on-main no-op
  (zero lockfile events across ~18 toolcalls), and prelude firing inside a
  sub-agent session for Bash/Read/Write toolcalls.

## E9 — Storage performance & git-on-FUSE
| Operation | Time |
|---|---|
| 10 MB sequential write to ossfs (/home/sync) | 0.17 s (~61 MB/s) |
| 10 MB write to PolarFS (/tmp/my-project) | 0.21 s (~50 MB/s) |
| 100 × 4 KB small files on ossfs | 6.39 s (~64 ms/file) |
| `git add` single file on ossfs repo | 0.22 s |
| `git commit` on ossfs repo | 0.70 s |
| `git add` / `git commit` on PolarFS repo | 0.12 s / 0.39 s |
- Git works on both FUSE mounts for small repos; ossfs small-file overhead
  makes large repos/snapshots-as-many-files impractical → zsave uses ONE tar.

## E10 — Persistence namespaces (observed, inference)
- Fresh chat boot: `/home/sync` EMPTY (no repo.tar until first graceful
  shutdown), `/tmp/my-project` contains only platform-written
  `.initial_snapshot.json` (today), `/home/user_skills` EMPTY with root-dir
  mtime Jul 27 (a month before this container).
- Inference: /home/sync + /tmp/my-project = per-chat namespaces;
  /home/user_skills = per-user (its inode/mtime predates this chat).
  NOT PROVEN — github remains the only guaranteed cross-chat persistence.

## E11 — Boot script facts (read from /start.sh, not black-box)
- repo.tar restore path wipes my-project (except upload/ mount) then extracts;
  clean-project path creates .env + download/README.md + skills/.
- `.gitignore` force-written to exactly `skills/` + `node_modules/` (with
  auto-heal of an older broad version; see start.sh comments about b407e6a).
- Git init at boot only if `[ ! -d .git ]` → a `.git` POINTER FILE routes to
  the init path; `git init` reinitializes the pointed-to repo (safe).
- Skills extracted from /home/official_skills/*.zip, gated by stages.yaml
  ("default" list ≈ the skill set seen by coding sessions).
- Boot service start order: .zscripts/dev.sh (if present) ELSE package.json →
  bun install → db:push → bun run dev; then mini-services/* each `bun run dev`.
- `/etc/.z-ai-config` written at boot with baseUrl+apiKey placeholder; the
  bridge injects per-session chatId/token/userId afterwards (observed live:
  5 fields, chatId matches this chat's UUID).

## E12 — Misc verification (corrections to v1)
- Seccomp: **enabled, filter mode** (Seccomp: 2) — v1 said disabled.
- vim, rg (ripgrep), jq ARE installed — v1 listed them missing.
- node v24.19.0, bun 1.3.14, python 3.12.14, git 2.47.3, uv 0.12.5.
- eth0: 21.0.12.27/32 (internal), MTU 1450, DNS 100.100.2.136/.138 confirmed.
- CapEff=0, ulimits: nproc 1024, nofile 1024, stack 8 MB — confirmed.
- `/start.sh` is world-readable at `/` — the primary source of boot truth.
- No runtime UUID commit observed mid-session (45+ min) → platform
  auto-commits are pre-stop/recycle-time only (as far as observed).

## E13 — Github remote activation (2026-08-28, session 2)
- PAT (classic, scopes `repo, workflow`) validated via API; account name
  withheld (kit is project-agnostic; the forensic source account carried a
  handful of private repos, placeholders untouched). Created a private
  workspace repo via API with `auto_init=false` → zero history conflicts,
  clean first push [V].
- Remote added with PAT embedded in the URL, full history pushed,
  `ls-remote origin` == local HEAD [V].
- Leak surfaces found and closed in v2.2.0: zsession printed `git remote -v`
  (PAT-bearing URL) in every session report; zsave echoed raw push stderr.
  Both now sed-mask `ghp_`/`github_pat_`-style tokens before printing [V].
- Credential persistence: zsave writes `zk-remote.url` (the origin URL) to
  `/home/sync/` and `/home/user_skills/` after every successful push, so a
  fresh chat can re-add origin without the user re-pasting the PAT [V].
  Deliberately placed OUTSIDE kit dirs (install.sh's dir swap would delete it).

## E14 — Post-recycle containment audit (2026-08-28, session 3)
- Fresh container restored from repo.tar (platform-rewritten at graceful
  shutdown): full history + remote intact; every file mode-only dirty
  (0644→0755 — tar extraction does not preserve modes). One-line fix, itself
  persistent via repo.tar: `git config core.fileMode false` [V].
- Full-token scan (token extracted from .git/config into a shell var, never
  printed): all 5 kit copies, /home/user_skills/z-container.zip, workspace
  tree (excl. .git), home dotfiles — CLEAN [V]. zk-remote.url files (x2)
  hold the token BY DESIGN [V].
- `git cat-file --batch-all-objects` blob scan (includes unreachable
  objects): token never committed → not on GitHub [V]. Credential files
  never tracked in history [V].
- repo.tar carries `.git/config` with the PAT-embedded origin URL (member
  name `.git/config`, no `./` prefix — platform naming) → boot-restore
  re-wires the remote automatically; zk-snapshots likewise [V].
  zk-remote entries inside any tar: 0 — credentials stay outside the
  project tree [V].
- Kit repo-agnosticism: zero hardcoded username/repo/PAT references in
  SCRIPTS [V]; SKILL.md carried two workspace-repo parentheticals — caught
  by T-r5-a, scrubbed in v2.2.3. reference.md/EXPERIMENTS.md retain the
  workspace repo name as historical record only (provenance, no functional
  coupling anywhere).
- One deviation found + fixed (v2.2.2): /home/user_skills/z-container.zip
  was stale at v2.2.0 while kit dirs were v2.2.1; install.sh now rebuilds
  the zip from the just-installed copy (root "z-container/", matching the
  /home/official_skills/<name>.zip convention).
- Round-5 fresh-context re-audit (T-r5-a): verdict CONTAINED — kit copies,
  zip content, git object DB (119 objects), and a whole-container sweep all
  clean; sanctioned carriers exactly as designed [V]. Two catches fixed in
  v2.2.3: (a) SKILL.md still named this workspace's repo in two
  parentheticals — scrubbed (operational docs fully repo-agnostic;
  reference.md/EXPERIMENTS.md keep the name as historical record);
  (b) /home/user_skills/z-container.zip was REMOVED at 07:41:36 by the
  platform at sub-agent session spawn — skill-ingestion behavior: the zip
  is a delivery vehicle the platform consumes; install.sh re-creates it,
  and the kit dir is the durable archive [V].
- T-r5-a bonus confirmations: /home/user_skills/zk-remote.url SURVIVED a
  real container recycle (07:14 boot) — the per-user cross-chat bet is
  now observed live, not just inferred [V]; repo.tar is gzip-compressed
  (snapshots are plain tar) — raw-byte PAT scans of repo.tar see nothing,
  use tar -xOf [V].
