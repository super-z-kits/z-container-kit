# repo.tar mechanics

Boot/shutdown source detail, mode law, conditional pre-stop commit,
.gitignore auto-heal, service boot. Graded [S] = read from /start.sh source;
[V] = verified across the real 19-day graceful recycle (2026-09-09 → 2026-09-28).

## Boot — restore branch [S start.sh:59–121; observed 2026-09-28]

- If `/home/sync/repo.tar` exists: start.sh DELETES everything in
  `/home/z/my-project` (except the `upload/` mountpoint), re-extracts the tar
  (the tar itself excludes `upload/`), rewrites `.env`, re-chowns to z, and
  **runs `chmod -R 755` over the whole restored tree** (start.sh:104–111 —
  the `find … -exec chmod -R 755` variant skips upload/; the plain fallback
  chmods everything).
- **The mode law [V]**: the tar itself carries normal modes (0644/0664/0775) —
  the BOOT chmod is what normalizes every file to 0755. The first `git status`
  after any recycle therefore shows a mass mode-only ` M` set (with
  `core.filemode=true`, which rides in the tar's `.git/config`). Remedy, once
  per repo: `git config core.filemode false`. NEVER commit the noise (it
  pollutes history and rides every push). Post-restore writes land 0664
  (umask) — the 755s remain visible until you set filemode=false.
- The restored project top dir gets mode 0700 + a BACKWARD mtime (from the
  platform's `/tmp/my-project` snapshot manifest — kb/persistence-
  namespaces.md). Cosmetic; the content is what the tar carried.
- `/tmp/boot-timeline.log` REGENERATES each boot — it always describes the
  LATEST boot, never the session's first (citation hazard).
- If no repo.tar: "clean project" path — fresh `.env`, `download/README.md`,
  `skills/`, and (only if `.git` missing, `[ ! -d .git ]`) `git init` +
  initial commit.

## Shutdown (pre-stop) [V + S]

- Order: **git FIRST, then tar** — proven by the tar's `.git` directory
  member carrying the tar-creation-second mtime (a git lockfile-dance
  fingerprint) while index/reflog inside were frozen at the last real commit.
- The `git add -A` commit is **CONDITIONAL**: on a clean tree NO commit
  appears — verified across the real recycle (restored history AND origin
  both ended at the session's last real commit; nothing was lost). The
  "UUID-message commit" is [I] — not observed in any forensic session (E12:
  mid-session absence only; E16: clean-tree recycle produced none); the
  UUID-subject examples quoted in kb/secrets-audits.md (F12/F15) are out-of-band
  reports, not raw-evidence-backed. A dirty-tree graceful recycle is the missing
  discriminator.
- The platform's pre-stop tar carried EXACTLY the tracked set + `.git`:
  `skills/` (gitignored, present in the tree at recycle time) was EXCLUDED —
  it returns via the
  boot's skills re-extraction instead — OFFICIAL skills only; custom skills/
  content survives solely via zsave snapshots or a commit. The old claim
  "git-excluded but tar-included (repo.tar archives the directory, not git)"
  was WRONG for the platform's pre-stop tar. (zsave's own snapshot tars are
  separate artifacts with their own rules — kb/zsave-internals.md.)
- Graceful shutdown only; a force-kill skips both tar and commit — next boot
  restores whatever repo.tar was last there. zsave refreshes repo.tar to
  bound the loss window.

## .gitignore auto-heal [S]

The platform force-writes a narrow `.gitignore` (`skills/`, `node_modules/`)
and auto-heals broader ones. Consequence: `upload/`, `tool-results/`,
`dev.log` are NOT excluded — seed `.git/info/exclude` (zsave maintains it) or
they ride every commit, the pre-stop absorption, and every push.

## Service boot [S]

Boot starts services from my-project only: `.zscripts/dev.sh` if present
(custom flow, replaces the default), else `package.json` → `bun install && bun
run db:push && bun run dev` (:3000), plus every `mini-services/<dir>` with a
`dev` script.
