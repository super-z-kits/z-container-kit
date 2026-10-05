# Bash tool output rendering — the two-layer invisible-bytes filter

Status: **[V]** 2026-10-05 — 72-case od-verified corpus (evidence/
EXPERIMENTS.md E19; matrix: `scratch/ansitest/matrix/`).

## The trap

An agent cats/greps a file containing ANSI escapes, sees garbage
(`[31PENDING`, `]0;title`) or seemingly MISSING text, and concludes the
file is corrupted. It is intact on disk — the Bash tool's OUTPUT
pipeline is a lossy filter. Judge bytes with `od -c`, never with
cat/echo/grep.

## Layer 1 — Bash output pipeline (lossy; before size accounting, preview, persistence)

- **R1 (SGR-eater):** every regex match of `\[[0-9;?]*m` is DELETED
  from the result text. The ESC prefix is NOT required — plain-text
  `[0m` / `[31m` / `[1;31m` with no escape byte anywhere is destroyed
  too. Params allow only `[0-9;?]`; final byte must be lowercase `m`;
  line-scoped (never crosses `\n`); leftmost scan. Applies to ANY Bash
  output (cat, echo, grep, ls) — and re-eats `cat -v`'s own `^[[31m`
  markers (double-mangling).
- **R2 (UTF-8 sanitize):** strict decode with replacement — each
  invalid byte → U+FFFD (persisted as EF BF BD); overlong rejected; NO
  latin-1 fallback.
- **R3:** everything else passes byte-exact — the persisted
  tool-results artifact still contains ESC, BEL, CR, NUL, TAB, DEL.
- **R4:** "Output too large (N KB)", the 30000-char truncation, the
  2KB preview and the persisted artifact are ALL computed on the
  post-R1/R2 text. Ground truth is NOT recoverable from the artifact.

## Layer 2 — display into agent context (Bash AND Read results)

ESC, BEL, BS, VT, FF, CR, SO, SI, DEL are invisible. CR and BS JOIN
fragments — never overwrite (`AAA\rXXX` → `AAAXXX`). NUL → one space.
TAB preserved. Not a terminal emulator: no clear/cursor/title handling.

## Tool differences

- **Read tool** skips Layer 1: shows SGR bodies (`pre[31mRED[0mPOST`) —
  the best human view; invalid bytes appear as LATIN-1 GLYPHS (`\xe9` →
  `é`); ESC/CR still invisible; refuses `.bin` files by EXTENSION
  (same bytes as `.txt` read fine).
- **Write tool + the Bash command channel** silently DROP raw ESC
  bytes (od-proven) — real-ESC files can only be created via bash
  escape expansion (`printf '\x1b'`, `echo -e`), programs, or
  downloads.

## Trigger → artifact table (what raw `cat` shows)

| bytes in the file | cat shows |
|---|---|
| `ESC[31m` … `ESC[m` (any well-formed SGR) | nothing — neighbors join seamlessly |
| literal `[0m` — NO ESC in the file | nothing — EATEN anyway (R1 needs no ESC) |
| `ESC[31` (incomplete CSI) | `[31PENDING` — body leaks as "garbage" |
| `ESC]0;title BEL` (OSC) | `]0;title` — body leaks |
| `ESC[2J` `ESC[?25l` (non-SGR CSI) | `[2J` `[?25l` — body leaks; no side effects |
| `AAA\rXXX` | `AAAXXX` — CR invisible, joins |
| `ABC\bX` | `ABCX` — BS invisible, no backstep |
| NUL / BEL / DEL | one space / nothing / nothing |
| `\xff`, `\xe9`, `0x9b` (invalid UTF-8) | U+FFFD per byte — strict UTF-8, no latin-1 |
| `EF BB BF` (BOM) | invisible zero-width char — passes through |

## Remedy ranking (validated on a worst-case composite)

1. `od -c FILE` (or `od -An -tx1`) — **fully reliable**; its output
   cannot contain the eaten pattern.
2. `base64 FILE` — fully reliable, lossless (roundtrip `cmp`
   identical); not human-readable.
3. Read tool — best second look (SGR bodies visible); refused on
   `.bin` extension; latin-1 glyphs for invalid bytes.
4. `cat -v` / `sed -n l` — PARTIAL: control-byte markers visible, but
   their own `[31m` output is re-eaten by R1. Bracket-breaking
   (`cat -v FILE | sed 's/\[/<LB>/g'`) restores full reliability.
5. `grep -a` — useless: identical mangling to cat (numerical counts
   via `grep -Fc` ARE immune).
