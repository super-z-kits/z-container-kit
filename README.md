# z-container-kit

Survival kit for the sandbox container ("z-container"): verified
mechanics of the git HEAD watchdog (a `git switch main` prelude that runs
before every toolcall), the persistence model (overlay vs PolarFS vs ossfs
vs github; `repo.tar` restore semantics), background-process survival
(double-fork daemons), the irreversible terminal-command lockout hazard,
and the `zsave` / `zsession` helpers.

Every operational claim in `SKILL.md` is graded: **[V]** verified live,
**[S]** read from the boot-script source, **[I]** inherited/unverified.
The experiment log backing the [V] grades is `evidence/EXPERIMENTS.md`.

## Cold-start bootstrap (fresh session — a PAT and this repo URL, nothing else)

```bash
# 0) get the kit (public repo — no PAT needed for the clone itself)
git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit   # any scratch path works

# 1) install helpers + kit copies into the workspace
bash /tmp/my-project/kit/scripts/install.sh

# 2) wire the GitHub repo that backs THIS workspace (user-supplied PAT)
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git

# 3) restore the workspace (skip the reset if the remote is brand-new/empty)
git -C /home/z/my-project fetch && git -C /home/z/my-project reset --hard origin/main

# 4) normalize all kit copies post-restore (LOAD-BEARING: restores skills/)
bash /tmp/my-project/kit/scripts/install.sh

# 5) re-anchor persistence (commit + push + snapshot + repo.tar in one shot)
bash /home/z/my-project/scripts/zsave "fresh-chat bootstrap checkpoint"
```

The PAT is typed exactly once (step 2) — it is already in the transcript via
the user's message; every helper masks it in all subsequent output (rotate at
github.com/settings/tokens anytime if concerned). install.sh strips any
clone-borne `.git` from kit copies, so they stay plain, trackable directories.

Then run `bash /home/z/my-project/scripts/zsession` (situation report) and
read `SKILL.md` — the ten laws come first.

Shortcut: if a prior session left `/home/user_skills/zk-remote.url` (the
zsave-maintained credential file), step 2 becomes
`git -C /home/z/my-project remote add origin "$(cat /home/user_skills/zk-remote.url)"`
— and if the kit copy in `/home/user_skills/z-container-kit` survived, you
can skip the clone entirely and install from there.

## Contents

| path | purpose |
|---|---|
| `SKILL.md` | operational survival guide — start here |
| `reference.md` | deep detail: boot sequence, storage internals, forensics, helper internals |
| `scripts/zsave` | one-command persistence: commit + push + snapshot + `repo.tar` refresh |
| `scripts/zsession` | read-only session situation report (recycle detection, watchdog hygiene) |
| `scripts/daemonize.py` | double-fork daemonizer — survives the per-toolcall process cull |
| `scripts/install.sh` | installs the kit into the container (all copies, idempotent) |
| `scripts/wdt_watch.py` | forensic HEAD-watchdog observer (how the evidence was gathered) |
| `evidence/` | experiment log + raw forensics backing every [V] claim |

## Notes

- The kit is **token-free and project-agnostic by construction**: it never
  embeds PATs, account names, or workspace repo URLs. All kit copies and
  the portable zip have passed full-text + git-object token scans.
- Helpers honor `ZK_PROJ` / `ZK_SYNC` env overrides for safe scratch testing.
- Version 2.3.2 — provenance and validation history (6 review rounds +
  cold-start usability rounds) in `reference.md` §13.
