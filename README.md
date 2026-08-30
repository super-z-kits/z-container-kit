# z-container-kit

Survival kit for the the sandbox container ("z-container"): verified
mechanics of the git HEAD watchdog (a `git switch main` prelude that runs
before every toolcall), the persistence model (overlay vs PolarFS vs ossfs
vs github; `repo.tar` restore semantics), background-process survival
(double-fork daemons), the irreversible terminal-command lockout hazard,
and the `zsave` / `zsession` helpers (six scripts — each earns its
existence; everything else is a documented one-liner).

Every operational claim in `SKILL.md` is graded: **[V]** verified live,
**[S]** read from the boot-script source, **[I]** inherited/unverified.
The experiment log backing the [V] grades is `evidence/EXPERIMENTS.md`.

## v5 layout (zero-install, STATIC user-skills, multi-track proven)

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
single-project account. v4 made it zero-install, multi-kit and multi-repo
(kits mind their own business; identity is configuration only). v5 closes
the last gap — **parallel sessions under one account, sometimes on the SAME
repo**: `/home/user_skills` has no git (no merge, no rebase, no conflict
handling), so it is now **read-only for sessions** (the static rule). The
only sanctioned writes are zero-collision ones (atomic kit refresh;
idempotent zip rebuild; secrets-vault-kit's prefix-keyed doppler env files;
the account default `zk-default.env`, set only by the explicit
`zk-init --set-default`). Same-repo divergence is handled by git itself:
zsave auto-recovers a rejected push via `pull --rebase` + retry, never
force-pushes, and concurrent saves serialize on a lock they WAIT for
instead of failing. v5.1 deleted the `${ZK_PREFIX}-remote.url` credential
files entirely — the origin URL travels INSIDE the repo (`.git/config` in
repo.tar/snapshots/github), so steady-state saves write `/home/user_skills`
zero times. Scripts are optional accelerators — every recurring flow is
documented so plain git + the docs always suffice.

- Project setup: `bash /home/user_skills/z-container-kit/scripts/zk-init <name>`
- Account upgrade: `bash <updated-clone>/scripts/refresh.sh`
- Single-project account default (opt-in):
  `bash /home/user_skills/z-container-kit/scripts/zk-init --set-default`

## Cold-start bootstrap (fresh session — a PAT and this repo URL, nothing else)

```bash
# 0) the kit: canonical per-account copy (survives new chats); clone only if absent
KIT=/home/user_skills/z-container-kit
[ -f "$KIT/scripts/zsave" ] || { git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit; KIT=/tmp/my-project/kit; }

# 1) wire the GitHub repo that backs THIS workspace — account default first:
#    - default set (single-project account)?  bash "$KIT/scripts/zk-init --default"
#      (writes config + wires origin + fetches + REVEALS which project came back)
#    - no default? user-supplied PAT (or Doppler-vault GH_PAT, see secrets-vault-kit):
git -C /home/z/my-project remote add origin https://<PAT>@github.com/<user>/<repo>.git

# 2) verify + restore the workspace (skip the reset if the remote is brand-new/empty)
git -C /home/z/my-project fetch
git -C /home/z/my-project log origin/main --oneline -5 | sed -E 's#(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+#\1***#g'   # SANITY CHECK before reset
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
report) and read `SKILL.md` — the "Session start — MUST READ" section comes
first.

Shortcut: a single-project account can skip the PAT handover entirely —
after the first successful save, run `bash "$KIT/scripts/zk-init
--set-default"` once (snapshots prefix + origin into
`/home/user_skills/zk-default.env`, mode 0600). Every later fresh chat is
one command: `bash "$KIT/scripts/zk-init --default"` — it wires the remote
and LOUDLY reveals which project came back (the tripwire that catches a
default set on what is really a multi-repo account).

## Contents

| path | purpose |
|---|---|
| `SKILL.md` | operational survival guide — start here (MUST-READ session section first) |
| `reference.md` | deep detail: boot sequence, storage internals, forensics, helper internals |
| `scripts/zsave` | one-command persistence: commit + push (auto-rebase on rejection) + snapshot + `repo.tar` refresh |
| `scripts/zsession` | read-only session situation report (recycle detection, kit & config status, account default) |
| `scripts/zk-init` | project identity (`--force`, `--status`) + account-default bridge (`--default`, `--set-default`) |
| `scripts/refresh.sh` | account-level upgrade: atomic package refresh + zip rebuild + housekeeping |
| `scripts/resolve-prefix.sh` | the identity contract (ZK_PREFIX env > .agents/config > loud failure) |
| `scripts/daemonize.py` | double-fork daemonizer — survives the per-toolcall process cull |
| `kb/` | deep-dive modules (session start & recovery, watchdog, …) |
| `evidence/` | experiment log + raw forensics backing every [V] claim |

## Notes

- The kit is **token-free and project-agnostic by construction**: it never
  embeds PATs, account names, or workspace repo URLs. All kit copies and
  the portable zip have passed full-text + git-object token scans.
- Helpers honor `ZK_PROJ` / `ZK_SYNC` / `ZK_USK` env overrides for safe scratch testing.
- Version 5.3.0 — provenance and validation history in `reference.md` §13
  (v5.2 entry appended). v5.3: knowledge-first restructure — the doc now
  introduces itself as tool-neutral know-how (laws + gotchas first), a
  "minimal path" section inlines what zsave does for agents that skip the
  helper flow, the sticky todo and laws 1/3 de-mandated; round-2 trim via
  masked-recitation drop tests (weak-model filter + strong sub-agent
  escalation) cut 7 command blocks agents recite from context; 28,903 →
  26,985 bytes (under the 27,000 Read-tool truncation threshold), 509 → 484
  lines, zero information loss (sub-agent audited); usability-validated
  both full-adopt and scripts-forbidden (knowledge-only) runs, both PASS.
  (v5.1 entry appended). v5.1: credential files deleted (the remote travels
  with the repo), script existence audit (12 → 6; zdoppler-smoke moved to
  secrets-vault-kit), account-default bootstrap, one unified session flow.
  v5.2: SKILL.md fat-cut (688 → 509 lines, zero information loss —
  inventorized line-by-line, sub-agent-reviewed drop/keep/condense,
  over-teaching resolved by experiment; kb/doppler-token-seed.md absorbed
  the detection sweep).
