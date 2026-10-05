# zbackupd — the continuous background backup daemon (v6)

Status: [V] built + live-validated 2026-10-05 (battery T1–T10, below). Design
doc + adversarial gate reports (T10-a/b, both SHIP-AFTER-FIXES, all P0/P1
folded): research repo `scratch/design/zenv-design.md` + `scratch/reports/`.

## What it solves

The most common session-loss pattern: an in-flight session is cut off before
finalizing. GIT-IS-DISK agents still lose the chunk between the last push and
the cutoff, because the platform archives `/home/z/my-project` only on GRACEFUL
shutdown (pre-stop repo.tar, tracked-set semantics) — a force-kill archives
nothing. zbackupd closes that gap continuously.

## Architecture (one paragraph)

Double-forked supervisor (PPID→1, survives the toolcall cull; dies on recycle —
by then /home/sync + remotes hold everything ≤60s old) respawns a foreground
loop. Each cycle it discovers sources (`/home/z/my-project` always + any git
repo at depth ≤2 under `/home/z`), and for each runs two independent legs:
**Leg A (primary)** — rsync mirror to `/home/sync/zbackup/<label>/mirror/`
(includes `.git`, so uncommitted AND unpushed work survive); **Leg B
(secondary)** — a sideband git dir (`/home/z/.zenv/repos/<label>.git`,
`git init --bare` + `core.bare false` + `core.worktree <src>`) snapshots the
work tree and pushes branch `auto/<label>/<chat8>-<bootts>` to the private
backup repos (github every change; gitlab every 2nd, WAF retried). A local
signature walk gates cycles (ossfs cost is O(changes), not O(files)).

## The laws (each one is a gate-found P0/P1 — do not "simplify" them away)

1. **Mirror is MERGE-ONLY — never `--delete`.** After a force-kill recycle the
   mirror may hold the ONLY copy of untracked work; the restored tracked-set
   source lacks those files and ANY delete cycle would prune the survivors.
   Monotonic superset is the correct semantics for a last-resort backup
   (growth bounded by the per-chat /home/sync namespace; sideband = exact view).
2. **Branch-per-boot `auto/<label>/<chat8>-<bootts>`.** The sideband lives on
   overlay and is wiped on recycle; a fresh sideband has no common ancestor
   with a flat remote branch → non-FF push rejected forever. Per-boot branches
   also namespace cross-chat runs (backup repos are account-wide; /home/sync
   is per-chat). Never create flat `auto/<label>` refs (permanently blocks
   the hierarchy).
3. **PATs never in URLs, cmdlines, or logs.** Auth via per-host `GIT_ASKPASS`
   helper files (0700, /home/z/.zenv/). Reason: PAT-in-URL push processes
   leak the token into `/proc/*/cmdline`, which observer daemons (and sibling
   agents) capture — this leaked live tokens into research logs once (T9-c B.6).
   API calls use Authorization headers (urllib, never curl).
4. **Zero writes inside sources.** All sideband ops use `--git-dir` pointing
   at the sideband; rsync only reads. Verified byte-level: source `.git`
   checksums identical across cycles. (The ONE sanctioned mutation is zenv's
   idempotent `core.filemode false` on my-project — the mode-noise law.)
5. **Sanitized subprocess env.** Whitelist PATH, absolute `/usr/bin/git`, no
   inherited `GIT_*` (an inherited `GIT_INDEX_FILE` can redirect sideband
   writes INTO a source). Stdio→/dev/null before daemonizing (else the
   toolcall's pipes stay open and the caller hangs).
6. **Privacy precheck before first push** to each remote (repo must be private;
   auto-created private if missing). Stop leg B loudly otherwise.
7. **/home/sync must be fuse** (stat -f %T) before leg A — an unmounted sync
   falls back to the tmpfs bridge and mirrors into RAM on a no-swap 4GiB box.
8. **Errors never crash the loop**; ≥3 consecutive failures + missing PATs
   surface in `/home/sync/zbackup/ALERT.txt` (survives force-kill) and
   `zenv status`.

## Validation battery (2026-10-05, this container)

| # | test | result |
|---|---|---|
| T1 | idempotent start | PASS — 2nd start detects alive, prints status |
| T2 | toolcall survival | PASS — supervisor+foreground alive across 10+ toolcalls, PPID=1 |
| T3 | zero interference | PASS — my-project + testrepo `.git` sha256 identical pre/post cycles |
| T4 | mirror correctness | PASS — new/modified/uncommitted files captured; source-deleted file SURVIVES (law 1) |
| T5 | sideband + pushes | PASS — github push ok (repo auto-created, private verified); gitlab push verified (WAF retried) |
| T6 | secrets hygiene | PASS — 0 token-shaped strings in daemon.log / STATE.json (askpass file is the by-design holder) |
| T7 | degraded (no PAT) | PASS — leg A continues, leg B skips, ALERT.txt + status banner |
| T8 | stale-pid recovery | PASS — kill -9 both, pidfiles stale, `zenv start` recovers |
| T9 | stop paths | PASS — clean when idle; SIGTERM now interrupts in-flight subprocesses |
| T10 | first-cycle cost | 6 min seed (2,363 files / 21.5 MB incl. .git); 36 s delta cycle; unchanged sources skipped by signature gate |

## Operational notes

- First cycle on a big tree is minutes (ossfs per-file latency); it is fully
  async — `zenv start` returns in <1s and never blocks the agent.
- Boot autostart: `zenv start` writes `mini-services/zbackupd/package.json`
  ONLY when `my-project/package.json` exists (start.sh gates mini-services on
  it — verified this round). The file is never committed by zenv; the
  platform's turn-boundary `git add -A` stages it into repo.tar. Without a
  root package.json there is NO boot autostart — the consumer SKILL one-liner
  is the primary path (research repos have no package.json by design).
- Config: `/home/z/.zenv/config.json` (optional) — `interval`, `push` toggles,
  remote repo overrides. Defaults: 60s, zikomolapoutl/zai-sandbox-backup +
  ansgareutychisO/zai-sandbox-backup.
- Restore: `zenv restore` prints the three recipes (mirror copy-back to a
  FRESH dir — never clobbers a live tree; remote branch clone; STATE.json
  orientation). Mirror may contain older extras (merge-only); the sideband
  branch is the exact-tree view per snapshot.
- Known edge: sideband snapshots of NESTED repos record gitlink stubs (empty
  on clone) — the mirror leg carries their real content; acceptable.
- Daemon dies on recycle by design; everything it wrote persists. Next
  session: `zenv start` again (or mini-services autostart on package.json
  projects).
