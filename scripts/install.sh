#!/usr/bin/env bash
# install.sh — instantiate the z-container kit into your repo at .agents/
# (kit v3.1.0)
#
# Usage:
#   bash /home/user_skills/z-container-kit/scripts/install.sh   # normal upgrade
#   bash /tmp/my-project/kit/scripts/install.sh                 # cold-start (from a clone)
#   ZK_PREFIX=myapp bash <kit>/scripts/install.sh               # non-interactive prefix
#
# What it creates/refreshes in $PROJ (default /home/z/my-project):
#   .agents/                  the instantiated kit (git-tracked — COMMIT IT)
#     .agents/SKILL.md        survival guide (authoritative copy)
#     .agents/scripts/        helpers (source ../config for ZK_PREFIX)
#     .agents/kb/             deep-dive modules
#     .agents/evidence/       experiment logs backing [V] grades
#     .agents/config          ZK_PREFIX=<name>  (PRESERVED on upgrades)
#   scripts/<bash-helpers>    shims that exec into .agents/scripts/ (git-tracked)
#   scripts/<python-helpers>  real copies (python3 invocation is documented)
#   scripts/resolve-prefix.sh real copy (must stay sourceable)
#   skills/z-container/SKILL.md  symlink -> ../../.agents/SKILL.md (platform
#                             discovery; skills/ is git-ignored, recreated here)
# Plus (live project only):
#   /home/user_skills/z-container-kit/   read-only package refresh
#   /home/user_skills/z-container.zip    portable zip refresh
#   one-shot migrations: stale /home/sync/*-remote.url (mode-0777 PAT leak),
#   legacy kit copies ($PROJ/z-container-kit, $SYNC/z-container-kit,
#   $PROJ/download/z-container-kit)
#
# Idempotent: re-running upgrades .agents/ in place and always preserves
# .agents/config. Safe to run from ANY kit copy, including .agents/ itself.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="${ZK_PROJ:-/home/z/my-project}"
AGENTS="$PROJ/.agents"
USK="${ZK_USK:-/home/user_skills}"          # override for scratch testing
PKG="$USK/z-container-kit"
LIVE=0; [ "$PROJ" = "/home/z/my-project" ] && LIVE=1
INSTALL_FAIL=0

[ -f "$KIT/SKILL.md" ] || {
  echo "install.sh: SKILL.md not found near $SCRIPT_DIR" >&2
  exit 1
}

# kit version (for skew reporting)
kit_v() { sed -n 's/^  version: "\(.*\)"/\1/p' "$1/SKILL.md" 2>/dev/null | head -1; }

echo "=== z-container kit installer ($(kit_v "$KIT")) ==="
echo "  kit source: $KIT"
echo "  project:    $PROJ"
[ "$USK" = /home/user_skills ] || echo "  (scratch mode: ZK_USK=$USK — package refresh skipped)"

# ---------------------------------------------------------------- helpers ----
copy_tree() {  # copy_tree <src-kit> <dest-dir> <preserve-file...>
  # copy-then-swap; strips VCS metadata; normalizes modes; preserves the
  # listed files from the OLD destination (e.g. .agents/config, .installed-from)
  local src="$1" dst="$2"; shift 2
  local keep=("$@") kept=()
  if [ "$src" = "$dst" ]; then
    echo "[ok] already in place: $dst"
    return 0
  fi
  mkdir -p "$(dirname "$dst")" 2>/dev/null || { echo "[skip] $(dirname "$dst") not writable" >&2; return 0; }
  local sv dv
  sv="$(kit_v "$src")"; dv="$(kit_v "$dst")"
  if [ -n "$sv" ] && [ -n "$dv" ] && [ "$sv" != "$dv" ]; then
    echo "[note] version skew: source=$sv destination($dst)=$dv — installing source version"
  fi
  rm -rf "$dst.incoming"
  if cp -r "$src" "$dst.incoming" 2>/dev/null; then
    # strip VCS metadata: a kit source that is a git CLONE (cold-start path)
    # carries .git — planted into kit copies it turns them into nested repos.
    rm -rf "$dst.incoming/.git"
    find "$dst.incoming" -name .git -exec rm -rf {} + 2>/dev/null
    find "$dst.incoming" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
    # top-level config NEVER travels with a kit copy (it is per-project state)
    rm -f "$dst.incoming/config"
    # normalize: 0644 files (avoids mode-only git dirt; bash scripts run via
    # `bash <script>` so +x is unneeded — shims/installs set their own modes)
    find "$dst.incoming" -type f -exec chmod 0644 {} + 2>/dev/null
    # preserve caller-listed files from the old destination (OF-10 pattern)
    for k in "${keep[@]}"; do
      if [ -e "$dst/$k" ]; then
        mkdir -p "$dst.incoming/$(dirname "$k")" 2>/dev/null
        cp -a "$dst/$k" "$dst.incoming/$k" 2>/dev/null && kept+=("$k")
      fi
    done
    rm -rf "$dst"
    if mv -f "$dst.incoming" "$dst" 2>/dev/null; then
      echo "[ok] kit -> $dst${kept[*]:+ (preserved: ${kept[*]})}"
    else
      rm -rf "$dst.incoming"
      echo "[warn] could not finalize $dst (mv failed — old copy was replaced; re-run install)" >&2
      INSTALL_FAIL=1
    fi
  else
    rm -rf "$dst.incoming"
    echo "[warn] copy to $dst failed — previous copy (if any) kept" >&2
    INSTALL_FAIL=1
  fi
}

# ------------------------------------------------- step 1: .agents/config ----
# ONE resolution chain, shared with every other helper: source resolve-prefix.sh
# (env var -> legacy config.env -> durable-artifact scan -> remote-URL basename).
# The instantiated .agents/config, when present, is sourced FIRST so it arrives
# as tier 1 and always wins (preserved on upgrades, never re-derived).
CONFIG_SRC=""
if [ -f "$AGENTS/config" ]; then
  # shellcheck disable=SC1091
  . "$AGENTS/config"
  echo "[ok] .agents/config exists — ZK_PREFIX=${ZK_PREFIX:-?} (will be preserved)"
  CONFIG_SRC="preserved"
fi
if [ "$CONFIG_SRC" = "" ] && [ -z "${ZK_PREFIX:-}" ]; then
  # shellcheck disable=SC1091
  if source "$SCRIPT_DIR/resolve-prefix.sh" 2>/dev/null && [ -n "${PREFIX:-}" ]; then
    ZK_PREFIX="$PREFIX"
    CONFIG_SRC="auto-discovered (legacy config.env / artifact scan / origin-URL basename)"
    echo "[note] ZK_PREFIX=$ZK_PREFIX ($CONFIG_SRC)"
    echo "      If that is the WRONG project (e.g. a legacy config file from another project"
    echo "      of yours, or an unwanted URL-basename derivation), fix now:"
    echo "        rm $AGENTS/config 2>/dev/null; ZK_PREFIX=<name> bash \"$0\""
  fi
fi
if [ "$CONFIG_SRC" = "" ] && [ -z "${ZK_PREFIX:-}" ]; then
  # last resort: interactive prompt — ONLY when a TTY exists (agent bash
  # toolcalls have none; fail loudly instead of hanging)
  if [ -t 0 ]; then
    echo
    echo "  ZK_PREFIX is your project name (lowercase [a-z0-9-], max 24 chars)."
    echo "  It names credential/snapshot/state files in /home/user_skills/ and /home/sync/."
    printf "  Enter ZK_PREFIX: "
    read -r ZK_PREFIX_INPUT || ZK_PREFIX_INPUT=""
    if [ -n "$ZK_PREFIX_INPUT" ]; then
      ZK_PREFIX="$ZK_PREFIX_INPUT"
      CONFIG_SRC="interactive prompt"
    fi
  fi
fi
if [ ! -f "$AGENTS/config" ]; then
  if [ -z "${ZK_PREFIX:-}" ]; then
    echo
    echo "[fail] ZK_PREFIX unknown and no TTY to prompt. Fix with ONE of:" >&2
    echo "  (a) ZK_PREFIX=<name> bash $SCRIPT_DIR/install.sh" >&2
    echo "  (b) git -C $PROJ remote add origin <url>   # derive from URL basename" >&2
    echo "  (c) echo 'ZK_PREFIX=<name>' > $USK/<name>-config.env   # legacy discovery" >&2
    echo "  (d) run me from a TTY and answer the prompt" >&2
    exit 1
  fi
  case "$ZK_PREFIX" in
    *[!a-z0-9-]*|'')
      echo "[fail] ZK_PREFIX '$ZK_PREFIX' must be lowercase [a-z0-9-] (got invalid chars or empty)" >&2
      exit 1
      ;;
  esac
  if [ "${#ZK_PREFIX}" -gt 24 ]; then
    echo "[fail] ZK_PREFIX '$ZK_PREFIX' longer than 24 chars" >&2
    exit 1
  fi
  [ -n "$CONFIG_SRC" ] || CONFIG_SRC="env var"
fi

# ------------------------------------------------- step 2: instantiate ------
echo "--- step 2: instantiate .agents/ ---"
mkdir -p "$AGENTS"
copy_tree "$KIT" "$AGENTS" "config" ".installed-from"
if [ ! -f "$AGENTS/config" ]; then
  umask 022
  printf 'ZK_PREFIX=%s\n' "$ZK_PREFIX" > "$AGENTS/config"
  chmod 0644 "$AGENTS/config"   # committed, non-secret (project name only)
  echo "[ok] wrote .agents/config (ZK_PREFIX=$ZK_PREFIX, $CONFIG_SRC)"
else
  chmod 0644 "$AGENTS/config" 2>/dev/null || true
fi
chmod 0755 "$AGENTS/scripts/"* 2>/dev/null || true

# ------------------------------------------------- step 3: scripts/ ---------
echo "--- step 3: scripts/ (shims + python copies) ---"
mkdir -p "$PROJ/scripts"
SHIM_TEMPLATE='#!/bin/bash
# %NAME% — shim -> .agents/scripts/%NAME% (kit v3.1)
# Resolves its own location (works from any cwd; survives repo.tar as a real file).
TARGET="$(cd "$(dirname "$0")" && pwd)/../.agents/scripts/%NAME%"
if [ ! -f "$TARGET" ]; then
  echo "shim error: $TARGET missing — run install.sh from a kit copy" >&2
  exit 1
fi
case "$TARGET" in
  *.py) exec python3 "$TARGET" "$@" ;;
  *)    exec bash    "$TARGET" "$@" ;;
esac
'
BASH_HELPERS="zsave zsession zdoppler-smoke zkit-selftest zcleanup-backups zremote install.sh"
PY_HELPERS="daemonize.py doppler_fetch.py verify_access.py wdt_watch.py"
made_shims=0; made_copies=0
for s in $BASH_HELPERS; do
  [ -f "$AGENTS/scripts/$s" ] || continue
  printf '%s' "$SHIM_TEMPLATE" | sed "s/%NAME%/$s/g" > "$PROJ/scripts/$s"
  chmod 0755 "$PROJ/scripts/$s"
  made_shims=$((made_shims + 1))
done
# python helpers + the SOURCED resolve-prefix.sh must be REAL files:
#   - `python3 scripts/<x>.py` is the documented invocation — a bash shim breaks it
#   - `source scripts/resolve-prefix.sh` must define functions, never exec
for s in $PY_HELPERS resolve-prefix.sh; do
  [ -f "$AGENTS/scripts/$s" ] || continue
  cp -f "$AGENTS/scripts/$s" "$PROJ/scripts/$s"
  case "$s" in *.py) chmod 0755 "$PROJ/scripts/$s";; *) chmod 0644 "$PROJ/scripts/$s";; esac
  made_copies=$((made_copies + 1))
done
echo "[ok] scripts/: $made_shims shims (exec -> .agents/scripts/), $made_copies real copies (python/sourced)"

# ------------------------------------------------- step 4: discovery symlink
echo "--- step 4: skills/z-container discovery symlink ---"
mkdir -p "$PROJ/skills/z-container"
ln -sfn ../../.agents/SKILL.md "$PROJ/skills/z-container/SKILL.md"
echo "[ok] skills/z-container/SKILL.md -> .agents/SKILL.md (platform discovery)"
# keep skills/ out of git (the symlink dangles in clones without .agents/;
# official skills re-extract at boot anyway). .git/info/exclude is kit-managed
# and never touches the user's .gitignore. Anchored at repo root so nested
# source dirs like app/skills/ stay tracked. (round-11 usability fix U1:
# the docs claim 'skills/ is git-ignored' — on a NEW repo nothing enforced it,
# and the first zsave committed the symlink.)
if [ -e "$PROJ/.git" ]; then
  EXCL="$PROJ/.git/info/exclude"
  if [ -f "$PROJ/.git" ] && grep -q '^gitdir: ' "$PROJ/.git" 2>/dev/null; then
    GD="$(sed -n 's/^gitdir: *//p' "$PROJ/.git" | tr -d '[:space:]')"
    [ -n "$GD" ] && EXCL="$GD/info/exclude"
  fi
  if mkdir -p "$(dirname "$EXCL")" 2>/dev/null; then
    touch "$EXCL" 2>/dev/null
    grep -qxF '/skills/' "$EXCL" 2>/dev/null || echo '/skills/' >> "$EXCL" 2>/dev/null
    echo "[ok] /skills/ kept out of git via .git/info/exclude (install-maintained)"
  fi
fi

# ------------------------------------------------- step 5: package refresh --
# NOTE: guard on $KIT (round-11 F3 fix — the v3.0.1 installer guarded on $PROJ
# and self-destructed the package when run FROM the package).
if [ "$LIVE" = 1 ] && [ "$USK" = /home/user_skills ] && [ "$(cd "$KIT" && pwd)" != "$(cd "$PKG" && pwd 2>/dev/null || echo /nonexistent)" ]; then
  echo "--- step 5: refresh read-only package ---"
  if [ -d "$USK" ]; then
    copy_tree "$AGENTS" "$PKG" ".installed-from"
  fi
else
  echo "--- step 5: package refresh skipped (installer IS the package, or scratch ZK_PROJ) ---"
fi

# portable zip (root "z-container/", the skill-package convention)
if [ "$LIVE" = 1 ] && [ -d "$PKG" ]; then
  ZT="/tmp/.zk-zipstage-$$"
  rm -rf "$ZT"; mkdir -p "$ZT"
  if cp -r "$PKG" "$ZT/z-container" 2>/dev/null; then
    rm -rf "$ZT/z-container/.git"
    find "$ZT/z-container" -name .git -exec rm -rf {} + 2>/dev/null
    rm -f "$ZT/z-container/config"
    if (cd "$ZT" && zip -qr z-container.zip z-container) 2>/dev/null \
       && mv -f "$ZT/z-container.zip" "$USK/z-container.zip" 2>/dev/null; then
      echo "[ok] portable zip -> $USK/z-container.zip"
    else
      echo "[warn] could not refresh $USK/z-container.zip (previous copy kept)" >&2
    fi
  fi
  rm -rf "$ZT"
fi

# ------------------------------------------------- step 6: migrations -------
if [ "$LIVE" = 1 ]; then
  echo "--- step 6: one-shot migrations ---"
  # Friction #12: pre-v3.1 zsave wrote PAT-bearing URLs to /home/sync/ where
  # ossfs ignores chmod (files sat world-readable at 0777). The canonical copy
  # is /home/user_skills/<prefix>-remote.url (PolarFS, 0600).
  for f in /home/sync/*-remote.url; do
    [ -f "$f" ] || continue
    rm -f "$f" 2>/dev/null && echo "[ok] removed stale $f (mode-0777 PAT-leak fix; canonical copy lives in /home/user_skills/)"
  done
  # legacy kit copies from the 4-copy era (v2.x): the repo-root and /home/sync
  # kit dirs are superseded by .agents/ + the read-only package.
  for legacy in "$PROJ/z-container-kit" "$PROJ/download/z-container-kit" "/home/sync/z-container-kit"; do
    if [ -d "$legacy" ] && [ "$(cd "$legacy" && pwd)" != "$(cd "$AGENTS" && pwd)" ]; then
      rm -rf "$legacy" 2>/dev/null \
        && echo "[ok] removed legacy kit copy: $legacy (superseded by .agents/ — commit the deletion)" \
        || echo "[warn] could not remove legacy copy: $legacy (remove manually)" >&2
    fi
  done
fi

# ------------------------------------------------- step 7: git config -------
git config --global --unset-all safe.directory "$PROJ" 2>/dev/null || true
git config --global --add safe.directory "$PROJ" 2>/dev/null || true

# ------------------------------------------------- wrap up ------------------
if [ "$INSTALL_FAIL" = 1 ]; then
  echo
  echo "install.sh: FINISHED WITH FAILURES — see [warn] lines above" >&2
  exit 1
fi
echo
echo "=== install complete ($(kit_v "$AGENTS")) ==="
echo "  next:"
echo "    bash $PROJ/scripts/zsession              # situation report"
echo "    bash $PROJ/scripts/zsave 'msg'           # commit + snapshot + push"
echo "  commit the kit so it travels with the repo (first time / after upgrade):"
echo "    git -C $PROJ add .agents/ scripts/ && git -C $PROJ commit -m 'kit: .agents/ v$(kit_v "$AGENTS")'"
