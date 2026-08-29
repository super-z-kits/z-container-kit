#!/usr/bin/env python3
"""doppler_fetch.py — verify Doppler PT and pull secrets from the vault.

Follows secrets-vault-kit conventions:
- PT sourced from /home/user_skills/{}-doppler.env (0600, outside git tree)
- Secrets JSON written to /tmp/my-project/doppler-secrets.json (0600) — never into git
- stdout shows only secret NAMES + value LENGTHS, never values
"""
import json
import os
import stat
import sys
import urllib.request

import os, sys, glob
PREFIX = os.environ.get("ZK_PREFIX")
if not PREFIX:
    # v3.1: .agents/config (instantiated kit) takes priority
    for cand in ("/home/z/my-project/.agents/config",):
        try:
            with open(cand) as f:
                for line in f:
                    if line.startswith("ZK_PREFIX="):
                        PREFIX = line.strip().split("=", 1)[1]
                        break
            if PREFIX:
                break
        except OSError:
            pass
if not PREFIX:
    # Auto-discover from /home/user_skills/*-config.env (like resolve-prefix.sh)
    configs = glob.glob("/home/user_skills/*-config.env")
    if len(configs) == 0:
        print("ZK_PREFIX not configured — no .agents/config and no /home/user_skills/*-config.env found")
        print("See SKILL.md 'New project setup'")
        sys.exit(1)
    elif len(configs) > 1:
        print(f"Multiple project configs found: {configs}")
        sys.exit(1)
    else:
        with open(configs[0]) as f:
            for line in f:
                if line.startswith("ZK_PREFIX="):
                    PREFIX = line.strip().split("=", 1)[1]
                    break
        if not PREFIX:
            print(f"ZK_PREFIX not set in {configs[0]}")
            sys.exit(1)
ENV_FILE = f"/home/user_skills/{PREFIX}-doppler.env"
OUT_JSON = "/tmp/my-project/doppler-secrets.json"
API = "https://api.doppler.com/v3"


def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    return env


def api_get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        return e.code, {"error": body}


def main():
    env = load_env(ENV_FILE)
    pt = env.get("DOPPLER_PT", "")
    project = env.get("DOPPLER_PROJECT")
    if not project:
        print("FATAL: DOPPLER_PROJECT not set in env file")
        sys.exit(1)
    config = sys.argv[1] if len(sys.argv) > 1 else env.get("DOPPLER_CONFIG")
    if not config:
        print("FATAL: DOPPLER_CONFIG not set in env file")
        sys.exit(1)
    if not pt.startswith("dp."):
        print("FATAL: DOPPLER_PT missing/invalid format in env file")
        sys.exit(1)
    print(f"env file: {ENV_FILE} mode={oct(stat.S_IMODE(os.stat(ENV_FILE).st_mode))}")
    print(f"PT format: ok (prefix masked, len={len(pt)})")
    print(f"project={project} config={config}")

    # 1. token identity
    code, wp = api_get(f"{API}/workplace", pt)
    if code == 200:
        w = wp.get("workplace", {})
        print(f"workplace: OK (name={w.get('name')!r}, slug={w.get('slug')!r}, id=...{str(w.get('id'))[-4:]})")
    else:
        print(f"workplace: FAILED http={code} {wp.get('error','')}")
        sys.exit(2)

    # 2. project + config visibility (via configs listing; single-project path endpoint quirk 400s)
    code, cfg = api_get(f"{API}/configs?project={project}", pt)
    if code == 200:
        names = [c.get("name") for c in cfg.get("configs", [])]
        print(f"project '{project}': visible — configs: {names}")
        if config not in names:
            print(f"config '{config}' NOT in list")
            sys.exit(3)
    else:
        print(f"project '{project}': NOT visible http={code}")
        sys.exit(3)

    # 3. fetch all secrets for project/config
    code, data = api_get(f"{API}/configs/config/secrets?project={project}&config={config}", pt)
    if code != 200:
        print(f"secrets fetch: FAILED http={code} {data.get('error','')}")
        sys.exit(4)
    secrets = data.get("secrets", {})
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({k: v.get("computed", "") for k, v in secrets.items()}, f)
    os.chmod(OUT_JSON, 0o600)
    print(f"secrets fetch: OK — {len(secrets)} secrets saved to {OUT_JSON} (0600)")
    print("--- secret inventory (name -> type hint, length only) ---")
    for name in sorted(secrets):
        val = secrets[name].get("computed", "") or ""
        hint = "set" if val else "EMPTY"
        print(f"  {name:<28} len={len(val):<5} {hint}")


if __name__ == "__main__":
    main()
