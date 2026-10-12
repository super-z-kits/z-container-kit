---
name: z-container-kit
metadata:
  author: z + Super Z forensic session
  version: "6.5.0"
  verified: "2026-10-12 (v6.5.0: credential-channel architecture — externally-rotatable session-separated PAT file on the account-shared disk (zk-secrets-<chat8>.env, PolarFS, 0600) now SHADOWS the container-locked sync copy; auto-adoption (never overwrites); status shows winning channel + last-4 fingerprint + age + the exact rotation path; sticky rotate-me alerts; quiet-tree push retry; the full external rotation drill live-proven E2E (poison-shadow / rotate-fail-alert / external-fix-autorecover); battery 93/93. v6.4.0: boot-tax elimination + copy integrity — second-granularity map compare (restore ns-zeroing re-copied 57% of tree, now ~0), phantom-copy fallback removed (failed batches retry next cycle), error cycles never advance the change-gate, health.log truth regime (ran/skip/defer/ORPHAN/EXC), map-stick canary, restore path live-proven E2E, package.json field trial passed; battery 75/75. v6.3.0: survival hardening — boot-race defer (per-boot budget), worker re-supervision + stop-flag + reparent check, orphan telemetry for vanished outside repos, status() error-string guards, durable health.log on /home/sync, versioned log lines, zenv on PATH via boot hook; battery 58/58 incl. kill-mid-run + stop-resurrection regression tests. v6.2.0: delta-copy leg A — map-driven changed-set cp, rsync removed after a >300s timeout at 2.5k files; acceptance battery caught the sig tuple/list gate bug; PAT-free stored URLs + self-bootstrapping askpass. v6.1.0: cross-recycle daemon seam validated live — cold start 0.4s, both remotes green first cycle, old+new sideband branches coexist; zenv autostart sticky boot hooks with self-migrating dev.sh; kernel flock singleton; cross-chat restore fallback; Write/Edit/Read display-redaction matrix — disk always intact. v6.0.0: consumer/research split + zbackupd daemon, battery T1-T10, laws E18-E21)"
  description: >
    Consumer router: the ONE command (zenv start — background backup daemon
    mirroring all work trees to /home/sync + private backup repos every 60s),
    the five laws, the irreversible dangers. Working agents read consumer/SKILL.md;
    kit researchers read RESEARCH.md + kb/.
---

# z-container-kit — SKILL (v6)

You almost only need one thing:

```bash
bash /home/user_skills/z-container-kit/consumer/zenv start
```

→ background backup daemon: mirrors all your work trees (uncommitted +
unpushed included) to /home/sync every 60s and pushes snapshot branches to
your private github + gitlab backup repos. Zero interference with your git.
Idempotent; `zenv status` to check; `zenv pat <gh> [gl]` to re-stamp tokens;
`zenv restore` after a cutoff.

## Read next (by role)

- **Working agent (95% of you):** `consumer/SKILL.md` — the five laws
  (stay-on-main, mode-noise, filtered bash output, lying token displays,
  git-is-disk) + the irreversible-danger list (never type `caddy` in command
  position; never scan-loop ports 12600/19001/19005/19006). 2 minutes.
- **Kit research/maintenance agent:** `RESEARCH.md` — full verified mechanics
  (watchdog forensics, persistence namespaces, platform internals), then `kb/`
  for deep topics and `evidence/EXPERIMENTS.md` for the experiment log.
