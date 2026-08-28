#!/usr/bin/env python3
"""verify_access.py — read-only access checks for GitHub / Cloudflare / Supabase
using credentials pulled from Doppler (agent-bootstrap/prd).

Prints NO secret material. Secrets file: /tmp/my-project/doppler-secrets.json (0600).
"""
import json
import sys
import urllib.request

SECRETS = "/tmp/my-project/doppler-secrets.json"
REPO = "zikomolapoutl/zk"


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
    print("\n========== GITHUB (GH_PAT from Doppler prd) ==========")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "zk-verify"}
    code, me = req("https://api.github.com/user", h)
    if code == 200:
        print(f"  token valid — login: {me.get('login')} (id ...{str(me.get('id'))[-4:]})")
    else:
        print(f"  /user FAILED http={code} {me.get('message','')}")
    code, repo = req(f"https://api.github.com/repos/{REPO}", h)
    if code == 200:
        perms = repo.get("permissions", {})
        print(f"  repo {REPO}: ACCESSIBLE")
        print(f"    private={repo.get('private')}  default_branch={repo.get('default_branch')}")
        print(f"    your permissions: admin={perms.get('admin')} maintain={perms.get('maintain')} push={perms.get('push')} pull={perms.get('pull')}")
        code2, br = req(f"https://api.github.com/repos/{REPO}/branches?per_page=100", h)
        if code2 == 200:
            print(f"    branches visible: {[b.get('name') for b in br]}")
        code3, ct = req(f"https://api.github.com/repos/{REPO}/commits?per_page=3", h)
        if code3 == 200 and isinstance(ct, list):
            for c in ct:
                msg = (c.get("commit", {}).get("message") or "").splitlines()[0][:70]
                print(f"    recent: {c.get('sha','')[:7]} {msg}")
    else:
        print(f"  repo {REPO}: NOT ACCESSIBLE http={code} ({repo.get('message','')})")


def check_cloudflare(key):
    print("\n========== CLOUDFLARE (CF_ACCOUNT_API_KEY from Doppler prd) ==========")
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
    # Try as Global API Key style (needs email — report if unusable)
    print(f"  Bearer-verify failed http={code} — trying legacy key probe requires X-Auth-Email (not available)")
    print(f"  detail: {json.dumps(v)[:200]}")


def check_supabase(tok):
    print("\n========== SUPABASE (SUPABASE_TOKEN from Doppler prd) ==========")
    h = {"Authorization": f"Bearer {tok}"}
    h = {"Authorization": f"Bearer {tok}", "User-Agent": "zk-verify"}  # audit M3: custom UA to bypass Supabase CF WAF
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
