# Fresh-chat bootstrap (detail)

Paths A/B, credential-file shortcut, branch-rename, env-override testing.
Extracted from SKILL.md v2.3.3.
Fresh-chat bootstrap. The container boots as a bare platform template —
`git init`'d, single "Initial commit", no remote, kit helpers absent from
`scripts/` (if the `/home/user_skills` copy survived,
`bash /home/user_skills/z-container-kit/scripts/zsession` works pre-recovery
and prints this same sequence). Two paths:

**A. Nothing survived** (true cold start — you have a PAT and the kit repo
URL, nothing else; `/home/user_skills` empty):

```
git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit   # any scratch path works
bash /tmp/my-project/kit/scripts/install.sh    # helpers + kit copies everywhere
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git   # the repo backing THIS workspace
git -C /home/z/my-project fetch origin                                   # fetch first (DO NOT reset --hard yet)
# F18 (audit): verify the remote is the one you expect BEFORE destructive reset.
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK the commits
# if the commits match your expectation, proceed; if they look like the WRONG repo's history, STOP and ask the user
git -C /home/z/my-project reset --hard origin/main   # restore the workspace (empty remote? skip)
bash /tmp/my-project/kit/scripts/install.sh    # normalize all copies post-restore (install strips any clone .git — copies stay plain dirs)
bash /home/z/my-project/scripts/zsave "fresh-chat bootstrap checkpoint"
```

The PAT is typed exactly ONCE (the remote-add line) — it is already in the
transcript via the user's message, and every helper masks it from here on
(rotate at github.com/settings/tokens anytime if concerned). The clone itself
needs no PAT — the kit repo is public.

**B. Something survived** (credential file or kit copy in `/home/user_skills`):
recover the remote — every successful `zsave` writes a `${ZK_PREFIX}-remote.url`
credential file to `/home/sync/` and `/home/user_skills/` (holds the origin
URL with embedded PAT — never print its contents; verify remotes with
`git remote` — NAMES ONLY — since `git remote -v` prints the PAT into the
transcript). If one survived, **first run `zsession`** — it now prints the
credential file's masked URL (audit F17) so you can sanity-check it BEFORE
recovery. Then:
`git remote add origin "$(cat /home/user_skills/${ZK_PREFIX}-remote.url)"`.
**Before `git reset --hard`**: `git fetch && git log origin/main --oneline -5`
to verify the commits are the ones you expect — a stale credential file (audit
F16) can silently point at a different repo, and `git reset --hard` would
overwrite your working tree with that repo's content. Consider also
`tar -cf /home/sync/recovery-pre-flight-$(date +%s).tar -C /home/z/my-project .`
to snapshot the current state before any destructive reset (audit F18).
Else the PAT is a user-side secret that cannot be recovered from the
container — ask the user for it (or a fresh token), then
`git remote add origin https://<PAT>@github.com/<u>/<r>.git`
(no repo name is hardcoded in this guide — it travels across projects; the
credential file, when present, already names the right one). Then
`git fetch && git reset --hard origin/main` and reinstall the kit —
`bash z-container-kit/scripts/install.sh`. The reinstall is
LOAD-BEARING: `skills/` is git-ignored, so only install.sh restores
`skills/z-container`. (`git clone` into my-project fails — the boot template
is not empty.)

Notes:
- If your repo's default branch is not `main` (e.g. `master`), rename it once:
  `git branch -m master main && git push origin HEAD:main` — the watchdog's
  `git switch main` fails every toolcall when no `main` exists.
- The helpers honor env overrides for safe scratch testing (never touches the
  real `/home/sync`): see "Testing the helpers safely" near the end.
