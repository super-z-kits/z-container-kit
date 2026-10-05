# Helpers reference (with audit callouts)

The kit ships SIX helpers (v5.1 existence audit — every script carries a
consumer-facing justification; the rest became documented one-liners):

**z-container-kit scripts (bash):**
- `zsave "msg"` — commit + push (auto-rebase on rejection) + snapshot +
  repo.tar refresh + state marker. Writes user_skills ZERO times in steady
  state (the v5.0 credential-file step was deleted in v5.1 — the remote
  travels inside the repo).
- `zsession` — read-only situation report (recycle detection via state.env;
  watchdog hygiene; kit & config status incl. the account default; deduped
  recommended actions — m11/m12).
- `zk-init` — writes `.agents/config` with a refuse-to-overwrite guard
  (wrong-prefix fix: `--force`); `--default` / `--set-default` manage the
  account-default bridge; `--status` inspects.
- `refresh.sh` — account-level package refresh (rename-aside swap + zip
  rebuild + housekeeping: backup prune, obsolete credential-file cleanup).
- `resolve-prefix.sh` — the identity contract, sourced by the bash helpers.
- `daemonize.py` — double-fork background process that survives toolcalls.

**Moved to secrets-vault-kit (v5.1):** `zdoppler-smoke` (audit F8) — Doppler
is that kit's domain; run it as
`bash /home/user_skills/secrets-vault-kit/scripts/zdoppler-smoke`.

**Deleted in v5.1 (each replaced by a documented one-liner or by svk
recipes):** `zremote` (mask one-liner in SKILL.md secrets section),
`doppler_fetch.py` (svk fact #4/#5 curl staging recipes), `verify_access.py`
(svk per-provider verification recipes), `wdt_watch.py` (forensics complete —
evidence in `evidence/`), `zkit-selftest` (dev suites live with kit
development, not in the shipped kit).

Historical audit callouts that still matter: F16 (verify a critical
user_skills write persisted — the pattern that motivated write-verify
loops; now applies to `zk-init --set-default`'s atomic write), F17 (mask
any credential you display), F13 (surface file modes so 0777 quirks stay
visible), F10 (self-tests belong to development, not the shipped kit).
