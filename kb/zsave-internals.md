# zsave internals

Full 6-step pipeline with exclude rules. Extracted from SKILL.md v2.3.3.
## Saving work — zsave

```
bash /home/z/my-project/scripts/zsave "milestone message"
```

Does, in order **[V]** (each step degrades gracefully; the exit code is nonzero
if commit/snapshot/repo.tar fail — a push failure is a warning):
1. maintain `.git/info/exclude` — keeps repo-ROOT `upload/`, `dev.log`,
   `tool-results/` (anchored `/upload/` etc., so nested source dirs like
   `app/api/upload/` stay tracked) plus `.next/`/`.turbo/` at any depth out
   of git (untracked only; the platform's .gitignore auto-heal does not
   touch `.git/info/exclude`); untracked NESTED git repos (scratch clones)
   are auto-excluded too — they would otherwise land as broken gitlink
   entries (already-tracked ones are reported with the fix command);
2. `git add -A` + commit (yes, including `.env` — law 9). A clean tree means
   no commit — your message argument is not used (noted in the output);
3. `git push origin HEAD:<current-branch>` if an origin remote exists — on
   success it also refreshes the `${ZK_PREFIX}-remote.url` credential file
   (`/home/user_skills/` only, mode 0600 — v3.1: the `/home/sync/` copy is no
   longer written; ossfs ignores chmod and left it world-readable at 0777,
   friction #9/#19; install.sh removes stale copies) for fresh-chat remote
   recovery; push
   stderr is echoed with embedded PATs masked;
4. tar snapshot to `/home/sync/${ZK_PREFIX}-snapshots/proj-<ts>.tar` (keep last 5).
   Excluded: `node_modules/`, `.next/`, `.turbo/` at ANY depth, `upload/`,
   `dev.log`, and OFFICIAL skills (boot re-extracts them); CUSTOM skills
   (including this kit) are kept;
5. refresh `/home/sync/repo.tar` — the artifact the platform restores at
   boot — so a force-killed container comes back at your latest zsave, not a
   stale one;
6. write `/home/sync/${ZK_PREFIX}-state.env` atomically (recycle detector for zsession).

Run it: after every meaningful milestone, before risky operations, and at least
every ~10 toolcalls in long sessions. It is cheap (a few seconds).

Concurrency: zsave takes a per-container lock (`/tmp/.zsave.lock`). **Sub-agents
must NOT run zsave** — the coordinating agent owns saves (two concurrent runs
would corrupt repo.tar). Pushing from a worktree is always fine.
