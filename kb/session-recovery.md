# Session recovery (fresh chat) — detail

> SCOPE: this module covers **starting a new session on an EXISTING
> project** — a repo that already uses the kit (`.agents/config` present in
> the workspace, or restorable from the backup repo) and whose workspace needs
> recovery. The inline MUST-READ section of SKILL.md carries the short
> version; this module is the deep dive. A project that has NEVER used the
> kit (no config, nothing to restore) is a different flow:
> `kb/new-project.md`.

Paths A/B/C, credential-file shortcut, branch-rename, env-override testing.
Extracted from SKILL.md v2.3.3, reworked for the v3.1 `.agents/` layout and
the v4.0 zero-install model. Fresh-chat recovery. The container boots as a
bare platform template — `git init`'d, single "Initial commit", no remote.
The canonical kit at `/home/user_skills/z-container-kit` usually survived
(per-user PolarFS) — its helpers work pre-recovery (`bash
/home/user_skills/z-container-kit/scripts/zsession` prints this same
sequence). Two-and-a-half paths:

**A. Nothing survived** (true cold start — you have a PAT and the repo URL,
nothing else; no credential file, and the canonical kit at
`/home/user_skills/z-container-kit` is absent — CHECK with `ls` first: when
it survived, you skip the clone below). There is NO install step in v4 —
the project's `.agents/config` is committed, so `reset --hard` brings
identity back with the code:

```
KIT=/home/user_skills/z-container-kit   # canonical per-account package — survives new chats
[ -f "$KIT/scripts/zsave" ] || { git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit; KIT=/tmp/my-project/kit; }   # fallback: public repo, no PAT needed
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git   # the repo backing THIS workspace
git -C /home/z/my-project fetch origin                                   # fetch first (DO NOT reset --hard yet)
# F18 (audit): verify the remote is the one you expect BEFORE destructive reset.
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK the commits
# if the commits match your expectation, proceed; if they look like the WRONG repo's history, STOP and ask the user
git -C /home/z/my-project reset --hard origin/main   # restore the workspace — .agents/config comes back WITH the repo
source /home/z/my-project/.agents/config && echo "$ZK_PREFIX"   # verify identity returned; absent (repo predates the kit) -> bash "$KIT/scripts/zk-init" <name> — in a RECOVERY reuse the prefix from the credential filename (before -remote.url), never invent one
bash "$KIT/scripts/zsave" "fresh-chat bootstrap checkpoint"
```

The PAT is typed exactly ONCE (the remote-add line) — it is already in the
transcript via the user's message, and every helper masks it from here on
(rotate at github.com/settings/tokens anytime if concerned). The kit comes
from the canonical per-account package when it survived; the fallback clone
needs no PAT (the kit repo is public).

**B. Something survived** (credential file or kit copy in `/home/user_skills`):
recover the remote — every successful `zsave` writes a `${ZK_PREFIX}-remote.url`
credential file to `/home/user_skills/` (v3.1+: only there; the pre-v3.1
`/home/sync/` copy is removed by refresh.sh — ossfs ignores chmod and left it
world-readable at 0777). ONE FILE PER PROJECT: on a multi-repo account `ls
/home/user_skills/*-remote.url` lists all of them — pick THIS session's
project by its prefix. It holds the origin URL with embedded PAT — never
print its contents; verify remotes with `git remote` — NAMES ONLY — since
`git remote -v` prints the PAT into the transcript. If one survived, **first
run `zsession`** — it prints the credential file's masked URL (audit F17) so
you can sanity-check it BEFORE recovery. Then:
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
`git fetch && git reset --hard origin/main` — and that is ALL: in v4 there is
no reinstall step (the kit never lived in the repo; `.agents/config` came back
with the reset, and the canonical kit in `/home/user_skills/` serves every
project). A v3-era repo may still carry a `.agents/` kit tree from before —
optional cleanup: `bash /home/user_skills/z-container-kit/scripts/zk-init --migrate-v3`.
(`git clone` into my-project fails — the boot template is not empty.)

**C. No PAT pasted, but the Doppler vault has GH_PAT** (vault-sourced
bootstrap — see secrets-vault-kit "Vault-sourced GitHub bootstrap"): fetch
GH_PAT from the vault via the M7 staging pattern, then use it in the
remote-add step of path A/B exactly as a pasted PAT. The Doppler project
name `agent-bootstrap` in the handover is the hint that this is the intended
flow.

Notes:
- If your repo's default branch is not `main` (e.g. `master`), rename it once:
  `git branch -m master main && git push origin HEAD:main` — the watchdog's
  `git switch main` fails every toolcall when no `main` exists.
- Worklog: after `reset --hard origin/main` the committed `worklog.md`
  re-appears — read its TAIL (`tail -80`) for prior-session context. If it is
  missing, recover it from git history (`git log --all --oneline -- worklog.md`
  then `git show <commit>:worklog.md > worklog.md`) instead of starting blank.
- The helpers honor env overrides for safe scratch testing (never touches the
  real `/home/sync`): see "Testing the helpers safely" in SKILL.md.
