#!/usr/bin/env bash
# install.sh — REMOVED in kit v4.0 (zero-install redesign)
#
# v3.x instantiated the whole kit into every project (.agents/ tree, scripts/
# shims, skills/ symlink) via this script. v4.0 removed that model: the kit
# lives ONCE per account at /home/user_skills/z-container-kit/ and projects
# carry only a one-line config (.agents/config — the .env pattern).
#
# v3 -> v4 command map:
#   install.sh (new project)      ->  zk-init <prefix>
#   install.sh (upgrade)          ->  refresh.sh   (from an updated clone)
#   install.sh (cold-start re-run) ->  nothing — the config comes back with
#                                     `git reset --hard origin/main`; only
#                                     zk-init if the repo never had one
{
  echo "install.sh was removed in kit v4.0 — the kit is zero-install now:"
  echo "  project setup:    bash \"\$(dirname \"\$0\")/zk-init\" <prefix>"
  echo "  package refresh:  bash <updated-kit-clone>/scripts/refresh.sh"
  echo "  v3 repo cleanup:  bash \"\$(dirname \"\$0\")/zk-init\" --migrate-v3"
  echo "  see SKILL.md 'New project setup' + 'Layout' for the v4 model"
} >&2
exit 1
