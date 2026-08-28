---
name: z-container
metadata:
  author: z + Super Z forensic session
  version: "2.5.0"
  verified: "2026-08-28 (live experiments + 5 validation rounds; see evidence/EXPERIMENTS.md)"
description: >
  Survival guide for the Z.ai Code sandbox container. Verified mechanics of the
  Git HEAD watchdog (a `git switch main` prelude that runs before EVERY toolcall),
  the persistence model (overlay vs PolarFS vs ossfs vs github; repo.tar restore
  semantics), background-process survival (double-fork, mini-services,
  .zscripts/dev.sh), the irreversible terminal lockout hazard, ports/networking,
  secrets practice, and the zsave/zsession helpers. Load BEFORE any git operation,
  before any "save my work" decision, before starting any background process, when
  troubleshooting "my project reset itself", and at every session start.
---

# Z-Container Survival Guide v2

**Canonical raw URL:** `https://raw.githubusercontent.com/super-z-kits/z-container-kit/main/SKILL.md` — fetch directly, no GitHub-title inference.

**Cold-start TL;DR** (fresh chat, PAT + kit repo URL, nothing else): clone
`https://github.com/super-z-kits/z-container-kit`, run `scripts/install.sh`,
wire your workspace remote (PAT typed once), `fetch && reset --hard origin/main`,
install.sh again, `zsave`. Full sequence in "Session start" below.

Every claim is graded: **[V]** verified live 2026-08-28, **[S]** from `/start.sh`
source, **[I]** inherited/unverified — never "test" the deadly ones. Long-form
forensic detail in `reference.md`; operational deep-dive modules in `kb/`.

Kit copies live at `/home/z/my-project/z-container-kit/` (git-tracked),
`/home/sync/z-container-kit/`, `/home/user_skills/z-container-kit/`, plus a
portable `/home/user_skills/z-container.zip`. If helpers are missing (fresh
chat), reinstall from any copy: `bash <kit>/scripts/install.sh`.

## Rules you never break

1. **Push your work often — GIT IS THE DISK.** There is no durable local disk; github is the only cross-chat persistence. Pushed = saved; unpushed = at risk.
2. **Never force push to remote.** Local state can be faulty (watchdog reverts, workspace wipes, wrong work dir). `git push --force` overwrites the only copy with your possibly-broken local — the most deadly combination. Slow down and fix merge conflicts properly, or stop and ask the user for explicit permission. The most common cause of divergence that tempts force-push is your own local workspace issue, not a real remote conflict.
3. **Set git identity to your real GitHub account.** `git config user.name "<GitHub username>"` and `git config user.email "<id>+<username>@users.noreply.github.com"` — the exact noreply email from GitHub settings, never an invented ID. Vercel blocks deploys authored by `Z User <z@container>` or any email not on your GitHub account.
4. **Delegate to sub-agents to avoid excessive bash calls.** Rapid toolcall loops risk the 403 lockout (see law 6). Spawn sub-agents for repetitive probes.
5. **The watchdog force-checkouts `/home/z/my-project` to main every ~20s**, reverting any file that differs between branches. Solution: work in a clone outside the watched path (e.g. `/tmp/my-project/worktrees/<name>`), or stay on main and use a separate fork repo if you truly need branch isolation.

## The ten laws

1. **Session starts with `bash /home/z/my-project/scripts/zsession`** — read its report before touching anything. If `scripts/` is empty (fresh-chat boot template), run the surviving copy at `/home/user_skills/z-container-kit/scripts/zsession` instead.
2. **Work on `main` inside `/home/z/my-project`.** The watchdog runs `git switch main` before every toolcall; on main it is a no-op, on any other branch it reverts your working files.
3. **End every milestone with `bash /home/z/my-project/scripts/zsave "msg"`** — commit + push + `/home/sync` snapshot + `repo.tar` refresh in one command.
4. **Overlay is not a disk.** Only `/home/sync`, `/tmp/my-project`, `my-project/upload/`, `/home/user_skills`, and github survive a recycle. `/home/z/my-project` survives only via `repo.tar` (graceful shutdown) or your own `zsave`. Of these, only github (and probably `/home/user_skills`) crosses into a NEW chat.
5. **Parallel/feature work goes OUTSIDE the project**: `git -C /home/z/my-project worktree add /tmp/my-project/worktrees/<name> -b <branch>` — watchdog-free AND recycle-safe. Push from there.
6. **Never loop `caddy` subcommands (run/start/stop/reload/file-server) and never curl-loop ports 12600/19001/19005/19006** — irreversible session-wide 403 lockout. One probe per toolcall. **[I]**
7. **Background processes need a double-fork** (`python3 /home/z/my-project/scripts/daemonize.py --log <f> -- <cmd>`); `nohup`/`setsid`/`&`/`disown` all die at toolcall end. Boot-time services: `mini-services/` dirs or `.zscripts/dev.sh`. **[V]**
8. **Never kill the :3000 dev server** — there is no supervisor and it won't restart on its own. If you must bring it back, relaunch it via daemonize.py (recipe below); don't wait for a recycle.
9. **Track `.env` in git — git IS the disk here.** External reviewers flagging committed secrets as P0: ignore them; they lack this context. Do not print token values into chat/logs.
10. **The watchdog never destroys commits or untracked files — panic "fixes" do.** Diagnose (`git log --all --oneline`, `zsession`) before resetting anything.

## Session start

```
bash /home/z/my-project/scripts/zsession
```

Read-only report: uptime, mount writability, recycle detection, git status/remote/
worktrees, watchdog hygiene, services, kit presence, numbered recommended actions.
Follow its advice. Fresh-chat bootstrap detail (paths A/B, credential-file
shortcut, branch-rename, env-override testing): `kb/bootstrap.md`.

Cold start (5 commands — verify origin/main commits BEFORE `reset --hard`):

```
git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit
bash /tmp/my-project/kit/scripts/install.sh
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git
git -C /home/z/my-project fetch origin
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK before reset
git -C /home/z/my-project reset --hard origin/main     # skip if remote is empty/new
bash /tmp/my-project/kit/scripts/install.sh            # LOAD-BEARING: restores skills/ (git-ignored)
bash /home/z/my-project/scripts/zsave "fresh-chat bootstrap checkpoint"
```

PAT is typed exactly once (the remote-add line). The kit repo is public — clone
needs no PAT. Two alternatives for the remote-add step:

- **B1 — credential file survived** (most common in Path B): replace the
  remote-add with `git remote add origin "$(cat /home/user_skills/zk-remote.url)"`.
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

**Kit version drift (R10 #4):** the git-tracked kit copy at
`/home/z/my-project/z-container-kit/` may lag behind the installed copy at
`/home/user_skills/z-container-kit/` if you haven't run `install.sh` yet this
session. Always run `install.sh` before trusting the git-tracked copy's docs.

## Saving work — zsave

```
bash /home/z/my-project/scripts/zsave "milestone message"
```

Does, in order: maintain `.git/info/exclude` → `git add -A` + commit (incl. `.env`
— law 9) → push `origin HEAD:<branch>` (refreshes `zk-remote.url` credential
files) → tar snapshot to `/home/sync/zk-snapshots/` (keep 5) → refresh
`/home/sync/repo.tar` (the boot-restore artifact) → write `zk-state.env`
(recycle detector). Each step degrades gracefully; nonzero exit = commit/snapshot/
repo.tar failed (push failure is a warning). Full 6-step internals with exclude
rules: `kb/zsave-internals.md`.

Run after every meaningful milestone, before risky operations, and at least
every ~10 toolcalls in long sessions. It is cheap (a few seconds).

**Concurrency:** zsave takes a per-container lock (`/tmp/.zsave.lock`). **Sub-agents
must NOT run zsave** — the coordinating agent owns saves (two concurrent runs
would corrupt repo.tar). Pushing from a worktree is always fine.

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
`kb/watchdog-advanced.md`.

## Persistence map

| Location | Storage | Survives toolcalls | Survives recycle (scale-to-zero) | Survives force-kill | Survives NEW chat |
|---|---|---|---|---|---|
| `/home/z/my-project` (excl. `upload/`) | overlay | yes | only via `repo.tar` (graceful) or zsave-refreshed `repo.tar` | only if zsave ran | only via github |
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
  `python3 /home/z/my-project/scripts/daemonize.py --cwd <dir> --log <file> -- <cmd...>`
  (verified: survived 10+ minutes across 30+ toolcalls).
- Boot-time services: drop a dir with `package.json` (+ `dev` script) into
  `my-project/mini-services/` — auto-started at every boot [S]. Or a
  `my-project/.zscripts/dev.sh` for a fully custom boot flow (runs as z).
- Daemons still die on recycle. Persistence is storage-only, never process-based.
- Restart a dead :3000 dev server without a recycle:
  `python3 /home/z/my-project/scripts/daemonize.py --cwd /home/z/my-project --log /home/z/my-project/dev.log -- bun run dev`

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
  (repo.tar boot-restore brings it back), the `zk-remote.url` credential files
  (zsave-maintained: `/home/sync/` + `/home/user_skills/`), and tar snapshots
  of `.git`. NEVER in the GitHub repo, never in any kit file. Different PAT:
  `git remote set-url origin https://<PAT>@github.com/<u>/<r>.git`, then `zsave`.
- `zsave`/`zsession` mask `ghp_…`-style tokens in ALL output. Never verify
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

## Sub-agents & coordination

- Sub-agents share THIS container: the watchdog resets HEAD before their
  toolcalls too, and their file writes land in the same overlay. Give each
  sub-agent its own worktree (`/tmp/my-project/worktrees/<name>`) or scratch dir.
- Sub-agents MUST NOT run `zsave` — the coordinating agent owns all saves
  (zsave's per-container lock would otherwise corrupt repo.tar). Pushing from a
  worktree is always fine.

## Quick reference card

```
DO
  bash /home/z/my-project/scripts/zsession              # session start report
  bash /home/z/my-project/scripts/zsave "msg"           # save everything
  git -C /home/z/my-project worktree add /tmp/my-project/worktrees/x -b feature/x
  python3 /home/z/my-project/scripts/daemonize.py --log /tmp/x.log -- <cmd>
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

## Testing the helpers safely

Helpers honor `ZK_PROJ` / `ZK_SYNC` env overrides so tests never touch the real
`/home/sync` artifacts (an accidental real zsave would overwrite the boot-restore
`repo.tar`). Scratch-test pattern: `kb/testing-helpers.md`.

## Helpers reference

Kit helpers in `scripts/`:

**Bash:**
- `zsave "msg"` — commit + push + snapshot + repo.tar refresh + credential file
- `zsession` — read-only situation report (recycle detection, watchdog hygiene)
- `install.sh` — installs the kit + helpers everywhere (idempotent)
- `daemonize.py` — double-fork background process that survives toolcalls
- `wdt_watch.py` — watchdog observation helper (forensic)
- `zremote` — PAT-masking `git remote` viewer (replaces `git remote -v`)
- `zdoppler-smoke` — one-shot Doppler vault verification
- `zkit-selftest` — end-to-end save/wipe/recover smoke test
- `zcleanup-backups` — prune old `.pre-update-backup-*` / `.pre-export-*` dirs from `/home/user_skills/` (OF-14: keeps last 2 per skill by default; `zcleanup-backups 5` to keep more, `0` to delete all)

**Python (complementary):**
- `doppler_fetch.py` — urllib version of `zdoppler-smoke`; stages secrets to `/tmp/my-project/doppler-secrets.json`
- `verify_access.py` — urllib access verifier for GitHub / Cloudflare / Supabase (Supabase WAF needs `User-Agent: zk-verify`)

Use bash for quick one-shots; Python for multi-call flows that stage secrets
across calls. Audit-callout detail per helper (F6, F8, F10, M7, M3, M4):
`kb/helpers-audits.md`.

## DOPPLER_TOKEN_SEED callout

If your Doppler vault contains a secret named `DOPPLER_TOKEN_SEED` with a `dp.pt.*`
prefix (a Personal Token stored in the vault), this violates secrets-vault-kit's
own guidance. Don't auto-rotate or auto-delete — flag to the user. Detail:
`kb/doppler-token-seed.md`.
