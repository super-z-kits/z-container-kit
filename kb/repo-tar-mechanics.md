# repo.tar mechanics

Boot/shutdown source detail, .gitignore auto-heal, service boot.
Extracted from SKILL.md v2.3.3.
## repo.tar mechanics [S]

- Boot: if `/home/sync/repo.tar` exists, start.sh **deletes everything** in
  `/home/z/my-project` (except the `upload/` mount) and re-extracts the tar
  (which itself excludes `upload/`), then rewrites `.env` and re-chowns to z.
  If it does not exist: "clean project" path — fresh `.env`,
  `download/README.md`, `skills/`, and (only if `.git` missing, checked with
  `[ ! -d .git ]`) `git init` + initial commit.
- Shutdown: the platform archives my-project to `/home/sync/repo.tar` on
  **graceful** shutdown only (plus a runtime `git add -A` UUID-message commit —
  observed at pre-stop, not mid-session). A force-kill skips both: next boot
  restores whatever `repo.tar` was last there — which is why zsave refreshes it.
- The platform force-writes a narrow `.gitignore` (`skills/`, `node_modules/`)
  and auto-heals broader ones. `skills/` and `node_modules/` are therefore
  git-excluded but still tar-included (repo.tar archives the directory, not git).
- Boot starts services **from my-project only [S]**: `.zscripts/dev.sh` if
  present (custom flow, replaces the default), else `package.json` ->
  `bun install && bun run db:push && bun run dev` (:3000), plus every
  `mini-services/<dir>` with a `dev` script.
