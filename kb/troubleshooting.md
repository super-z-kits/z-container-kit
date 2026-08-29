# Troubleshooting trees

6 named scenarios: project reset, files vanished, zsave push failed, dirty tree
after boot, dev server dead, /home/sync slow.
Extracted from SKILL.md v2.3.3.
## Troubleshooting trees

**"The project reset itself"**
1. `bash /home/z/my-project/scripts/zsession` — recycle? remote? worktrees?
2. `git -C /home/z/my-project log --all --oneline` — refs still there? Nothing
   committed is ever lost. `git fsck --lost-found` for dangling commits.
3. `/home/sync/repo.tar` + `/home/sync/${ZK_PREFIX}-snapshots/` — if the tree is stale,
   follow "Restore procedures" B above (never extract over a live .git).
4. Remote is truth: `git fetch && git log origin/main --oneline -3`.

**"My files vanished mid-session"** — watchdog branch-switch (table above):
`git switch <branch>` back; commits are safe; then zsave. If you were on a
branch in my-project, move that work to a worktree first (law 5).

**"zsave push failed"** — PAT expired/revoked (403) / repo renamed / diverged
history. Diverged: `git pull --rebase origin main && bash scripts/zsave`.
Bad PAT: rotate at github.com/settings/tokens, then
`git remote set-url origin https://<NEWPAT>@github.com/<u>/<r>.git` and zsave
again (script output is PAT-masked either way). Repo renamed (pushes keep
working via GitHub redirects, but keep it clean): `git remote set-url origin
https://<PAT>@github.com/<u>/<NEW-NAME>.git` — the next successful zsave
refreshes both `${ZK_PREFIX}-remote.url` credential files automatically.

**"Dirty tree right after boot — mode-only changes (0644 → 0755)"** — the
platform's repo.tar extraction does not preserve file modes; every file
lands executable and git flags many files "modified" with zero content
diff (`git diff` empty). Fix once per workspace (the setting persists via
repo.tar): `git -C /home/z/my-project config core.fileMode false`. Nothing
was actually changed — status goes clean immediately.

**"Dev server dead"** — `ss -tln | grep 3000`; if gone, relaunch via
daemonize.py (recipe above). If :3000 is up but preview 5xx's, check dev.log.

**"/home/sync writes are slow"** — ossfs is ~60 MB/s for big sequential writes
but ~64 ms per small-file op [V]. Snapshot tarballs are fine; live git repos or
thousands of tiny files there are not. Use `/tmp/my-project` for hot data.
