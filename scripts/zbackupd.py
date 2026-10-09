#!/usr/bin/env python3
"""zbackupd — continuous background backup daemon for the Z container.

Design: scratch/design/zenv-design.md (v1 + T10-a/T10-b gate fixes).
Gate verdicts: SHIP-AFTER-FIXES (both attackers); all P0/P1 fixes folded in:
  - sideband init: `git init --bare` + core.bare=false + core.worktree (git 2.47.3 law)
  - PATs NEVER in URLs or cmdlines: GIT_ASKPASS helper files (0700) per host
  - branch-per-boot: auto/<label>/<chat8>-<bootts> (recycle = fresh sideband,
    never non-FF against the remote; never create flat auto/<label> refs)
  - mirror never deletes (monotonic, T12-a lost-work law); orphan rule
  - flock singleton; /proc cmdline verify before any kill; stale lock sweep
  - sanitized subprocess env (whitelist; /usr/bin/git absolute; no GIT_* inherit)
  - subprocess timeouts; ossfs-is-fuse gate; privacy precheck before first push
  - supervisor (--daemon) double-forks, respawns on crash, forwards SIGTERM
  - ALERT file on /home/sync survives force-kill; STATE.json atomic
  - observer*.log + tool-results/ excluded from BOTH legs (PAT-leak law, T9-c B.6)

Legs per source, every cycle (default 60s), change-gated by a local walk:
  A (primary)  delta-copy mirror -> /home/sync/zbackup/<label>/mirror/ (incl .git)
               round-11 redesign: map-driven changed-set `cp --parents -p -f -P`
               in batches; O(changed) fuse ops; NEVER deletes (lost-work law).
               rsync removed (per-file protocol measured 6x cp; seed timed out
               >300s at only 2.5k files). Map beside the mirror
               (<label>.map.json); invariant: an entry exists ONLY when the
               mirror provably holds that file (map-behind = safe re-copy,
               map-ahead = loss). Daily reconcile + rotating 8-sample check.
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
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.1.2"
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
CP_BATCH = 2000             # files per cp invocation (argv safety, ARG_MAX 2MB)
CP_TIMEOUT = 240            # per-batch seconds; a 2000-file batch runs ~50-60s
CP_BATCH_BYTES = 48 << 20   # byte cap per batch — 2000 LARGE files must not
                            # blow CP_TIMEOUT (T13-b P2 count-only batching)
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


def walk_filters(src):
    """Single source of truth for the walked set == the mirrored set (T13
    P1-4). Replaces the old hardcoded walk prune set AND leg-A's rsync
    excludes: under delta-copy the walk product IS the copy list, so one
    filter list must decide both (upload root-anchored; skills my-project
    only; dev.log root file skip)."""
    prune_any = {"node_modules", ".next", ".turbo", "tool-results"}
    if src == MYPROJECT:
        prune_any.add("skills")            # official skills re-extract at boot
    prune_root = {"upload"}                # was rsync "/upload/" — root only
    skip_root_files = {"dev.log"}          # parity with the old "/dev.log" rule
    return prune_any, prune_root, skip_root_files


def walk_tree(src):
    """One walk, two products (T13 P1-2/P1-4):
    - the sig triple (nfiles, total_bytes, max_mtime) — the change-gate that
      keeps ossfs cost O(changes) (T10-b); .git IS walked so commits and
      branch-moves change the signature and trigger a cycle.
    - {relpath: (mtime_ns, size)} from os.lstat — the delta engine's product.
      Regular files and symlinks are kept (lstat: broken links survive, link
      size = target length); fifo/socket/device are counted, never mirrored,
      never an error (a fifo would hang cp)."""
    prune_any, prune_root, skip_root = walk_filters(src)
    n = b = 0
    mx = 0.0
    files = {}
    specials = 0
    for root, dirs, fnames in os.walk(src):
        at_root = (root == src)
        dirs[:] = [d for d in dirs
                   if d not in prune_any and not (at_root and d in prune_root)]
        for f in fnames:
            if f.endswith(".tar") or f.startswith("observer") and f.endswith(".log"):
                continue
            if at_root and f in skip_root:
                continue
            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            m = st.st_mode
            if (stat.S_ISFIFO(m) or stat.S_ISSOCK(m) or stat.S_ISCHR(m)
                    or stat.S_ISBLK(m)):
                specials += 1
                continue
            if not (stat.S_ISREG(m) or stat.S_ISLNK(m)):
                continue
            rel = os.path.relpath(p, src)
            files[rel] = (st.st_mtime_ns, st.st_size)
            n += 1
            b += st.st_size
            mx = max(mx, st.st_mtime)
    return (n, b, mx), files, specials


# --------------------------------------------------------------- leg A -------
def sync_is_fuse():
    """T10-b: unmounted /home/sync falls back to the tmpfs bridge -> mirrors into
    RAM on a no-swap box. Gate: only run leg A when the fuse layer is present."""
    rc, out, _ = run(["stat", "-f", "-c", "%T", SYNC], timeout=10)
    return rc == 0 and "fuse" in out


def map_path(label):
    return "%s/%s.map.json" % (BACKUP_ROOT, label)


def load_map(label):
    """Map = what the MIRROR provably holds. Survives recycles beside the
    mirror, so the first cycle after a boot is near-free."""
    try:
        m = json.load(open(map_path(label)))
        if isinstance(m, dict) and m.get("__v") == 2:
            return m
    except Exception:
        pass
    return None


def save_map(label, m):
    """Atomic tmp+rename. sort_keys -> deterministic iteration -> stable
    rotating sample (T13 P1-5). Never stash this into STATE (P2-8)."""
    tmp = map_path(label) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(m, f, sort_keys=True, separators=(",", ":"))
    os.replace(tmp, map_path(label))


def build_map_from_mirror(mirror, old=None):
    """Map-missing/damage/stale recovery, ONE unified path (T13 P2-10 — no
    6a/6b split): walk the mirror (fuse) once and index what it holds; an
    empty/missing mirror degenerates to the full-copy seed by itself. Crash
    mid-seed: the map is never written -> next cycle rebuilds from the partial
    mirror -> copies only the rest. Resume falls out for free.
    T13-b P1-1: dirs that EIO on readdir (ossfs x control-char names, seen
    live) keep their OLD map slots — only readable-and-absent paths are
    dropped, so manual mirror cleanup still converges AND an unreadable
    subtree does not become a recurring re-copy loop."""
    m = {"__v": 2}
    failed = []

    def _err(e):
        try:
            rel = os.path.relpath(e.filename or "", mirror)
        except ValueError:
            rel = "?"
        failed.append(rel)
        log("mirror walk error %r (entries under it keep their old map slots)" % e)

    for root, _dirs, fnames in os.walk(mirror, onerror=_err):
        for f in fnames:
            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
                m[os.path.relpath(p, mirror)] = [st.st_mtime_ns, st.st_size]
            except OSError:
                pass
    if failed and old:
        kept = 0
        for k, v in old.items():
            if k.startswith("__") or k in m:
                continue
            if any(k == f or k.startswith(f + "/") for f in failed):
                m[k] = v
                kept += 1
        if kept:
            log("mirror rebuild kept %d entries under unreadable dirs" % kept)
    return m


def _copy_batches(src, mirror, changed, files):
    """Batched `cp --parents -p -f -P --` (T13 P0-1/P1-2/P1-3): -p preserves
    mode+mtime; -f unlinks and retries when the dest cannot be opened (git's
    0444 objects); -P never dereferences symlinks. Batches are capped by BOTH
    count (CP_BATCH) and bytes (CP_BATCH_BYTES) — T13-b P2.
    P0-1 classification: a file enters `mapped` ONLY when the mirror
    provably holds its size — vanished source files are benign partial
    (rsync-23 class); anything else (EACCES/ENOSPC/EIO/timeout) is an ERROR
    so the file stays OUT of the map and retries next cycle."""
    batches, batch, bbytes = [], [], 0
    for f in changed:
        batch.append(f)
        bbytes += files[f][1]
        if len(batch) >= CP_BATCH or bbytes >= CP_BATCH_BYTES:
            batches.append(batch)
            batch, bbytes = [], 0
    if batch:
        batches.append(batch)
    mapped, partial, errs = [], False, []
    for batch in batches:
        rc, _, err = run(["cp", "--parents", "-p", "-f", "-P", "--"]
                         + batch + [mirror + "/"],
                         timeout=CP_TIMEOUT, cwd=src)
        if rc == 0:
            mapped.extend(batch)
            continue
        ok, vanished = [], []
        for f in batch:
            sp, mp = os.path.join(src, f), mirror + "/" + f
            try:
                if not os.path.lexists(sp):
                    vanished.append(f)
                    continue
                if os.lstat(mp).st_size == os.lstat(sp).st_size:
                    ok.append(f)
            except OSError:
                pass
        mapped.extend(ok)
        if vanished:
            partial = True
        nfail = len(batch) - len(ok) - len(vanished)
        if nfail > 0:
            errs.append("copy: %d/%d failed rc=%s %s"
                        % (nfail, len(batch), rc, mask(err.strip()[:120])))
    return mapped, partial, errs


def leg_a(src, label, files, sig, st):
    """delta-copy mirror — MERGE-ONLY: overwrite/new, NEVER delete (lost-work
    law, T10-b P0-3 + T12-a). Manual cleanup stays opt-in: rm -rf
    /home/sync/zbackup/<label>/mirror/old-dir (converges <=24h via the daily
    reconcile). The source's .git rides along (unpushed commits are the crown
    jewels). Health (T13-b P1-4 regime fix): the rotating 8-sample cursor AND
    the daily-reconcile due-clock live in STATE (rewritten every cycle) — a
    busy map no longer starves the reconcile, an idle map no longer stalls
    the rotation; the documented <=24h damage bound holds in every band.
    Map-ahead-of-mirror is the one forbidden state (P0-1)."""
    mirror = "%s/%s/mirror" % (BACKUP_ROOT, label)
    os.makedirs(mirror, exist_ok=True)
    now = time.time()
    old = load_map(label)
    m = old
    rebuilt = False
    if m is not None and now >= st.get("_ck_due", 0):
        m = None                    # daily full reconcile is DUE (P1-4)
    if m is not None:
        keys = [k for k in m if not k.startswith("__")]
        i = st.get("__si", 0)       # rotating cursor in STATE (P1-5: SIZE
        damage = False               # ONLY — mtime legitimately diverges)
        for k in keys[i:i + 8]:
            try:
                if os.lstat(mirror + "/" + k).st_size != m[k][1]:
                    damage = True
                    break
            except OSError:
                damage = True
                break
        if damage:
            m = None
        else:
            st["__si"] = (i + 8) % max(len(keys), 1)
    if m is None:
        m = build_map_from_mirror(mirror, old)
        rebuilt = True
        st["_ck_due"] = now + 86400
        # rebuild maps carry mirror-side mtimes — ossfs ignores utimensat
        # (mirror holds full-ns copy-time stamps; the tar-restored source is
        # second-truncated), so an unaligned map would force a FULL re-copy
        # pass on every rebuild. Align size-matching entries to source-side
        # values (the same size-only identity class the sampling uses).
        for k, v in files.items():
            if k in m and m[k][1] == v[1]:
                m[k] = [v[0], v[1]]
    changed = [k for k, v in files.items()
               if k not in m or m[k][0] != v[0] or m[k][1] != v[1]]
    mapped, partial, errs = _copy_batches(src, mirror, changed, files)
    for k in mapped:
        m[k] = [files[k][0], files[k][1]]
    m["__ck"] = now
    if changed or rebuilt:                              # P2-9: no-op cycles
        save_map(label, m)                              # write NOTHING to fuse
    if errs:
        return False, "; ".join(errs)[:200]
    return True, {"files": sig[0], "bytes": sig[1], "partial": partial,
                  "copied": len(mapped)}


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
        # per-source isolation (T13-b P2): one source's exception must not
        # abort the remaining sources of this cycle.
        try:
            # change-gate (local walk; ossfs cost only when something moved)
            sig, files, specials = walk_tree(src)
            if specials:
                log("walk label=%s skipped_specials=%d (fifo/socket/device — never mirrored)"
                    % (label, specials))
            # normalize: STATE round-trips tuples to lists — tuple != list made the
            # first cycle of every fresh process run unconditionally (T13-L find;
            # this also removes the boot-cycle full-pass after a no-change seam).
            same = (list(st.get("sig") or ()) == list(sig)) and \
                   (time.time() - st.get("last_full", 0) < 1800)
            if same:
                st["consec"] = 0
                continue
            errs = []
            if not sync_is_fuse():
                errs.append("/home/sync is not fuse (unmounted?) — leg A SKIPPED")
            else:
                ok, info = leg_a(src, label, files, sig, st)
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
        except Exception as e:
            st["consec"] = st.get("consec", 0) + 1
            st["last_errors"] = ["exception: %r" % e]
            alerts.append("%s: exception %r" % (label, e))
            log("source exception label=%s: %r" % (label, e))
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
                print("    mirror : %s files, %.1f MB" %
                      (m.get("files", "?"), m.get("bytes", 0) / 1e6))
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
