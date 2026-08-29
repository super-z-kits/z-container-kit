# Pointing the helpers at another project (and scratch testing)

ZK_PROJ / ZK_SYNC / ZK_USK env overrides: the general mechanism for running
the kit against ANY project directory — a worktree, a second project on the
same account, a sandbox/scratch copy, or a test harness. Same mechanism,
same rules. (Extracted from SKILL.md v2.3.3; ZK_USK added in v3.1; rewritten
for v4.0; reframed v4.1 after usability rounds showed agents hunting for
exactly this under "testing" docs when they needed it for REAL workflows.)

## Pointing helpers at a non-default project

The helpers default to `/home/z/my-project` + `/home/user_skills` +
`/home/sync`. Point them anywhere else with the overrides (this is also
what makes scratch TESTS safe — same mechanism, not a separate "test mode").
Overriding keeps runs away from the real `/home/sync` artifacts (an
accidental real zsave would overwrite `/home/sync/repo.tar` — the
boot-restore artifact — with whatever the project contains at that moment)
and away from the real `/home/user_skills` (credential files; refresh.sh
would refresh the real canonical package):

```
S=/tmp/my-project/helper-test; mkdir -p $S/demo $S/sync $S/usk
cd $S/demo && git init -q -b main && git commit -q --allow-empty -m init
KIT=/home/user_skills/z-container-kit          # the helpers under test
ZK_PROJ=$S/demo ZK_SYNC=$S/sync ZK_USK=$S/usk bash $KIT/scripts/zk-init demo    # scratch identity
ZK_PROJ=$S/demo ZK_SYNC=$S/sync ZK_USK=$S/usk bash $KIT/scripts/zsave "test"
ZK_PROJ=$S/demo ZK_SYNC=$S/sync ZK_USK=$S/usk bash $KIT/scripts/zsession
```

**The fresh-subshell trap (round-4 live incident):** each bash toolcall is a
FRESH subshell — overrides exported (or set bare) in one call are GONE in the
next. Prefix EVERY test command with the full override set, all on ONE line
in the SAME toolcall as the command, exactly as the examples above do. A
helper run with missing overrides silently targets the REAL
`/home/z/my-project` — that is how a scratch test becomes a live one by
accident.

Notes:
- `ZK_PROJ` redirects the project dir (watchdog checks and live-project
  checks are skipped cleanly for scratch paths).
- `ZK_SYNC` redirects snapshots/repo.tar/state writes.
- `ZK_USK` redirects the credential-file write, the canonical-package
  presence check in zsession, and refresh.sh's package refresh. Without it,
  a scratch run still READS the real `/home/user_skills` (zsession reports
  the real canonical package path). Prefix resolution itself no longer
  reads any account-wide state (v4.1: env + project config only), so
  scratch identity is fully controlled by `ZK_PROJ`/`ZK_PREFIX`.
- The python helpers (`doppler_fetch.py`, `verify_access.py`) honor
  `ZK_USK` / `ZK_PROJ` the same way (v3.1.5 — PR#2 review F4).
- `ZK_PREFIX` passed explicitly outranks everything (tier 1) — use it to test
  a specific prefix without creating config files.
- Scratch-mode guards: zsave writes the credential file to `$ZK_USK` only
  when ZK_USK is overridden OR the run is live (a scratch ZK_PROJ with the
  REAL /home/user_skills writes nothing there); refresh.sh skips nothing —
  it refreshes `$ZK_USK/z-container-kit`, so point ZK_USK at scratch.
- v4 note: `zk-init` only ever writes inside `$ZK_PROJ/.agents/config` — it
  cannot touch anything shared unless you point ZK_PROJ at the real project.
