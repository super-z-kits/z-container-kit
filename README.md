# z-container-kit

Survival kit for the the sandbox container ("z-container"): verified
mechanics of the git HEAD watchdog (a `git switch main` prelude that runs
before every toolcall), the persistence model (overlay vs PolarFS vs ossfs
vs github; `repo.tar` restore semantics), background-process survival
(double-fork daemons), the irreversible terminal-command lockout hazard,
and the `zsave` / `zsession` helpers.

Every operational claim in `SKILL.md` is graded: **[V]** verified live,
**[S]** read from the boot-script source, **[I]** inherited/unverified.
The experiment log backing the [V] grades is `evidence/EXPERIMENTS.md`.

## v3.1 layout (two copies, by design)

Running `install.sh` **instantiates** the kit into your repo at `.agents/`
(git-tracked: SKILL.md + scripts/ + kb/ + evidence/ + `config` with your
`ZK_PREFIX`), creates `scripts/` shims that exec into `.agents/scripts/`,
and a `skills/z-container/SKILL.md` discovery symlink. The copy in
`/home/user_skills/z-container-kit/` is the read-only install source. This
replaces the v2.x four-copy sprawl (repo root + /home/sync + skills/ +
user_skills) and moves per-project config out of shared
`/home/user_skills/*-config.env` into repo-local `.agents/config`, which
survives boot (the platform only rewrites `.env`).

## Cold-start bootstrap (fresh session — a PAT and this repo URL, nothing else)

Wire the remote BEFORE the kit install so the installer can derive
`ZK_PREFIX` from the origin URL (same order as SKILL.md MUST-READ step 4):

```bash
# 0) get the kit (public repo — no PAT needed for the clone itself)
git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit   # any scratch path works

# 1) wire the GitHub repo that backs THIS workspace (user-supplied PAT)
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git

# 2) verify + restore the workspace (skip the reset if the remote is brand-new/empty)
git -C /home/z/my-project fetch
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK before reset
git -C /home/z/my-project reset --hard origin/main

# 3) instantiate the kit (LOAD-BEARING: .agents/ + config + scripts/ shims + skills/ symlink)
bash /tmp/my-project/kit/scripts/install.sh

# 4) re-anchor persistence (commit + push + snapshot + repo.tar in one shot)
bash /home/z/my-project/scripts/zsave "fresh-chat bootstrap checkpoint"
```

The PAT is typed exactly once (step 2) — it is already in the transcript via
the user's message; every helper masks it in all subsequent output (rotate at
github.com/settings/tokens anytime if concerned). install.sh strips any
clone-borne `.git` from kit copies, so they stay plain, trackable directories.

Then run `bash /home/z/my-project/scripts/zsession` (situation report) and
read `SKILL.md` — the "New session — MUST READ" section comes first.

Shortcut: if a prior session left `/home/user_skills/${ZK_PREFIX}-remote.url` (the
zsave-maintained credential file — the prefix is the filename part before
`-remote.url`), step 1 becomes
`git -C /home/z/my-project remote add origin "$(cat /home/user_skills/${ZK_PREFIX}-remote.url)"`
— and if the kit copy in `/home/user_skills/z-container-kit` survived, you
can skip the clone entirely and install from there.

## Contents

| path | purpose |
|---|---|
| `SKILL.md` | operational survival guide — start here (MUST-READ session section first) |
| `reference.md` | deep detail: boot sequence, storage internals, forensics, helper internals |
| `scripts/zsave` | one-command persistence: commit + push + snapshot + `repo.tar` refresh |
| `scripts/zsession` | read-only session situation report (recycle detection, watchdog hygiene) |
| `scripts/install.sh` | instantiates the kit into `.agents/` (idempotent, preserves config) |
| `scripts/daemonize.py` | double-fork daemonizer — survives the per-toolcall process cull |
| `scripts/wdt_watch.py` | forensic HEAD-watchdog observer (how the evidence was gathered) |
| `kb/` | deep-dive modules (session recovery, new-project setup, watchdog, …) |
| `evidence/` | experiment log + raw forensics backing every [V] claim |

## Notes

- The kit is **token-free and project-agnostic by construction**: it never
  embeds PATs, account names, or workspace repo URLs. All kit copies and
  the portable zip have passed full-text + git-object token scans.
- Helpers honor `ZK_PROJ` / `ZK_SYNC` / `ZK_USK` env overrides for safe scratch testing.
- Version 3.1.2 — provenance and validation history in `reference.md` §13
  (v3.x entry appended).
