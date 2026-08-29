# Sub-agents & coordination (container-specific deltas)

> **Preset boundary.** The environment preset already provides Task-tool
> usage (agent types, parallel launching, stateless invocations, the
> self-contained-prompt requirement), the fact that sub-agents see nothing
> of your context, Task-ID assignment (`1`, `2-a`, `2-b`, `3` …), and the
> shared worklog protocol (path, append-only, `---` sections, the
> Task ID / Agent / Task / Work Log / Stage Summary template). This module
> deliberately does NOT restate any of that — it records only what is
> specific to THIS container. If a directive here stops being net-new, cut
> it.

## Worklog deltas for this container

The preset's worklog protocol applies unchanged (`/home/z/my-project/worklog.md`,
append-only). This container adds three things:

- **The worklog is COMMITTED** — zsave picks it up via `git add -A`; that is
  what makes it survive into the next chat.
- **If it is missing in a fresh session**, recover it from git history
  before starting a blank one: `git log --all --oneline -- worklog.md`,
  then `git show <last-commit>:worklog.md > worklog.md`.
- **Keep entries concise** (10-20 lines); full detail belongs in the task's
  deliverables (docs/, evidence/), not the worklog.

## Sub-agent rules for this container

- Sub-agents share THIS container: the watchdog resets HEAD before their
  toolcalls too, and their file writes land in the same overlay. Give each
  sub-agent its own worktree
  (`git -C /home/z/my-project worktree add /tmp/my-project/worktrees/<name> -b feature/<x>`)
  or a scratch dir outside the project.
- **Sub-agents MUST NOT run `zsave`** — the coordinating agent owns all saves
  (zsave's per-container lock would otherwise corrupt repo.tar). Pushing from
  a worktree is always fine.
- Sub-agents get independent tool sessions — delegate risky probes (port
  checks, command filters) to them to protect the main session from the
  terminal-lockout hazard (see `kb/terminal-lockout.md`). When you do, embed
  the hazard warnings in their prompt (never loop caddy commands, never
  curl-loop the gateway ports, one probe per toolcall) — they will not know
  them otherwise.
