# resolve-prefix.sh — sourced by other scripts to discover ZK_PREFIX.
# Resolution order (highest priority first):
#   1. Explicit ZK_PREFIX env var — including the value a CALLER just sourced
#      from .agents/config (the v3.1 canonical location; scripts source
#      "$SCRIPT_DIR/../config" BEFORE falling back to this file, so an
#      instantiated kit's prefix arrives here as tier 1)
#   2. ZK_PREFIX from /home/user_skills/*-config.env (legacy per-project
#      discovery; install.sh migrates it into .agents/config but leaves the
#      file in place — other v2.x-era tools may still read it)
#   3. SELF-HEALING: scan durable artifacts (/home/sync/*-state.env,
#      /home/sync/*-snapshots/, /home/user_skills/*-remote.url,
#      /home/user_skills/*-doppler.env) for any existing prefix — prevents
#      drift (Friction #11). Only if NO existing prefix is found:
#   3f. Derive from `git -C $PROJ remote get-url origin` (basename, sanitized)
#       — true cold start, no prior state
#   4. Fail loudly with actionable hint
#
# Why no .env tier: the platform REWRITES .env on every recycle (only .env —
# other files survive), so .env is documented as boot-managed, DATABASE_URL-
# only state. Teaching scripts to read ZK_PREFIX from .env invites a config
# that evaporates at the next boot. .agents/config (git-tracked) is the
# durable answer; tiers 2-4 below are the fallback chain.
#
# Usage: source this file at the top of any script that needs ZK_PREFIX.
#   source "$(dirname "$0")/resolve-prefix.sh"
# Sets PREFIX on success. Returns nonzero (or exits 1 in package mode) on
# failure — callers decide whether failure is fatal (zsave) or degradable
# (zsession prints cold-start help instead).

_resolve_prefix() {
  local PROJ PRE

  # (1) Explicit env var override — always wins
  if [ -n "${ZK_PREFIX:-}" ]; then
    PREFIX="$ZK_PREFIX"
    return 0
  fi

  PROJ="${ZK_PROJ:-/home/z/my-project}"
  local USK="${ZK_USK:-/home/user_skills}"   # scratch-testing override
  local SYNC="${ZK_SYNC:-/home/sync}"        # scratch-testing override

  # (2) Legacy per-project discovery via /home/user_skills/*-config.env
  local configs count
  configs=$(ls "$USK"/*-config.env 2>/dev/null || true)
  count=$(printf '%s\n' "$configs" | grep -c . 2>/dev/null || echo 0)
  if [ "$count" = "1" ]; then
    # Single config — unambiguous, use it
    # shellcheck disable=SC1090
    source "$configs" 2>/dev/null || true
    if [ -n "${ZK_PREFIX:-}" ]; then
      PREFIX="$ZK_PREFIX"
      return 0
    fi
  fi
  # (count = 0 OR count > 1: fall through to (3))

  # (3) SELF-HEALING: scan for any existing prefix in durable artifacts BEFORE
  # deriving from the git remote URL. This prevents prefix drift (Friction #11):
  # if a prior session used ZK_PREFIX=zk but the git remote basename is
  # zk-stress-test, naive derivation would orphan all zk-* state/cred/doppler
  # files. By scanning existing artifacts first, the derivation agrees with
  # whatever prefix prior sessions used. Only derive from the remote URL if
  # NO existing prefix is found anywhere.
  local existing_prefix=""
  # (3a) Scan /home/sync/*-state.env (recycle detector files — per-chat but
  #      reflect whatever prefix was last zsave'd in this chat)
  for f in "$SYNC"/*-state.env; do
    [ -f "$f" ] || continue
    # state.env is parsed with sed (never sourced); ZK_PREFIX= is one of the keys
    p=$(sed -n 's/^ZK_PREFIX=//p' "$f" 2>/dev/null | head -1)
    if [ -n "$p" ]; then
      existing_prefix="$p"
      break
    fi
  done
  # (3b) Scan /home/sync/*-snapshots/ dirs (per-chat, but reveal prior prefixes)
  if [ -z "$existing_prefix" ]; then
    for d in "$SYNC"/*-snapshots; do
      [ -d "$d" ] || continue
      # dir name format: <prefix>-snapshots
      p=$(basename "$d" | sed -E 's/-snapshots$//')
      if [ -n "$p" ] && [ "$p" != "*" ]; then
        existing_prefix="$p"
        break
      fi
    done
  fi
  # (3c) Scan /home/user_skills/*-remote.url (cross-chat, PolarFS — most durable)
  if [ -z "$existing_prefix" ]; then
    for f in "$USK"/*-remote.url; do
      [ -f "$f" ] || continue
      p=$(basename "$f" | sed -E 's/-remote\.url$//')
      if [ -n "$p" ] && [ "$p" != "*" ]; then
        existing_prefix="$p"
        break
      fi
    done
  fi
  # (3d) Scan /home/user_skills/*-doppler.env (cross-chat, PolarFS)
  if [ -z "$existing_prefix" ]; then
    for f in "$USK"/*-doppler.env; do
      [ -f "$f" ] || continue
      p=$(basename "$f" | sed -E 's/-doppler\.env$//')
      if [ -n "$p" ] && [ "$p" != "*" ]; then
        existing_prefix="$p"
        break
      fi
    done
  fi
  # (3e) Scan /home/user_skills/*-config.env (single-config case already handled
  #      in step 2, but in multi-config scenarios, pick the first one as a tie-
  #      breaker rather than failing — better than deriving from remote URL)
  if [ -z "$existing_prefix" ] && [ "$count" -ge 1 ] 2>/dev/null; then
    first_config=$(printf '%s\n' "$configs" | head -1)
    if [ -n "$first_config" ] && [ -f "$first_config" ]; then
      # shellcheck disable=SC1090
      p=$(source "$first_config" 2>/dev/null && printf '%s' "${ZK_PREFIX:-}")
      if [ -n "$p" ]; then
        existing_prefix="$p"
      fi
    fi
  fi
  if [ -n "$existing_prefix" ]; then
    PREFIX="$existing_prefix"
    return 0
  fi

  # (3f) Last resort: derive from git remote URL — true cold start, no prior state
  local remote_url derived
  remote_url=$(git -C "$PROJ" remote get-url origin 2>/dev/null || true)
  if [ -n "$remote_url" ]; then
    # Examples:
    #   https://ghp_xxx@github.com/user/my-project.git -> my-project
    #   git@github.com:user/my-cool-repo              -> my-cool-repo
    #   https://github.com/user/zk-stress-test        -> zk-stress-test
    derived=$(printf '%s' "$remote_url" \
      | sed -E 's|^[^:]+://||; s|.*[:/]||; s|\.git$||; y/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/' \
      | tr -dc 'a-z0-9-' \
      | head -c 24)
    if [ -n "$derived" ]; then
      PREFIX="$derived"
      return 0
    fi
  fi

  # (4) Fail loudly with actionable hint
  {
    echo "ZK_PREFIX not discoverable. Set one of:" >&2
    echo "  (a) ZK_PREFIX=<name> bash <script>                          # explicit override" >&2
    echo "  (b) .agents/config in your repo: ZK_PREFIX=<name>           # canonical (run install.sh)" >&2
    echo "  (c) echo 'ZK_PREFIX=<name>' > ${ZK_USK:-/home/user_skills}/<name>-config.env  # legacy discovery" >&2
    echo "  (d) git -C $PROJ remote add origin <url>                    # derive ZK_PREFIX from URL basename" >&2
    if [ "$count" -gt 1 ] 2>/dev/null; then
      echo "  (multiple config.env files found — pass ZK_PREFIX explicitly to disambiguate)" >&2
      printf '%s\n' "$configs" | sed 's/^/    /' >&2
    fi
  }
  return 1
}

_resolve_prefix
