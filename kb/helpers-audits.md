# Helpers reference (with audit callouts)

Full list of scripts/ helpers with F6, F8, F10, M7, M3, M4 audit callouts.
Extracted from SKILL.md v2.3.3.
## Helpers reference (audit m1, M7)

The kit ships these helpers in `scripts/`:

**z-container-kit scripts (bash):**
- `zsave "msg"` — commit + push + snapshot + repo.tar refresh + credential file (F16: verified post-write)
- `zsession` — read-only situation report (F17: prints masked credential file URL; m11: notes worklog absence; m12: deduped recs)
- `zk-init` / `refresh.sh` — v4 replacements for the removed install.sh
  (project setup / account-level package refresh)
- `daemonize.py` — double-fork background process for surviving toolcalls
- `wdt_watch.py` — watchdog observation helper
- `zremote` (audit F6) — PAT-masking `git remote` viewer (replaces `git remote -v` muscle memory)
- `zdoppler-smoke` (audit F8) — one-shot Doppler vault verification (validates PT format, lists secrets)
- `zkit-selftest` (audit F10) — end-to-end save/wipe/recover smoke test (creates a temp repo, verifies the full cycle)

**Also present (Python helpers from prior session, complementary):**
- `doppler_fetch.py` — Python urllib version of `zdoppler-smoke`; stages secrets to `/tmp/my-project/doppler-secrets.json` (audit M7 staging pattern). Verifies PT via `/workplace` (avoids the M4 `/projects/project/<slug>` 400 quirk).
- `verify_access.py` — Python urllib access verifier for GitHub / Cloudflare / Supabase. **NOTE (audit M3):** uses default urllib UA — will hit the Supabase WAF 403. Patched version should send `User-Agent: ${ZK_PREFIX}-verify` (the GitHub section already does this).

Use bash helpers for quick one-shots; use Python helpers for multi-call verification flows that need to stage secrets across calls.
