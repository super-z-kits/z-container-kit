#!/usr/bin/env bash
# refresh.sh — account-level kit refresh (kit v5.0)
#
# The kit is ZERO-INSTALL: ONE canonical copy per account at
# /home/user_skills/z-container-kit/. This script refreshes that copy from a
# kit SOURCE (a clone/checkout of github.com/super-z-kits/z-container-kit —
# typically /tmp/my-project/kit or a build checkout), atomically
# (per-run staging + rename-aside swap — a concurrent session never sees a
# TORN kit; worst case one racing command errors once and works on re-run),
# and rebuilds the portable zip. It NEVER touches any project — project
# state is one line in $PROJ/.agents/config, managed by zk-init.
#
# refresh.sh is the ONE conscious account-level maintenance operation (the
# static rule's sanctioned write #1): kit refresh + zip rebuild + stale-artifact
# cleanups, including the old zcleanup-backups prune (keep newest 2 .pre-*
# backup dirs per skill — OF-14). Sessions never run it casually.
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

# ------------------------------------------------- package: rename-aside swap --
if [ -d "$USK" ]; then
  # per-run staging names: two concurrent refreshes never clobber each
  # other's staging tree (H-2 — a shared fixed name could swap a HALF-copied
  # tree in = torn kit). Stale leftovers from a KILLED refresh are removed —
  # age-gated (-mmin +10) so the glob can never delete a CONCURRENT refresh's
  # live staging/aside tree.
  INCOMING="$PKG.incoming.$$"
  ASIDE="$PKG.old.$$"
  find "$USK" -maxdepth 1 \( -name 'z-container-kit.incoming.*' -o -name 'z-container-kit.old.*' \) \
    -mmin +10 -exec rm -rf {} + 2>/dev/null
  rm -rf "$INCOMING"
  if cp -r "$KIT" "$INCOMING" 2>/dev/null; then
    # strip VCS metadata + caches; the package must never be a nested repo
    rm -rf "$INCOMING/.git"
    find "$INCOMING" -name .git -exec rm -rf {} + 2>/dev/null
    find "$INCOMING" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
    # top-level config NEVER travels with the package (it is per-project state)
    rm -f "$INCOMING/config"
    # normalize modes (avoids mode-only git dirt in repos that track a copy)
    find "$INCOMING" -type f -exec chmod 0644 {} + 2>/dev/null
    # rename-aside swap: the canonical dir is renamed AWAY, then the staging
    # tree renamed IN — two atomic directory renames, so a concurrent reader
    # sees the old OR the new tree, never a mix. (mv onto an existing dir
    # would nest INSIDE it — the v4 bug. The microsecond gap between the two
    # renames is the documented worst case: one racing command errors once.)
    if mv -f "$PKG" "$ASIDE" 2>/dev/null || [ ! -d "$PKG" ]; then
      if mv -f "$INCOMING" "$PKG" 2>/dev/null; then
        echo "[ok] canonical package -> $PKG (v$(kit_v "$PKG"))"
        rm -rf "$ASIDE"
      else
        echo "[warn] could not finalize $PKG" >&2
        [ -d "$ASIDE" ] && { rm -rf "$PKG"; mv -f "$ASIDE" "$PKG" 2>/dev/null; }  # put the old copy back
        rm -rf "$INCOMING"
        REFRESH_FAIL=1
      fi
    else
      rm -rf "$INCOMING"
      echo "[warn] could not move the old package aside — canonical copy unchanged" >&2
      REFRESH_FAIL=1
    fi
  else
    rm -rf "$INCOMING"
    echo "[warn] copy to staging failed — canonical copy unchanged" >&2
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
# H-1 (v5 static rule): the backup-dir prune lives HERE — refresh.sh is the
# one conscious account-level maintenance op (zcleanup-backups was a 4th
# unsanctioned user_skills writer and was deleted). Keep newest 2 .pre-*
# backup dirs per skill, delete the rest (OF-14). Only touches $USK, so a
# ZK_USK-overridden scratch run tests it safely.
find "$USK" -maxdepth 1 -type d \
  \( -name '*.pre-update-backup-*' -o -name '*.pre-export-*' \
     -o -name '*.pre-round-*' -o -name '*.pre-rollback-*' \) -printf '%f\n' 2>/dev/null \
  | sed 's/\.pre-.*//' | sort -u | while IFS= read -r s; do
    n=0
    while IFS= read -r b; do
      [ -n "$b" ] || continue
      n=$((n + 1))
      # $b is an ABSOLUTE path from ls -dt — do NOT prefix $USK again
      if [ "$n" -gt 2 ]; then
        rm -rf "$b" 2>/dev/null \
          && echo "[ok] pruned old backup dir: $(basename "$b") (keep newest 2 per skill — OF-14)"
      fi
    done <<< "$(ls -dt "$USK/$s".pre-* 2>/dev/null)"
  done

if [ "$REFRESH_FAIL" = 1 ]; then
  echo "refresh.sh: FINISHED WITH FAILURES — see [warn] lines above" >&2
  exit 1
fi
echo
echo "=== refresh complete (canonical package v$(kit_v "$PKG")) ==="
echo "  all projects on this account now use this version (zero-install: no"
echo "  per-project copies exist to go stale). Verify a project with:"
echo "    bash $PKG/scripts/zsession"
