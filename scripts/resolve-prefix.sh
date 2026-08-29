# resolve-prefix.sh — sourced by other scripts to discover ZK_PREFIX.
# (kit v4.0 — PROJ-based identity: the .env pattern)
#
# The kit is ZERO-INSTALL: scripts live once per ACCOUNT (canonical package
# at /home/user_skills/z-container-kit/) and are location-agnostic. Project
# identity comes from the PROJECT, never from this script's own location:
#
# Resolution order (highest priority first):
#   1. ZK_PREFIX env var — explicit override (tests, one-off commands)
#   2. $PROJ/.agents/config — the project's zk env, one line
#      `ZK_PREFIX=<name>`: git-tracked, travels with the repo, survives boot
#      (the platform only rewrites .env). THE canonical location. v3.x repos
#      already carry this exact file — zero migration needed.
#   3. Exactly one legacy $USK/*-config.env (v2-era) — used, with a stderr
#      migration hint
#   4. Origin-URL basename — ONLY when unambiguous:
#        - no prefix artifacts exist anywhere (true first project), or
#        - existing artifacts MATCH the derived name (resuming the project)
#      If artifacts exist with DIFFERENT prefixes, this FAILS and lists them.
#      Shared artifacts are NEVER silently adopted: on a multi-repo account
#      they are ambiguous evidence, not identity (the "zk-onboard-test"
#      lesson — a stale test project's prefix leaked into the next session).
#   5. Loud failure with the setup recipe.
#
# Artifact prefixes (state/snapshots/credential/doppler files) are per-USER;
# they are used for conflict DETECTION and reporting (_zk_found_prefixes),
# never for silent resolution.
#
# Why no .env tier: the platform REWRITES .env on every recycle (only .env —
# other files survive). .agents/config is the boot-safe equivalent.
#
# Usage: source this file at the top of any script that needs ZK_PREFIX.
#   source "$(dirname "$0")/resolve-prefix.sh"
# Sets PREFIX on success (return 0). Returns 1 on failure — callers decide
# whether failure is fatal (zsave) or degradable (zsession prints cold-start
# help instead). Also defines _zk_found_prefixes for reporting.

_ZK_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"

# All prefix-ish artifacts on this account (space-separated, deduped, sorted).
# Read-only; used for conflict detection + zsession display.
_zk_found_prefixes() {
  local p pfx=""
  local USK="${ZK_USK:-/home/user_skills}"
  local SYNC="${ZK_SYNC:-/home/sync}"
  for f in "$SYNC"/*-state.env; do
    [ -f "$f" ] || continue
    p="$(sed -n 's/^ZK_PREFIX=//p' "$f" 2>/dev/null | head -1 | tr -d "\"'")"
    [ -n "$p" ] && pfx="$pfx $p"
  done
  for d in "$SYNC"/*-snapshots; do
    [ -d "$d" ] || continue
    p="$(basename "$d" | sed -E 's/-snapshots$//')"
    [ -n "$p" ] && [ "$p" != "*-snapshots" ] && pfx="$pfx $p"
  done
  for f in "$USK"/*-remote.url "$USK"/*-doppler.env; do
    [ -f "$f" ] || continue
    p="$(basename "$f" | sed -E 's/-(remote\.url|doppler\.env)$//')"
    [ -n "$p" ] && pfx="$pfx $p"
  done
  printf '%s\n' $pfx | sort -u | grep -v '^$' | tr '\n' ' '
}

_zk_strip_quotes() { printf '%s' "$1" | tr -d "\"'"; }

_zk_fail_recipe() {
  local PROJ="$1" USK="$2" found="$3" configs="$4"
  {
    echo "ZK_PREFIX not set for this project. Fix with ONE of:" >&2
    echo "  (a) bash "$_ZK_SCRIPTS_DIR/zk-init" <name>        # canonical: writes $PROJ/.agents/config" >&2
    echo "  (b) ZK_PREFIX=<name> bash <script>          # explicit one-off override" >&2
    if git -C "$PROJ" remote get-url origin >/dev/null 2>&1; then
      echo "  (c) a remote exists — write the config (a) or pass ZK_PREFIX (b)" >&2
    else
      echo "  (c) git -C $PROJ remote add origin <url>    # derive from URL basename (if unambiguous)" >&2
    fi
    [ -n "$found" ] && echo "  existing prefixes on this account:$found — pick THIS project's, not another's" >&2
    [ -n "$configs" ] && printf '%s\n' "$configs" | sed 's/^/    legacy: /' >&2
  }
}

_resolve_prefix() {
  local PROJ USK SYNC p f derived found configs count

  # (1) explicit env var — always wins
  if [ -n "${ZK_PREFIX:-}" ]; then
    PREFIX="$ZK_PREFIX"
    return 0
  fi

  PROJ="${ZK_PROJ:-/home/z/my-project}"
  USK="${ZK_USK:-/home/user_skills}"
  SYNC="${ZK_SYNC:-/home/sync}"

  # (2) project config — the canonical identity (.env pattern)
  if [ -f "$PROJ/.agents/config" ]; then
    p="$(_zk_strip_quotes "$(sed -n 's/^ZK_PREFIX=//p' "$PROJ/.agents/config" 2>/dev/null | head -1)")"
    if [ -n "$p" ]; then
      PREFIX="$p"
      return 0
    fi
  fi

  # (3) legacy single config.env (v2-era per-project discovery). Conflict-
  # checked like tier 4: if the origin URL derives a DIFFERENT prefix, this
  # is ambiguous on a multi-repo account — fail loudly instead of silently
  # adopting the legacy value (MED-3, round 8 validation).
  configs=$(ls "$USK"/*-config.env 2>/dev/null || true)
  count=$(printf '%s\n' "$configs" | grep -c . 2>/dev/null || true)
  if [ "$count" = "1" ]; then
    p="$(_zk_strip_quotes "$(sed -n 's/^ZK_PREFIX=//p' "$configs" 2>/dev/null | head -1)")"
    if [ -n "$p" ]; then
      local ru
      ru=$(git -C "$PROJ" remote get-url origin 2>/dev/null || true)
      if [ -n "$ru" ]; then
        local rd
        rd=$(printf '%s' "$ru" \
          | sed -E 's|^[^:]+://||; s|.*[:/]||; s|\.git$||; y/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/' \
          | tr -dc 'a-z0-9-' | head -c 24)
        if [ -n "$rd" ] && [ "$rd" != "$p" ]; then
          echo "resolve-prefix: AMBIGUOUS — legacy $configs says '$p' but the origin URL" >&2
          echo "  derives '$rd'. Refusing to guess between projects; make it explicit:" >&2
          found="$(_zk_found_prefixes)"
          _zk_fail_recipe "$PROJ" "$USK" "$found" "$configs"
          return 1
        fi
      fi
      echo "resolve-prefix: using legacy $configs — migrate to the project config:" >&2
      echo "  echo 'ZK_PREFIX=$p' > $PROJ/.agents/config && rm '$configs'" >&2
      PREFIX="$p"
      return 0
    fi
  fi
  # (count = 0 OR > 1: fall through — multiple legacy configs are ambiguous
  # on a multi-repo account; they surface in the failure recipe, never pick)

  found="$(_zk_found_prefixes)"

  # (4) origin-URL basename — only when unambiguous
  local remote_url
  remote_url=$(git -C "$PROJ" remote get-url origin 2>/dev/null || true)
  if [ -n "$remote_url" ]; then
    derived=$(printf '%s' "$remote_url" \
      | sed -E 's|^[^:]+://||; s|.*[:/]||; s|\.git$||; y/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/' \
      | tr -dc 'a-z0-9-' \
      | head -c 24)
    if [ -n "$derived" ]; then
      if [ -z "$found" ]; then
        PREFIX="$derived"
        echo "resolve-prefix: derived ZK_PREFIX=$derived from the origin URL (no prior state — first project on this account)." >&2
        echo "  pin it in the repo: echo 'ZK_PREFIX=$derived' > $PROJ/.agents/config" >&2
        return 0
      fi
      case " $found " in
        *" $derived "*)
          PREFIX="$derived"   # existing artifacts match — resuming this project
          return 0
          ;;
        *)
          echo "resolve-prefix: AMBIGUOUS — the origin URL derives '$derived' but this" >&2
          echo "  account's artifacts use:$found" >&2
          echo "  Refusing to guess between projects. Make this project's identity explicit:" >&2
          _zk_fail_recipe "$PROJ" "$USK" "$found" "$configs"
          return 1
          ;;
      esac
    fi
  fi

  # (5) loud failure
  _zk_fail_recipe "$PROJ" "$USK" "$found" "$configs"
  return 1
}

_resolve_prefix
