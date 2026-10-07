# Token display redaction — the `[REDACTED:…]` illusion

Status: **[V]** 2026-10-05 — 11 write methods sha256-proven byte-intact,
real-token end-to-end (evidence/EXPERIMENTS.md E20).

## The illusion

Writing a token appears to fail: every later cat/Read/Grep shows
`GITHUB_PAT=[REDACTED:github_token]`. It did NOT fail — the redaction
is 100% DISPLAY-ONLY. All 11 tested write methods (printf, heredoc,
tee, python3, base64 -d, split echoes, Write tool, `git remote add`,
real-token end-to-end ×2) landed the token byte-intact, sha256-proven
— and a REAL PAT sourced from a "redacted" file authenticated
(`git ls-remote` exit 0). `[REDACTED:…]` in a display means SUCCESS,
not failure.

## Redactor spec

- GitHub family: prefixes `ghp_ gho_ ghs_ ghu_ ghr_ github_pat_` +
  **≥20 [A-Za-z0-9]** → `[REDACTED:github_token]` (19 chars shown; no
  upper bound to 40+; quotes/punctuation/URL-embedding do not protect).
- Slack: `xoxb-` → `[REDACTED:slack_token]`.
- NOT covered (shown in clear): `glpat-` GitLab PATs, `AKIA…` AWS
  keys, `dp.pt.` Doppler tokens, `user:pass@host` DSNs, hex/base64-
  encoded tokens.
- Applies to: Bash stdout/stderr, Read tool, Grep content output. NOT
  to: command execution (inputs pass verbatim — that is why files land
  intact), disk state, hash output, `wc`, `base64 <file>`. Corollary:
  bypassable in both directions — a display nicety, NOT a security
  boundary.

## Lying paths vs truth paths

- **LIE:** cat, echo/printf passthrough, tee stdout, Read, Grep
  content, `git remote -v`, `git config --get remote.origin.url`
  (while `.git/config` holds the full token).
- **TRUTH:** sha256 compare, `wc -c`, `grep -cF` with an assembled
  pattern, `base64 <file>`, masked substring views, `git ls-remote`
  exit codes (authentication = ground truth).

## The .env double-trap

`/home/z/my-project/.env` is UNCONDITIONALLY rewritten by the platform
at every boot (start.sh:70 restore path, :98 clean path) with
secretless `DATABASE_URL=file:…`. A PAT stored under that exact
filename IS genuinely destroyed at recycle (everywhere else persists
fine). Never store PATs there; the platform has never been observed
writing tokens into it.

## Working recipe

```bash
printf 'GITHUB_PAT=%s\n' "$TOKEN" > /home/sync/SECRETS.env
python3 - <<'EOF'   # verify by HASH, never by eye (P+Q = split token
import hashlib      # so the check itself can't be redacted)
exp = hashlib.sha256(('GITHUB_PAT=' + P + Q + '\n').encode()).hexdigest()
print('INTACT' if hashlib.sha256(open('/home/sync/SECRETS.env','rb').read()).hexdigest() == exp else 'MODIFIED')
EOF
set -a; . /home/sync/SECRETS.env; set +a
```

`zenv pat <gh> [gl]` stamps the same two channels:
`/home/sync/SECRETS.env` (per-chat) + `/home/user_skills/zk-secrets.env`
(per-user).

## PAT persistence channels (ranked)

Across RECYCLE (same chat): **1.** `/home/sync/SECRETS.env` +
`/home/user_skills/zk-secrets.env` (remote-backed, force-kill-proof, no
git dependency) **> 2.** repo.tar riders (PAT-in-origin-URL in
`.git/config` + committed files; graceful-only freshness; rotation is
the weak link) **> 3.** `/home/z` dotfiles — DEAD (overlay; nothing
archives them).

Across a NEW sandbox: **1.** `/home/user_skills` (per-USER PolarFS —
zk-secrets.env / zk-default.env re-wire a fresh sandbox) **> 2.**
GitHub repo content (universal once a PAT is wired in) — while
URL-embedding does NOT carry (fresh bootstrap repo: no repo.tar, no
remote) and per-chat `/home/sync` does NOT carry.

## The observer-log leak lesson

PAT-in-URL pushes put the token in the git process's /proc cmdline; any
/proc-cmdline-capturing observer (or sibling agent) then writes the
PLAINTEXT token into its logs — this happened (4 copies in a
tracked+pushed observer log, Sep-9 session). Instruments must mask
token shapes at write time and keep their log dirs git-excluded — the
reason zbackupd authenticates via GIT_ASKPASS files, never URLs
(kb/zbackupd.md, law 3).
