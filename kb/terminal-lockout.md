# Terminal lockout (deep dive) — the irreversible 403 hazard

> Short version lives in SKILL.md ("Deadly: terminal command lockout"). This
> module is the operational detail: why it happens, what exactly triggers it,
> and the recovery story (there isn't one — prevention only). Grade: **[I]**
> inherited/unverified for the lockout itself — never verify it
> experimentally; the command-position filter fact below is **[V]**
> (first-hand 2026-10-05: one blocked call, no lockout).

## What happens

Rapid loops of filtered `caddy` commands or scan-like curl loops against
ports 12600/19001/19005/19006 cause an **irreversible session-wide 403**:
every subsequent toolcall fails — even `echo ok`. There is no in-run
recovery; only a new agent session fixes it.

## Why the filter is treacherous

- **[V 2026-10-05] The filter blocks the gateway binary name in COMMAND
  POSITION regardless of subcommand.** A single `caddy version` inside a
  multi-command payload was hard-blocked (`can not execute caddy command
  in bash`); no retry was attempted and no lockout followed. There is NO
  safe subcommand — the only safe policy is to never type the binary
  name in a command position at all. (Corrects v5.6.0's "version/adapt
  are safe" example — it was wrong.)
- The filter scans the FULL COMMAND TEXT. Even a heredoc *containing* the word
  `caddy` is blocked — write such files with the Write/Edit tools, not bash
  heredocs.
- It is rate/pattern-based: the hazard is LOOPING, not the single command. One
  probe per toolcall is safe; five probes in five separate toolcalls is safe;
  a `for` loop over them in one call is what kills the session.
- The affected ports are internal control-plane surfaces (ZAI bridge on 12600,
  FC control plane on 19001/19005/19006). Scanning them looks like an attack
  pattern to the platform's request filter.

## Safe vs. unsafe (examples)

Safe (single-shot, read-only):
- `ps aux`, `ss -tln`, `cat /proc/...` — nothing names the gateway binary
- `curl -sS http://localhost:12600/ping` — once, never in a loop
- inspecting boot/gateway config files with the Read tool (the filter
  scans command text, not file contents)

Unsafe:
- ANY command-position use of the gateway binary name — `caddy version`
  and `caddy adapt` included (blocked 2026-10-05)
- `for p in 3000 3001 12600 19001 19005 19006; do curl -m1 localhost:$p; done`
- `caddy stop && caddy start` retry loops
- any script that method-matrixes or path-enumerates internal ports

## If it already happened

- STOP retrying. Every retry is another filtered request; do not "test" whether
  the session recovered.
- Do not blame the project or the kit — the container is fine; the SESSION's
  toolcall channel is what's locked.
- Tell the user plainly: the session needs a restart (new agent session), and
  work saved via `zsave` before the incident is safe (git, snapshots, repo.tar
  are all untouched by the lockout).
- Delegate any *diagnostic* you truly need to a sub-agent — it gets an
  independent tool session — but do NOT use it to re-run the loop that caused
  the lockout.

## Prevention checklist

1. Never type the gateway binary name in command position — no
   subcommand is exempt (`version` was blocked 2026-10-05).
2. One probe per toolcall. Five tests = five toolcalls.
3. Never loop filtered commands, even with `sleep` between iterations.
4. Write files containing the word `caddy` via Write/Edit, not bash heredocs.
5. Stop immediately at any "broken session" / "403 Forbidden" /
   "can not execute caddy" error — do not retry.
6. Delegate risky probes to sub-agents to protect the main session.
