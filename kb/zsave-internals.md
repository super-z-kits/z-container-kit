# zsave internals

Full pipeline with exclude rules. Extracted from SKILL.md v2.3.3; v4 added
steps 5b (zip rebuild) and 7 (worktree prune); v5 adds push auto-recovery,
the lock-wait, and the write-only-on-change credential swap.

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
   no commit — your message argument is not used (noted in the output);
3. `git push origin HEAD:<current-branch>` if an origin remote exists. A
   REJECTED push (non-fast-forward — a parallel session on the same repo
   pushed first) auto-recovers once: `git pull --rebase origin <branch>` +
   retry (v5). Never force-pushes; a rebase conflict degrades to a loud
   by-hand recipe. On success it refreshes the `${ZK_PREFIX}-remote.url`
   credential file — atomically (same-dir tmp + mv) and ONLY when its bytes
   actually changed (static user_skills rule: a steady-state save writes
   user_skills zero times; mode 0600; the `/home/sync/` copy is never
   written — ossfs ignores chmod and left it world-readable at 0777,
   friction #9/#19; refresh.sh removes stale copies). Push stderr is echoed
   with embedded PATs masked;
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
