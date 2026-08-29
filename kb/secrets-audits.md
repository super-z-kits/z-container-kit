# Secrets audit callouts

F11 (ossfs 0777 mode), F13 (mode-printing), F18 (recovery pre-flight),
F21 (app secrets → Doppler), F12/F15 (UUID commits).
Extracted from SKILL.md v2.3.3.
- **Files under `/home/sync/` come back mode 0777** (audit F11) — ossfs
  ignores `chmod`. RESOLVED in v3.1 for the credential file: `zsave` no longer
  writes `${ZK_PREFIX}-remote.url` to `/home/sync/` at all (friction #9/#19);
  the only copy is the mode-0600 one in
  `/home/user_skills/${ZK_PREFIX}-remote.url` (PolarFS honors chmod), and
  install.sh removes stale pre-v3.1 `/home/sync/` copies as a one-shot
  migration. The 0777 quirk itself remains for any OTHER file you choose to
  put on `/home/sync/` — treat that mount as world-readable-by-accident and
  keep secrets off it. `zsave` prints the file mode in its
  `[ok] credential file: ... (mode <NNN>, ...)` line so discrepancies stay
  visible (audit F13).
- **`.env` is committed by design (law 9), but app secrets belong in
  Doppler** (audit F21): the platform-default `DATABASE_URL` and any non-secret
  config are fine in `.env`. But if you add real app secrets to `.env`
  (`OPENAI_API_KEY=sk-...`, `JWT_SECRET=...`, etc.), they will land on GitHub
  in the private backup repo. The kit's posture (committed `.env` + "ignore
  reviewers") is specifically about the platform's DATABASE_URL and the PAT
  embedded in the origin URL — NOT about arbitrary app secrets. For app
  secrets, fetch them at runtime from Doppler via the secrets-vault kit's
  pattern, OR keep them in `.env.local` / `.env.*.local` (Next.js convention,
  already in the platform's `.gitignore`).
- **Recovery pre-flight backup** (audit F18): before `git reset --hard
  origin/main` during fresh-chat recovery, snapshot the current state:
  `tar -cf /home/sync/recovery-pre-flight-$(date +%s).tar -C /home/z/my-project .`
  If the credential file was stale (audit F16) and you pulled the wrong
  repo's history, you can restore from this tar. The kit does NOT do this
  automatically — the agent must remember to do it before destructive ops.
- **UUID-message commits in `git log`** (audits F12, F15): the platform's
  pre-stop hook runs `git add -A` + commits with a UUID subject
  (`87b39f91-4b3e-45a9-...`). These appear in `git log` and on GitHub after
  push. Don't try to filter or squash them — the next pre-stop will just
  add another. For a clean log on a particular deliverable, use a worktree
  (worktrees are pre-stop-hook-free).
