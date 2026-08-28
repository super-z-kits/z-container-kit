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
