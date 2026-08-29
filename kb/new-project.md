# New project setup — instantiating the kit into a repo that has never used it

> SCOPE: you are here when the project has NEVER used the kit — no
> `.agents/config` in the workspace and no backup-repo history carrying one.
> What TRIGGERS this flow: a brand-new workspace whose backup repo is empty or
> newly created, or deliberately adopting the kit into an existing repo that
> predates it. What does NOT trigger it: starting a new session on a project
> that already has the kit — that project's setup is already done; RESTORE it
> instead (SKILL.md MUST-READ / `kb/session-recovery.md`).

## When you are here

- A brand-new workspace whose backup repo is empty or newly created.
- Adopting the kit into an existing repo that has no `.agents/config` yet.
- You will know: `ls /home/z/my-project/.agents/config` fails, and the
  workspace is either the boot template or your own fresh project.

## The flow

v4 is ZERO-INSTALL: setup means writing ONE line — the project's identity
file (`.agents/config`, the .env pattern). No kit copy, no shims, no symlink
ever enters the project:

```bash
# 1) (optional but recommended) wire the remote first — identity derivation
#    and credential persistence both key off the origin URL:
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git

# 2) initialize the project's identity (the ONLY per-project artifact):
bash /home/user_skills/z-container-kit/scripts/zk-init <your-project-name>
#    -> writes .agents/config (ZK_PREFIX=<name>) — nothing else

# 3) commit the identity so it travels with the repo:
git -C /home/z/my-project add .agents/
git -C /home/z/my-project commit -m "kit: project identity (.agents/config)"

# 4) first save (anchors repo.tar + snapshots + credential file):
bash /home/user_skills/z-container-kit/scripts/zsave "project bootstrap checkpoint"
```

If you picked the wrong prefix, fix it deliberately:
`bash /home/user_skills/z-container-kit/scripts/zk-init <name> --force`
(zk-init refuses to overwrite an existing config without --force — that is
the guard against accidentally re-identifying a live project).

Inspect the current state any time: `zk-init --status` (config, v3 leftovers,
canonical kit version). Repos that used v3.x may still carry a `.agents/`
kit tree + `scripts/` shims + `skills/z-container` symlink — v4 helpers never
read them; strip with `zk-init --migrate-v3` and zsave the removal.

## Choosing ZK_PREFIX

`ZK_PREFIX` names every cross-repo artifact of this project:
`/home/user_skills/${ZK_PREFIX}-remote.url`, `${ZK_PREFIX}-doppler.env`,
`/home/sync/${ZK_PREFIX}-snapshots/`, `${ZK_PREFIX}-state.env`. Rules:

- lowercase `[a-z0-9-]` only, max 24 chars (zk-init enforces this).
- **unique per project** among everything you run under this account — the
  platform runs 2-3 concurrent sessions sharing `/home/user_skills/`, and two
  projects with the same prefix would clobber each other's credential files
  (see `kb/parallel-sessions.md`).
- short and stable: it outlives repo renames (it is NOT derived from the repo
  name after setup — derivation is only the cold-start fallback).

## How helpers resolve the prefix (v4 order)

1. `ZK_PREFIX` env var (explicit override — tests, one-off commands)
2. `$PROJ/.agents/config` — the canonical identity (git-tracked; what
   `zk-init` writes; what survives boot, repo.tar, and `reset --hard`)
3. exactly one legacy `/home/user_skills/*-config.env` (v2-era; used with a
   migration hint)
4. origin-URL basename — ONLY if unambiguous: no prefix artifacts exist
   anywhere (true first project), or the existing artifacts MATCH the derived
   name. If other prefixes exist, resolution FAILS listing them —
   shared artifacts are per-USER evidence, never identity. This is the
   multi-repo protection: a stale test project's prefix can never leak into
   a new project's session (the "zk-onboard-test" lesson).
5. loud failure with the exact fix commands

## Why config lives in .agents/ (design notes)

v2.x kept ZK_PREFIX in `/home/user_skills/*-config.env` — per-user state for a
per-project setting. That caused: collision ambiguity when several projects
ran in parallel (glob finds N files, scripts refuse to pick), `.env`-clobbering
(the platform rewrites `.env` every boot, so an earlier design that stored the
prefix there lost it), and glob-scan "self-healing" that adopted whatever
prefix it found first — silently inheriting ANOTHER project's identity on
multi-repo accounts. v3.1 moved the config INTO the repo (`.agents/config`,
git-tracked) — right call. v4.0 completes it: the config is ALL the project
carries (v3 also instantiated a whole kit copy per repo — the staleness and
bug surface that v4 removes), and helpers are location-agnostic, reading
identity from the project the way the whole world reads `.env`.

## First-save checklist

- [ ] `.agents/config` contains your intended `ZK_PREFIX`
- [ ] `git status` shows `.agents/` tracked (nothing else kit-related exists)
- [ ] first zsave ran and pushed (github is the only guaranteed cross-chat
      persistence layer)
- [ ] `/home/user_skills/${ZK_PREFIX}-remote.url` exists (mode 0600) — this is
      what saves the next fresh chat
- [ ] if you use Doppler: `zdoppler-smoke` passes and the PT file
      `/home/user_skills/${ZK_PREFIX}-doppler.env` is written (see
      secrets-vault-kit)
