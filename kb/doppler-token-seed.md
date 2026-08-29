# DOPPLER_TOKEN_SEED callout

Edge case: PT stored in Doppler vault. Extracted from SKILL.md v2.3.3.
## ⚠️ DOPPLER_TOKEN_SEED callout (audit m7)

If your Doppler project's `prd` (or any) config contains a secret named `DOPPLER_TOKEN_SEED` with a `dp.pt.` prefix (i.e. a Personal Token stored in the vault), this violates the secrets-vault-kit's own fact #3 ("don't put `dp.pt.*` in persistent deployment targets — from a `dp.pt.*` they can mint write-capable Service Tokens"). A PT in the Doppler vault has the same blast radius as a PT in any other persistent store.

**Policy (decided, v5 — closes UF-1):** agents NEVER write a `dp.pt.*` seed
into any Doppler config. The PT arrives via handover only, lives in
`/home/user_skills/${ZK_PREFIX}-doppler.env` (atomic, fresher-wins), and the
user rotates it after the session. If a flow seems to need a stored seed,
use the seed/worker split from `SKILL-DEPLOY.md` with the seed held by the
user, not the vault.

**Don't auto-rotate or auto-delete an encountered seed** — it's the user's
credential. Flag it to the user and ask: (detection recipe lives in SKILL.md's
DOPPLER_TOKEN_SEED callout; the smoke tool is now at
`bash /home/user_skills/secrets-vault-kit/scripts/zdoppler-smoke` — v5.1
moved it to the Doppler kit)
- If it's the seed for minting STs (per `SKILL-DEPLOY.md` seed/worker split), document its purpose explicitly in the project description.
- If it's a stray PT left from a prior workflow, recommend the user delete it from Doppler via the dashboard and rotate.
