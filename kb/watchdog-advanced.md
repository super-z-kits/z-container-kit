# Watchdog advanced patterns

Recovery patterns, dirty shield, gitdir relocation, worktree orphan recovery.
Extracted from SKILL.md v2.3.3.
Advanced (know they exist, avoid making them habits):
- **Dirty shield [V — but more subtle than v2.3.2 implied]:** an uncommitted
  edit to a file that differs between your branch and main blocks the
  prelude's switch — BUT only if the edit CONFLICTS with main's content for
  that file (e.g. you modified a line that exists on main, or `git rm`'d a
  file main still has). A non-conflicting change (appending to a tracked file,
  adding a new file) does NOT trigger the shield — the watchdog happily
  switches to main and carries your edits over (per the table above). This
  was a real footgun in v2.3.2: an agent reading "make an uncommitted edit
  to block the watchdog" would naturally `echo ... >> file` (an append),
  which is non-conflicting, and the shield would silently fail.

  If you genuinely need to pin a branch across one critical multi-toolcall
  sequence, use `git update-index --skip-worktree <file>` on a tracked file
  (reliably blocks `git switch`) or, better, **use a worktree** (below) —
  worktrees are watchdog-free by construction. Costs of the dirty shield:
  permanent dirty status, broken by the next `zsave` (it commits everything),
  confuses other tooling. Emergency use only.
- **gitdir relocation [V] (persistence hardening, NOT watchdog evasion):**
  ```
  mkdir -p /tmp/my-project/gitdirs
  mv /home/z/my-project/.git /tmp/my-project/gitdirs/main.git
  printf 'gitdir: /tmp/my-project/gitdirs/main.git\n' > /home/z/my-project/.git
  ```
  Puts full git history on PolarFS so it survives even a force-kill (repo.tar is
  only written on graceful shutdown). The watchdog still resets through the
  pointer (verified) — this is about recycle-safety, not branch freedom.
  `zsave` detects the pointer and snapshots the real gitdir too. Rollback:
  `rm /home/z/my-project/.git && mv /tmp/my-project/gitdirs/main.git /home/z/my-project/.git`.
  Boot quirk [S]: start.sh treats `.git`-as-file as "no .git" and runs
  `git init`, which is reinit-safe (it reinitializes the pointed-to repo, no loss).
- **Worktrees for parallel work [V]** (the recipe works for any repo; the
  `/tmp/my-project/...` path is the load-bearing recycle-safe part):
  ```
  git -C /home/z/my-project worktree add /tmp/my-project/worktrees/<name> -b feature/<x>
  ```
  Worktree HEADs are never reset; the directory lives on PolarFS; refs/objects
  live in the main repo's .git. **Push or `zsave` immediately after committing
  in a worktree**: on a force-kill the worktree DIRECTORY survives (PolarFS) but
  its commits live only in the main .git — without a zsave/push they are lost,
  and the worktree comes back orphaned. Verified orphan recovery (a plain
  `git worktree add` over an existing dir fails — `--force` does NOT bypass
  "already exists"):
  ```
  mv <wt> <wt>.orphaned                                  # salvage uncommitted files from it
  git worktree add <wt> <branch>                         # or -b <branch> if the ref was lost too
  # then diff/copy anything you need back from <wt>.orphaned
  ```
  Sub-agents should each get their own worktree.
