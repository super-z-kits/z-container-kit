#!/usr/bin/env python3
"""verify_access.py — read-only access checks for GitHub / Cloudflare / Supabase
using credentials pulled from Doppler (config from env file).

Prints NO secret material. Secrets file: /tmp/my-project/doppler-secrets.json (0600).

Usage:
  python3 verify_access.py [owner/repo]

  owner/repo  — GitHub repo to verify access to (defaults to VERIFY_REPO env var,
                or the first repo found via GET /user/repos if neither is set)
"""
import json
import os
import sys
import urllib.request

SECRETS = "/tmp/my-project/doppler-secrets.json"
# No hardcoded repo — use env var or CLI arg. Fail loudly if neither is provided.
REPO = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VERIFY_REPO", "")
 if not os.environ.get("ZK_PREFIX"): print("ZK_PREFIX not set — see SKILL.md"); sys.exit(1)


def req(url, headers, timeout=30):
    try:
        r = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode(errors="replace"))
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def check_github(tok):
    print("\n========== GITHUB (GH_PAT from Doppler) ==========")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": os.environ.get("ZK_PREFIX") + "-verify"}
    code, me = req("https://api.github.com/user", h)
    if code == 200:
        print(f"  token valid — login: {me.get('login')} (id ...{str(me.get('id'))[-4:]})")
    else:
        print(f"  /user FAILED http={code} {me.get('message','')}")
        return

    repo_to_check = REPO
    if not repo_to_check:
        # No repo specified — auto-discover the most recently updated repo
        code2, repos = req("https://api.github.com/user/repos?per_page=5&sort=updated", h)
        if code2 == 200 and repos:
            repo_to_check = repos[0].get("full_name", "")
            print(f"  no repo specified — using most recent: {repo_to_check}")
        else:
            print("  no repo specified and auto-discovery failed — pass owner/repo as arg or set VERIFY_REPO")
            return

    code, repo = req(f"https://api.github.com/repos/{repo_to_check}", h)
    if code == 200:
        perms = repo.get("permissions", {})
        print(f"  repo {repo_to_check}: ACCESSIBLE")
        print(f"    private={repo.get('private')}  default_branch={repo.get('default_branch')}")
        print(f"    your permissions: admin={perms.get('admin')} maintain={perms.get('maintain')} push={perms.get('push')} pull={perms.get('pull')}")
        code2, br = req(f"https://api.github.com/repos/{repo_to_check}/branches?per_page=100", h)
        if code2 == 200:
            print(f"    branches visible: {[b.get('name') for b in br]}")
        code3, ct = req(f"https://api.github.com/repos/{repo_to_check}/commits?per_page=3", h)
        if code3 == 200 and isinstance(ct, list):
            for c in ct:
                msg = (c.get("commit", {}).get("message") or "").splitlines()[0][:70]
                print(f"    recent: {c.get('sha','')[:7]} {msg}")
    else:
        print(f"  repo {repo_to_check}: NOT ACCESSIBLE http={code} ({repo.get('message','')})")


def check_cloudflare(key):
    print("\n========== CLOUDFLARE (CF_ACCOUNT_API_KEY from Doppler (config from env file)) ==========")
    # Try as an API Token (Bearer) first
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    code, v = req("https://api.cloudflare.com/client/v4/user/tokens/verify", h)
    if code == 200 and v.get("success"):
        print(f"  valid API TOKEN — status: {v.get('result', {}).get('status')}")
        code2, acc = req("https://api.cloudflare.com/client/v4/accounts", h)
        if code2 == 200 and acc.get("success"):
            for a in acc.get("result", []):
                print(f"  account: {a.get('name')} (id ...{a.get('id','')[-6:]})")
        return
    # R3 NEW #1 fix: /user/tokens/verify returns 401 for account-scoped cfat_* tokens
    # (the F3 trap documented in secrets-vault-kit). Fall back to GET /accounts —
    # 200 + non-empty result = token is valid, just lacks User API Tokens: Read scope.
    code2, acc = req("https://api.cloudflare.com/client/v4/accounts", h)
    if code2 == 200 and acc.get("success") and acc.get("result"):
        print(f"  valid API TOKEN (verified via /accounts — /user/tokens/verify returned {code}, the F3 trap)")
        for a in acc.get("result", []):
            print(f"  account: {a.get('name')} (id ...{a.get('id','')[-6:]})")
        return
    # Both failed — token is actually invalid
    print(f"  Bearer-verify failed http={code}, /accounts also failed http={code2}")
    print(f"  detail: {json.dumps(v)[:200]}")


def check_supabase(tok):
    print("\n========== SUPABASE (SUPABASE_TOKEN from Doppler (config from env file)) ==========")
    h = {"Authorization": f"Bearer {tok}"}
    h = {"Authorization": f"Bearer {tok}", "User-Agent": os.environ.get("ZK_PREFIX") + "-verify"}  # audit M3: custom UA to bypass Supabase CF WAF
    # audit M3: api.supabase.com is fronted by Cloudflare WAF; default urllib UA → 403.
    # Always send a custom User-Agent. (GitHub section already does this.)
    code, projs = req("https://api.supabase.com/v1/projects", h)
    if code == 200 and isinstance(projs, list):
        print(f"  token valid — {len(projs)} project(s) visible:")
        for p in projs:
            print(f"    {p.get('name')} (ref={p.get('ref')}, region={p.get('region')}, status={p.get('status')})")
    else:
        print(f"  /projects FAILED http={code} {json.dumps(projs)[:200]}")


def main():
    with open(SECRETS) as f:
        s = json.load(f)
    gh = s.get("GH_PAT", "")
    cf = s.get("CF_ACCOUNT_API_KEY", "")
    sb = s.get("SUPABASE_TOKEN", "")
    if gh:
        check_github(gh)
    if cf:
        check_cloudflare(cf)
    if sb:
        check_supabase(sb)
    print("\n(done — read-only checks only; no secret material printed)")


if __name__ == "__main__":
    main()
