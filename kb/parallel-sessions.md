# Parallel sessions & shared state (R10-13)

## The hazard: `/home/user_skills` is shared across concurrent chats

The platform runs 2-3 concurrent chats under the same account. Each chat gets
its own container, but `/home/user_skills/` is **per-user, not per-chat** —
all your concurrent sessions share the same directory. This is a huge boon
(skills installed once are available in all sessions) but can cause surprises:

### What can go wrong

1. **Silent overwrites**: session A writes `${ZK_PREFIX}-doppler.env` with a fresh PT;
   session B's older copy is silently replaced. The "fresh paste wins" rule
   means the last writer wins — no atomicity, no session attribution.
2. **Push divergence**: session A and session B both `zsave` to the same
   backup repo. The first push succeeds; the second is rejected (divergence).
   Per rule 3 (never force-push — the "Rules you never break" list; NOT a law),
   resolve with `git pull --rebase origin main` and re-push.
3. **Phantom file writes**: a parallel session's write to `/home/user_skills/`
   appears in *your* container's filesystem — e.g. a timestamp on
   `${ZK_PREFIX}-doppler.env` that you didn't write.
4. **Contentious writes on shared kits**: if two sessions both run `refresh.sh`
   on the same kit, the last writer wins. refresh.sh is copy-then-swap atomic,
   so the worst case is a session running the previous version for one
   command — never a half-written kit.

### What works

- zsave's per-container lock (`/tmp/.zsave.lock`) prevents concurrent zsave
  *within one chat* — but it's useless across chats.
- zsave degrades gracefully on push rejection: snapshot + repo.tar still
  refresh locally; push failure is a warning with the exact recovery hint.
- `git pull --rebase origin main` resolves divergence cleanly in 2 commands.
- The worklog (`/home/z/my-project/worklog.md`) is per-chat (lives in the
  overlay, not `/home/user_skills/`), so concurrent sessions don't clobber
  each other's worklog — but they also can't see each other's entries until
  they push + the other session pulls.

### Mitigations

- **Before destructive ops** (reset --hard, force-install), check if the
  file you're about to overwrite was recently modified by another session:
  `stat /home/user_skills/<file>` — if the mtime is more recent than your
  session start, another session may have written it.
- **For shared credential files** (`${ZK_PREFIX}-doppler.env`, `${ZK_PREFIX}-remote.url`): treat
  them as read-mostly. If you must write, preserve any fields you didn't
  set (e.g. don't blow away `DOPPLER_PT_STORED_AT` if it's already there).
- **For kit upgrades**: running `refresh.sh` is idempotent and atomic
  (copy-then-swap). Concurrent installs are safe — the last one wins, and
  the result is always a complete kit.
- **For backup repo pushes**: if your push is rejected, don't force-push.
  `git pull --rebase origin main` and re-push. Your local commit will
  land on top of the other session's.
