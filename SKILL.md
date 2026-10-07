---
name: z-container-kit
metadata:
  author: z + Super Z forensic session
  version: "6.1.0"
  verified: "2026-10-07 (v6.1.0: cross-recycle daemon seam validated live — cold start 0.4s, both remotes green first cycle, old+new sideband branches coexist; zenv autostart sticky boot hooks with self-migrating dev.sh; kernel flock singleton; cross-chat restore fallback; Write/Edit/Read display-redaction matrix — disk always intact. v6.0.0: consumer/research split + zbackupd daemon, battery T1-T10, laws E18-E21)"
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
