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

## v4 layout (zero-install: one canonical copy + one line per project)

The kit lives ONCE per account at `/home/user_skills/z-container-kit/`
(per-user PolarFS — survives recycles, force-kills, and new chats, observed
live). Helpers run straight from there and are location-agnostic: project
identity comes from the project, never from the script's own location. A
project's ONLY kit artifact is `.agents/config` — one line, `ZK_PREFIX=<name>`,
git-tracked, boot-safe (the platform rewrites `.env` every boot; it never
touches `.agents/config`). This is the .env pattern: identity travels with
the repo through GitHub and `repo.tar`, so a cold start needs no install
step — `git reset --hard origin/main` brings the config back with the code.

Why: v3.x instantiated a full kit copy per repo (`.agents/` tree, `scripts/`
shims, `skills/` symlink) — the copies went stale, the install flow carried
a disproportionate share of the bug history, and the whole model assumed a
single-project account. v4 is multi-kit and multi-repo by construction:
every kit is a self-contained dir in `/home/user_skills/` (kits mind their
own business — no cross-kit registries or managers), every project is
a config line, upgrades happen once per account (atomic `refresh.sh`), and
prefix resolution reads ONLY the env var + the project's `.agents/config`
(no artifact scanning, no URL guessing — a missing config fails loudly with
the one-command fix, and a stale artifact can never leak into a session).

- Project setup: `bash /home/user_skills/z-container-kit/scripts/zk-init <name>`
- Account upgrade: `bash <updated-clone>/scripts/refresh.sh`
- v3 repo cleanup: `bash /home/user_skills/z-container-kit/scripts/zk-init --migrate-v3`

## Cold-start bootstrap (fresh session — a PAT and this repo URL, nothing else)

```bash
# 0) the kit: canonical per-account copy (survives new chats); clone only if absent
KIT=/home/user_skills/z-container-kit
[ -f "$KIT/scripts/zsave" ] || { git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit; KIT=/tmp/my-project/kit; }

# 1) wire the GitHub repo that backs THIS workspace (user-supplied PAT)
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git

# 2) verify + restore the workspace (skip the reset if the remote is brand-new/empty)
git -C /home/z/my-project fetch
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's|(ghp_[A-Za-z0-9]+)|(***PAT***)|g'   # SANITY CHECK before reset
git -C /home/z/my-project reset --hard origin/main

# 3) identity comes back WITH the repo (.agents/config is committed) — verify:
source /home/z/my-project/.agents/config && echo "$ZK_PREFIX"
#    absent (repo predates the kit)? bash "$KIT/scripts/zk-init" <name>

# 4) re-anchor persistence (commit + push + snapshot + repo.tar in one shot)
bash "$KIT/scripts/zsave" "fresh-chat bootstrap checkpoint"
```

There is no install step — that is the whole point. The PAT is typed exactly
once (step 1); every helper masks it in all subsequent output (rotate at
github.com/settings/tokens anytime if concerned).

Then run `bash /home/user_skills/z-container-kit/scripts/zsession` (situation
report) and read `SKILL.md` — the "New session — MUST READ" section comes
first.

Shortcut: if a prior session left `/home/user_skills/<prefix>-remote.url`
(the zsave-maintained credential file — ONE PER PROJECT on multi-repo
accounts; list them with `ls /home/user_skills/*-remote.url` and pick THIS
session's project), step 1 becomes
`git -C /home/z/my-project remote add origin "$(cat /home/user_skills/<your-prefix>-remote.url)"`.

## Contents

| path | purpose |
|---|---|
| `SKILL.md` | operational survival guide — start here (MUST-READ session section first) |
| `reference.md` | deep detail: boot sequence, storage internals, forensics, helper internals |
| `scripts/zsave` | one-command persistence: commit + push + snapshot + `repo.tar` refresh |
| `scripts/zsession` | read-only session situation report (recycle detection, kit & config status) |
| `scripts/zk-init` | project setup: writes `.agents/config` (`--migrate-v3` strips v3 leftovers) |
| `scripts/refresh.sh` | account-level upgrade: atomic package refresh + zip rebuild |
| `scripts/install.sh` | REMOVED in v4 (deprecation stub) |
| `scripts/daemonize.py` | double-fork daemonizer — survives the per-toolcall process cull |
| `scripts/wdt_watch.py` | forensic HEAD-watchdog observer (how the evidence was gathered) |
| `kb/` | deep-dive modules (session recovery, new-project setup, watchdog, …) |
| `evidence/` | experiment log + raw forensics backing every [V] claim |

## Notes

- The kit is **token-free and project-agnostic by construction**: it never
  embeds PATs, account names, or workspace repo URLs. All kit copies and
  the portable zip have passed full-text + git-object token scans.
- Helpers honor `ZK_PROJ` / `ZK_SYNC` / `ZK_USK` env overrides for safe scratch testing.
- Version 4.0.0 — provenance and validation history in `reference.md` §13
  (v4.0 entry appended).
