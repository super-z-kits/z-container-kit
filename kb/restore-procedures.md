# Restore procedures

Full A/B/C/D recovery flow. Extracted from SKILL.md v2.3.3.
## Restore procedures (when things went wrong)

Golden rule: **never extract a snapshot tar over a live `.git`** — the
archive's `.git` (including the reflog) would overwrite your newer history.
Always recover at the ref level first; tar-restore is the last resort.

**A. "Project reset / files missing" — ref level first:**
1. `git -C /home/z/my-project log --all --oneline` (commits live on refs)
2. `git -C /home/z/my-project reflog -15` and `git fsck --lost-found`
3. Restore the view: `git switch main` (or the right branch/worktree).

**B. Snapshot tar-restore** (tree is garbage/template and history is expendable
or already pushed). Paths below are the live ones — for a scratch rehearsal,
substitute your scratch project + `ZK_SYNC` scratch dir and run the same steps:
1. Quarantine the old repo state:
   `mv /home/z/my-project/.git /tmp/my-project/.git.quarantine-$$`
2. Extract the newest snapshot (error if none — fall back to C):
   `LATEST=$(ls -t /home/sync/${ZK_PREFIX}-snapshots/proj-*.tar 2>/dev/null | head -1); [ -n "$LATEST" ] && tar xf "$LATEST" -C /home/z/my-project`
3. Gitdir relocation variant: the timestamp-matched pair is
   `proj-<ts>.tar` <-> `gitdir-<ts>.tar`. **Only restore `gitdir-<ts>.tar` if
   `/tmp/my-project/gitdirs/` was actually lost** — if the surviving gitdir is
   NEWER than the tar (it usually is: it lives on PolarFS and kept receiving
   commits), keep the surviving gitdir and restore only the tree/pointer file.
4. If the project has package.json: `cd /home/z/my-project && bun install`
   (node_modules is excluded from tars)
5. Review `git status`: untracked files that appeared during the disaster
   SURVIVE the tar overlay — delete true leftovers before the next zsave or
   they will be committed. Phantom "modifications" are stale stat-cache —
   `git update-index --refresh` clears them (cosmetic).
6. Re-anchor: `bash /home/z/my-project/scripts/zsave "post-restore checkpoint"`
   so repo.tar reflects the restored state.

**C. Fresh chat / empty /home/sync:** `git clone` into my-project fails (the
boot template is not empty). Recover the URL from a surviving `${ZK_PREFIX}-remote.url`
credential file (`git remote add origin "$(cat /home/user_skills/${ZK_PREFIX}-remote.url)"`),
else ask the user for the PAT and re-add by hand (verify with `git remote` —
names only, never `git remote -v`); then `git fetch && git reset --hard
origin/main` — in v4 that is the whole recovery (`.agents/config` comes back
with the reset; no install step exists), then
`bash /home/user_skills/z-container-kit/scripts/zsave "fresh-chat recovery checkpoint"`
to re-anchor repo.tar, snapshots, and the credential files.

**D. Stuck repo states:**
- mid-rebase/merge after a failed pull: `git rebase --abort` /
  `git merge --abort`, then zsave.
- `error: index.lock exists` after an interrupted git op (e.g. force-kill
  during the platform's pre-stop commit): confirm no git is running
  (`ps aux | grep git`), then `rm -f /home/z/my-project/.git/index.lock`.
