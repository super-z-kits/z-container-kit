#!/usr/bin/env bash
# install.sh — install the z-container kit into this container. (kit v2.3.2)
# Safe to run from ANY kit copy, including the persistent ones
# (/home/sync/z-container-kit, /home/user_skills/z-container-kit,
#  z-container-kit, skills/z-container) — self-install is detected
# and skipped; updates use copy-then-swap so the previous copy survives a
# failed copy.
#
# Installs:
#   docs+scripts -> $PROJ/skills/z-container/   (repo.tar coverage)
#   runtime helpers -> $PROJ/scripts/            (git/github coverage)
#   git-tracked copy -> $PROJ/z-container-kit/   (github coverage)
#   kit copy -> /home/sync/z-container-kit/      (recycle-safe, per-chat)
#   kit copy -> /home/user_skills/z-container-kit/ (probably cross-chat)
#   portable zip -> /home/user_skills/z-container.zip (root "z-container/",
#      the skill-package convention; refreshed from the fresh copy so it
#      never goes stale — kit files are token-free by construction)
#
# Cold start (fresh chat, PAT + kit repo URL only):
#   git clone https://github.com/super-z-kits/z-container-kit.git /tmp/my-project/kit
#   bash /tmp/my-project/kit/scripts/install.sh
# then wire the workspace remote (see SKILL.md "Session start") and re-run
# install.sh once more from the clone so every copy matches the latest kit.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="${ZK_PROJ:-/home/z/my-project}"
INSTALL_FAIL=0

# canonical fallback: the my-project/scripts/ copy has no SKILL.md next to it
if [ ! -f "$KIT/SKILL.md" ] && [ -f "$PROJ/skills/z-container/SKILL.md" ]; then
  KIT="$PROJ/skills/z-container"
fi
[ -f "$KIT/SKILL.md" ] || {
  echo "install.sh: SKILL.md not found near $SCRIPT_DIR (nor at $PROJ/skills/z-container)" >&2
  exit 1
}

echo "installing kit from: $KIT"

copy_into() {  # copy_into <dest-dir> — atomic swap; self-install aware
  local d="$1"
  if [ "$d" = "$KIT" ]; then
    echo "[ok] already in place: $d"
    return 0
  fi
  if ! mkdir -p "$(dirname "$d")" 2>/dev/null; then
    echo "[skip] $(dirname "$d") not writable"
    return 0
  fi
  # version-skew warning (informational; still installs the source version)
  if [ -f "$d/SKILL.md" ] && [ -f "$KIT/SKILL.md" ]; then
    src_v="$(sed -n 's/^  version: "\(.*\)"/\1/p' "$KIT/SKILL.md" | head -1)"
    dst_v="$(sed -n 's/^  version: "\(.*\)"/\1/p' "$d/SKILL.md" | head -1)"
    [ "$src_v" = "$dst_v" ] || echo "[note] version skew: source=$src_v destination($d)=$dst_v — installing source version"
  fi
  rm -rf "$d.incoming"
  if cp -r "$KIT" "$d.incoming" 2>/dev/null; then
    # strip VCS metadata: a kit source that is a git CLONE (cold-start path)
    # carries a .git dir — planted into kit copies it turns them into nested
    # repos (broken gitlinks / silently-untracked kit files). Kit copies are
    # plain dirs by design; the workspace repo tracks them from OUTSIDE.
    rm -rf "$d.incoming/.git"
    find "$d.incoming" -name .git -exec rm -rf {} + 2>/dev/null
    # normalize: file modes to 0644 (avoids mode-only git dirt on tracked
    # copies; scripts run via `bash <script>`, so +x is unneeded); strip
    # any __pycache__ bytecode cruft
    find "$d.incoming" -type f -exec chmod 0644 {} + 2>/dev/null
    find "$d.incoming" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
    rm -rf "$d"
    if mv -f "$d.incoming" "$d"; then
      echo "[ok] kit -> $d"
    else
      rm -rf "$d.incoming"
      echo "[warn] could not finalize $d (mv failed — old copy was replaced; re-run install)" >&2
      INSTALL_FAIL=1
    fi
  else
    rm -rf "$d.incoming"
    echo "[warn] copy to $d failed — previous copy (if any) kept" >&2
    INSTALL_FAIL=1
  fi
}

# 1. docs + scripts into the project
copy_into "$PROJ/skills/z-container"

mkdir -p "$PROJ/scripts"
for s in zsave zsession daemonize.py install.sh wdt_watch.py; do
  if [ -f "$KIT/scripts/$s" ]; then
    cp -f "$KIT/scripts/$s" "$PROJ/scripts/$s" && chmod 0755 "$PROJ/scripts/$s" || INSTALL_FAIL=1
  fi
done
echo "[ok] helpers -> $PROJ/scripts/ (zsave zsession daemonize.py install.sh wdt_watch.py)"

# 1b. git-tracked copy at the repo root (download/ is the platform's own
# deliverables dir; the kit does NOT belong there — v2.2.x legacy copies
# living at download/z-container-kit are removed below)
copy_into "$PROJ/z-container-kit"

# 1c. legacy cleanup: v2.2.x installed the git-tracked copy at
# $PROJ/download/z-container-kit — remove it (git status will show the
# deletion; the next zsave commits the migration)
if [ -d "$PROJ/download/z-container-kit" ] && [ "$PROJ/download/z-container-kit" != "$KIT" ]; then
  rm -rf "$PROJ/download/z-container-kit"
  echo "[ok] removed legacy kit copy at $PROJ/download/z-container-kit (now lives at $PROJ/z-container-kit)"
fi

# 2. recycle-safe / cross-chat copies
copy_into /home/sync/z-container-kit
copy_into /home/user_skills/z-container-kit

# 3. refresh the portable zip artifact (root "z-container/", matching the
#    /home/official_skills/<name>.zip skill-package convention). Built in
#    /tmp from the just-installed copy, moved in atomically. Kit files carry
#    no tokens by construction — the zip is safe to hand to any session.
if [ -d /home/user_skills/z-container-kit ]; then
  ZT="/tmp/.zk-zipstage-$$"
  rm -rf "$ZT"; mkdir -p "$ZT"
  if cp -r /home/user_skills/z-container-kit "$ZT/z-container" 2>/dev/null; then
    # belt-and-braces: never ship VCS metadata in the portable zip
    rm -rf "$ZT/z-container/.git"
    find "$ZT/z-container" -name .git -exec rm -rf {} + 2>/dev/null
  fi
  if [ -d "$ZT/z-container" ] && (cd "$ZT" && zip -qr z-container.zip z-container) 2>/dev/null \
     && mv -f "$ZT/z-container.zip" /home/user_skills/z-container.zip 2>/dev/null; then
    echo "[ok] portable zip -> /home/user_skills/z-container.zip"
  else
    echo "[warn] could not refresh /home/user_skills/z-container.zip (previous copy kept)" >&2
  fi
  rm -rf "$ZT"
fi

# add safe.directory exactly once (re-runs used to accumulate duplicates)
git config --global --unset-all safe.directory "$PROJ" 2>/dev/null || true
git config --global --add safe.directory "$PROJ" 2>/dev/null || true

if [ "$INSTALL_FAIL" = 1 ]; then
  echo
  echo "install.sh: FINISHED WITH FAILURES — see [warn] lines above" >&2
  exit 1
fi
echo
echo "installed. next:"
echo "  bash $PROJ/scripts/zsession            # situation report"
echo "  bash $PROJ/scripts/zsave 'msg'         # commit + snapshot + push"
echo "  cat $PROJ/skills/z-container/SKILL.md  # full survival guide"
