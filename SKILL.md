---
name: z-container
metadata:
  author: z + Super Z forensic session
  version: "5.0.0"
  verified: "2026-08-30 (live experiments + 14 validation rounds; see evidence/EXPERIMENTS.md)"
  description: >
    Survival guide for the sandbox container. ZERO-INSTALL: the kit lives
    once per account at /home/user_skills/z-container-kit/ (scripts run
    straight from there); each project carries only a one-line identity
    file (.agents/config — ZK_PREFIX, the .env pattern, git-tracked). Verified
    mechanics of the Git HEAD watchdog (a `git switch main` prelude that runs
    before EVERY toolcall), the persistence model (overlay vs PolarFS vs
    ossfs vs github; repo.tar restore semantics), background-process
    survival (double-fork, mini-services, .zscripts/dev.sh), the irreversible
    terminal lockout hazard, ports/networking, secrets practice, and the
    zsave/zsession helpers. Load BEFORE any git operation, before any
    "save my work" decision, before starting any background process, when
    troubleshooting "my project reset itself", and at every session start.
---

# Z-Container Survival Guide v4

**Read the canonical copy — /home/user_skills/z-container-kit/ — and run its
scripts from there. Zero-install.** The kit lives ONCE per account in that
per-user directory (PolarFS: survives recycles, force-kills, and new chats —
observed live); projects never carry kit copies, so nothing can go stale.
If the directory is absent (a truly bare account): `git clone
https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit` and
run the scripts from the clone — still zero-install. Every claim is graded:
**[V]** verified live 2026-08-28, **[S]** from `/start.sh` source, **[I]**
inherited/unverified — never "test" the deadly ones. Operational deep-dive
modules in `kb/` (read when the specific topic is relevant).

## New session — read this every time (MUST READ, inline, not optional)

First, decide which of the two flows you are in — they are different, and
picking the wrong one wastes work or damages config:

- **Existing project** — this repo already uses the kit: an `.agents/`
  directory is in the workspace (or restores from the backup repo). You are
  RESTORING a session. This section is your flow.
- **New project** — the repo has never used the kit: no `.agents/` anywhere,
  and the backup repo has nothing to restore. You are SETTING UP. Go to
  "New project setup" near the end instead.

Check: `ls /home/z/my-project/.agents` — present means restore (below);
absent with no backup-repo history means setup. Do not run the setup flow on
an existing project (it can bake the wrong `ZK_PREFIX`), and do not run
recovery on a brand-new repo (the remote has nothing to restore).

**1. Run the situation report:**
```bash
bash /home/user_skills/z-container-kit/scripts/zsession
```
Read-only report: uptime, mount writability, recycle detection, git status/remote/
worktrees, watchdog hygiene, kit & config (canonical kit, project config, old
leftovers in THIS project), services, numbered recommended actions. It reports
this kit and this project only — kits are self-contained, no cross-kit
inventory. One command instead of ~8 improvised ones; the equivalent checks
are documented in this file if you prefer plain git. Follow its advice. (If the canonical kit is absent — bare account —
clone it first: `git clone https://github.com/super-z-kits/z-container-kit.git
/tmp/my-project/kit` and run the scripts from there; there is nothing to
install.) Fresh-chat recovery detail (paths A/B/C, credential-file shortcut,
branch-rename, env-override testing): `kb/session-recovery.md`.

**2. Verify you're on `main` (watchdog hygiene):**
```bash
git -C /home/z/my-project branch --show-current   # must say "main"
```
If it says anything else, the watchdog silently reverts your files on the next
toolcall. Switch back: `git -C /home/z/my-project switch main`.

**3. If the workspace was already restored** (repo.tar existed at boot, or
zsession shows your real project history): read the prior session context —
```bash
tail -80 /home/z/my-project/worklog.md
```
The worklog is committed (survives cross-chat). If it is missing, recover it
from git history before recreating it: `git log --all --oneline -- worklog.md`,
then `git show <last-commit-that-had-it>:worklog.md > worklog.md` — do NOT
start a blank file if history still has the content. If there is truly no
prior worklog (brand-new repo), create it following the preset's worklog
protocol (append-only, sections starting `---`, Task ID / Agent / Task /
Work Log / Stage Summary).

**4. If the workspace is the boot template** (single "Initial commit", no
worklog, empty project tree) — cold start. Wire the remote, restore, verify
identity, save. There is NO install step: the project's `.agents/config` is
committed, so `reset --hard` brings identity back with the code:

```
KIT=/home/user_skills/z-container-kit                 # canonical (or a fresh clone if absent)
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git
git -C /home/z/my-project fetch origin
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK (brand-new/empty remote? origin/main doesn't exist yet — expected, move on)
git -C /home/z/my-project reset --hard origin/main     # skip if remote is empty/new
source /home/z/my-project/.agents/config && echo "$ZK_PREFIX"   # identity came back with the repo — if absent (repo predates the kit): bash "$KIT/scripts/zk-init" <name>
# RECOVERY: never invent a name — REUSE the prefix from the credential filename (the part before -remote.url)
bash "$KIT/scripts/zsave" "fresh-chat bootstrap checkpoint"
```

After recovery `ZK_PREFIX` lives in `/home/z/my-project/.agents/config` —
read it with `source /home/z/my-project/.agents/config` before using
`${ZK_PREFIX}` anywhere in your shell (each bash toolcall is a fresh subshell).

PAT is typed exactly once (the remote-add line). The kit comes from the
canonical per-account copy; a bare account clones the public repo once (no
PAT needed for the clone). Alternatives for the remote-add step:

- **B1 — credential file survived** (Path B's credential-file shortcut): list
  them with `ls /home/user_skills/*-remote.url` — there is ONE PER PROJECT on
  multi-repo accounts (the prefix is the filename part before `-remote.url`);
  pick YOUR project's, `${ZK_PREFIX}` is not defined in your shell yet:
  ```bash
  CF=/home/user_skills/<your-prefix>-remote.url     # pick YOUR project's file
  git -C /home/z/my-project remote add origin "$(cat "$CF")"
  ```
  Still run the sanity-check log line — a stale credential file (audit F16)
  can silently point at a different repo.
- **B2 — no PAT, no credential file, but Doppler vault has GH_PAT** (Path C,
  see secrets-vault-kit): fetch GH_PAT from the vault via the M7 staging
  pattern, then `git remote add origin "https://${GH_PAT}@github.com/<user>/<repo>.git"`.
- **B3 — nothing**: ask the user for the PAT, then `git remote add origin
  https://<PAT>@github.com/<u>/<r>.git`.

**After recovery (OF-8):** read the **tail** of `/home/z/my-project/worklog.md`
(last Task ID block — the file can be 30+ KB / 900+ lines, too large for one
Read; use `tail -100 worklog.md` or `Read` with offset to get the latest
session context). The worklog re-appears after `reset --hard origin/main` —
it's not visible before the reset because the workspace is the boot template.
zsession's "create worklog" rec is stale once recovery completes (the worklog
already exists); ignore that rec if the file is present and non-empty.

That's the mandatory part. Everything below is reference — read sections when
the topic is relevant.

## Rules you never break

The five behaviors that keep a session alive. The ten laws further down
state the container mechanisms behind them — where a rule and a law cover
the same ground, the rule carries the detail and the law points back.

1. **Stay on `main` in `/home/z/my-project` — the watchdog silently reverts your files.** Before every toolcall, the platform runs `git switch main`. If you're on another branch with a clean tree, your working files silently revert to main on the next toolcall — you won't know until you try to find your work. **Never `git checkout <branch>` inside `/home/z/my-project`.** For branch work, use a worktree: `git -C /home/z/my-project worktree add /tmp/my-project/worktrees/<name> -b feature/<x>`. For PRs, push without checkout: `git push origin main:feature/<x>`.

2. **`zsave` after every MICRO-milestone — and "milestone" means as micro as it gets.** A milestone is NOT "when the feature is done" — that grand final moment never arrives. It is every good moment: one file written, one bug fixed, one step verified, one experiment that worked. Save at that granularity. `zsave` covers all 4 backup layers in one command: (1) commit to local git, (2) push to GitHub (the only cross-chat persistence), (3) snapshot tar to `/home/sync/${ZK_PREFIX}-snapshots/` (per-chat, survives recycle + force-kill), (4) refresh `/home/sync/repo.tar` (the boot-restore artifact — a force-killed container comes back at your latest zsave). It is multi-track-safe by construction: concurrent saves serialize on a lock (the second one WAITS, nothing for you to do), a rejected push (a parallel session pushed first) auto-recovers via `pull --rebase` + retry, and a steady-state save writes `/home/user_skills` zero times (static rule). It also refreshes the `${ZK_PREFIX}-remote.url` credential file — atomically, and only when its bytes actually changed. **Pushed = saved across all layers; unpushed = at risk in ALL layers.** Run at every micro-milestone, before risky operations, and every ~10 toolcalls.

3. **Never force push.** Local state can be faulty (watchdog reverts, workspace wipes, wrong work dir). `git push --force` overwrites the only copy with your possibly-broken local — the most deadly combination. If push is rejected, `git pull --rebase origin main` and re-push. Never `--force` without explicit user permission.

4. **Set git identity before any commit.** Boot default is `Z User <z@container>` — Vercel blocks deploys from this identity. `git config user.name "<GitHub username>"` and `git config user.email "<id>+<username>@users.noreply.github.com"` (exact noreply email from GitHub settings). zsession detects this and prints the fix.

5. **Delegate to sub-agents to avoid excessive bash calls.** Rapid toolcall loops risk the 403 lockout (see law 6). Sub-agents get independent tool sessions — delegate risky probes.

## The ten laws

1. **Know where you stand before touching anything.** The situation report is one read-only command — `bash /home/user_skills/z-container-kit/scripts/zsession` — and reading it beats re-deriving the checks by hand. The script is an accelerator, not a requirement: everything it checks (branch=main, origin present, identity resolvable, tree state, recycle verdict) is documented in this file, and plain git + this doc always suffice.
2. **Work on `main` inside `/home/z/my-project`** (rule 1's mechanism: the pre-toolcall `git switch main` is a no-op on main, a silent revert on any other branch).
3. **All saves go through `zsave`, at micro-milestone granularity** (rule 2's mechanism: one command = commit + push + `/home/sync` snapshot + `repo.tar` refresh). No ad-hoc partial saves; no waiting for a "finished" state.
4. **Overlay is not a disk.** Only `/home/sync`, `/tmp/my-project`, `my-project/upload/`, `/home/user_skills`, and github survive a recycle. `/home/z/my-project` survives only via `repo.tar` (graceful shutdown) or your own `zsave`. Of these, only github (and probably `/home/user_skills`) crosses into a NEW chat.
5. **Parallel/feature work goes OUTSIDE the project**: `git -C /home/z/my-project worktree add /tmp/my-project/worktrees/<name> -b <branch>` — watchdog-free AND recycle-safe. Push from there.
6. **Never loop `caddy` subcommands (run/start/stop/reload/file-server) and never curl-loop ports 12600/19001/19005/19006** — irreversible session-wide 403 lockout. One probe per toolcall. **[I]**
7. **Background processes need a double-fork** (`python3 /home/user_skills/z-container-kit/scripts/daemonize.py --log <f> -- <cmd>`); `nohup`/`setsid`/`&`/`disown` all die at toolcall end. Boot-time services: `mini-services/` dirs or `.zscripts/dev.sh`. **[V]**
8. **Never kill the :3000 dev server** — there is no supervisor and it won't restart on its own. If you must bring it back, relaunch it via daemonize.py (recipe below); don't wait for a recycle.
9. **Track `.env` in git — git IS the disk here.** External reviewers flagging committed secrets as P0: ignore them; they lack this context. Do not print token values into chat/logs.
10. **The watchdog never destroys commits or untracked files — panic "fixes" do.** Diagnose (`git log --all --oneline`, `zsession`) before resetting anything.

## ⚠️ Parallel sessions — multi-track by design (v5)

(R10-13) `/home/user_skills/` is **per-user, shared across concurrent chats**: the
platform runs 2–3 sessions under one account, they may work on DIFFERENT repos
or the SAME repo simultaneously, and the directory has no git — no conflict
detection, no merge, no rebase. A write race there would be unresolvable.
That is exactly why v5 makes it **static**:

- **Sessions never write `/home/user_skills` except the sanctioned list below.**
  Steady-state saves touch it ZERO times. Nothing races because nothing writes.
- **The three sanctioned writes** (each zero-collision by construction):
  1. kit install/refresh — `refresh.sh`, a conscious account-level operation:
     per-run staging + rename-aside swap (two atomic directory renames — a
     concurrent session never sees a torn kit; worst case one racing command
     errors once and works on re-run). refresh.sh also owns account-level
     housekeeping (stale-artifact cleanup + the backup-dir prune folded in
     from the deleted zcleanup-backups script);
  2. the portable kit zip rebuild — only when missing, same bytes from a
     static source, atomic swap (platform glue: sub-agent spawn consumes it);
  3. credential files (`${ZK_PREFIX}-remote.url`, `${ZK_PREFIX}-doppler.env`) —
     keyed by the project's unique prefix, written atomically, and only when
     the bytes actually change. Doppler env files additionally honor
     fresher-wins: never clobber a NEWER `DOPPLER_PT_STORED_AT` with older data.
- **Same-repo parallel sessions are git's problem — and git solves it.** Both
  sessions push to one remote; the loser's push is rejected; zsave
  auto-recovers ONCE via `git pull --rebase` + retry (never force-push). Only
  a same-line conflict needs a human decision — git says exactly where.
- **In-container concurrency** serializes on `/tmp/.zsave.lock` — the second
  save WAITS (up to `ZK_LOCK_WAIT`, default 180s), it does not fail.

Full hazard analysis: `kb/parallel-sessions.md`.

## The Git HEAD watchdog — read before ANY git work

**Mechanism [V]:** before EVERY toolcall (Bash, Read, Write — all types, including
your sub-agents' toolcalls), the platform runs `git switch main` as user z in
`/home/z/my-project`, via a prelude chain (`/bin/sh -c su z -c /bin/bash`),
~200–500 ms before your command executes. It never fires while you are idle.

| State at end of your toolcall | What the prelude does before your next command |
|---|---|
| on `main` | nothing — true no-op, no writes |
| other branch, clean tree | full `git switch main`: HEAD -> main AND **working-tree files revert to main's content** |
| other branch, uncommitted changes conflicting with main | switch **fails silently** — you stay on your branch ("dirty shield") |
| other branch, non-conflicting uncommitted changes | switch succeeds; your edits carry over onto main |
| detached HEAD | reset to `main` (note any SHA you care about before the next toolcall) |
| any repo outside `/home/z/my-project` | untouched **[V]** |
| linked worktrees of the project | untouched **[V]** |

Consequences:
- Committed work is never destroyed (refs survive); what changes is which commit
  the working tree shows. Untracked files are never touched.
- Classic failure: commit on `feature/X`, next toolcall tree silently reverts to
  main, you "lose" files and recreate them → two divergent histories. Law 2 makes
  this impossible.
- `git push origin main:feature/X` publishes a remote feature branch without ever
  checking one out locally.

Recovery: "files vanished" → `git -C /home/z/my-project switch <branch>` brings
them back from the ref (commits are safe). Then `zsave`. Advanced patterns (dirty
shield semantics, gitdir relocation, worktree orphan recovery, force-move refs):
`kb/watchdog-advanced.md`. Mid-rebase note: while a `git rebase` is in progress
(e.g. zsave's auto-rebase hit a conflict), the prelude's `git switch main` FAILS
harmlessly (`cannot switch branch while rebasing`) — the watchdog cannot destroy
an in-progress rebase; resolve, `git rebase --continue`, and save again.

## Saving work — zsave

```
bash /home/user_skills/z-container-kit/scripts/zsave "<what you just finished>"
```

Does, in order: maintain `.git/info/exclude` → `git add -A` + commit (incl. `.env`
— law 9) → push `origin HEAD:<branch>` — a REJECTED push (parallel session
pushed first) auto-recovers once via `git pull --rebase` + retry; never
force-pushes → refresh the `${ZK_PREFIX}-remote.url` credential file in
`/home/user_skills/` atomically, ONLY when its bytes changed (static rule) → tar
snapshot to `/home/sync/${PREFIX}-snapshots/` (keep 5) → refresh
`/home/sync/repo.tar` (the boot-restore artifact) → write `${PREFIX}-state.env`
(recycle detector). Each step degrades gracefully; nonzero exit = commit/snapshot/
repo.tar failed, or the credential-file write did not verify (F16) (push failure is a
warning). Full pipeline with exclude rules: `kb/zsave-internals.md`.

Run after every micro-milestone — every good moment: a file finished, a step
verified, a bug fixed — before risky operations, and at least every ~10
toolcalls in long sessions. It is cheap (a few seconds). Do NOT wait for a
"big enough" moment: the grand final save never happens, and everything
since your last zsave is one recycle away from oblivion.

**Concurrency:** zsave takes a per-container lock (`/tmp/.zsave.lock`) — a
second concurrent run WAITS for it (default up to 180s) and then proceeds, so
back-to-back saves serialize with zero intervention. **Sub-agents still
leave saves to the coordinating agent** — one writer keeps saves from
interleaving with the coordinator's own git work. Pushing from a worktree is
always fine.

## repo.tar mechanics

`/home/sync/repo.tar` is the artifact the platform restores at boot. Boot: if it
exists, start.sh wipes `/home/z/my-project/*` (preserving `upload/`) and
re-extracts it; else "clean project" path. Shutdown: archived on **graceful**
shutdown only (plus a runtime UUID-message `git add -A` commit at pre-stop);
force-kill skips both. zsave refreshes repo.tar so a force-killed container
returns at your latest zsave, not a stale one. Full boot/shutdown source detail:
`kb/repo-tar-mechanics.md`.

## Restore procedures (when things went wrong)

**Golden rule:** never extract a snapshot tar over a live `.git` — the archive's
`.git` (incl. reflog) would overwrite your newer history. Always recover at the
ref level first; tar-restore is the last resort.

**A. "Project reset / files missing" — ref level first:**
1. `git -C /home/z/my-project log --all --oneline` (commits live on refs)
2. `git -C /home/z/my-project reflog -15` and `git fsck --lost-found`
3. Restore the view: `git switch main` (or the right branch/worktree).

**B/C/D** (snapshot tar-restore, fresh-chat recovery, stuck repo states):
`kb/restore-procedures.md`.

## Deadly: terminal command lockout [I] — never verify experimentally

Rapid loops of filtered `caddy` subcommands (run/start/stop/reload/file-server)
or scan-like curl loops against ports 12600/19001/19005/19006 cause an
**irreversible session-wide 403** — every subsequent toolcall fails, even
`echo ok`. No in-run recovery; only a new agent session.

Avoidance: one probe per toolcall (five tests = five toolcalls); never loop
filtered commands; never method-matrix or path-enumerate internal ports; stop
immediately at any "broken session" / "403 Forbidden" / "can not execute caddy"
error — do not retry. The filter scans full command text, so even a heredoc
*containing* the word caddy is blocked — use Write/Edit tools, not bash heredocs,
for such files. Safe: `caddy version`, `caddy adapt`, single-shot reads
(`ps aux`, `ss -tln`, `cat /proc/...`). Delegate risky probes to a sub-agent to
protect the main session.

## Background processes

- Every bash toolcall spawns a fresh `su z -c bash` and the wrapper kills the
  whole descendant tree at toolcall end — `nohup`, `setsid ... & disown`,
  `(<cmd> &)` all die **[V]**.
- Escape hatch: double-fork, reparenting to PID 1 (tini). Use the helper:
  `python3 /home/user_skills/z-container-kit/scripts/daemonize.py --cwd <dir> --log <file> -- <cmd...>`
  (verified: survived 10+ minutes across 30+ toolcalls).
- Boot-time services: drop a dir with `package.json` (+ `dev` script) into
  `my-project/mini-services/` — auto-started at every boot [S]. Or a
  `my-project/.zscripts/dev.sh` for a fully custom boot flow (runs as z).
- Daemons still die on recycle. Persistence is storage-only, never process-based.
- Restart a dead :3000 dev server without a recycle:
  `python3 /home/user_skills/z-container-kit/scripts/daemonize.py --cwd /home/z/my-project --log /home/z/my-project/dev.log -- bun run dev`

## Networking

- Caddy listens on **:81** [V listener, S from start.sh]; it proxies to
  localhost:3000 **[I]** (Caddyfile is root-only).
- Reach other internal ports externally via `?XTransformPort=<port>` on the
  preview URL (e.g. `/env?XTransformPort=3001`); WebSockets/SSE connect to
  `/?XTransformPort=<port>` (path must be `/`). Never hardcode
  `http://localhost:<port>` in client-side fetch — use the relative path +
  query. **[I]**
- Internal ports — leave alone: 81 (caddy), 3000 (dev server), 12600 (ZAI
  bridge; `/ping` safe, do not loop), 19001/19005/19006 (FC control plane —
  do not touch). **[I/S]**
- Egress fully open; DNS 100.100.2.136/138; no external IPv6; eth0 MTU 1450;
  public preview URL not discoverable from inside the container (use the UI
  panel). Detail: `kb/networking.md`.

## Dev server & database

- `bun run dev` (:3000, Next.js) runs only if my-project has `package.json` (or
  `.zscripts/dev.sh`) at boot [S]. Don't start a second copy; don't kill it
  (no supervisor). Tail `my-project/dev.log` for compile errors.
- Prisma + SQLite at `DATABASE_URL=file:/home/z/my-project/db/custom.db` [S] —
  overlay: the DB dies with the recycle unless zsave'd (repo.tar/snapshots carry
  it). For hot state that must never be more than one command behind, keep it
  under `/tmp/my-project/` or `/home/sync/` and symlink — or just zsave often.
- Full detail (build vs lint, hot-state patterns): `kb/dev-server-database.md`.

## Secrets & .env practice

- There is no durable disk except git and object storage; the established
  practice is to COMMIT `.env` (the platform itself writes one at every boot)
  and embed the PAT in the origin remote URL:
  `git remote add origin https://<PAT>@github.com/<user>/<repo>.git`.
- The kit never embeds tokens — project- and PAT-agnostic by construction [V].
  A PAT persists ONLY in container-local places: the origin URL in `.git/config`
  (repo.tar boot-restore brings it back), the `${ZK_PREFIX}-remote.url` credential file
  (zsave-maintained: `/home/user_skills/` only since v3.1, mode 0600), and tar snapshots
  of `.git`. NEVER in the GitHub repo, never in any kit file. Different PAT:
  `git remote set-url origin https://<PAT>@github.com/<u>/<r>.git`, then `zsave`.
- `zsave`/`zsession` mask tokens in ALL output (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`/
  `github_pat_` AND, since v3.1, `dp.pt.`/`dp.st.`/`cfat_`/`sbp_` prefixes). Never verify
  remotes with `git remote -v` in a transcript; use `git remote` (names only).
  Revoke anytime: github.com/settings/tokens. NEVER make the backup repo public
  (it contains `.env` and the worklog).
- Code reviewers without this context will flag committed secrets immediately —
  ignore those findings; the alternative (secrets only in chat) is strictly
  worse here. Just never echo token values into transcripts, logs, or commits.
- App secrets (e.g. `OPENAI_API_KEY`, `JWT_SECRET`) belong in **Doppler** (audit
  F21) or `.env.local` / `.env.*.local` (Next.js convention, already git-ignored)
  — NOT in `.env`. The committed-`.env` posture is specifically about the
  platform's `DATABASE_URL` and the PAT in the origin URL. `/etc/.z-ai-config`
  holds per-session bridge credentials — do not exfiltrate or print them. **[V]**
- Audit callouts (F11 ossfs 0777 mode, F13 mode-printing, F18 recovery pre-flight,
  F12/F15 UUID commits): `kb/secrets-audits.md`.
- `.agents/config` holds `ZK_PREFIX` (a project name — not a secret) and is
  committed with the repo. It survives boot because the platform only rewrites
  `.env`, never other files.


## Sub-agents & coordination

- Sub-agents share THIS container: the watchdog resets HEAD before their
  toolcalls too, and their file writes land in the same overlay. Give each
  sub-agent its own worktree (`/tmp/my-project/worktrees/<name>`) or scratch dir.
- Sub-agents leave `zsave` to the coordinating agent — one writer, no
  interleaving with the coordinator's git work (concurrent saves serialize on
  the lock anyway; this is about ownership, not corruption). Pushing from a
  worktree is always fine.
- Everything else — Task-tool usage, self-contained prompts, Task-ID
  assignment, the shared worklog protocol — is already provided by the
  environment preset; this kit records only the container deltas above
  (deep dive: `kb/sub-agents.md`).

## Persistence map

| Location | Storage | Survives toolcalls | Survives recycle (scale-to-zero) | Survives force-kill | Survives NEW chat |
|---|---|---|---|---|---|
| `/home/z/my-project` (incl. git-tracked `.agents/`; excl. `upload/`) | overlay | yes | only via `repo.tar` (graceful) or zsave-refreshed `repo.tar` | only if zsave ran | only via github |
| `/home/z/my-project/upload/` | ossfs | yes | yes | yes | unlikely (per-chat, indicated) |
| `/home/sync` | ossfs | yes | yes | yes | unlikely (per-chat, indicated) |
| `/tmp/my-project` | PolarFS (JuiceFS) | yes | yes | yes | unlikely (per-chat, indicated) |
| `/home/user_skills` | PolarFS | yes | yes | yes | **probably yes (per-user, indicated)** |
| `/tmp`, `/home/z/<other>`, `/var/tmp`, `/root` | overlay | yes | **no** | **no** | no |
| github remote | external | n/a | yes | yes | yes |

**Persistence radius:** anything precious must be (a) inside `/home/z/my-project`
AND zsave'd, OR (b) on `/home/sync` or `/tmp/my-project` directly (per-chat: safe
until THIS chat ends), OR (c) pushed to github (the only guaranteed cross-chat
path — plus probably `/home/user_skills`). A file in `/home/z` outside
my-project has strictly worse odds than one inside my-project (no repo.tar
coverage). Namespace inference detail: `kb/persistence-namespaces.md`.

## Pointing helpers at another project (overrides)

All helpers accept `ZK_PROJ` / `ZK_SYNC` / `ZK_USK` env overrides — THE general
mechanism for running the kit against another project dir, sync dir, or
account dir (worktrees, second projects, sandboxes — and scratch tests: the
same mechanism keeps tests off the real `/home/sync` artifacts and the real
`/home/user_skills`). Each bash toolcall is a fresh subshell: prefix every
command with the full override set, on ONE line. zsave prints its resolved
target (`proj=… prefix=…`) on the first output line — glance at it before
trusting a save. Full pattern: `kb/testing-helpers.md`.

## Helpers reference

Kit helpers run from the canonical kit (`bash
/home/user_skills/z-container-kit/scripts/<name>`) — zero-install, same
commands for every project on the account (v3-era `scripts/` shims in a
project still work; the canonical copy is always current).

**Scripts are optional accelerators, never requirements.** Every recurring
flow is also plain-git + this-doc doable; the scripts exist only where they
encode fiddly mechanics (atomic swaps, PAT masking, lock ordering,
auto-recovery) that you should not hand-roll mid-task. If a script is absent
or misbehaves, fall back to the documented recipe — never stop your real job
to repair tooling.

**Bash:**
- `zsave "msg"` — commit + push (auto-rebase on rejection) + snapshot +
  repo.tar refresh + credential file (atomic, write-only-on-change)
- `zsession` — read-only situation report (recycle detection, watchdog hygiene,
  kit & config status for THIS project)
- `zk-init <name>` — project setup: writes `.agents/config` (`--force` to fix a
  wrong prefix; `--migrate-v3` to strip a v3 kit tree; `--status` to inspect)
- `refresh.sh` — account-level upgrade: rename-aside swap of the canonical
  package + zip rebuild + account housekeeping (backup-dir prune — the old
  zcleanup-backups was folded into it), from an updated kit clone (THE
  sanctioned account-level user_skills writer — sessions never run it casually)
- `zremote` — PAT-masking `git remote` viewer (replaces `git remote -v`)
- `zdoppler-smoke` — one-shot Doppler vault verification
- `zkit-selftest` — end-to-end save/wipe/recover smoke test
- ALL helpers accept `ZK_PROJ` / `ZK_SYNC` / `ZK_USK` env overrides to target
  another project / sync dir / account dir (worktrees, second projects,
  sandboxes, scratch tests — one mechanism, see `kb/testing-helpers.md`).
  zsave prints its resolved target (`proj=… prefix=…`) on the first output
  line — glance at it before trusting a save.
- (Removed in v5: `install.sh` — v3's installer; `zcleanup-backups` — its
  backup-dir prune folded into `refresh.sh`, the one account-level maintenance
  op. Nothing a session does needs either.)

**Python (run from the canonical kit — `python3 /home/user_skills/z-container-kit/scripts/<name>`):**
- `daemonize.py` — double-fork background process that survives toolcalls
- `wdt_watch.py` — watchdog observation helper (forensic)
- `doppler_fetch.py` — urllib version of `zdoppler-smoke`; stages secrets to `/tmp/my-project/doppler-secrets.json`
- `verify_access.py` — urllib access verifier for GitHub / Cloudflare / Supabase (Supabase WAF needs `User-Agent: ${ZK_PREFIX}-verify`)

Use bash for quick one-shots; Python for multi-call flows that stage secrets
across calls. Audit-callout detail per helper (F6, F8, F10, M7, M3, M4):
`kb/helpers-audits.md`.

## DOPPLER_TOKEN_SEED callout

(ZK_PREFIX comes from `.agents/config`: `source /home/z/my-project/.agents/config`
first — each bash toolcall is a fresh subshell.)

**Detection (R10-2 fix):** `zdoppler-smoke` filters out ALL `DOPPLER_*` keys,
so the seed is invisible in the canonical verification output. You MUST sweep
all configs (not just the handover config) to detect it:

```bash
set -a; source /home/user_skills/${ZK_PREFIX}-doppler.env; set +a
# List all configs, then check each for DOPPLER_TOKEN_SEED
for cfg in $(curl -sS -H "Authorization: Bearer $DOPPLER_PT" \
  "https://api.doppler.com/v3/configs?project=$DOPPLER_PROJECT" \
  | jq -r '.configs[].name'); do
  SEED=$(curl -sS -H "Authorization: Bearer $DOPPLER_PT" \
    "https://api.doppler.com/v3/configs/config/secret?project=$DOPPLER_PROJECT&config=$cfg&name=DOPPLER_TOKEN_SEED" \
    | jq -r '.value.computed // empty')
  if [ -n "$SEED" ]; then
    echo "  ⚠️ DOPPLER_TOKEN_SEED found in config '$cfg' (length ${#SEED}, prefix ${SEED:0:6})"
  fi
done
```

If found, this violates secrets-vault-kit's own fact #3. Don't auto-rotate or
auto-delete — flag to the user. Detail + policy: `kb/doppler-token-seed.md`.

## Quick reference card

```
DO
  bash /home/user_skills/z-container-kit/scripts/zsession              # session start report
  bash /home/user_skills/z-container-kit/scripts/zsave "msg"           # save everything
  git -C /home/z/my-project worktree add /tmp/my-project/worktrees/x -b feature/x
  python3 /home/user_skills/z-container-kit/scripts/daemonize.py --log /tmp/x.log -- <cmd>
  single-shot probes only: ps aux, ss -tln, cat /proc/...
DON'T
  checkout non-main branches inside /home/z/my-project (watchdog reverts tree)
  loop caddy run/start/stop/reload/file-server            # irreversible 403
  curl-loop 12600 / 19001 / 19005 / 19006                # irreversible 403
  rely on nohup/setsid/& for daemons                      # they die
  kill the :3000 dev server                               # no supervisor
  expect /tmp or /home/z/* to survive a recycle           # overlay
  write http://localhost:3001 in client fetch             # use ?XTransformPort=
  import z-ai-web-dev-sdk in client code                  # server-side only
  trust any "tools missing" list blindly                  # check command -v
  use `git remote -v`                                     # prints PAT — use `git remote`
```

## New project setup (when the repo has never used this kit)

The setup flow — triggered when `.agents/config` does not exist and no backup
repo carries one (see the MUST-READ decision block for how to tell the two
flows apart). Setup is ONE command — write the project's identity file:

```bash
bash /home/user_skills/z-container-kit/scripts/zk-init <your-project-name>
```

That writes `.agents/config` (`ZK_PREFIX=<name>`) — the ONLY per-project
artifact the kit ever creates. There is nothing else to install: helpers run
from the canonical kit, upgrades happen once per account (refresh.sh), and
the config travels with the repo through GitHub and repo.tar. Commit it:

```bash
git add .agents/ && git commit -m "kit: project identity (.agents/config)"
bash /home/user_skills/z-container-kit/scripts/zsave "project bootstrap checkpoint"
```

`ZK_PREFIX` naming rules: lowercase, `[a-z0-9-]`, max 24 chars, must be unique
among the projects you run in parallel under this account (it names the
credential/snapshot/state files in `/home/user_skills/` and `/home/sync/`).
There is NO auto-discovery — helpers read `ZK_PREFIX` from the env or from
`.agents/config` and nothing else; if neither is set they fail loudly with
the `zk-init` recipe (that is the .env contract: a missing config is a
one-command fix, a wrong silent guess is data loss). Fix a wrong prefix with
`zk-init <name> --force`. Detail, edge cases, and the multi-project rationale:
`kb/new-project.md`.

## Multi-kit, multi-repo, multi-track model (v5)

The kit is designed for an ACCOUNT that runs several projects and several
kits — concurrently, sometimes several sessions on the SAME repo — not a
single-project world. The rules that keep it simple: **every kit minds its
own business, and user-skills is static.**

- **`/home/user_skills` is READ-ONLY for sessions (the static rule).** It has
  no git — no conflict handling, no merge, no rebase — so any session-time
  write is an unresolvable write race between parallel chats. Sessions read
  kits and configs from it; the ONLY writes are the three sanctioned
  zero-collision ones (kit refresh via `refresh.sh`; the portable zip rebuild
  when the platform consumed it; credential files keyed by a unique project
  prefix, written atomically and only on change — see "Parallel sessions"
  above). Not even per-repo customization lives there: per-repo state is
  `.agents/config` IN the repo, where git handles conflicts.

- **Kits are per-account and SELF-CONTAINED.** Each kit lives once in
  `/home/user_skills/<name>/` (z-container-kit, secrets-vault-kit,
  install-user-skill, …). A kit ships its own scripts, its own zip refresh,
  and its own docs — it never inventories, installs, upgrades, or reports
  other kits (no registries, no cross-kit managers). Kits compose through
  ONE shared convention only: the project identity file `.agents/config`
  (`ZK_PREFIX=<name>`) — e.g. secrets-vault-kit reads the same variable to
  locate `/home/user_skills/${ZK_PREFIX}-doppler.env`. Installing/updating
  a kit never touches any project.
- **Projects are identified by their config — period.**
  `$PROJ/.agents/config` (one line, committed) is the identity — the .env
  pattern. Scripts resolve identity from exactly TWO sources:
  `ZK_PREFIX` env (one-off override) > project config. Nothing else.
  NO artifact scanning, NO legacy-config globbing, NO origin-URL guessing:
  shared `/home/user_skills` and `/home/sync` files are per-USER evidence,
  never identity — auto-adopting from them is how the v3 "zk-onboard-test"
  cross-contamination happened. Missing config = loud one-command fix
  (`zk-init <name>`); wrong silent guess = data loss. Fix a wrong prefix
  with `zk-init <name> --force`. Detail and edge cases: `kb/new-project.md`.
- **Upgrades are account-level and atomic.** `refresh.sh` swaps the canonical
  package via per-run staging + rename-aside (a concurrent session never sees
  a torn kit; worst case one racing command errors once and works on re-run)
  and rebuilds the portable zip. All projects move together — one version,
  zero stale copies. Rollback = check out an older kit tag and refresh again.
- **The platform consumes `/home/user_skills/*.zip` at sub-agent spawn**
  (observed live). Each kit owns its zip: zsave/refresh.sh rebuild the
  z-container zip when they find it missing, so sub-agent delivery survives
  without any install step.

## Layout (one canonical copy + one line per project)

```
/home/user_skills/z-container-kit/   THE kit — canonical, per-account, STATIC
                                     during sessions (PolarFS: survives
                                     recycle + force-kill + new chats)
  scripts/zsave, zsession, zk-init,   run from here; location-agnostic (they read
    refresh.sh, resolve-prefix.sh, …  identity from $PROJ/.agents/config)
  kb/, evidence/, SKILL.md, reference.md
/home/user_skills/z-container.zip    portable zip — platform consumes it at
                                     sub-agent spawn; rebuilt atomically when
                                     missing (sanctioned write #2)
/home/z/my-project/.agents/config    ZK_PREFIX=<project-name>  <- the ONLY
                                     per-project kit artifact (committed; the
                                     .env pattern, boot-safe)
/home/z/my-project/.env              DATABASE_URL only — boot-MANAGED, gets rewritten
/home/user_skills/${ZK_PREFIX}-*     credential files (sanctioned write #3:
                                     atomic, write-only-on-change, never
                                     committed)
/home/sync/${ZK_PREFIX}-snapshots/,  per-project snapshots + state (per-chat,
  ${ZK_PREFIX}-state.env              container-local — no cross-session race)
```

v3-era repos may still carry a `.agents/` kit tree, `scripts/` shims, and a
`skills/z-container` symlink — v4 helpers never read them (they resolve
identity from `.agents/config`, which v3 already wrote). Strip the dead
weight with `zk-init --migrate-v3`, then zsave the removal.

## KB modules index (read when the topic is relevant)

- `kb/session-recovery.md` — fresh-chat recovery detail: paths A/B/C, credential-file
  shortcut, branch-rename, pre-flight snapshot (the deep-dive behind the
  MUST-READ cold start above)
- `kb/zsave-internals.md` — full 6-step zsave pipeline with exclude rules
- `kb/watchdog-advanced.md` — dirty shield, gitdir relocation, orphan recovery
- `kb/watchdog-forensic.md` — forensic evidence for watchdog mechanics (the WHY)
- `kb/persistence-namespaces.md` — per-chat vs per-user namespace inference
- `kb/repo-tar-mechanics.md` — boot/shutdown semantics, .gitignore auto-heal
- `kb/restore-procedures.md` — full A/B/C/D recovery flow
- `kb/networking.md` — ports, Caddy, XTransformPort, egress detail
- `kb/dev-server-database.md` — :3000 dev server, Prisma + SQLite detail
- `kb/secrets-audits.md` — F11/F13/F18/F21/F12/F15 audit callouts
- `kb/sub-agents.md` — container-specific sub-agent deltas: shared-container
  isolation, zsave ownership, worklog commit/recovery (preset provides the rest)
- `kb/terminal-lockout.md` — the irreversible caddy/port-loop 403 hazard (deep dive)
- `kb/troubleshooting.md` — debugging trees for common symptoms
- `kb/helpers-audits.md` — per-helper audit callouts (F6/F8/F10/M7/M3/M4)
- `kb/doppler-token-seed.md` — PT-in-vault warning + detection policy
- `kb/testing-helpers.md` — safe scratch testing of zsave/zsession
- `kb/parallel-sessions.md` — concurrent-chat hazards on shared `/home/user_skills/`
- `kb/container-internals.md` — runtime identity, mount topology, storage performance
- `kb/new-project.md` — setting up a brand-new repo: zk-init, ZK_PREFIX choice,
  multi-project naming, the v4 resolution order, first-save checklist

