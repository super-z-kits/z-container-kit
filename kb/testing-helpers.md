# Testing the helpers safely

ZK_PROJ / ZK_SYNC / ZK_USK env overrides for scratch testing.
Extracted from SKILL.md v2.3.3; ZK_USK added in v3.1.
## Testing the helpers safely

The helpers honor overrides so tests never touch the real `/home/sync`
artifacts (an accidental real zsave would overwrite `/home/sync/repo.tar` —
the boot-restore artifact — with whatever the project contains at that
moment), and never touch the real `/home/user_skills` (prefix discovery would
read your real config/credential files; install.sh would refresh the real
read-only package):

```
S=/tmp/my-project/helper-test; mkdir -p $S/demo $S/sync $S/usk
cd $S/demo && git init -q -b main && git commit -q --allow-empty -m init
ZK_PROJ=$S/demo ZK_SYNC=$S/sync ZK_USK=$S/usk bash /home/z/my-project/scripts/zsave "test"
ZK_PROJ=$S/demo ZK_SYNC=$S/sync ZK_USK=$S/usk bash /home/z/my-project/scripts/zsession
ZK_PROJ=$S/demo ZK_SYNC=$S/sync ZK_USK=$S/usk ZK_PREFIX=demo bash <kit>/scripts/install.sh
```

**The fresh-subshell trap (round-4 live incident):** each bash toolcall is a
FRESH subshell — overrides exported (or set bare) in one call are GONE in the
next. Prefix EVERY test command with the full override set, all on ONE line
in the SAME toolcall as the command, exactly as the examples above do. An
install.sh run with missing overrides silently targets the REAL
`/home/z/my-project` (it upgrades `.agents/` in place) — that is how a
scratch test becomes a live one by accident.

Notes:
- `ZK_PROJ` redirects the project dir (watchdog checks and live-project
  checks are skipped cleanly for scratch paths).
- `ZK_SYNC` redirects snapshots/repo.tar/state writes.
- `ZK_USK` (v3.1) redirects install.sh's package refresh + the prefix
  discovery chain (legacy config.env glob, artifact scan) AND zsession's
  package-presence check. Without it, a scratch install.sh still READS the
  real `/home/user_skills/*-config.env` during prefix discovery and zsession
  reports the real package path.
- The python helpers (`doppler_fetch.py`, `verify_access.py`) honor
  `ZK_USK` / `ZK_PROJ` the same way (v3.1.5 — PR#2 review F4).
- `ZK_PREFIX` passed explicitly outranks everything (tier 1) — use it to test
  a specific prefix without creating config files.
- Scratch-mode guards: zsave writes NO credential file (the write is gated on
  PROJ being the real /home/z/my-project AND SYNC being the real /home/sync),
  install.sh skips the package/zip refresh and the one-shot migrations when
  ZK_USK or ZK_PROJ are overridden.
