# Networking detail

Egress, DNS, MTU, IPv6, preview-URL detail. Extracted from SKILL.md v2.3.3.
## Networking

- Caddy listens on **:81** [V listener, S from start.sh]; it proxies to
  localhost:3000 **[I]** (Caddyfile is root-only).
- Reach other internal ports externally via `?XTransformPort=<port>` on the
  preview URL (e.g. `/env?XTransformPort=3001`); WebSockets/SSE connect to
  `/?XTransformPort=<port>` (path must be `/`). Never hardcode
  `http://localhost:<port>` in client-side fetch — use the relative path +
  query. **[I]**
- Internal ports — leave alone: 81 (caddy), 3000 (dev server), 12600 (ZAI
  bridge; `/ping` safe, do not loop), 19001/19005/19006 (FC control plane —
  do not touch). **[I/S]**
- Egress fully open (github/npm/pypi reachable); no external IPv6; eth0 MTU 1450;
  DNS 100.100.2.136/138. **[V/I]**
- The public preview URL is not discoverable from inside the container — use the
  UI's preview panel. **[I]**
