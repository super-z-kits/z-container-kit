# New project setup (rare) — instantiating the kit into a new repo

> SCOPE: this module is about **new repos/projects** — the rare case where a
> workspace has never used this kit (or you are deliberately adopting it in a
> fresh repo). If you are starting a new SESSION in a repo that already has
> `.agents/`, you want the MUST-READ section of SKILL.md (or
> `kb/session-recovery.md` if the workspace needs recovery) instead.

## When you are here

- A brand-new workspace whose backup repo is empty or newly created.
- Adopting the kit into an existing repo that has no `.agents/` yet.
- You will know: `ls /home/z/my-project/.agents` fails, and the workspace is
  either the boot template or your own fresh project.

## The flow

Always name the project explicitly — never rely on auto-discovery for a NEW
repo (discovery can inherit another project's prefix from shared
`/home/user_skills/` artifacts):

```bash
# 1) wire the workspace remote FIRST if you have the PAT (lets install.sh
#    fall back to URL-basename derivation if you forget ZK_PREFIX):
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git

# 2) install with an EXPLICIT prefix (from the read-only package, or a fresh
#    clone of the kit repo):
ZK_PREFIX=<your-project-name> bash /home/user_skills/z-container-kit/scripts/install.sh
#    -> instantiates .agents/, writes .agents/config, creates scripts/ shims,
#       skills/z-container symlink, refreshes the package + portable zip

# 3) commit the kit so it travels with the repo:
git -C /home/z/my-project add .agents/ scripts/
git -C /home/z/my-project commit -m "kit: .agents/ instantiated"

# 4) first save (anchors repo.tar + snapshots + credential file):
bash /home/z/my-project/scripts/zsave "project bootstrap checkpoint"
```

If you forgot `ZK_PREFIX` in step 2, the installer auto-discovers one and
WARNS; a wrongly baked prefix is fixed with:
`rm .agents/config && ZK_PREFIX=<name> bash install.sh` (env-var re-runs
cannot override an existing config — preservation is what makes upgrades safe).

## Choosing ZK_PREFIX

`ZK_PREFIX` names every cross-repo artifact of this project:
`/home/user_skills/${ZK_PREFIX}-remote.url`, `${ZK_PREFIX}-doppler.env`,
`/home/sync/${ZK_PREFIX}-snapshots/`, `${ZK_PREFIX}-state.env`. Rules:

- lowercase `[a-z0-9-]` only, max 24 chars (install.sh enforces this).
- **unique per project** among everything you run under this account — the
  platform runs 2-3 concurrent sessions sharing `/home/user_skills/`, and two
  projects with the same prefix would clobber each other's credential files
  (see `kb/parallel-sessions.md`).
- short and stable: it outlives repo renames (it is NOT derived from the repo
  name after setup — derivation is only the cold-start fallback).

How install.sh picks it (first match wins):
1. existing `.agents/config` (preserved on every upgrade — never re-derived)
2. `ZK_PREFIX` env var passed to install.sh
3. migration from a legacy `/home/user_skills/*-config.env` (exactly one file)
4. durable-artifact scan: `/home/sync/*-state.env`, `/home/sync/*-snapshots/`,
   `/home/user_skills/*-remote.url`, `/home/user_skills/*-doppler.env` — any
   prefix a prior session of ANY of your projects left behind (this is why an
   explicit `ZK_PREFIX` matters on multi-project accounts: the scan cannot
   tell projects apart)
5. derivation from the origin URL basename (`.../zk-stress-test.git` → `zk-stress-test`)
6. interactive prompt (only when a TTY exists — agent toolcalls have none)
7. fail loudly with the exact fix commands

## Why config lives in .agents/ (design notes)

v2.x kept ZK_PREFIX in `/home/user_skills/*-config.env` — per-user state for a
per-project setting. That caused: collision ambiguity when several projects
ran in parallel (glob finds N files, scripts refuse to pick), `.env`-clobbering
(the platform rewrites `.env` every boot, so an earlier design that stored the
prefix there lost it), and multi-tier `resolve-prefix.sh` globbing as
mitigation. v3.1 moves the config INTO the repo (`.agents/config`,
git-tracked): it survives boot (only `.env` is rewritten), travels with the
repo through repo.tar and GitHub, and each parallel session resolves its own
project's prefix from its own working tree. The legacy config.env file is
still honored (migration tier) but no longer required.

`scripts/` shims exist so the documented commands
(`bash /home/z/my-project/scripts/zsave …`) keep working; they exec into
`.agents/scripts/` where each helper sources `../config`. Python helpers are
real copies (the documented `python3 scripts/daemonize.py` invocation must
keep working), and `resolve-prefix.sh` is a real copy because it is sourced,
never exec'd.

## First-save checklist

- [ ] `.agents/config` contains your intended `ZK_PREFIX`
- [ ] `git status` shows `.agents/` and `scripts/` tracked (not ignored)
- [ ] first zsave ran and pushed (github is the only guaranteed cross-chat
      persistence layer)
- [ ] `/home/user_skills/${ZK_PREFIX}-remote.url` exists (mode 0600) — this is
      what saves the next fresh chat
- [ ] if you use Doppler: `zdoppler-smoke` passes and the PT file
      `/home/user_skills/${ZK_PREFIX}-doppler.env` is written (see
      secrets-vault-kit)
