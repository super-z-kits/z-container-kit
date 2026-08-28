# Persistence namespace inference

Per-chat vs per-user namespace analysis. Extracted from SKILL.md v2.3.3.
Namespaces: `/home/sync` and `/tmp/my-project` were empty at this chat's first
boot while `/home/user_skills` carried a month-old mtime — strong indication the
first two are per-chat and user_skills is per-user. Not proven; treat github as
the only guaranteed cross-chat persistence. **[V-observed, inference]**
