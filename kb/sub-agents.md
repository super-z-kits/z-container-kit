# Sub-agents & coordination (container-specific)

> The worklog protocol below is the coordination surface for ALL agents working
> in this container — main agent and sub-agents alike. It is committed to the
> repo, so it survives cross-chat (it is how a fresh session learns what the
> prior sessions did).

## The worklog protocol

**File:** `/home/z/my-project/worklog.md` — single shared, append-only log.
Never create per-agent log files; never overwrite existing content.

**Before starting work**, every agent (including sub-agents) MUST read the
tail of the worklog to understand what previous agents did:
```bash
tail -100 /home/z/my-project/worklog.md        # or Read with offset — the file
                                               # can be 30+ KB / 900+ lines
```

**After finishing a Task ID**, every agent MUST append a section:
```markdown
---
Task ID: <task id, e.g. 2-a>
Agent: <agent name>
Task: <the task you were asked to do>

Work Log:
- <concrete step 1>
- <concrete step 2>
- ...

Stage Summary:
- <key results / important decisions / produced artifacts>
```

Rules:
- Each section MUST start with a line containing exactly `---`.
- Append-only: never edit or delete prior entries.
- The worklog is COMMITTED (zsave picks it up via `git add -A`); that is what
  makes it survive into the next chat. If it is missing in a fresh session,
  recover it from git history before starting a blank one:
  `git log --all --oneline -- worklog.md` then
  `git show <last-commit>:worklog.md > worklog.md`.
- Keep entries concise (10-20 lines); the full detail belongs in the task's
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
- The coordinating agent assigns each sub-agent a Task ID reflecting global
  order and possible parallelism (`1`, `2-a`, `2-b`, `3` …) and passes it in
  the task prompt, together with the instruction to read and append to the
  worklog.
- Sub-agents get independent tool sessions — delegate risky probes (port
  checks, command filters) to them to protect the main session from the
  terminal-lockout hazard (see `kb/terminal-lockout.md`).
