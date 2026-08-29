# resolve-prefix.sh — sourced by other scripts to discover ZK_PREFIX
# Auto-discovers ZK_PREFIX from /home/user_skills/*-config.env files.
# If exactly one, sources it. If zero, fails loudly. If multiple, fails with list.
#
# Usage: source this file at the top of any script that needs ZK_PREFIX.
#   source "$(dirname "$0")/resolve-prefix.sh"

_resolve_prefix() {
  local configs count
  configs=$(ls /home/user_skills/*-config.env 2>/dev/null || true)
  count=$(printf '%s\n' "$configs" | grep -c . 2>/dev/null || echo 0)
  
  if [ "$count" = "0" ]; then
    echo "ZK_PREFIX not configured — no /home/user_skills/*-config.env found." >&2
    echo "Run first-time setup:" >&2
    echo "  echo 'ZK_PREFIX=<your-project-name>' > /home/user_skills/<your-project>-config.env" >&2
    exit 1
  elif [ "$count" -gt 1 ]; then
    echo "Multiple project configs found in /home/user_skills/:" >&2
    printf '%s\n' "$configs" | sed 's/^/  /' >&2
    echo "Set ZK_PREFIX in the environment to disambiguate: ZK_PREFIX=<prefix> bash <script>" >&2
    exit 1
  fi
  
  source "$configs"
  
  if [ -z "${ZK_PREFIX:-}" ]; then
    echo "ZK_PREFIX not set in $configs" >&2
    exit 1
  fi
  
  PREFIX="$ZK_PREFIX"
}

_resolve_prefix
