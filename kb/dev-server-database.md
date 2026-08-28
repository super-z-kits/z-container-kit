# Dev server & database detail

:3000 dev server, Prisma + SQLite, hot-state patterns.
Extracted from SKILL.md v2.3.3.
## Dev server & database

- `bun run dev` (:3000, Next.js) runs only if my-project has `package.json` (or
  `.zscripts/dev.sh`) at boot [S]. Don't start a second copy; don't kill it
  (no supervisor). Tail `my-project/dev.log` for compile errors; `bun run lint`
  is safe anytime. Avoid `bun run build` as the normal path.
- Prisma + SQLite at `DATABASE_URL=file:/home/z/my-project/db/custom.db` [S] —
  overlay: the DB dies with the recycle unless zsave'd (it is inside my-project,
  so repo.tar/snapshots carry it). For hot state that must never be more than
  one command behind, keep it under `/tmp/my-project/` or `/home/sync/` and
  symlink — or just zsave often.
