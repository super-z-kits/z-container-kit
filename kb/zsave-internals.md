# zsave internals

Full pipeline with exclude rules. v4 added the zip rebuild and worktree
prune; v5 added push auto-recovery and the lock-wait; v5.1 DELETED the
credential-file step (the origin URL travels inside the repo — `.git/config`
in repo.tar/snapshots/github — so a save has nothing to write to
/home/user_skills).

## Saving work — zsave

```
bash /home/user_skills/z-container-kit/scripts/zsave "<what you just finished>"
```

Does, in order **[V]** (each step degrades gracefully; the exit code is nonzero
if commit/snapshot/repo.tar fail — a push failure is a warning):
0. acquire the per-container lock `/tmp/.zsave.lock` — **waiting** up to
   `ZK_LOCK_WAIT` (default 180s) if another zsave holds it (v5: concurrent
   saves serialize; exit 75 only after a full timeout, with nothing changed);
1. maintain `.git/info/exclude` — keeps repo-ROOT `upload/`, `dev.log`,
   `tool-results/` (anchored `/upload/` etc., so nested source dirs like
   `app/api/upload/` stay tracked) plus `.next/`/`.turbo/` at any depth out
   of git (untracked only; the platform's .gitignore auto-heal does not
   touch `.git/info/exclude`); untracked NESTED git repos (scratch clones)
   are auto-excluded too — they would otherwise land as broken gitlink
   entries (already-tracked ones are reported with the fix command);
2. `git add -A` + commit (yes, including `.env` — law 9). A clean tree means
   no content commit — if you passed a message, an EMPTY checkpoint commit
   records it instead (F19) so the message is never silently discarded;
3. `git push origin HEAD:<current-branch>` if an origin remote exists. A
   REJECTED push (non-fast-forward — a parallel session on the same repo
   pushed first) auto-recovers once: `git pull --rebase origin <branch>` +
   retry (v5). Never force-pushes; a rebase conflict degrades to a loud
   by-hand recipe. Push stderr is echoed with embedded PATs masked. (v5.1:
   no credential-file write happens here at all — the remote lives in
   `.git/config` and travels with the repo; a fresh chat re-wires it from
   the account default or the user.)
4. tar snapshot to `/home/sync/${ZK_PREFIX}-snapshots/proj-<ts>.tar` (keep last 5).
   Excluded: `node_modules/`, `.next/`, `.turbo/` at ANY depth, `upload/`,
   `dev.log`, and OFFICIAL skills (boot re-extracts them); CUSTOM skills
   are kept (v4: the kit no longer lives in the repo, so this is only
   user-added skills);
5. refresh `/home/sync/repo.tar` — the artifact the platform restores at
   boot — so a force-killed container comes back at your latest zsave, not a
   stale one;
6. write `/home/sync/${ZK_PREFIX}-state.env` atomically (recycle detector for zsession);
7. v4 housekeeping (LIVE only): rebuild `/home/user_skills/z-container.zip`
   if the platform consumed it at a sub-agent spawn (sanctioned write #2 —
   idempotent, atomic, zero-collision), then prune stale git worktree entries.

Run it: after every micro-milestone — any good moment: a file finished, a
step verified, a bug fixed — before risky operations, and at least every ~10
toolcalls in long sessions. It is cheap (a few seconds). Waiting for a
"big enough" moment is how work gets lost — the grand final save never
happens.

Concurrency: zsave takes a per-container lock (`/tmp/.zsave.lock`) and WAITS
on it (default 180s) — concurrent saves serialize transparently. Sub-agents
leave saves to the coordinating agent (one writer, no interleaving with its
git work — an ownership convention). Pushing from a worktree is always fine.
