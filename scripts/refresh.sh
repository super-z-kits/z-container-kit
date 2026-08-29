#!/usr/bin/env bash
# refresh.sh — account-level kit refresh (kit v4.0)
#
# The kit is ZERO-INSTALL: ONE canonical copy per account at
# /home/user_skills/z-container-kit/. This script refreshes that copy from a
# kit SOURCE (a clone/checkout of github.com/super-z-kits/z-container-kit —
# typically /tmp/my-project/kit or a build checkout), atomically
# (copy-then-swap: a concurrent session never sees a half-written package),
# and rebuilds the portable zip. It NEVER touches any project — project
# state is one line in $PROJ/.agents/config, managed by zk-init.
#
# Usage:
#   git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit
#   bash /tmp/my-project/kit/scripts/refresh.sh
# (or run it from any updated checkout; ZK_USK overrides for scratch tests)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
KIT="$(cd "$SCRIPT_DIR/.." && pwd)"
USK="${ZK_USK:-/home/user_skills}"
PKG="$USK/z-container-kit"
LIVE=0; [ "$USK" = /home/user_skills ] && LIVE=1
REFRESH_FAIL=0

kit_v() { sed -n 's/^  version: "\(.*\)"/\1/p' "$1/SKILL.md" 2>/dev/null | head -1; }

[ -f "$KIT/SKILL.md" ] || { echo "refresh.sh: SKILL.md not found near $SCRIPT_DIR" >&2; exit 1; }

echo "=== z-container kit refresh (source $(kit_v "$KIT")) ==="
echo "  source:       $KIT"
echo "  destination:  $PKG"
[ "$LIVE" = 1 ] || echo "  (scratch mode: ZK_USK=$USK)"

# never refresh onto ourselves (running FROM the canonical package)
if [ "$(cd "$KIT" && pwd)" = "$(cd "$PKG" 2>/dev/null && pwd 2>/dev/null || echo /nonexistent)" ]; then
  echo "[note] source IS the canonical package — nothing to refresh"
  echo "       to upgrade, clone/update the kit repo first, then run its refresh.sh"
  exit 0
fi

# ------------------------------------------------- package: copy-then-swap --
if [ -d "$USK" ]; then
  rm -rf "$PKG.incoming"
  if cp -r "$KIT" "$PKG.incoming" 2>/dev/null; then
    # strip VCS metadata + caches; the package must never be a nested repo
    rm -rf "$PKG.incoming/.git"
    find "$PKG.incoming" -name .git -exec rm -rf {} + 2>/dev/null
    find "$PKG.incoming" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
    # top-level config NEVER travels with the package (it is per-project state)
    rm -f "$PKG.incoming/config"
    # normalize modes (avoids mode-only git dirt in repos that track a copy)
    find "$PKG.incoming" -type f -exec chmod 0644 {} + 2>/dev/null
    if mv -f "$PKG.incoming" "$PKG" 2>/dev/null; then
      echo "[ok] canonical package -> $PKG (v$(kit_v "$PKG"))"
    else
      rm -rf "$PKG.incoming"
      echo "[warn] could not finalize $PKG (old copy kept)" >&2
      REFRESH_FAIL=1
    fi
  else
    rm -rf "$PKG.incoming"
    echo "[warn] copy to $PKG.incoming failed — canonical copy unchanged" >&2
    REFRESH_FAIL=1
  fi
else
  echo "[warn] $USK missing — cannot refresh the canonical package" >&2
  REFRESH_FAIL=1
fi

# ------------------------------------------------- portable zip -------------
# The platform CONSUMES /home/user_skills/z-container.zip at sub-agent session
# spawn (observed live, round-5 audit) — the zip is a delivery vehicle.
# zsave rebuilds it if missing between spawns; refresh.sh always rebuilds it.
if [ "$LIVE" = 1 ] && [ -d "$PKG" ]; then
  ZT="/tmp/.zk-zipstage-$$"
  rm -rf "$ZT"; mkdir -p "$ZT"
  if cp -r "$PKG" "$ZT/z-container" 2>/dev/null; then
    rm -rf "$ZT/z-container/.git"
    rm -f "$ZT/z-container/config"
    if (cd "$ZT" && zip -qr z-container.zip z-container) 2>/dev/null \
       && mv -f "$ZT/z-container.zip" "$USK/z-container.zip" 2>/dev/null; then
      echo "[ok] portable zip -> $USK/z-container.zip"
    else
      echo "[warn] could not rebuild $USK/z-container.zip (previous copy kept)" >&2
    fi
  fi
  rm -rf "$ZT"
fi

# ------------------------------------------------- account-level cleanups ----
if [ "$LIVE" = 1 ]; then
  # Friction #12 (v3-era): pre-v3.1 zsave wrote PAT-bearing URLs to /home/sync
  # where ossfs ignores chmod (files sat world-readable at 0777). Canonical
  # copy is /home/user_skills/<prefix>-remote.url (PolarFS, 0600).
  for f in /home/sync/*-remote.url; do
    [ -f "$f" ] || continue
    rm -f "$f" 2>/dev/null && echo "[ok] removed stale $f (0777 PAT-leak fix; canonical copy lives in /home/user_skills/)"
  done
fi

if [ "$REFRESH_FAIL" = 1 ]; then
  echo "refresh.sh: FINISHED WITH FAILURES — see [warn] lines above" >&2
  exit 1
fi
echo
echo "=== refresh complete (canonical package v$(kit_v "$PKG")) ==="
echo "  all projects on this account now use this version (zero-install: no"
echo "  per-project copies exist to go stale). Verify a project with:"
echo "    bash $PKG/scripts/zsession"
