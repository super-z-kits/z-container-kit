#!/usr/bin/env python3
"""zbackupd — continuous background backup daemon for the Z container.

Design: scratch/design/zenv-design.md (v1 + T10-a/T10-b gate fixes).
Gate verdicts: SHIP-AFTER-FIXES (both attackers); all P0/P1 fixes folded in:
  - sideband init: `git init --bare` + core.bare=false + core.worktree (git 2.47.3 law)
  - PATs NEVER in URLs or cmdlines: GIT_ASKPASS helper files (0700) per host
  - branch-per-boot: auto/<label>/<chat8>-<bootts> (recycle = fresh sideband,
    never non-FF against the remote; never create flat auto/<label> refs)
  - mirror seed cycle without --delete; >50% shrink guard; orphan rule
  - flock singleton; /proc cmdline verify before any kill; stale lock sweep
  - sanitized subprocess env (whitelist; /usr/bin/git absolute; no GIT_* inherit)
  - subprocess timeouts; ossfs-is-fuse gate; privacy precheck before first push
  - supervisor (--daemon) double-forks, respawns on crash, forwards SIGTERM
  - ALERT file on /home/sync survives force-kill; STATE.json atomic
  - observer*.log + tool-results/ excluded from BOTH legs (PAT-leak law, T9-c B.6)

Legs per source, every cycle (default 60s):
  A (primary)  rsync mirror  -> /home/sync/zbackup/<label>/mirror/   (includes .git)
  B (secondary) sideband git -> push auto-branch to github + gitlab backup repos
The daemon NEVER writes inside a source's .git (sole exception: none — zenv,
not the daemon, sets core.filemode on my-project).

Usage:
  zbackupd.py --daemon              # supervised daemon (called by `zenv start`)
  zbackupd.py --foreground          # one loop process (called by supervisor)
  zbackupd.py --status              # one-screen status
  zbackupd.py --cycle-once          # one cycle, no daemonizing (testing)
"""
import errno
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"
ZENV = "/home/z/.zenv"
SYNC = "/home/sync"
BACKUP_ROOT = SYNC + "/zbackup"
STATE_PATH = BACKUP_ROOT + "/STATE.json"
ALERT_PATH = BACKUP_ROOT + "/ALERT.txt"
DAEMON_PID = ZENV + "/daemon.pid"
SUP_PID = ZENV + "/supervisor.pid"
LOG_PATH = ZENV + "/daemon.log"
MYPROJECT = "/home/z/my-project"
GIT = "/usr/bin/git"
DEFAULT_INTERVAL = 60.0
REPO_GH = "zikomolapoutl/zai-sandbox-backup"
REPO_GL = "ansgareutychisO/zai-sandbox-backup"
GL_PUSH_EVERY = 2          # gitlab push every Nth change-push (WAF cost, Q2)
MAX_CONSEC_FAILS = 3       # ALERT threshold

# excludes shared by BOTH legs (gitignore syntax for sideband; rsync gets translated)
EX_FILES = ["/home/sync/SECRETS.env", "/home/user_skills/zk-secrets.env",
            "/home/user_skills/zk-default.env"]
EXCLUDES = [
    ".git",              # any depth: source's own + nested repos (mirror uses -a on
                         # the tree including .git ONLY at top level via explicit copy)
    "node_modules/", ".next/", ".turbo/",
    "/upload/", "/dev.log", "tool-results/",
    "observer*.log", "*.tar",
]
EXCLUDES_MYPROJECT = EXCLUDES + ["skills/"]   # official skills re-extract at boot

MASK_RE = re.compile(r"(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-)[A-Za-z0-9._-]+")


def mask(s):
    return MASK_RE.sub(r"\1***", s or "")


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------- logging ----
def log(msg):
    try:
        os.makedirs(ZENV, exist_ok=True)
        line = "%s %s\n" % (utc(), mask(msg))
        with open(LOG_PATH, "a") as f:
            f.write(line)
        # rotate at 512KB, keep one .1
        if os.path.getsize(LOG_PATH) > 512 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".1")
            open(LOG_PATH, "w").close()
    except OSError:
        pass


# ------------------------------------------------------------------- pats ----
def parse_kv(path):
    d = {}
    try:
        for ln in open(path):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return d


def load_pats():
    """PAT resolution order (re-read every cycle; zenv pat takes effect live)."""
    gh = gl = None
    for p in EX_FILES:
        kv = parse_kv(p)
        gh = gh or kv.get("GITHUB_PAT")
        gl = gl or kv.get("GITLAB_PAT")
    if not gh:  # legacy channel: token embedded in zk-default remote URL
        url = parse_kv("/home/user_skills/zk-default.env").get("ZK_DEFAULT_REMOTE", "")
        m = re.search(r"(ghp_[A-Za-z0-9]+)", url)
        if m:
            gh = m.group(1)
    gh = gh or os.environ.get("GH_PAT")
    gl = gl or os.environ.get("GL_PAT")
    return gh, gl


def askpass_path(host, pat):
    """GIT_ASKPASS helper (0700) — PAT never in URL/cmdline/argv. One file per host."""
    p = "%s/askpass-%s.sh" % (ZENV, host)
    body = "#!/bin/bash\ncase \"$1\" in *sername*) echo 'token';; *) echo %s;; esac\n" % ("'" + pat + "'")
    try:
        os.makedirs(ZENV, exist_ok=True)
        old = ""
        try:
            old = open(p).read()
        except OSError:
            pass
        if old != body:
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o700)
    except OSError as e:
        log("askpass setup failed host=%s err=%r" % (host, e))
        return None
    return p


# --------------------------------------------------------------- subprocs ----
def run(cmd, timeout=120, env_extra=None, cwd="/"):
    """Sanitized subprocess. Whitelist env; absolute git; never inherits GIT_*."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/home/z", "LANG": "C"}
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=env, cwd=cwd)
        _CURPROC["p"] = p
        try:
            out, err = p.communicate(timeout=timeout)
            return p.returncode, out, err
        finally:
            _CURPROC["p"] = None
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return 124, "", "timeout after %ss: %s" % (timeout, cmd[0])
    except OSError as e:
        return 125, "", repr(e)


# -------------------------------------------------------------- api (urllib) --
def api(method, url, headers, data=None, timeout=20):
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(data).encode() if data else None)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:                     # network/timeout
        return 0, {"_err": repr(e)}


_REPO_CACHE = {}


def ensure_repo_private(host, pat):
    """Privacy precheck + create-on-missing (cached per daemon life). Returns
    (ok, url|why). PAT travels in Authorization headers only, never a URL.
    GitLab WAF 403 -> retried."""
    if host in _REPO_CACHE:
        return _REPO_CACHE[host]
    r = _ensure_repo_private(host, pat)
    if r[0]:
        _REPO_CACHE[host] = r
    return r


def _ensure_repo_private(host, pat):
    if host == "github":
        hdr = {"Authorization": "token " + pat, "Accept": "application/vnd.github+json"}
        st, d = api("GET", "https://api.github.com/repos/" + REPO_GH, hdr)
        if st == 200:
            if not d.get("private", False):
                return False, "backup repo is PUBLIC — refusing to push work tree"
            return True, "https://github.com/%s.git" % REPO_GH
        if st == 404:
            st, d = api("POST", "https://api.github.com/user/repos", hdr,
                        {"name": REPO_GH.split("/")[-1], "private": True})
            if st in (201, 422):               # 422 = already exists
                st2, d2 = api("GET", "https://api.github.com/repos/" + REPO_GH, hdr)
                if st2 == 200 and d2.get("private"):
                    return True, "https://github.com/%s.git" % REPO_GH
                return False, "create ok but verify failed (%s)" % st2
            return False, "create failed %s %s" % (st, mask(str(d.get("message"))[:120]))
        return False, "check failed %s" % st
    if host == "gitlab":
        hdr = {"PRIVATE-TOKEN": pat}
        enc = REPO_GL.replace("/", "%2F")
        for attempt in range(6):               # WAF retry (creation is one-time)
            st, d = api("GET", "https://gitlab.com/api/v4/projects/" + enc, hdr)
            if st == 200:
                if d.get("visibility") not in ("private",):
                    return False, "backup repo is %s — refusing" % d.get("visibility")
                return True, "https://gitlab.com/%s.git" % REPO_GL
            if st == 404:
                st, d = api("POST", "https://gitlab.com/api/v4/projects", hdr,
                            {"name": REPO_GL.split("/")[-1], "visibility": "private"})
                if st in (201, 400, 409):      # 400 may be "name taken" wording
                    continue                    # re-GET to confirm
                if st == 403:                  # WAF
                    time.sleep(2)
                    continue
                return False, "create failed %s" % st
            if st == 403:
                time.sleep(2)
                continue
            return False, "check failed %s" % st
        return False, "gitlab unreachable after retries"
    return False, "unknown host"


# ---------------------------------------------------------------- sources ----
def slug(name):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return s[:40] or "src"


def discover_sources():
    """my-project always + git repos at depth<=2 under /home/z."""
    srcs = [(MYPROJECT, "my-project")]
    try:
        names = sorted(os.listdir("/home/z"))
    except OSError:
        return srcs
    for n in names:
        if n.startswith(".") or n == "my-project":
            continue
        if ".restored-" in n:                     # zenv restore outputs — never
            continue                              # back up backups of backups
        p = "/home/z/" + n
        if os.path.isdir(p) and os.path.exists(p + "/.git"):
            srcs.append((p, slug(n)))
        else:
            try:                                # depth-2
                for n2 in sorted(os.listdir(p)):
                    p2 = p + "/" + n2
                    if os.path.isdir(p2) and os.path.exists(p2 + "/.git"):
                        srcs.append((p2, slug(n + "-" + n2)))
            except OSError:
                pass
    return srcs


def excludes_for(src):
    return EXCLUDES_MYPROJECT if src == MYPROJECT else EXCLUDES


def walk_signature(src, excl):
    """(nfiles, total_bytes, max_mtime) over the backup-relevant tree. Local disk
    only (overlay) — the change-gate that keeps ossfs cost O(changes) (T10-b).
    NOTE: .git IS walked (top and nested) so commits/branch-moves change the
    signature and trigger a cycle; heavy regen dirs are skipped."""
    n = b = 0
    mx = 0.0
    ex_names = {"node_modules", ".next", ".turbo", "tool-results", "upload",
                "skills"}
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ex_names]
        for f in files:
            if f.endswith(".tar") or f.startswith("observer") and f.endswith(".log"):
                continue
            try:
                st = os.stat(os.path.join(root, f))
                n += 1
                b += st.st_size
                mx = max(mx, st.st_mtime)
            except OSError:
                pass
    return n, b, mx


# --------------------------------------------------------------- leg A -------
def sync_is_fuse():
    """T10-b: unmounted /home/sync falls back to the tmpfs bridge -> mirrors into
    RAM on a no-swap box. Gate: only run leg A when the fuse layer is present."""
    rc, out, _ = run(["stat", "-f", "-c", "%T", SYNC], timeout=10)
    return rc == 0 and "fuse" in out


def leg_a(src, label, excl, src_sig):
    """rsync mirror — MERGE-ONLY, never --delete (T10-b P0-3, hardened).

    Why no --delete, ever: after a force-kill recycle the mirror may hold the
    ONLY copy of untracked work; the restored tracked-set source lacks those
    files and ANY --delete cycle (even behind a % shrink guard) would prune
    the survivors. A last-resort backup must be monotonic: files may be
    overwritten by newer versions but never removed. Growth is bounded by the
    per-chat /home/sync namespace; the sideband branch is the exact-tree view;
    manual cleanup: rm -rf /home/sync/zbackup/<label>/mirror/old-dir.

    The source's .git rides ALONG (top and nested — plain file copy; unpushed
    commits are the crown jewels). The '.git' entry of EXCLUDES is a
    SIDEBAND-only rule and is skipped here."""
    mirror = "%s/%s/mirror" % (BACKUP_ROOT, label)
    os.makedirs(mirror, exist_ok=True)
    args = ["rsync", "-a", "--no-perms", "--no-owner", "--no-group"]
    for e in excl:
        if e == ".git":                         # mirror WANTS .git (see docstring)
            continue
        args.append("--exclude=" + e)
    args += [src + "/", mirror + "/"]
    rc, out, err = run(args, timeout=600)
    if rc in (0, 23):                           # 23: file vanished mid-copy (live tree)
        return True, {"files": src_sig[0], "bytes": src_sig[1],
                      "partial": rc == 23}
    return False, "rsync rc=%s %s" % (rc, mask(err.strip()[:200]))


# --------------------------------------------------------------- leg B -------
def sideband_dir(label):
    return "%s/repos/%s.git" % (ZENV, label)


def sideband_init(src, label, excl):
    sb = sideband_dir(label)
    if not os.path.isdir(sb):
        os.makedirs(sb, exist_ok=True)
        rc, _, err = run([GIT, "init", "--bare", "-b", "main", sb], timeout=30)
        if rc != 0:
            return False, "init %s" % mask(err.strip()[:120])
        for k, v in (("core.bare", "false"),            # T10 P0-1: required on git 2.47
                     ("core.worktree", src),
                     ("user.name", "zbackupd"),
                     ("user.email", "zbackupd@zcontainer.local"),
                     ("gc.auto", "256")):
            rc, _, err = run([GIT, "--git-dir", sb, "config", k, v], timeout=10)
            if rc != 0:
                return False, "config %s %s" % (k, mask(err.strip()[:120]))
        excl_path = sb + "/info/exclude"
        os.makedirs(os.path.dirname(excl_path), exist_ok=True)
        with open(excl_path, "w") as f:
            f.write("# zbackupd sideband excludes\n")
            for e in excl:
                f.write(e + "\n")
            # NOTE: root .env* files are force-added explicitly in leg_b (git IS
            # disk law) — no .env rules needed here.
    # stale lock sweep (T10-a: kill -9 remnants)
    for lk in (sb + "/index.lock", sb + "/shallow.lock"):
        if os.path.exists(lk):
            try:
                os.remove(lk)
                log("swept stale lock %s" % lk)
            except OSError:
                pass
    return True, sb


def leg_b(src, label, excl, run_id, pats, st):
    ok, sb = sideband_init(src, label, excl)
    if not ok:
        return False, sb
    # stage everything (source .gitignore respected read-only; sideband excludes add)
    rc, _, err = run([GIT, "--git-dir", sb, "add", "-A"], timeout=300)
    if rc != 0:
        return False, "add rc=%s %s" % (rc, mask(err.strip()[:160]))
    # .env is precious and usually gitignored — force-add root-level ones
    run([GIT, "--git-dir", sb, "add", "-f", "--", ".env", ".env.local",
         ".env.production"], timeout=60)
    # change?
    rc, _, _ = run([GIT, "--git-dir", sb, "diff", "--quiet", "--cached"], timeout=60)
    head_rc, _, _ = run([GIT, "--git-dir", sb, "rev-parse", "--verify", "HEAD"],
                        timeout=10)
    has_head = head_rc == 0
    if rc == 0 and has_head:
        return True, {"changed": False, "commits": st.get("commits", 0)}
    rc, _, err = run([GIT, "--git-dir", sb, "commit", "-qm",
                      "auto %s src=%s" % (utc(), label)], timeout=120)
    if rc != 0:
        return False, "commit rc=%s %s" % (rc, mask(err.strip()[:160]))
    rc, sha, _ = run([GIT, "--git-dir", sb, "rev-parse", "--short", "HEAD"],
                     timeout=10)
    sha = sha.strip()
    st["commits"] = st.get("commits", 0) + 1
    st.setdefault("_push_counter", 0)
    st["_push_counter"] += 1
    branch = "refs/heads/auto/%s/%s" % (label, run_id)
    st["branch"] = branch
    out = {"changed": True, "commit": sha, "commits": st["commits"], "branch": branch}

    # --- pushes: github every change; gitlab every GL_PUSH_EVERY-th
    gh, gl = pats
    if gh:
        ap = askpass_path("github", gh)
        if ap:
            okc, url = ensure_repo_private("github", gh)
            if okc:
                rc, _, err = run([GIT, "--git-dir", sb, "push", url,
                                  "HEAD:" + branch], timeout=120,
                                 env_extra={"GIT_ASKPASS": ap,
                                            "GIT_TERMINAL_PROMPT": "0"})
                out["push_gh"] = ("ok" if rc == 0 else
                                  "FAIL %s" % mask(err.strip()[:140]))
            else:
                out["push_gh"] = "SKIP %s" % url
        else:
            out["push_gh"] = "SKIP askpass"
    else:
        out["push_gh"] = "SKIP no-pat"
    if gl and st["_push_counter"] % GL_PUSH_EVERY == 0:
        ap = askpass_path("gitlab", gl)
        if ap:
            okc, url = ensure_repo_private("gitlab", gl)
            if okc:
                rcs = []
                for _ in range(3):              # WAF retry
                    rc, _, err = run([GIT, "--git-dir", sb, "push", url,
                                      "HEAD:" + branch], timeout=120,
                                     env_extra={"GIT_ASKPASS": ap,
                                                "GIT_TERMINAL_PROMPT": "0"})
                    rcs.append(rc)
                    if rc == 0:
                        break
                    time.sleep(1.5)
                out["push_gl"] = ("ok" if rcs and rcs[-1] == 0 else
                                  "FAIL(waf?) rc=%s" % rcs[-1])
            else:
                out["push_gl"] = "SKIP %s" % url
        else:
            out["push_gl"] = "SKIP askpass"
    else:
        out["push_gl"] = ("skip cadence" if gl else "SKIP no-pat")
    # occasional housekeeping
    if st["commits"] % 20 == 0:
        run([GIT, "--git-dir", sb, "gc", "--auto", "--quiet"], timeout=120)
    return True, out


# ---------------------------------------------------------------- state ------
def read_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {"sources": {}}


def write_state(st):
    try:
        os.makedirs(BACKUP_ROOT, exist_ok=True)
        tmp = BACKUP_ROOT + "/.STATE.json.tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, indent=1, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except OSError as e:
        log("state write failed %r" % e)


def set_alerts(lines):
    try:
        os.makedirs(BACKUP_ROOT, exist_ok=True)
        if lines:
            with open(ALERT_PATH, "w") as f:
                f.write("zbackupd ALERTS %s\n" % utc() + "\n".join(lines) + "\n")
        elif os.path.exists(ALERT_PATH):
            os.remove(ALERT_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------- cycle ------
def load_config():
    cfg = {"interval": DEFAULT_INTERVAL}
    try:
        cfg.update(json.load(open(ZENV + "/config.json")))
    except Exception:
        pass
    return cfg


def run_id_of():
    """<chat8>-<boot-epoch> — per-boot branch namespace (T10-b P0-2)."""
    chat = ""
    try:
        d = json.load(open("/etc/.z-ai-config"))
        c = str(d.get("chatId", ""))
        chat = c.replace("chat-", "")[:8] or "nochat"
    except Exception:
        chat = "nochat"
    try:
        up = float(open("/proc/uptime").read().split()[0])
        boot = int(time.time() - up)
    except Exception:
        boot = 0
    return "%s-%d" % (chat, boot)


_STOP = {"flag": False}
_CURPROC = {"p": None}


def _sigterm(_s, _f):
    _STOP["flag"] = True
    p = _CURPROC["p"]                      # interrupt an in-flight subprocess
    if p is not None:
        try:
            p.terminate()
        except Exception:
            pass


def cycle(state, cfg, run_id):
    pats = load_pats()
    alerts = []
    for src, label in discover_sources():
        if _STOP["flag"]:
            break
        st = state["sources"].setdefault(label, {"src": src})
        st["src"] = src
        excl = excludes_for(src)
        if not os.path.isdir(src):              # orphan rule: vanished source
            st["orphaned_since"] = st.get("orphaned_since") or utc()
            st["mirror_kept"] = True
            alerts.append("source vanished, mirror kept: %s" % label)
            continue
        st.pop("orphaned_since", None)
        # change-gate (local signature; ossfs cost only when something moved)
        sig = walk_signature(src, excl)
        same = (sig == st.get("sig")) and (time.time() - st.get("last_full", 0) < 1800)
        if same:
            st["consec"] = 0
            continue
        errs = []
        if not sync_is_fuse():
            errs.append("/home/sync is not fuse (unmounted?) — leg A SKIPPED")
        else:
            ok, info = leg_a(src, label, excl, sig)
            st["mirror"] = info if ok else {"error": info}
            st["mirror_at"] = utc()
            if not ok:
                errs.append("mirror: %s" % info)
        ok, info = leg_b(src, label, excl, run_id, pats, st)
        st["sideband"] = info
        st["sideband_at"] = utc()
        if not ok:
            errs.append("sideband: %s" % info)
        st["sig"] = sig
        st["last_full"] = time.time()
        st["consec"] = 0 if not errs else st.get("consec", 0) + 1
        st["last_errors"] = errs or None
        if errs:
            alerts += ["%s: %s" % (label, e) for e in errs]
            log("cycle errors label=%s: %s" % (label, "; ".join(errs)))
        else:
            log("cycle ok label=%s mirror=%s sideband=%s" %
                (label, st.get("mirror"), {k: v for k, v in st.get("sideband", {}).items()
                                           if k in ("changed", "commit", "push_gh", "push_gl")}))
    state["last_cycle"] = utc()
    state["run_id"] = run_id
    state["version"] = VERSION
    # PAT-channel health
    if not pats[0]:
        alerts.append("no GITHUB_PAT in any channel (leg B github disabled) — "
                      "run: zenv pat <gh-token> [gl-token]")
    write_state(state)
    set_alerts(alerts)
    return alerts


def foreground(interval):
    signal.signal(signal.SIGTERM, _sigterm)
    os.makedirs(ZENV, exist_ok=True)
    with open(DAEMON_PID, "w") as f:
        f.write(str(os.getpid()))
    state = read_state()
    cfg = load_config()
    run_id = run_id_of()
    state["daemon_pid"] = os.getpid()
    state["started"] = utc()
    state["interval"] = cfg["interval"]
    log("foreground start pid=%d run_id=%s interval=%ss" %
        (os.getpid(), run_id, cfg["interval"]))
    while not _STOP["flag"]:
        try:
            cycle(state, cfg, run_id)
        except Exception as e:                  # never die on one bad cycle
            log("CYCLE EXCEPTION %r" % e)
            try:
                st = read_state()
                st["last_exception"] = repr(e)
                write_state(st)
            except Exception:
                pass
        # rest the FULL interval after the cycle END (a long seed cycle must not
        # be followed immediately by the next one — ossfs wear + CPU)
        t_end = time.time()
        while not _STOP["flag"] and time.time() - t_end < cfg["interval"]:
            time.sleep(1.0)
    log("foreground clean stop")
    try:
        os.remove(DAEMON_PID)
    except OSError:
        pass
    return 0


def daemon():
    """Double-fork; grandchild supervises: respawn foreground unless it exited 0.
    Stdio is redirected to /dev/null in the children — otherwise the daemonized
    processes hold the toolcall's stdout/stderr pipes open forever and the
    calling toolcall never returns (observed live: 120s timeout)."""
    if os.fork():
        return 0                                # parent returns to caller
    os.setsid()
    if os.fork():
        os._exit(0)                             # first child exits
    # grandchild, PPID=1 — release the caller's pipes FIRST
    devnull = os.open("/dev/null", os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    if devnull > 2:
        os.close(devnull)
    signal.signal(signal.SIGTERM, _sigterm)
    os.makedirs(ZENV, exist_ok=True)
    # kernel-enforced singleton (T12-b D2): a racing second supervisor takes
    # the lock or exits quietly. Held for the supervisor's lifetime; the lock
    # file is advisory-flock on ZENV/daemon.lock and auto-released on death.
    try:
        global _SINGLETON_LOCK
        _SINGLETON_LOCK = open(ZENV + "/daemon.lock", "w")
        fcntl.flock(_SINGLETON_LOCK.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("singleton lock held by another supervisor - exiting (not an error)")
        os._exit(0)
    with open(SUP_PID, "w") as f:
        f.write(str(os.getpid()))
    log("supervisor start pid=%d" % os.getpid())
    while not _STOP["flag"]:
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--foreground"])
        rc = None
        while rc is None and not _STOP["flag"]:
            try:
                rc = p.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        if _STOP["flag"]:
            if rc is None:
                p.terminate()
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    p.kill()
            break
        if rc == 0:                             # clean stop (zenv stop)
            break
        log("foreground exited rc=%s — respawning in 30s" % rc)
        for _ in range(30):
            if _STOP["flag"]:
                break
            time.sleep(1.0)
    log("supervisor exit")
    try:
        os.remove(SUP_PID)
    except OSError:
        pass
    os._exit(0)


# ---------------------------------------------------------------- status -----
def pid_alive(path, needle):
    try:
        pid = int(open(path).read().strip())
    except (OSError, ValueError):
        return None
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        if needle in cmd:
            return pid
    except OSError:
        pass
    return None


def status():
    sup = pid_alive(SUP_PID, "zbackupd")
    fg = pid_alive(DAEMON_PID, "zbackupd")
    st = read_state()
    print("zbackupd %s  %s" % (VERSION, utc()))
    print("supervisor: %s   foreground: %s" %
          ("pid %d ALIVE" % sup if sup else "not running",
           "pid %d ALIVE" % fg if fg else "not running"))
    gh, gl = load_pats()
    print("PAT channels: github %s | gitlab %s" %
          ("present" if gh else "MISSING (zenv pat <gh> [gl])",
           "present" if gl else "absent (optional)"))
    if os.path.exists(ALERT_PATH):
        print("!! ALERTS (see %s):" % ALERT_PATH)
        print("   " + "\n   ".join(open(ALERT_PATH).read().strip().splitlines()[1:6]))
    else:
        print("alerts: none")
    srcs = st.get("sources", {})
    if not srcs:
        print("sources: none backed up yet (first cycle pending)")
    for label, s in sorted(srcs.items()):
        m = s.get("mirror", {})
        sbd = s.get("sideband", {}) or {}
        print("- %-16s last-cycle %s" % (label, s.get("sideband_at", "?")))
        if isinstance(m, dict):
            if "error" in m:
                print("    mirror : ERROR %s" % m["error"][:100])
            else:
                print("    mirror : %s files, %.1f MB%s" %
                      (m.get("files", "?"), m.get("bytes", 0) / 1e6,
                       " (seed)" if m.get("seed") else ""))
        print("    remote snap: %s -> backup-repo commit %s (gh: %s, gl: %s)"
              "  [backup repo only — your repo is never touched]"
              % (sbd.get("changed"), sbd.get("commit", "-"),
                 sbd.get("push_gh", "-"), sbd.get("push_gl", "-")))
        if s.get("last_errors"):
            print("    errors  : %s" % "; ".join(s["last_errors"])[:140])
        if s.get("orphaned_since"):
            print("    ORPHANED since %s (mirror kept on /home/sync)" % s["orphaned_since"])
    print("state: %s | mirror root: %s" % (STATE_PATH, BACKUP_ROOT))


def stop():
    """zenv stop calls this: SIGTERM supervisor (verified), grace, then force."""
    pid = pid_alive(SUP_PID, "zbackupd")
    if not pid:
        print("zbackupd: not running")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    for _ in range(20):
        if pid_alive(SUP_PID, "zbackupd") is None:
            print("zbackupd: stopped cleanly")
            return 0
        time.sleep(0.5)
    pid = pid_alive(SUP_PID, "zbackupd")
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)        # last resort (cmdline verified)
        except OSError:
            pass
        print("zbackupd: force-killed supervisor %d" % pid)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    mode = sys.argv[1]
    if mode == "--check":                       # exit 0 running / 3 not
        sp = pid_alive(SUP_PID, "zbackupd")
        return 0 if sp else 3
    if mode == "--daemon":
        return daemon()
    if mode == "--foreground":
        return foreground(load_config()["interval"])
    if mode == "--status":
        status()
        return 0
    if mode == "--stop":
        return stop()
    if mode == "--cycle-once":
        state = read_state()
        cycle(state, load_config(), run_id_of())
        status()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
