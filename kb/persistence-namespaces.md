# Persistence namespaces [V — observed across a real 19-day graceful recycle]

Per-chat vs per-user namespaces. Upgraded from inference (v2.3.3) to OBSERVED
2026-09-28: this chat's container was gracefully recycled 2026-09-09→09-28 and
every namespace's survival was verified directly on the restored container.

| Namespace | Backing | Scope | Observed across the real recycle |
|---|---|---|---|
| `/home/z/my-project` | overlay | per-chat | via repo.tar only — byte-identical tracked set; `.git` history+reflog verbatim; modes normalized to 755 by the boot chmod (kb/repo-tar-mechanics.md) |
| `/home/sync` | ossfs (on a tmpfs bridge) | per-chat | yes — repo.tar (mtime = pre-stop second) present in the new container; held exactly what the chat last wrote there |
| `/tmp/my-project` | PolarFS | per-chat | yes — incl. a PLATFORM snapshot of the tracked set (see below) |
| `/home/user_skills` | PolarFS | per-USER (crosses chats) | yes — kit + zip byte-stable across the recycle (and across a parallel chat's mid-session v5.5.0 upgrade on 2026-09-09) |
| github remote | external | universal | the only guaranteed cross-chat layer |

## The /tmp/my-project platform snapshot [V — one observation]

The platform (not your agents) maintains a mirror of my-project's TRACKED set
under `/tmp/my-project/` (PolarFS — force-kill-safe) plus
`.initial_snapshot.json`, an mtime manifest (keys == tracked set exactly). In
the observed recycle it was written at the END of the session's last turn
(05:10:22, before the 05:47 pre-stop) and was NOT updated by the next session's
active turns — i.e. it is a session-idle/recycle-boundary artifact, not
per-turn. At boot-restore the platform has been observed using it for the
project top dir's metadata — once: mode 0700 + the manifest's backward
mtime on a fresh inode (2026-09-28 boot, T5-d). That normalization is NOT
invariant: the 2026-10-05 boot restored the top dir with mode 755 + the
boot mtime instead — do not build anything on top-dir mode/mtime. The
top dir's mtime can also be touched mid-session (entry create+delete) —
the namespace is live, not inert. Trigger timing beyond this is
unverified.

## Reading hazards

- **Read mounts by their TOPMOST layer** (`df -T <path>`, `stat -f`,
  findmnt) — `mount` output lists a tmpfs BRIDGE under `/home/sync` and
  `/tmp/my-project`; the effective filesystems (ossfs, PolarFS) are mounted on
  top. Taking `mount`'s first matching line produced a real "mount drift"
  misobservation in this investigation — there was no drift.
- ossfs mounts show 0777 modes and epoch-0-ish directory dates — do not infer
  permissions or freshness from mode bits there.
- **Bridge tmpfs UUIDs regenerate per boot** (sync bridge: Sep-9
  `rundoss-ffcf909f…`, Oct-5 `rundoss-5b5c8ff8…`) while the backing-store
  content persists — repo.tar continuity proves the same OSS namespace —
  so a bridge ID is NOT a persistence handle [V 2026-10-05]. The PolarFS
  volume ID, in contrast, IS stable: identical across 3 container
  generations.
- Per-chat namespaces (`/home/sync`, `/tmp/my-project`, `upload/`) do not
  follow you into a NEW chat; github is the only guaranteed cross-chat
  persistence (the account default file in `/home/user_skills` can re-wire a
  fresh chat — see the account model in SKILL.md).
