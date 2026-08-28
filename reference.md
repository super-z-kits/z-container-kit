# Z-Container Reference — deep detail (v2)

Companion to `SKILL.md` (operational rules). This file holds the WHY: forensic
evidence, boot-source walkthrough, storage internals, environment specs, and
the v1 → v2 correction log. Evidence grading as in SKILL.md: **[V]** verified
2026-08-28, **[S]** from `/start.sh` source, **[I]** inherited/unverified.

## 1. v1 → v2 corrections (what the old notes got wrong or stale)

| v1 claim | v2 finding | Grade |
|---|---|---|
| Watchdog "resets only the branch pointer, not files" | It runs a FULL `git switch main`: working-tree files revert to main's content when your branch has committed work | **[V]** |
| Watchdog acts "between every bash toolcall" | It runs as a prelude BEFORE every toolcall (Bash, Read, Write — all types), never while idle | **[V]** |
| Workaround Option C (update-ref main → feature HEAD) as the main strategy | Simpler and safer: just work on main (prelude becomes a no-op). Remote feature branches via `git push origin main:feature/X`. Worktrees for parallel work | **[V]** |
| `.git/HEAD` written by an unknown mechanism | Literal `git switch main` executed as user z in a prelude `su z -c /bin/bash` chain; git lockfile protocol (HEAD.lock → rename); inode changes each real reset | **[V]** |
| Seccomp disabled (0) | Seccomp ENABLED (filter mode, Seccomp: 2) | **[V]** |
| Missing: vim, rg, nc, tmux... | vim, rg, jq ARE present; check `command -v` instead of trusting lists | **[V]** |
| `/etc/.z-ai-config` ~422 B, 2 fields | start.sh writes 2 fields at boot; the bridge injects chatId/token/userId per session (5 fields total) | **[S+V]** |
| Public IP ~47.57.x.x | eth0 is 21.0.12.27/32 (FC internal /32); public egress IP not re-verified | **[V-internal]** |
| "First action: git pull (or clone if .git missing)" | Right idea, formalized: `zsession` detects the state (fresh chat vs recycle vs restore) and prints exact next commands | **[V]** |
| dev.sh "typically already running" | Dev server starts ONLY if my-project has package.json (or .zscripts/dev.sh) at boot; this chat (no package.json) has no :3000 listener | **[S]** |

## 2. Container identity [V]

- Runtime user `z` (uid 1001, gid 1001), no sudo, no root. CapEff = 0
  (bounding set unusable). Seccomp filter mode ON. Containment = Kata +
  read-only cgroup mounts + the bash command filter.
- Debian 13 trixie; host kernel 5.10.134 (Aliyun Linux 8 / LifseaOS via Kata).
- 2 vCPU Xeon Sapphire Rapids (AVX-512 + AMX), 4 GiB RAM hard limit, no swap.
  kata-agent drops page cache under memory pressure — page-cache eviction
  spikes are normal **[I]**.
- PID 1 = `tini -- /start.sh`; caddy (root, PID 2); ZAI bridge
  `/app/.venv/bin/python3 main.py` (root, ~PID 925); bash toolcalls spawn
  `/bin/sh -c su z -c '/bin/bash --noprofile --norc'` chains per call.
- ulimits: max user processes 1024, open files 1024 (hard 100000), stack 8 MB.
- Hostname = FC container id (e.g. c-6a90fbaa-…), mapped in /etc/hosts.
- TZ=UTC. `date` prints UTC — use UTC everywhere.

## 3. Boot sequence (from /start.sh source [S])

1. Timeline logging to `/tmp/boot-timeline.log` (read it after any odd boot).
2. **Project init check**: if `/home/sync/repo.tar` exists → wipe
   `/home/z/my-project/*` (preserving the `upload/` mountpoint) → `tar xf
   repo.tar -C /home/z/my-project --exclude=./upload` → rewrite `.env` with
   `DATABASE_URL=file:/home/z/my-project/db/custom.db` → chown z:z.
   Else ("Whoa, wat a nice clean project"): create `.env`,
   `download/README.md`, `skills/`.
3. **Skills**: extract allowed zips from `/home/official_skills/` (allow-list
   from `stages.yaml`; the `default` stage defines the common coding skill
   set) into `skills/`, chown z. Custom dirs already in `skills/` are NOT
   removed by boot.
4. **Git setup**: `safe.directory`, identity (Z User / z@container),
   `init.defaultBranch main` — all global. Force-write narrow `.gitignore`
   (`skills/`, `node_modules/`) with auto-heal for a historical broad version.
   If `[ ! -d .git ]`: `git init && git add . && git commit -m 'Initial
   commit'` (a `.git` pointer file passes this test → `git init` reinit — safe).
5. **ZAI service** (root): `cd /app && uv run main.py` — the bridge; /app is
   mode 700 root (unreadable to z).
6. **Project services** (as z, background):
   - `/home/z/my-project/.zscripts/dev.sh` if present (fully custom flow), ELSE
   - `package.json` → `bun install` → `bun run db:push` → `bun run dev`
     (health-checked on :3000), plus
   - every `mini-services/<dir>` with `package.json` + `dev` script →
     `bun install && bun run dev` (logs: `/tmp/mini-service-<name>.log`).
7. Wait for ZAI :12600, then `exec caddy run --config /app/Caddyfile` (port 81
   must be healthy within 120 s or FC recycles the instance).
- Boot ≈ 13 s to caddy in the observed session.

## 4. The HEAD watchdog — forensic detail [V]

Method: double-forked observer (`scripts/wdt_watch.py`) armed inotify (ctypes)
on `/home/z/my-project/.git` + 4 Hz `/proc` scanning; interleaved bash/Read/
Write toolcalls; markers written into the log for windowing. Raw evidence:
`evidence/watchdog-forensics.log`.

Model (all points verified live or re-verified independently):
- Trigger: EVERY toolcall of every observed type — Bash, Read, Write — also
  observed from within a sub-agent session (the round-1 audit agent watched
  the prelude fire for its own toolcalls, including a Write that failed path
  validation). Not time-based; nothing happens while the session is idle.
- Actor: `git switch main` run as user z, cwd `/home/z/my-project`, spawned as
  a child of a prelude chain `/bin/sh -c su z -c /bin/bash` that the bridge
  starts ~200–500 ms before the toolcall's command chain
  (`/bin/bash --noprofile --norc`).
- Write mechanism: real git (lockfile create/write/rename; new inode per
  reset; file mode 664, owner z:z).
- Semantics = `git switch main`, exactly:
  - already on main → no-op (no HEAD write at all);
  - clean non-main branch → switch succeeds; tree reverts to main's content;
  - conflicting uncommitted changes → switch fails silently; branch kept;
  - non-conflicting uncommitted changes → carried onto main.
- Scope: ONLY the repo at `/home/z/my-project` (resolved through a `.git`
  pointer file too). Other repos anywhere else: untouched. Linked worktrees:
  untouched.
- The watchdog itself commits nothing; UUID-message commits come from the
  platform's own git add -A at recycle/pre-stop (not observed mid-session).

Why it exists (inferred): the platform wants the workspace on a stable branch
so its `git add -A` snapshot commits land linearly on main. Do not fight it —
stay on main and it is inert.

## 5. Storage internals

Mount topology [V] (each "persistent" path is a tmpfs bridge with a FUSE mount
nested inside it — `findmnt` shows both layers):
- `/tmp/my-project` → PolarFS (JuiceFS-backed; volume
  pcs-ue6ju0nuiu0hz7tjc-0e3odv6t4dackr8s3) — per-chat subtree (inferred).
- `/home/user_skills` → same PolarFS volume, different subtree — per-user
  (inferred from month-old mtime on a fresh chat).
- `/home/sync` → ossfs (Alibaba OSS) — per-chat (inferred).
- `/home/z/my-project/upload` → ossfs.
- `/home/official_skills` → ossfs, read-only, the skill zip store.
- Everything else (`/`, `/tmp` (excl. my-project), `/home/z/...`) → overlay,
  ephemeral; root overlay ~10 GB; /dev/shm 64 MB; cgroup ro.

Performance [V]: see evidence/EXPERIMENTS.md E9. Summary: ossfs ≈ 61 MB/s
sequential but ~64 ms per small-file op; PolarFS behaves like a local FS
(~50 MB/s sequential, ms-level small ops). Practical implications: tarball
snapshots on /home/sync are cheap; live git repos on ossfs are viable but
sluggish; hot working data belongs on PolarFS.

Quotas: PolarFS df shows cluster-wide numbers (64P/36P) — per-subtree quota
unknown; ossfs df shows 16E (unlimited-looking) — actual bucket quota unknown.

## 6. repo.tar lifecycle

- Graceful shutdown → platform `git add -A && git commit` (UUID message) →
  tar `/home/z/my-project` → `/home/sync/repo.tar` **[S+I: archiver itself is
  outside the container; its exact exclusions are unknown]**.
- Force-kill / crash → nothing written; next boot restores the LAST repo.tar
  that exists — which may be minutes or days stale, or (fresh chat) absent.
- Boot restore semantics [S]: full wipe + extract (see §3.2) — stale files do
  not linger, but any file NOT in the tar is gone.
- zsave's contract: after every zsave, `/home/sync/repo.tar` equals the
  project at that moment → force-kill restores at worst to your last zsave.
- Excluded from zsave tars: node_modules/.next/.turbo (any depth), upload/,
  dev.log, and OFFICIAL skills (boot re-extracts them from
  /home/official_skills); CUSTOM skills (dirs in skills/ with no matching
  official zip) are appended back into the tar. Boot re-runs `bun install`
  when package.json exists [S].

## 7. Process model

- Per-toolcall cull: the bridge spawns `sh -c su z -c bash` per bash toolcall
  and kills the descendant tree when the call ends. Verified death: `nohup ...
  & disown` and `setsid ... &` (re-verified 2026-08-28 by two independent
  review agents — dead within one toolcall); verified survival: double-fork
  (E8, re-verified: daemonize.py daemon alive 14+ ticks later, PPID 1).
- PID 1 (tini) adopts orphans → double-forked daemons live until recycle.
- Boot-started services (dev server, mini-services) are children of
  start.sh's background subshells → not culled; also not supervised: killing
  them means manual restart via daemonize.py or waiting for a recycle.
- Memory: 4 GiB hard, no swap — daemons that leak will OOM-kill themselves;
  page-cache pressure evictions are normal.

## 8. Networking detail

- Ports [V for listeners, I for roles]: 81 caddy (public), 3000 Next.js dev
  (only when package.json/dev.sh exists), 12600 ZAI bridge (127.0.0.1;
  `/ping` → pong, do not loop), 19001/19006 FC control plane HTTP (404s),
  19005 FC gRPC/binary. Leave 12600/19001/19005/19006 alone — scanning them
  risks the irreversible 403 lockout.
- Caddy :81 proxies to localhost:3000 **[I]** — the Caddyfile is root-only;
  start.sh only shows caddy runs with /app/Caddyfile.
- `?XTransformPort=<port>` on the preview URL reaches other internal ports;
  WS/SSE must use path `/` **[I]**.
- Egress open (github/npm/pypi verified reachable) [V]; no external IPv6 [I];
  MTU 1450 [V]; DNS 100.100.2.136/138 [V].
- Preview URL not discoverable from inside (no *_URL env vars) [I].

## 9. ZAI bridge & SDK

- Bridge: `/app/main.py` (root, unreadable) relays to
  `https://internal-api.z.ai/v1` using `/etc/.z-ai-config` [S].
- `/etc/.z-ai-config` per session: baseUrl, apiKey ("Z.ai" placeholder),
  chatId (matches this chat's UUID), token (JWT), userId [V]. Do not print or
  exfiltrate the token.
- `z-ai-web-dev-sdk` global bun package; config search order: cwd → ~ →
  /etc. Import only in server code (route handlers / server components) [I].
- The system prompt is assembled platform-side at the LLM call — not mutable
  from inside the container [I].

## 10. Helper internals

- `zsave`: env overrides ZK_PROJ / ZK_SYNC / ZK_KEEP. Per-container flock
  (/tmp/.zsave.lock — one zsave at a time; sub-agents defer to the
  coordinating agent). Steps: maintain .git/info/exclude (repo-ROOT anchored
  /upload/, /dev.log, /tool-results/ + any-depth .next/, .turbo/ — legacy
  unanchored entries are stripped on upgrade; untracked only) → NESTED git
  repos (scratch clones) auto-excluded, tracked gitlinks reported with fix
  command → commit (git add -A; clean tree = no
  commit, message unused) → push `HEAD:<branch>` (warning on failure) →
  tar built on local /tmp (excl. node_modules/.next/.turbo at ANY depth,
  upload/, dev.log, official skills; custom skills appended back) → copied
  to zk-snapshots + repo.tar atomically (PID-unique tmp + mv; tar exit 1
  "file changed" tolerated for live dev servers) → zk-state.env written
  atomically with sanitized values (zsession parses with sed, never
  sources it). Detects `.git`-as-pointer and snapshots the real gitdir as
  `gitdir-<ts>.tar`. Exit nonzero if commit/snapshot/repo.tar fail (push
  failure stays a warning). GNU coreutils assumed (head -n -N, stat -c,
  flock).
- `zsession`: read-only report (container, recycle detection via
  zk-state.env + boot-epoch cross-check, git, watchdog hygiene with
  detached-HEAD / missing-main handling, services, kit presence, recommended
  actions). No persistent changes (mount checks create+remove a unique
  probe file); state file parsed with sed, never sourced. ZK_PROJ override
  cleanly skips live-project-only checks. Cold-start detection (no remote +
  no state file): prints the exact bootstrap sequence — kit source
  (surviving copy or the public canonical clone URL), remote recovery
  (credential file or PAT+URL), fetch+reset, LOAD-BEARING install, first
  zsave — and never recommends zsave before its script exists.
- `daemonize.py`: double-fork + setsid + stdio to --log (or /dev/null) +
  `--cwd` + execvp. Reparented to PID 1; survives all toolcalls; dies on
  recycle.
- `install.sh`: kit → skills/z-container (tar coverage), scripts →
  my-project/scripts (git coverage), git-tracked copy →
  z-container-kit at the repo ROOT (github coverage; v2.2.x legacy copies
  at download/z-container-kit are auto-removed), kit copies →
  /home/sync/z-container-kit and /home/user_skills/z-container-kit.
  Self-install-aware, atomic copy-then-swap, 0644 mode normalization,
  version-skew note, nonzero exit on failure.

## 11. Sub-agent playbook (for the agent reading this)

- Task-tool sub-agents: independent tool sessions (lockout isolation) but the
  SAME container (same watchdog prelude, same overlay). Give each: its own
  worktree or scratch dir under `/tmp/my-project/`, a fully self-contained
  prompt (they see nothing of your context), explicit hazard warnings (never
  loop caddy cmds / never curl-loop 12600|19001|19005|19006 / one probe per
  toolcall), their Task ID, and the worklog protocol.
- Worklog: `/home/z/my-project/worklog.md`, append-only, sections starting
  `---`, each with Task ID / Agent / Task / Work Log / Stage Summary.
- After any sub-agent round: review their findings, fix the kit, re-run
  reviews until clean (this kit itself was validated through such rounds —
  see §13).

## 12. Open questions (unverified today)

- Exact scoping (per-chat vs per-user) of /home/sync, /tmp/my-project,
  /home/user_skills — strong inference, no proof. Test across chats only.
- Pre-stop archiver's exclusions (does it tar node_modules?).
- Runtime git_commit trigger conditions (only pre-stop observed).
- Whether custom skills in `skills/` are auto-loaded by the skill system in
  coding sessions (stages.yaml gates official zips at extract; discovery of
  custom dirs unconfirmed) — if not auto-loaded, the kit is still fully
  usable by reading its SKILL.md at session start.
- XTransformPort behavior as seen from inside (gateway-layer feature).
- Public egress IP today (v1 cached ~47.57.x.x).
- Lockout specifics (never test: irreversible).

## 13. Kit provenance

Built 2026-08-28 by the main agent from live forensics (evidence/), then
hardened through fresh-context sub-agent review rounds: round 1 (technical
audit T-r1-a, cold usability T-r1-b, adversarial review T-r1-c) drove the
v2.1.0 fixes — install.sh self-install guards + atomic swaps, safe restore
runbook replacing the destructive one-liners, tar hardening (any-depth
excludes, file-changed tolerance, local build, official-skills exclusion),
concurrent-zsave lock, eval-safe state file, worktree and stuck-repo-state
coverage, detached-HEAD and non-main-default-branch handling; round 2 (recovery-path usability T-r2-a + verification review T-r2-b) then
fixed the remaining set: zsession boot-epoch recycle detector quoting bug,
anchored .git/info/exclude entries (nested source dirs stay tracked),
verified orphaned-worktree recovery recipe, gitdir-restore decision rule,
install.sh mode normalization + version-skew note + exit codes. A final
verification round confirmed the fixes. v2.2.0 then activated the github
remote path (PAT embedded in the origin URL; the source workspace repo —
name withheld, kit stays project-agnostic), added PAT masking to all script output
(zsession remote display, zsave push stderr), and zsave-maintained
`zk-remote.url` credential files (`/home/sync/`, `/home/user_skills/`)
for fresh-chat remote recovery. Round 4 (T-r4-a E2E push/masking 8/8 PASS;
T-r4-b fresh-chat recovery simulation, all steps PASS; T-r4-c adversarial
containment audit — verdict CONTAINED, full git object DB scanned including
unreachable objects) then drove v2.2.1: token masking extended to branch
names and the state file, `git remote -v` transcript warning, ask-the-user
PAT fallback in the fresh-chat runbook, load-bearing reinstall note
(skills/ is git-ignored), install.sh safe.directory dedupe. Round 5
(post-recycle containment audit: full-token scan of all five kit copies,
the portable zip, the workspace tree and home dotfiles; git object-DB scan
including unreachable blobs; repo.tar/snapshot internals) confirmed the PAT
is fully contained — never in any kit file, never committed, never on
GitHub — and drove v2.2.2: install.sh refreshes the portable
`/home/user_skills/z-container.zip` (had gone stale at v2.2.0), SKILL.md
states the PAT contract explicitly (kit is token-free and project-agnostic;
credential files track the last remote that pushed successfully), and the
boot-restore mode-churn quirk got a documented fix
(`git config core.fileMode false`). Round 5's fresh-context re-audit
(T-r5-a) confirmed CONTAINED (kit copies, zip content, git object DB,
whole-container sweep) and caught two items that drove v2.2.3: the last
workspace-repo parentheticals were scrubbed from SKILL.md (operational docs
are now fully repo-agnostic; this provenance and the evidence log keep the
name as historical record), and the platform was observed INGESTING
`/home/user_skills/z-container.zip` on sub-agent session spawn (zip
removed at spawn; install.sh re-creates it — treat the zip as a delivery
vehicle, the kit dir as the archive). T-r5-a also confirmed the
cross-chat bet live: `/home/user_skills/zk-remote.url` survived a real
container recycle. Version
history: 2.0.0 — first evidence-graded release; 2.1.0 — round-1 fixes;
2.1.1 — round-2 fixes; 2.2.0 — github push path + PAT masking + credential
persistence; 2.2.1 — round-4 fixes (branch/state masking, recovery-doc
hardening); 2.2.2 — round-5 containment audit (zip auto-refresh, explicit
PAT contract, fileMode quirk fix); 2.2.3 — round-5 fixes (SKILL.md
repo-scrub, zip-as-delivery-vehicle model); 2.3.0 — round-6 dogfood fixes
(cold-start path A, zsession bootstrap detection, zsave nested-repo guard,
repo-root layout); 2.3.1 — cold-start usability round (install.sh strips
VCS metadata from kit copies + zip, TL;DR card, absolute-path idioms,
PAT-once note); 2.3.2 — ut2 verification round (scratch-mode zsession hides
live credential file). Verification round 2 (sub-agent ut2, blind re-run of the
cold start against the published v2.3.1): verdict FRICTIONLESS — all four
regression checkpoints PASS (no .git planted anywhere incl. the zip; kit
files trackable and reaching github; PAT guidance + TL;DR + absolute idioms
present; every documented command verbatim first-try; end-to-end zsave
verified incl. ls-remote branch match and a clean pushed-tree token scan).
Its two nits drove v2.3.2: zsession no longer lists the live
/home/user_skills credential file under ZK_PROJ/ZK_SYNC scratch overrides
(the ZK_SYNC one still shows — it is scratch-local), and the clone-path note
was already annotated in v2.3.1.

Round 6 (2026-08-28, dogfood session) — a fresh session bootstrapped purely
via the kit's own documented onboarding (credential-file path, live) and
audited it for friction. Findings and v2.3.0 fixes: (F1) the cold-start
flow — PAT + kit repo URL, nothing else — existed only as scattered pieces
across three sections; SKILL.md now has an explicit "Path A: nothing
survived" five-command sequence, install.sh documents it, zsession prints
it on cold-start detection, and the kit has a canonical public home
(github.com/super-z-kits/z-container-kit) making the bootstrap clone
PAT-free; (F2) zsession recommended zsave before the script existed and
omitted the fetch/reset/install steps — recommendations are now guarded and
the cold-start block prints the full sequence; (F3) a repo rename left the
zk-remote.url credential file stale (worked via GitHub redirects, silent
drift) — rename handling documented in the zsave-push troubleshooting tree;
(F4) zsave committed nested git repos (scratch clones) as broken gitlinks —
now auto-excluded when untracked, flagged with a fix command when tracked;
(F5) version-string skew across kit files — all helpers now carry the kit
version; (F6) workspace repo layout: the git-tracked kit copy moved from
download/z-container-kit (the platform's own deliverables dir) to
z-container-kit at the repo root, with install.sh auto-removing legacy
copies; a clean, project-detail-free variant of the kit is published to
the canonical public home (see its README for the bootstrap one-liner).
Round 6 also ran a cold-start usability test (sub-agent ut1, given only a
PAT + the public repo URL, scratch dirs): every documented command worked
first-try (verdict MINOR FRICTION, 20 toolcalls), and it caught a real bug —
install.sh planted the bootstrap clone's `.git` into every kit copy
(broken-gitlink / silently-untracked kit files; 45 stray entries in the
portable zip), driving v2.3.1: copy_into() and the zip build now strip all
VCS metadata. Also in v2.3.1: cold-start TL;DR at the top of SKILL.md,
absolute `git -C /home/z/my-project` idioms in the path-A block (cwd no
longer ambiguous), a PAT-typed-once note (the remote-add is the single
 sanctioned echo; helpers mask everything after), and the zsave nested-repo
warning now spells out the consequence (new files inside stay untracked).
Supersedes the two inline v1 documents.
