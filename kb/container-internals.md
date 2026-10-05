# Container identity & internals

Forensic detail from `reference.md` (sections 2, 5, 7). Read this when you need
to understand the container's hardware/software stack or storage performance.

## Runtime identity [V]

- Runtime user `z` (uid 1001, gid 1001), no sudo, no root. CapEff = 0
  (bounding set unusable). Seccomp filter mode ON. Containment = Kata +
  read-only cgroup mounts + the bash command filter.
- Debian 13 trixie; host kernel 5.10.134 (Aliyun Linux 8 / LifseaOS via Kata).
- 2 vCPU Xeon Sapphire Rapids (AVX-512 + AMX), 4 GiB RAM hard limit, no swap.
  kata-agent drops page cache under memory pressure — page-cache eviction
  is normal, not a sign of disk problems.

## /start.sh record & image toolchain [V 2026-10-05]

- Image built 2026-09-21 (start.sh mtime 2026-09-21 11:34; /app Sep 21);
  previous image 2026-07-22. `/start.sh` now: 425 lines, 18,206 B,
  sha256 `c36a315314f8e6aa4537c8533202d737e79d1951946d06c19a17225bd00ed5cb`
  (was 421 lines / 17,892 B / `6e4bc962…`).
- The ONLY change vs the previous image: a +4-line `AI_GATEWAY_URL`
  injection in "Z.ai config setup" (lines 287–291). Default unchanged
  (`https://internal-api.z.ai`); comments name `oss_gateway.py`,
  `prestop.py` (first named reference to the pre-stop archiver) and
  `wsmgr` (delivers the env when creating the FC function) — evidence
  of a multi-region gateway rollout. Still ZERO watchdog/git-switch
  code in start.sh (re-verified on the new image).
- Toolchain (drifts with the IMAGE, not per boot): 2026-09-21 image —
  node v24.21.0, uv 0.12.17; git 2.47.3 / bun 1.3.14 / python 3.12.14
  unchanged from the 2026-07-22 image (which had node 24.19.0 /
  uv 0.12.5).

## Bridge environment (observable) [V 2026-10-05]

First direct observation of the bridge process env (wdt9 observer
prelude dumps) — it is inherited into every agent bash environment:

- `UV_CACHE_DIR=/var/cache/uv` — OVERRIDES start.sh's inline
  `/root/.cache/uv`; the service env is set after start.sh's assignment
  (image ENV or app bootstrap).
- Platform vars: `FC_ACCOUNT_ID`, `FC_FUNCTION_NAME` /
  `FC_FUNCTION_HANDLER`, `SIGMA_APP_NAME`, `FC_REGION`,
  `FC_CUSTOM_LISTEN_PORT=81`, `KATA_CONTAINER=true`.
- `STEP_START_TIME` (start.sh's own export) leaks into every agent
  bash env — boot-script env inheritance into all agent processes.

## Mount topology [V]

Each "persistent" path is a tmpfs bridge with a FUSE mount nested inside it
(`findmnt` shows both layers):

- `/tmp/my-project` → PolarFS (JuiceFS-backed) — per-chat subtree (inferred).
- `/home/user_skills` → same PolarFS volume, different subtree — **per-user,
  shared across concurrent chats** (R10-13 — see `kb/parallel-sessions.md`).
- `/home/sync` → ossfs (Alibaba OSS) — per-chat (inferred).
- `/home/z/my-project/upload` → ossfs.
- `/home/official_skills` → ossfs, read-only, the skill zip store.
- Everything else (`/`, `/tmp` (excl. my-project), `/home/z/...`) → overlay,
  ephemeral; root overlay ~10 GB; /dev/shm 64 MB; cgroup ro.

## Storage performance [V]

(see `evidence/EXPERIMENTS.md` E9 for full benchmarks)

- ossfs: ~61 MB/s sequential, ~64 ms per small-file op. Tarball snapshots
  are cheap; live git repos or thousands of tiny files are sluggish.
- PolarFS: ~50 MB/s sequential, ms-level small ops. Behaves like a local FS.
- Practical implication: hot working data belongs on PolarFS
  (`/tmp/my-project/`), snapshots on ossfs (`/home/sync/`).

## Process model [V]

- Per-toolcall cull: the bridge spawns `sh -c su z -c bash` per bash toolcall
  and kills the descendant tree when the call ends. `nohup`/`setsid`/`&` all
  die within one toolcall; only double-fork (reparent to PID 1) survives.
- PID 1 (tini) adopts orphans → double-forked daemons live until recycle.
- Boot-started services (dev server, mini-services) are children of
  start.sh's background subshells → not culled; also not supervised: killing
  them means manual restart via daemonize.py or waiting for a recycle.
- Memory: 4 GiB hard, no swap — daemons that leak will OOM-kill themselves.
