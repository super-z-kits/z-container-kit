# Long-running mode & the cron tool — deep dive

The platform's **long-running tasks** feature exposes a `cron` tool to the agent so a
session can schedule its own future re-prompts (and the platform can schedule isolated
reviewer runs after web-dev). This KB is the verified-live operator's manual for that
machinery — every claim graded **[V]** verified live 2026-09-09, **[I]** inferred, **[?]**
open. Experiments A (one_time) + B (fixed_rate recurring) ran end-to-end across user-driven
and cron-fired rounds; raw evidence in the originating research repo
(`zikomolapoutl/zai-cron-research-20260909-030712`, private).

## TL;DR — the four questions

| Question | Answer | Confidence |
|---|---|---|
| Can I customize the re-prompt message? | **Yes** — `payload.kind="agentTurn"` + arbitrary `payload.message`, delivered verbatim. (`webDevReview` is NOT customizable — platform template.) | High [V] |
| Does cron work outside long-running mode? | **No** — tool is mode-gated at INJECTION level (doctrine still in the prompt). | High [V] (A/B) |
| Interval / count / message all controllable? | **Interval yes** (cron-expr / fixed_rate-sec / one_time-epoch). **Count: no native cap** (`MaxAttempt=0`); stop via `delete` or N one_time jobs. **Message yes** (see above). | High [V] |
| Recurring `agentTurn` actually fires repeatedly? | **Yes** — proven over 4 fires on a 300s grid. | High [V] |

## The tool surface

Actions: `create` / `list` / `get` / `delete`. `list` accepts `includeDisabled` and
`name` filters. `get`/`delete` take `jobId` (numeric string).

`create` knobs:
- `name` — human label (free text).
- `schedule.kind` ∈ `{cron, fixed_rate, one_time}`:
  - `cron` → `expr` = 6-field cron (`sec min hour day month week`, e.g. `0 0 9 * * ?`).
  - `fixed_rate` → `expr` = **seconds** as a string (`"300"` = 5 min). Doctrine says min
    5 min for the recurring cadence; **fire #1 is always immediate regardless** (see
    "Interval model" below).
  - `one_time` → `expr` = epoch-millis string OR `yyyy-MM-dd HH:mm:ss` (interpreted in
    `schedule.tz`).
- `schedule.tz` — IANA tz (default `Asia/Shanghai` if omitted). **Always set it
  explicitly** for one_time/cron; for fixed_rate it is cosmetic but harmless.
- `payload.kind` ∈ `{agentTurn, webDevReview}` (see next section).
- `payload.message` — arbitrary text. This IS the re-prompt body for `agentTurn`. Length
  not bounded in testing (multi-paragraph protocols delivered intact).
- `params.priority` ∈ `{1,5,10,15}` — **captured but NOT wired** to the scheduler's
  native Priority (stays 0). Cosmetic. [V]

### `agentTurn` vs `webDevReview` — the critical distinction

| | `agentTurn` | `webDevReview` |
|---|---|---|
| Runs WHERE | **in the bound live session** (same chat/container) | **isolated reviewer run** (separate context) |
| Message | **your custom `payload.message`, verbatim** | **platform template** (generic, self-directed — "independently select work focus", "[Mandatory] Add more features!!!") |
| Use for | custom recurring prompts into an ongoing chat | autonomous dev/QA loop after web-dev work |
| Can the fired round use `cron`? | **NO** (tool stripped — see below) | untested (isolated context) |

**The "generic non-customizable message" experience = the `webDevReview` path, by design.**
For custom recurring prompts into a LIVE session, use `agentTurn` + `fixed_rate` +
your own `message`. The platform's long-running web-dev model is a background loop of
isolated `webDevReview` reviewers coordinating via `worklog.md`, NOT in-session re-prompts.

## What the harness adds around your message (the envelope) [V]

A fired `agentTurn` delivers your `payload.message` wrapped in a standard envelope:

```
<task>
[System 2026-09-09 11:13:31 +08:00]   <- header: backend wall-clock, always +08:00
<your payload.message, byte-for-byte>
Job ID: 370097                          <- footer: the numeric job id
</task>
```

- `<task>`/`</task>` tags wrap the whole body.
- The `[System <ts>]` header is the **fire/schedule time** (backend +08:00, second
  resolution). It equals the requested one_time instant, or the fixed_rate fire instant.
- `Job ID: <id>` footer.
- Your text sits inside, unmodified — **verbatim delivery proven** (proof markers, step
  lists, exact wording all matched storage).

## Gateway trace marking [V]

A cron-fired turn's gateway `trace_id` = `<creating-round-trace>-cron-agent-loop-<YYYYMMDDHHmm>`
where the stamp is backend +08:00 at minute resolution. Identifiable from inside the turn
(the IM-context JSON carries it). Use it to distinguish user-driven vs cron-fired rounds
without reading the message.

## Same-container delivery [V]

A fire does NOT recycle the container or spawn a new chat — it continues the SAME live
session (same git HEAD, same working tree, same `.git`). End-to-end latency ~24 s for a
scheduled one_time; ~1 s for the first fixed_rate fire. `uptime`/mtimes confirm no recycle.

## ⚠ The cron tool is STRIPPED in cron-fired rounds [V]

**The single most important gotcha.** In cron-fired rounds (trace suffixed
`-cron-agent-loop`), the `cron` tool is NOT available — 7/7 and 8/8 dispatch failures
across two experiments, vs 4/4 success in user-driven rounds. Refined rule: **tool binding
is per-TURN, set by the trigger (user vs cron), NOT by message composition** — a user
message merged into a cron-claimed turn does NOT restore cron tooling.

Consequences:
- **A recurring cron CANNOT self-delete from its own fired round.** Stopping it requires a
  user-driven round (you, manually) or the harness UI. Design every recurring-cron workflow
  so cleanup happens in a round YOU trigger.
- A fired round cannot inspect its own job (`get`), list jobs, or create new ones.
- **Send manual messages OUTSIDE fire windows** — if a fire claims your turn, your message
  is handled by a tool-less (cron-wise) turn.

## ⚠ Concurrent turns — a fire does NOT queue behind an active user round [V]

mtime forensics proved a cron fire spawns a **parallel agent turn on the same
container/checkout** while a user-driven round is still running. `MaxConcurrency=1` is
**per-JOB** (no overlapping fires of one job), NOT per-session turn arbitration —
session-level turns CAN overlap.

Hazards + mitigations:
- **Same-file write races are real.** Two turns editing the same file clobber each other.
  Mitigations that held: worklog append-only convention; `zsave`'s per-container lock
  (`/tmp/.zsave.lock`) serializes commits; git auto-rebase on push rejection. **Best
  practice for any turn that may overlap a fire window: RE-READ files immediately before
  writing; keep writes append-only; commit+push promptly.**

## Interval model (fixed_rate) [V]

Tested with `expr="300"` (300 s). Observed fire schedule times (`[System ts]`):
- **fire #1: IMMEDIATE** (t ≈ creation + 1 s). Not interval-delayed.
- **fire #2: at creation + 2×interval** (backend's initial-`next` quirk; the `get`
  response's `next` field equals this).
- **fire #3+: every interval** (next = prev_next + interval).

So a 300 s cron fires at roughly: t≈0, t=600 s, t=900 s, t=1200 s, … The doctrine's
"minimum interval 5 minutes" is accurate for the recurring cadence; the only anomaly is
the first-gap/initial-next computation (fire #2 lands one interval "late"). **Practical:
expect fire #1 instantly; expect fire #2 at 2×interval; from fire #3 it's on the grid.**

`one_time` fires once at the requested instant (epoch-ms or `yyyy-MM-dd HH:mm:ss` in
`schedule.tz`), then **auto-purges** (does not linger disabled) [V].

## Queue / delivery-lag semantics [V]

Fires that land while a fired turn is already running are **QUEUED, not skipped**
(`MissWorkerEnable=false` refers to alerting, not skipping). Two independent timestamps
per fire:
- `[System ts]` = **schedule time** (fires are generated on schedule regardless of session
  state; they can pipeline — fire #N+1 scheduled while fire #N is mid-turn).
- trace-suffix stamp = **turn-start time** (waits for the previous fire's turn to finish;
  observed lag 0–6.5 min under load).

Under sustained load, delivery lag grows but **no fire is lost** — `MaxConcurrency=1`
serializes fire TURNS. If your fired turns run long (near the 2 h per-run timeout), expect a
backlog of queued fires to drain afterward.

## Backend internals (from `cron get`) [V]

Captured at create time into the job record:
- `im_context` — `{zai_chat_id, session_id, channel, trace_id, zai_user_id, …}`: **the
  cron is bound to the creating chat+session+trace**. This is how an `agentTurn` finds the
  live session to re-prompt.
- `app_id: cronjob-gateway-prod` — the scheduler service.
- `MaxConcurrency: 1` — per-job, no overlapping fires (turns still overlap — see above).
- `MaxAttempt: 0` — **no run-count cap** (truly recurring until deleted). [?] whether 0
  means infinite vs "default retry" — observed no stop after 4 fires.
- `Timeout: 7200` — **2 h soft per-run timeout** per fire.
- backend clock: **+08:00** (Asia/Shanghai).
- `TimeConfig.TimeType`: **5 = one_time, 3 = fixed_rate** [V]. cron-expr kind's value
  **untested** [?] — create a cron-expr job, `get`, `delete` to map it (likely 1 or 2).
- `next` field: **valid ISO time for recurring**; **garbage overflow (year-58658) for
  one_time** (harmless — one_time has already fired/purged by the time you'd read it).
- `execution: {stage, info}` — recurring lifecycle field; observed `stage:"started"`.
  [?] full enum untested.
- `params.priority` stored in `Parameters` JSON, but native `Priority: 0` — **priority is
  captured-but-not-wired** [V]. Do not rely on it for ordering.

## Mode-gating (A/B confirmed) [V]

The `cron` tool is injected **only when long-running mode is enabled** for the session.
A/B test result (user's non-long-running session): 15 tools available (`Task, Bash, Glob,
Grep, LS, Read, Edit, MultiEdit, Write, TodoWrite, TodoRead, Skill, Complete,
AskUserQuestion, Outline`), **none named `cron`** — BUT the system prompt STILL contained
the full cron doctrine (min interval 5 min, set tz, kind semantics) byte-for-byte.

**Conclusion: the gate is at tool-INJECTION level, not prompt level.** The harness ships
cron doctrine to every session but only binds the callable when long-running mode is on.
→ You cannot "use" cron in a non-long-running chat even if you know the schema; you must
enable the mode (platform-side toggle) first.

## No in-container doctrine [V]

There is NO long-running/cron/webDevReview skill doc anywhere in-container
(`/home/user_skills`, `/home/official_skills`, `/start.sh`, `/app`, `/opt`, `/etc` all
clean). The system-prompt rule IS the doc; the entire machinery (cronjob-gateway-prod,
envelope injection, trace marking, tool-binding gate) is **platform-side, invisible to the
container**. Implication: you cannot inspect or debug the scheduler from inside — only
observe its effects (fired messages, `cron get` responses, trace stamps).

## Template placeholders are NOT interpolated [V]

`payload.message` is **static text**. A `FIRE #<count>` placeholder is delivered literally
as `<count>` — the fired agent must compute its own state (e.g. count prior worklog
sections). Do not expect the scheduler to substitute values into your message.

## Recommended workflows

1. **Custom recurring prompt into a live session** →
   `agentTurn` + `fixed_rate` + your own `message` + `tz`. Expect fire #1 instantly, fire
   #2 at 2×interval, then on-grid. Plan cleanup from a user round.
2. **Autonomous dev/QA loop after web-dev** → `webDevReview` (platform-blessed, every 15 min
   via the system-prompt "Important Rule"). Isolated reviewer; coordinate via `worklog.md`.
   Message is NOT customizable — that's by design.
3. **One-shot future reminder into a session** → `agentTurn` + `one_time` + epoch-ms + your
   message. Auto-purges after firing.
4. **Any recurring cron** → always document the `job_id` + a `delete` instruction in
   `worklog.md` so a future user round can stop it (fired rounds cannot).
5. **Fired-round protocol design** → keep it self-contained (read worklog → do bounded work
   → append-only write → push → stop). Assume NO cron tool. Assume possible concurrent
   turns (re-read before write, append-only, prompt push).

## Cleanup law (derived)

**Every recurring cron you create is your responsibility to delete from a user-driven
round.** Fired rounds cannot. Add the `cron delete jobId=<id>` line to your worklog the
moment you arm a recurring job. Unattended recurring crons fire indefinitely (MaxAttempt=0)
into the bound session — including while you sleep.

## Open questions [?] — candidates for a long-interval endurance cron

A long-interval `agentTurn` cron whose fired rounds each pick the next un-investigated
question, investigate it (using whatever tools the fired round has), document in worklog,
push, stop — turns each otherwise-idle wake into a research step:

- [?] `cron`-expr kind `TimeType` value (create a cron-expr job → `get` → `delete`, in a
  user round; expected 1 or 2).
- [?] MaxInterval ceiling — does the scheduler accept very large `fixed_rate` expr (e.g.
  432000 s = 5 d)? Silently cap? Reject?
- [?] `webDevReview` full behavior — does the isolated reviewer receive tools? what does it
  produce? (hard to observe from an `agentTurn` session — needs a web-dev project context.)
- [?] `execution.stage` full enum (seen `started`; what follows? `running`/`done`/`failed`?)
- [?] effect of session deletion/expiry on bound crons (do they orphan? auto-delete? error?)
- [?] DST / timezone edge cases for `cron`-expr jobs at tz boundaries.
- [?] whether fired rounds count against any session rate/quota limit.
- [?] `MaxAttempt=0` true semantics (infinite vs default-retry).
- [?] `MissWorkerEnable=false` full semantics (alerting-only confirmed; deeper?).
- [?] whether `params.priority` affects ANYTHING (queue ordering under backlog? currently
  appears no).

## Experiment provenance

- Exp A (one_time, job 370097): fired 2026-09-09 03:13:31 UTC, verbatim delivery proven,
  envelope/trace discovered, fired-round tool strip discovered (7/7).
- Exp B (fixed_rate 300s, job 370140): 4 fires observed (03:25:49 / 03:35:49 / 03:40:49 /
  03:45:49 UTC), 300s grid confirmed from fire #3, immediate-first-fire confirmed,
  queue/serialization confirmed, concurrent-turns confirmed, then deleted from a user round.
- Round-2 fired turn ran concurrently with the creating round-3 user turn (mtime proof);
  template-placeholder-non-interpolation confirmed (3×).
