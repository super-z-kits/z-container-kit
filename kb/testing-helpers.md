# Testing the helpers safely

ZK_PROJ / ZK_SYNC / ZK_USK env overrides for scratch testing.
Extracted from SKILL.md v2.3.3; ZK_USK added in v3.1; rewritten for v4.0
(zero-install — the helpers under test run from the canonical kit, the
scratch pattern is a config line, not an install).

## Testing the helpers safely

The helpers honor overrides so tests never touch the real `/home/sync`
artifacts (an accidental real zsave would overwrite `/home/sync/repo.tar` —
the boot-restore artifact — with whatever the project contains at that
moment), and never touch the real `/home/user_skills` (prefix resolution
would read your real config/credential files; refresh.sh would refresh the
real canonical package):

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
- `ZK_USK` redirects the prefix-resolution chain (project config is under
  ZK_PROJ; legacy config.env glob and the artifact conflict-scan read
  ZK_USK/ZK_SYNC), the credential-file write, zsession's kit registry, and
  refresh.sh's package refresh. Without it, a scratch run still READS the
  real `/home/user_skills` during conflict detection and zsession reports
  the real canonical package path.
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
