# Session start & recovery — detail (one flow)

> SCOPE: the deep dive behind the MUST-READ section of SKILL.md. Session
> start is ONE flow now: ensure identity → ensure remote → restore what
> exists → save. "Recovery" and "first-time setup" are the same checklist —
> a brand-new repo simply has nothing to restore. v5.1 removed the old
> per-project credential files (`${ZK_PREFIX}-remote.url`): the origin URL
> travels INSIDE the repo (`.git/config` in repo.tar, snapshots, and
> github), and fresh chats get the remote from the **account default** or
> from the user.

## Where the remote comes from (in order)

1. **It is already there.** A same-chat recycle/force-kill restores
   `.git/config` (with the PAT-embedded origin) from repo.tar — nothing to
   wire. Check: `git remote` (names only).
2. **The account default** (`/home/user_skills/zk-default.env`, 0600, set
   once by `zk-init --set-default`). Single-project accounts: run
   `bash /home/user_skills/z-container-kit/scripts/zk-init --default` —
   it writes the config, wires origin, fetches, and REVEALS the project
   (masked origin/main log). Guards: refuses if the repo's own
   `.agents/config` names a different prefix, or if a wired origin differs
   from the default remote — the repo always wins.
3. **The Doppler vault** holds GH_PAT (secrets-vault-kit "Vault-sourced
   GitHub bootstrap" — its SKILL.md has the exact recipe).
4. **The user.** Ask for the PAT + repo, then
   `git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git`.
   Single-project account? Offer to make it the default afterwards:
   `zk-init --set-default`.

## The restore block (run after the remote is wired)

```
git -C /home/z/my-project fetch origin                                   # fetch first (DO NOT reset yet)
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's#(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+#\1***#g'   # SANITY CHECK (F18)
git -C /home/z/my-project reset --hard origin/main   # your commits? proceed. Empty/new remote? skip. WRONG repo? STOP.
source /home/z/my-project/.agents/config && echo "$ZK_PREFIX"           # identity came back with the repo
tail -80 /home/z/my-project/worklog.md                                   # prior-session context
bash /home/user_skills/z-container-kit/scripts/zsave "fresh-chat bootstrap checkpoint"
```

The sanity-check log line is the whole game: it is the last gate before a
destructive reset. A wrong remote (mis-typed default, wrong project on a
multi-repo account) shows a stranger's commits — STOP and re-wire instead
of resetting. Consider also a pre-flight snapshot before the reset (audit
F18): `tar -cf /home/sync/recovery-pre-flight-$(date +%s).tar -C
/home/z/my-project .` — the kit does not do this automatically; it is the
agent's job before destructive ops.

Notes:
- Identity on a repo that predates the kit (config absent after reset):
  `bash /home/user_skills/z-container-kit/scripts/zk-init <name>` — in a
  RECOVERY reuse the project's existing name (worklog/git history say it),
  never invent one. Fix a wrong prefix with `zk-init <name> --force`.
- Default branch not `main` (e.g. `master`)? Rename once:
  `git branch -m master main && git push origin HEAD:main` — the watchdog's
  `git switch main` fails every toolcall while no `main` exists.
- Worklog: after `reset --hard origin/main` the committed `worklog.md`
  re-appears — read its TAIL (`tail -80`, or Read with offset; the file can
  be 30+ KB). If missing, recover from git history (`git log --all
  --oneline -- worklog.md` then `git show <commit>:worklog.md > worklog.md`)
  before starting blank.
- The kit itself: canonical package at `/home/user_skills/z-container-kit`
  (per-user PolarFS — usually survived). Truly bare account: `git clone
  https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit`
  (public, no PAT needed) and run helpers from the clone.
- (`git clone` directly into my-project fails — the boot template is not
  empty.)
- v3-era leftovers (a `.agents/` kit tree, `scripts/` shims, a
  `skills/z-container` symlink): helpers never read them; remove by hand
  and zsave the removal if you want a clean tree.

## First time on a brand-new repo

The same flow with nothing to restore: `zk-init <name>` (identity — the
ONLY per-project artifact), `git add .agents/ && git commit`, wire the
remote (user PAT or Doppler), `zsave "project bootstrap checkpoint"`.
Single-project account: `zk-init --set-default` afterwards so future fresh
chats are zero-input. `ZK_PREFIX` rules: lowercase `[a-z0-9-]`, ≤24 chars,
unique among the account's parallel projects.

## Git identity: fetching the exact noreply email (law 11)

zsession flags the boot placeholder (`Z User <z@container>`) and prints the
fix shape. To get the exact `<id>+<username>@users.noreply.github.com`
without visiting GitHub settings, ask the API with the same PAT you wired
into origin (never echoes the token):

```bash
GH_PAT=$(sed -E 's#https://([^@]+)@github.com/.*/.git#\1#' <<<"$(git config --get remote.origin.url)")
curl -sS -H "Authorization: Bearer $GH_PAT" https://api.github.com/user \
  | jq -r '"git config user.name \(.login) && git config user.email \(.id)+\(.login)@users.noreply.github.com"'
```

Run the printed command verbatim. A repo with an established working
identity (check `git log --format='%an <%ae>' -3`) can simply reuse it —
the noreply form matters only where Vercel deploys read the commit author.

## Why identity is configuration, never discovery

`ZK_PREFIX` resolves from exactly TWO sources (resolve-prefix.sh):
`ZK_PREFIX` env > `$PROJ/.agents/config`. Nothing else — no artifact
scanning, no URL guessing, and the account default is NOT consulted. Shared
`/home/user_skills` and `/home/sync` files are per-USER evidence, never
identity — auto-adopting from them is how the v3 "zk-onboard-test"
cross-contamination happened. A missing config is a one-command fix
(`zk-init <name>`); a wrong silent guess is data loss. v2.x kept the prefix
in per-user `*-config.env` files (collision ambiguity, silent adoption);
v3.1 moved it INTO the repo; v4 made it the only per-project artifact; the
account default (v5.1) is the deliberate exception for REMOTES only — and
it is applied only through the explicit, guarded `--default` flag.

## Env-override testing

The helpers honor `ZK_PROJ` / `ZK_SYNC` / `ZK_USK` overrides for safe
scratch testing (never touches the real `/home/sync` or `/home/user_skills`):
see `kb/testing-helpers.md` and the overrides section of SKILL.md.
