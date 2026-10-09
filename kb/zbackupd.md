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
**Leg A (primary)** — delta-copy mirror to `/home/sync/zbackup/<label>/mirror/`
(includes `.git`, so uncommitted AND unpushed work survive). Round-11: map-driven
changed-set `cp --parents -p -f -P` in batches — O(changed) fuse ops; rsync
removed (its per-file protocol timed out >300s at 2.5k files while dd streamed
the same mount at 116MB/s). **Leg B
(secondary)** — a sideband git dir (`/home/z/.zenv/repos/<label>.git`,
`git init --bare` + `core.bare false` + `core.worktree <src>`) snapshots the
work tree and pushes branch `auto/<label>/<chat8>-<bootts>` to the private
backup repos (github every change; gitlab every 2nd, WAF retried). A local
signature walk gates cycles (ossfs cost is O(changes), not O(files)).

## The laws (each one is a gate-found P0/P1 — do not "simplify" them away)

1. **Mirror is MERGE-ONLY — never deletes.** (rsync --delete era ended round-11;
   delta-copy only ever adds/overwrites.) After a force-kill recycle the
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
   at the sideband; cp only reads. Verified byte-level: source `.git`
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

## Round-11 redesign — delta-copy leg A (v6.2.0, zbackupd 1.1.x — 1.1.1 regime + 1.1.2 alignment)

Measured motivation: full-tree rsync to /home/sync TIMED OUT >300s at 2,571
files / 22.5MB (dd streams 116MB/s; cp ~20ms/file; rsync's per-file protocol
~6x cp). The per-cycle cost was O(nfiles) — the wrong shape; the failure
class predicted for large repos, reproduced at only 2.5k files.

- **Map**: `/home/sync/zbackup/<label>.map.json` — `{relpath: [mtime_ns,
  size]}` + `__ck/__si/__v` keys; survives recycles beside the mirror, so the
  first cycle after a boot is near-free. sort_keys dump; never stash into
  STATE.json (it is rewritten every cycle).
- **Hard invariant (T13 P0-1)**: a map entry exists ONLY when the mirror
  provably holds that file. cp rc!=0 splits vanished (benign partial,
  rsync-23 class) from real failures (error + consec + ALERT; the file stays
  OUT of the map and retries on the next cycle that runs).
- **Health (v1.1.1 regime, T13-b P1-4)**: the rotating 8-sample cursor (`__si`)
  AND the daily-reconcile due-clock (`_ck_due`) live in STATE — rewritten every
  cycle — so a busy map no longer starves the reconcile and an idle map no
  longer stalls the rotation; the <=24h damage bound holds in every band.
  Sampling is SIZE ONLY — cp -p and tar restores legitimately diverge on
  mtime ns (T13-b P1-5).
- **One filter list** (T13 P1-4): `walk_filters` is the single source of truth
  for the walked set == mirrored set (upload root-anchored; skills
  my-project only; dev.log root skip; .tar/observer*.log file skips). Leg B
  keeps its own gitignore-syntax excludes (its view is the tracked set).
- **Specials** (P1-2): lstat walk keeps symlinks as links (broken links
  survive; link size = target length); fifo/socket/device are counted and
  logged, never mirrored, never an error (a fifo would hang cp).
- **mtime law (v1.1.2)**: ossfs ignores utimensat — the mirror holds full-ns
  copy-time stamps while tar-restored sources are second-truncated, so
  mirror-side maps can never match the source by mtime. Rebuild maps are
  therefore SIZE-ALIGNED to source values (same size-only identity class
  the sampling uses) — without it every rebuild would be a full re-copy
  pass (measured: 2451 files / ~96s once, then steady-state deltas of
  a few files).
- **0444 files** (P1-3): `cp -f` unlinks-and-retries — git's read-only objects
  must never make the mirror unwritable (silent livelock class).
- **EIO dirs** (v1.1.1, T13-b P1-1 — seen live): dirs that EIO on readdir
  (ossfs x control-char filenames) keep their OLD map slots during a
  rebuild; only readable-and-absent paths are dropped, so manual mirror
  cleanup still converges and an unreadable subtree does not become a
  recurring re-copy loop.
- **Gate fix (found by the acceptance battery, test L)**: STATE round-trips
  tuples to lists — tuple != list made the first cycle of every fresh
  process run unconditionally (also the cause of boot-cycle full passes
  after no-change seams). Comparison normalized list-to-list.
- Per-source isolation (v1.1.1, T13-b P2): one source's exception can no
  longer abort the remaining sources of a cycle.
- Batches are capped by BOTH count (2000) and bytes (48MB) — 2000 large
  files must not blow the 240s per-batch timeout (T13-b P2).
- Cost honesty: a fresh-mirror seed ≈ 40ms/file WALL (2.5k files ≈ 100-110s
  including the rebuild walk — not the naive 20ms/file create estimate);
  steady-state changed cycles are seconds; no-op cycles write nothing for
  the map (STATE.json still updates every cycle).
- Residual failure classes (all pre-existing, none worsened): file<->dir type
  flips (manual rm of the mirror path needed); empty dirs not mirrored
  (file-granularity mirror); concurrent source writes during a cycle can
  tear an individual copy (self-heals next cycle — same class as rsync
  23/24); .git snapshots torn by construction (the sideband branch is the
  consistent view); the map shrinks ONLY via rebuild-from-mirror, which
  reflects actual mirror content (EIO-dir entries stay kept).

## Operational notes

- Hygiene (P1-7, hardened T13-b P1-2/P1-3): research-repo stored URLs are
  PAT-free by law — pushes use GIT_ASKPASS (`~/.zenv/askpass-*.sh`, 0700;
  `zenv start` does NOT create them, the daemon's first cycle does <=60s
  later; `zenv restore` bootstraps eagerly; `scripts/push-research.sh`
  self-bootstraps on a fresh boot). push-research.sh verifies success by
  comparing remote shas to the local rev-parse — a failed push exits 1
  (never a masked rc through a pipe); the gitlab leg retries WAF on both
  the push AND the verification (observed live: landed on attempt 4).
- Cycle costs (round-11, honest): changed cycle ≈ seconds (O(changed) fuse
  ops); the 30-min forced heartbeat ≈ 2-4s (nothing written for the map;
  STATE.json still updates); a fresh-mirror seed ≈ 40ms/file wall incl. the
  rebuild walk (2.5k ≈ 100-110s; 100k ≈ 8-10 min) — resumable, per-batch
  timeouts (240s, capped at 2000 files / 48MB per batch), never a hung 600s.
  Fully async — `zenv start` returns in <1s and never blocks the agent.
- Boot autostart [v6.1, T12-b D1/D2 redesign — seam-3 PROVEN 2026-10-09:
  the committed hook started the daemon 3s after a real container boot, zero
  commands, first cycle green on both remotes]: `zenv autostart` is the ONE
  explicit door — `zenv start` never writes inside the repo (zero-interference
  contract restored). Dual mechanism by workspace type: package.json →
  `mini-services/zbackup/package.json` (boots with the dev server); bare
  workspace → `.zscripts/dev.sh` (start.sh:332 runs it regardless of
  package.json — the elif at :342 only fires when dev.sh is absent). dev.sh is
  SELF-MIGRATING: if package.json appears later, it rm's itself, installs the
  mini-services hook, and still starts the daemon that boot (its bare
  existence would otherwise shadow the dev-server flow — T12-b D1 P0). The
  hook must be committed (repo.tar = tracked set exactly, verified T12-b D3);
  after one graceful recycle it survives even force-kills. Singleton is a real
  kernel flock on /home/z/.zenv/daemon.lock held by the supervisor (T12-b D2 —
  the docstring claim is true since v6.1; before that it was check-then-act).
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
