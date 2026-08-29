# Parallel sessions & multi-track safety (v5)

## The hazard: `/home/user_skills` is shared, and it is not git

The platform runs 2-3 concurrent chats under the same account. Each chat gets
its own container (own overlay, own `/home/sync`, own `/tmp`), but
`/home/user_skills/` is **per-user** — every concurrent session sees the same
bytes. And it has **no git**: no conflict detection, no merge, no rebase. A
write race there cannot be resolved, only prevented.

Sessions may also work on the **same repo** at the same time (two chats, one
backup repo). That race surface is different — it has git.

## The v5 answer: static user-skills + git as the conflict handler

**Rule 1 — user_skills is read-only for sessions.** Steady-state saves touch
it ZERO times. The only sanctioned writes, each zero-collision by
construction:

1. **Kit install/refresh** (`refresh.sh`) — a conscious account-level
   operation: per-run staging + rename-aside swap (two atomic directory
   renames). Concurrent refresh + read worst case: one racing command errors
   once and works on re-run — never a torn kit. refresh.sh also owns the
   account-level housekeeping (stale-artifact cleanup, backup-dir prune).
   The old zcleanup-backups script was a FOURTH unsanctioned writer and was
   deleted (its prune folded into refresh.sh).
2. **Portable kit zip rebuild** — only when the platform consumed it, same
   bytes from a static source, atomic tmp+mv. Concurrent rebuilds are
   harmless (both produce identical bytes).
3. **Credential files** (`${ZK_PREFIX}-remote.url`, `${ZK_PREFIX}-doppler.env`)
   — keyed by the project's unique prefix (different repos never share a
   filename); written atomically (same-dir tmp + mv — a parallel reader sees
   old-or-new, never partial); and only when the bytes actually changed
   (zsave skips the write entirely on identical content). For same-repo
   parallel sessions the accepted semantic is last-writer-wins: every writer
   just pushed to the SAME repo, so whichever bytes survive are a URL that
   last worked. Doppler env files additionally honor **fresher-wins**: never
   overwrite a file whose `DOPPLER_PT_STORED_AT` timestamp is newer than
   yours (an older chat's stale PT must not clobber a fresh rotation).

Anything else a session might want to persist belongs in the REPO (git-tracked
— mergeable) or in per-chat storage (`/home/sync`, `/tmp/my-project` —
container-local, no cross-session race). Per-repo customization lives in
`.agents/config` inside the repo, never in user_skills.

**Rule 2 — same-repo divergence is git's problem, and git solves it.**
Session A and session B both zsave to one remote:

- First push wins; the second is rejected (non-fast-forward).
- zsave detects the rejection and auto-recovers ONCE:
  `git pull --rebase origin <branch>` then retry the push. Histories
  interleave cleanly; nothing is lost; no agent intervention needed.
- Only a same-line conflict (both sessions edited the same file) falls back
  to a human decision — and git names the exact file and hunks.
- **Never force-push** (rule 3). Force-push overwrites the only good copy
  with your possibly-broken local state — the one deadly move in the whole
  flow.

**Rule 3 — in-container concurrency serializes; it does not fail.** zsave
flocks `/tmp/.zsave.lock` with a WAIT (default 180s): a second concurrent
save queues silently and runs after the first. Exit 75 (nothing changed)
only fires after a full timeout. Sub-agents still leave saves to the
coordinating agent — one writer avoids interleaving with its git work; it is
an ownership convention, not a corruption guard.

## What used to go wrong (pre-v5) — and where it went

- **Every-push credential rewrite** wrote `user_skills/<prefix>-remote.url`
  unconditionally and non-atomically — mtime churn and partial-read windows
  for parallel sessions. → Now: write-only-on-change + atomic swap.
- **"Fresh paste wins" PT clobber**: a session holding an older PT could
  overwrite a newer one; writes were `cat > file` (non-atomic). → Now:
  fresher-wins timestamp guard + atomic swap (secrets-vault-kit recipe).
- **Push rejection handed the recovery to the agent** (read the hint, run
  pull --rebase, re-save — three extra steps of tax). → Now: auto-recovery.
- **Lock contention exited 75** and demanded retry choreography. → Now: wait.

## Practical notes

- A parallel session's write to user_skills can appear in *your* container's
  filesystem mid-session (phantom mtimes). With the static rule the only
  files this can happen to are the sanctioned ones — expected, harmless.
- Before a CONSCIOUS destructive op (e.g. re-running refresh.sh, deleting a
  stale credential), `stat` the file: an mtime newer than your session start
  means a parallel session touched it — look before you leap.
- The worklog is per-container (repo-dir overlay). Concurrent sessions merge
  their worklogs the same way they merge code: commit, push, and let git
  rebase one on top of the other (zsave does this automatically on push).
