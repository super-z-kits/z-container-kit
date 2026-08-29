# resolve-prefix.sh — sourced by other scripts to read ZK_PREFIX.
# (kit v4.1 — identity is CONFIGURATION, not discovery; the .env pattern)
#
# The kit is ZERO-INSTALL: scripts live once per ACCOUNT (canonical package
# at /home/user_skills/z-container-kit/) and are location-agnostic. Project
# identity comes from the PROJECT, never from this script's own location.
#
# Resolution order — exactly TWO sources, nothing else:
#   1. ZK_PREFIX env var — explicit one-off override (tests, single commands)
#   2. $PROJ/.agents/config — one line `ZK_PREFIX=<name>`: git-tracked,
#      travels with the repo, comes back on reset --hard, survives container
#      recycles (the platform rewrites .env but never touches .agents/config).
#      THE canonical location.
#
# If neither is set we FAIL LOUDLY with the zk-init recipe. There is NO
# artifact scanning and NO URL guessing, by design: on a multi-repo account,
# shared /home/user_skills and /home/sync files are ambiguous evidence, not
# identity — auto-adopting from them is how the v3 "zk-onboard-test"
# cross-contamination happened. A missing config is a one-command fix
# (zk-init); a wrong silent guess is data loss.
#
# Why no .env tier: the platform REWRITES .env on every recycle (only .env —
# other files survive). .agents/config is the boot-safe equivalent.
#
# Usage: source this file at the top of any script that needs ZK_PREFIX.
#   source "$(dirname "$0")/resolve-prefix.sh"
# Sets PREFIX on success (return 0). Returns 1 on failure — callers decide
# whether failure is fatal (zsave) or degradable (zsession prints the
# zk-init recommendation instead).

_ZK_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"

_zk_strip_quotes() { printf '%s' "$1" | tr -d "\"'"; }

_resolve_prefix() {
  local PROJ p

  # (1) explicit env var — always wins
  if [ -n "${ZK_PREFIX:-}" ]; then
    PREFIX="$ZK_PREFIX"
    return 0
  fi

  # (2) project config — the canonical identity (.env pattern)
  PROJ="${ZK_PROJ:-/home/z/my-project}"
  if [ -f "$PROJ/.agents/config" ]; then
    p="$(_zk_strip_quotes "$(sed -n 's/^ZK_PREFIX=//p' "$PROJ/.agents/config" 2>/dev/null | head -1)")"
    if [ -n "$p" ]; then
      PREFIX="$p"
      return 0
    fi
  fi

  # (3) loud failure — configuration missing, never guessed
  {
    echo "resolve-prefix: ZK_PREFIX is not configured for $PROJ." >&2
    echo "  Identity is configuration (.env pattern). Fix with ONE of:" >&2
    echo "    (a) bash $_ZK_SCRIPTS_DIR/zk-init <name>    # writes $PROJ/.agents/config (canonical)" >&2
    echo "    (b) ZK_PREFIX=<name> <command>              # explicit one-off override" >&2
    echo "  (no artifact scanning, no URL guessing — a wrong silent guess is worse than a loud miss)" >&2
  }
  return 1
}

_resolve_prefix
