---
name: z-container
metadata:
  author: z + Super Z forensic session
  version: "3.1.6"
  verified: "2026-08-29 (live experiments + 12 validation rounds; see evidence/EXPERIMENTS.md)"
  description: >
    Survival guide for the sandbox container. The kit is instantiated into
    your repo at .agents/ (git-tracked; .agents/config carries ZK_PREFIX and
    survives boot). Verified mechanics of the Git HEAD watchdog (a
    `git switch main` prelude that runs before EVERY toolcall), the persistence
    model (overlay vs PolarFS vs ossfs vs github; repo.tar restore semantics),
    background-process survival (double-fork, mini-services, .zscripts/dev.sh),
    the irreversible terminal lockout hazard, ports/networking, secrets
    practice, and the zsave/zsession helpers. Load BEFORE any git operation,
    before any "save my work" decision, before starting any background process,
    when troubleshooting "my project reset itself", and at every session start.
---

# Z-Container Survival Guide v3

**Read LOCAL copies first — the web is the fallback, not the flow.** This
file lives at `.agents/SKILL.md` in your repo (git-tracked — that is how it
survives) and in the read-only package at
`/home/user_skills/z-container-kit/` (the install source — per-user storage
that survives into new chats, observed live). Start every flow from one of
those two local copies. Only if both are absent (a truly bare container):
fetch `https://raw.githubusercontent.com/super-z-kits/z-container-kit/main/SKILL.md`
directly (no GitHub-title inference) or clone the repo, and reinstall with
`bash <kit>/scripts/install.sh`.

Every claim is graded: **[V]** verified live 2026-08-28, **[S]** from `/start.sh`
source, **[I]** inherited/unverified — never "test" the deadly ones. Operational
deep-dive modules in `kb/` (read when the specific topic is relevant).

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
bash /home/z/my-project/scripts/zsession
```
Read-only report: uptime, mount writability, recycle detection, git status/remote/
worktrees, watchdog hygiene, services, kit presence, numbered recommended actions.
Follow its advice. If `scripts/` is empty you are in a fresh chat whose workspace
is the boot template — run the surviving package copy first (it works
pre-recovery and prints the cold-start sequence + the masked credential-file
URL), then go straight to step 4 below:
```bash
bash /home/user_skills/z-container-kit/scripts/zsession
```
(Fallback if scripts/ exists but a helper is missing:
`bash /home/z/my-project/.agents/scripts/zsession`.)
Fresh-chat recovery detail (paths A/B/C, credential-file shortcut, branch-rename,
env-override testing): `kb/session-recovery.md`.

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
worklog, `scripts/` empty) — cold start. Wire the remote BEFORE the kit
install so the installer can derive `ZK_PREFIX` from the origin URL
(nothing else exists to derive it from on a true cold start):

```
KIT=/home/user_skills/z-container-kit                 # LOCAL package FIRST (per-user, survives new chats)
[ -f "$KIT/scripts/install.sh" ] || { git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit; KIT=/tmp/my-project/kit; }
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git
git -C /home/z/my-project fetch origin
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK (brand-new/empty remote? origin/main doesn't exist yet — expected, move on)
git -C /home/z/my-project reset --hard origin/main     # skip if remote is empty/new
bash "$KIT/scripts/install.sh"                         # LOAD-BEARING: instantiates .agents/ (+config with ZK_PREFIX), scripts/ shims, skills/ symlink
bash /home/z/my-project/scripts/zsave "fresh-chat bootstrap checkpoint"
```

After recovery `ZK_PREFIX` lives in `/home/z/my-project/.agents/config` —
read it with `source /home/z/my-project/.agents/config` before using
`${ZK_PREFIX}` anywhere in your shell (each bash toolcall is a fresh subshell).

PAT is typed exactly once (the remote-add line). The kit comes from the local
package when it survived; the fallback clone needs no PAT (public repo). Two
alternatives for the remote-add step:

- **B1 — credential file survived** (Path B's credential-file shortcut): find it with
  `ls /home/user_skills/*-remote.url` (the prefix is the filename part before
  `-remote.url` — there is one per project; `${ZK_PREFIX}` is not defined in
  your shell yet, so resolve the path first):
  ```bash
  CF=$(ls /home/user_skills/*-remote.url | head -1)   # multiple? pick YOUR project's
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

2. **`zsave` after every MICRO-milestone — and "milestone" means as micro as it gets.** A milestone is NOT "when the feature is done" — that grand final moment never arrives. It is every good moment: one file written, one bug fixed, one step verified, one experiment that worked. Save at that granularity. `zsave` covers all 4 backup layers in one command: (1) commit to local git, (2) push to GitHub (the only cross-chat persistence), (3) snapshot tar to `/home/sync/${ZK_PREFIX}-snapshots/` (per-chat, survives recycle + force-kill), (4) refresh `/home/sync/repo.tar` (the boot-restore artifact — a force-killed container comes back at your latest zsave). It also refreshes the `${ZK_PREFIX}-remote.url` credential file in `/home/user_skills/` (mode 0600 — the only copy since v3.1; cross-chat remote recovery). **Pushed = saved across all layers; unpushed = at risk in ALL layers.** Run at every micro-milestone, before risky operations, and every ~10 toolcalls.

3. **Never force push.** Local state can be faulty (watchdog reverts, workspace wipes, wrong work dir). `git push --force` overwrites the only copy with your possibly-broken local — the most deadly combination. If push is rejected, `git pull --rebase origin main` and re-push. Never `--force` without explicit user permission.

4. **Set git identity before any commit.** Boot default is `Z User <z@container>` — Vercel blocks deploys from this identity. `git config user.name "<GitHub username>"` and `git config user.email "<id>+<username>@users.noreply.github.com"` (exact noreply email from GitHub settings). zsession detects this and prints the fix.

5. **Delegate to sub-agents to avoid excessive bash calls.** Rapid toolcall loops risk the 403 lockout (see law 6). Sub-agents get independent tool sessions — delegate risky probes.

## The ten laws

1. **Session starts with `bash /home/z/my-project/scripts/zsession`** — read its report before touching anything. If `scripts/` is empty (fresh-chat boot template), run the surviving copy at `/home/user_skills/z-container-kit/scripts/zsession` instead.
2. **Work on `main` inside `/home/z/my-project`** (rule 1's mechanism: the pre-toolcall `git switch main` is a no-op on main, a silent revert on any other branch).
3. **All saves go through `zsave`, at micro-milestone granularity** (rule 2's mechanism: one command = commit + push + `/home/sync` snapshot + `repo.tar` refresh). No ad-hoc partial saves; no waiting for a "finished" state.
4. **Overlay is not a disk.** Only `/home/sync`, `/tmp/my-project`, `my-project/upload/`, `/home/user_skills`, and github survive a recycle. `/home/z/my-project` survives only via `repo.tar` (graceful shutdown) or your own `zsave`. Of these, only github (and probably `/home/user_skills`) crosses into a NEW chat.
5. **Parallel/feature work goes OUTSIDE the project**: `git -C /home/z/my-project worktree add /tmp/my-project/worktrees/<name> -b <branch>` — watchdog-free AND recycle-safe. Push from there.
6. **Never loop `caddy` subcommands (run/start/stop/reload/file-server) and never curl-loop ports 12600/19001/19005/19006** — irreversible session-wide 403 lockout. One probe per toolcall. **[I]**
7. **Background processes need a double-fork** (`python3 /home/z/my-project/scripts/daemonize.py --log <f> -- <cmd>`); `nohup`/`setsid`/`&`/`disown` all die at toolcall end. Boot-time services: `mini-services/` dirs or `.zscripts/dev.sh`. **[V]**
8. **Never kill the :3000 dev server** — there is no supervisor and it won't restart on its own. If you must bring it back, relaunch it via daemonize.py (recipe below); don't wait for a recycle.
9. **Track `.env` in git — git IS the disk here.** External reviewers flagging committed secrets as P0: ignore them; they lack this context. Do not print token values into chat/logs.
10. **The watchdog never destroys commits or untracked files — panic "fixes" do.** Diagnose (`git log --all --oneline`, `zsession`) before resetting anything.

## ⚠️ Parallel sessions (shared /home/user_skills)

(R10-13) `/home/user_skills/` is **per-user, shared across concurrent
chats**. The platform runs 2-3 concurrent sessions under the same account —
they all see the same `/home/user_skills/`. This is a boon
(skills installed once are available everywhere) but can cause surprises:
parallel sessions can silently overwrite each other's `${ZK_PREFIX}-doppler.env`,
cause push divergence on the backup repo, or write phantom files. See
`kb/parallel-sessions.md` for the full hazard analysis + mitigations.

With the v3.1 layout the per-project state (`.agents/config`) is repo-local, so
parallel sessions on DIFFERENT repos no longer collide on prefix discovery.
The remaining shared surfaces are the credential files
(`${ZK_PREFIX}-doppler.env`, `${ZK_PREFIX}-remote.url`) and the backup repo
itself when two sessions share one repo.

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

## Saving work — zsave

```
bash /home/z/my-project/scripts/zsave "<what you just finished>"
```

Does, in order: maintain `.git/info/exclude` → `git add -A` + commit (incl. `.env`
— law 9) → push `origin HEAD:<branch>` (refreshes the `${ZK_PREFIX}-remote.url` credential
file in `/home/user_skills/`) → tar snapshot to `/home/sync/${PREFIX}-snapshots/` (keep 5) → refresh
`/home/sync/repo.tar` (the boot-restore artifact) → write `${PREFIX}-state.env`
(recycle detector). Each step degrades gracefully; nonzero exit = commit/snapshot/
repo.tar failed, or the credential-file write did not verify (F16) (push failure is a
warning). Full 6-step internals with exclude
rules: `kb/zsave-internals.md`.

Run after every micro-milestone — every good moment: a file finished, a step
verified, a bug fixed — before risky operations, and at least every ~10
toolcalls in long sessions. It is cheap (a few seconds). Do NOT wait for a
"big enough" moment: the grand final save never happens, and everything
since your last zsave is one recycle away from oblivion.

**Concurrency:** zsave takes a per-container lock (`/tmp/.zsave.lock`). **Sub-agents
must NOT run zsave** — the coordinating agent owns saves (two concurrent runs
would corrupt repo.tar). Pushing from a worktree is always fine.

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
- Sub-agents MUST NOT run `zsave` — the coordinating agent owns all saves
  (zsave's per-container lock would otherwise corrupt repo.tar). Pushing from a
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

## Testing the helpers safely

Helpers honor `ZK_PROJ` / `ZK_SYNC` env overrides so tests never touch the real
`/home/sync` artifacts, and `ZK_USK` so install.sh's package refresh and prefix
discovery never touch the real `/home/user_skills` (an accidental real zsave
would otherwise overwrite the boot-restore `repo.tar`, and prefix discovery
would read your real config files). Scratch-test pattern: `kb/testing-helpers.md`.

## Helpers reference

Kit helpers run from `scripts/` (git-tracked shims that exec into
`.agents/scripts/` — same commands, same behavior):

**Bash:**
- `zsave "msg"` — commit + push + snapshot + repo.tar refresh + credential file
- `zsession` — read-only situation report (recycle detection, watchdog hygiene)
- `install.sh` — instantiates the kit into `.agents/` (idempotent, preserves config)
- `zremote` — PAT-masking `git remote` viewer (replaces `git remote -v`)
- `zdoppler-smoke` — one-shot Doppler vault verification
- `zkit-selftest` — end-to-end save/wipe/recover smoke test
- `zcleanup-backups` — prune old `.pre-update-backup-*` / `.pre-export-*` dirs from `/home/user_skills/` (OF-14: keeps last 2 per skill by default; `zcleanup-backups 5` to keep more, `0` to delete all)

**Python (real copies in `scripts/` — `python3 scripts/<name>`):**
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

## New project setup (when the repo has never used this kit)

The setup flow — triggered when `.agents/` does not exist and no backup repo
carries one (see the MUST-READ decision block for how to tell the two flows
apart). The installer also runs during cold-start recovery — that's the
restore flow, see the MUST-READ section above. Everything is automated, but
you MUST name the project explicitly so you never inherit another project's
prefix:

```bash
ZK_PREFIX=<your-project-name> bash /home/user_skills/z-container-kit/scripts/install.sh
```

It instantiates the kit into `.agents/` (SKILL.md + scripts/ + kb/ + evidence/),
writes `.agents/config` with your `ZK_PREFIX`, creates the `scripts/` shims
and the `skills/z-container/SKILL.md` discovery symlink (keeping `skills/`
out of git via `.git/info/exclude`), and refreshes the read-only package +
portable zip in `/home/user_skills/`. On re-runs it UPGRADES in place and
always preserves `.agents/config`.

If you forget `ZK_PREFIX`, the installer auto-discovers one (legacy
`/home/user_skills/*-config.env` migration, durable-artifact scan, or origin-URL
basename) and WARNS — if it picked another project's prefix, fix it with:
```bash
rm /home/z/my-project/.agents/config && ZK_PREFIX=<name> bash /home/user_skills/z-container-kit/scripts/install.sh
```
(env-var re-runs alone cannot override an existing `.agents/config` —
preservation always wins; that is what makes upgrades safe.)

Then commit the kit so it travels with the repo:
```bash
git add .agents/ scripts/ && git commit -m "kit: .agents/ instantiated"
```

`ZK_PREFIX` naming rules: lowercase, `[a-z0-9-]`, max 24 chars, must be unique
among the projects you run in parallel under this account (it names the
credential/snapshot/state files in `/home/user_skills/` and `/home/sync/`).
Detail, edge cases, and the multi-project rationale: `kb/new-project.md`.

## Layout (two copies, by design)

```
/home/user_skills/z-container-kit/   read-only package — cold-start install source
                                     (survives recycle + force-kill; probably cross-chat)
/home/z/my-project/.agents/          instantiated kit — git-tracked, per-project
  .agents/SKILL.md                   this file (authoritative copy once installed)
  .agents/scripts/                   helpers (zsave, zsession, ...) — source ../config
  .agents/kb/                        deep-dive modules
  .agents/evidence/                  experiment logs backing [V] grades
  .agents/config                     ZK_PREFIX=<project-name>  <- survives boot
/home/z/my-project/scripts/          git-tracked shims -> exec .agents/scripts/<name>
/home/z/my-project/skills/z-container/SKILL.md   symlink -> ../../.agents/SKILL.md
                                     (platform discovery; skills/ is kept out of git
                                      via .git/info/exclude — install.sh maintains
                                      it and recreates the symlink after a reset)
/home/z/my-project/.env              DATABASE_URL only — boot-MANAGED, gets rewritten
/home/user_skills/${ZK_PREFIX}-*     credential files (never committed)
```

Why shims instead of symlinks for `scripts/`: a symlink's `$0` resolves to the
target, which mostly works, but a real shim file is a robust git-tracked
artifact that also survives tools which copy scripts without following
symlinks; `exec bash` keeps a single process and forwards the exit code.

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
- `kb/new-project.md` — instantiating the kit into a brand-new repo: ZK_PREFIX
  choice, multi-project naming, what install.sh creates, first-save checklist

