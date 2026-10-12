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

VERSION = "1.4.2"
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

# ---- PAT channels (R14 law: the PolarFS copies SHADOW /home/sync — the
# sync copy locks to the container and is unreachable for external
# rotation). ONE order, shared verbatim by every reader (zbackupd,
# push-research.sh, consumer/zenv): session > canonical > sync > legacy > env.
CANON_PAT_FILE = "/home/user_skills/zk-secrets.env"     # account carrier (a
                                                        # fresh session boot-
                                                        # straps from it)
SYNC_PAT_FILE = "/home/sync/SECRETS.env"                # container redundancy
SESS_PAT_TMPL = "/home/user_skills/zk-secrets-%s.env"   # % chat8 — THE
                                                        # external rotation
                                                        # target (shared disk:
                                                        # session-separated)
LEGACY_KV = "/home/user_skills/zk-default.env"          # v5.1 zk-default
CHATID_FILE = "/etc/.z-ai-config"                       # chatId lands AFTER
                                                        # boot — never cache

# excludes shared by BOTH legs (gitignore syntax for sideband; rsync gets translated)
EXCLUDES = [
    ".git",              # any depth: source's own + nested repos (mirror uses -a on
                         # the tree including .git ONLY at top level via explicit copy)
    "node_modules/", ".next/", ".turbo/",
    "/upload/", "/dev.log", "tool-results/",
    "observer*.log", "*.tar",
    # R14 addendum — tracked-set diet: ~89MB of historical watchdog captures
    # (round-6 era) sat in the tracked set (platform checkpoint commit),
    # bloating repo.tar 10.7->90MB, every sideband snapshot and every fresh
    # mirror seed. They are safe in remote history + PolarFS + the never-
    # deleting mirror; also gitignored repo-side so the platform's turn-
    # boundary add -A cannot re-add them. This also prevents a false boot-
    # defer blip (walked-count drop) on the first boot after the diet.
    "wdt6-full/", "scratch/wdt6/", "scratch/wdt/",
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
        # utf-8-sig: an externally-edited rotation saved with a BOM must not
        # silently no-op the first key; non-UTF-8 garbage must not crash the
        # cycle (R14-A: UnicodeDecodeError is NOT an OSError)
        for ln in open(path, encoding="utf-8-sig"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    return d


def chat8_of():
    """First 8 chars of the platform chatId. The chatId lands in CHATID_FILE
    AFTER container boot (this daemon's own boots read 'nochat' until the
    first message) — re-derive per use, never cache across cycles."""
    try:
        d = json.load(open(CHATID_FILE))
        return (str(d.get("chatId", "")).replace("chat-", "")[:8]) or None
    except Exception:
        return None


def sess_pat_path():
    """This session's PAT file — the EXTERNAL ROTATION TARGET (drop a new
    token here from outside the container; picked up next cycle). None until
    the chatId is known (early cycles resolve canon/sync instead)."""
    c = chat8_of()
    return SESS_PAT_TMPL % c if c else None


def pat_files():
    """PAT resolution order (R14 law — every reader shares it verbatim):
      1. session zk-secrets-<chat8>.env — this chat's own copy on the
         account-shared disk; externally updatable; concurrent sessions
         never touch each other's file (shared-disk separation)
      2. canonical zk-secrets.env — account-level carrier; a fresh session
         bootstraps from it before its session file exists
      3. sync SECRETS.env — container-local redundancy (fast path)
      4. legacy zk-default URL embed, 5. GH_PAT/GL_PAT env (last resort)
    Per key, first found wins; gh and gl resolve independently."""
    files = []
    p = sess_pat_path()
    if p:
        files.append(p)
    files.append(CANON_PAT_FILE)
    files.append(SYNC_PAT_FILE)
    return files


def _age_of(p):
    try:
        return max(0.0, time.time() - os.path.getmtime(p))
    except OSError:
        return None


def resolve_pats():
    """(gh, gl, prov) — prov maps each key to (file-basename, age-s) of the
    channel that WON it (status/rotation verification). Re-read every cycle:
    an external rotation takes effect on the next cycle, no restart."""
    prov = {}
    gh = gl = None
    for p in pat_files():
        kv = parse_kv(p)
        if gh is None and kv.get("GITHUB_PAT"):
            gh = kv["GITHUB_PAT"]
            prov["gh"] = (os.path.basename(p), _age_of(p))
        if gl is None and kv.get("GITLAB_PAT"):
            gl = kv["GITLAB_PAT"]
            prov["gl"] = (os.path.basename(p), _age_of(p))
    if not gh:  # legacy channel: token embedded in zk-default remote URL
        url = parse_kv(LEGACY_KV).get("ZK_DEFAULT_REMOTE", "")
        m = re.search(r"(ghp_[A-Za-z0-9]+)", url)
        if m:
            gh = m.group(1)
            prov["gh"] = ("zk-default.env", _age_of(LEGACY_KV))
    gh = gh or os.environ.get("GH_PAT")
    gl = gl or os.environ.get("GL_PAT")
    if gh and "gh" not in prov:
        prov["gh"] = ("env", 0)
    if gl and "gl" not in prov:
        prov["gl"] = ("env", 0)
    return gh, gl, prov


def load_pats():
    """Back-compat 2-tuple (cycle + status use resolve_pats for provenance)."""
    gh, gl, _ = resolve_pats()
    return gh, gl


def _adopt_session_creds():
    """R14: on the first cycle that knows the chatId, seed THIS session's PAT
    file from the lower channels. Idempotent by construction — an existing
    session file is NEVER overwritten (external edits are sacred; `zenv pat`
    is the only in-container re-writer)."""
    p = sess_pat_path()
    if not p or os.path.exists(p):
        return
    gh, gl, _ = resolve_pats()
    if not (gh or gl):
        return
    try:
        # R14-A: tmp + os.replace — atomic. A failed/partial write must not
        # leave a truncated session file behind (the exists-guard would then
        # disable adoption forever while looking freshly rotated).
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            if gh:
                f.write("GITHUB_PAT=%s\n" % gh)
            if gl:
                f.write("GITLAB_PAT=%s\n" % gl)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        log("creds: session file adopted %s (seeded from canon/sync — this is "
            "the external rotation target from now on)" % os.path.basename(p))
    except OSError as e:
        try:
            os.remove(p + ".tmp")
        except OSError:
            pass
        log("creds: session adoption failed err=%r (retry next cycle)" % e)


_AUTH_RE = re.compile(r"403|401|Authentication failed|Access denied|Unauthorized", re.I)


def _push_auth_alerts(label, info):
    """An auth-rejected push must name the rotation path — a revoked PAT
    otherwise reads as generic push noise (R14)."""
    out = []
    if not isinstance(info, dict):
        return out
    for k, host in (("push_gh", "github"), ("push_gl", "gitlab")):
        v = info.get(k) or ""
        if isinstance(v, str) and v.startswith("FAIL") and _AUTH_RE.search(v):
            out.append("%s: %s rejected the PAT (revoked or rotated?) — rotate: "
                       "edit %s (or: zenv pat <gh> [gl])"
                       % (label, host, sess_pat_path() or CANON_PAT_FILE))
    return out


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
        # R13 phantom-copy fix (P0-1 restored): a failed batch must NEVER be
        # blessed via size-match against possibly-stale mirror files — live
        # twice (2026-10-11: the 1119-file and 2000-file "copies" wrote
        # nothing; the mirror kept original stamps while the map moved
        # ahead of it, and a same-size content edit in that window would
        # have been silently unsynced forever). Now: vanished sources are
        # benign (rsync-23 class); everything else stays OUT of the map and
        # retries next cycle. One bounded retry without the vanished files
        # covers the one-file-deleted poisons-the-batch case without a
        # full re-copy.
        vanished = [f for f in batch if not os.path.lexists(os.path.join(src, f))]
        live = [] if len(vanished) == len(batch) else \
            [f for f in batch if f not in set(vanished)]
        if vanished:
            partial = True
        if live and vanished:
            rc2, _, err2 = run(["cp", "--parents", "-p", "-f", "-P", "--"]
                               + live + [mirror + "/"],
                               timeout=CP_TIMEOUT, cwd=src)
            if rc2 == 0:
                mapped.extend(live)
            else:
                errs.append("copy(retry): %d/%d failed rc=%s %s"
                            % (len(live), len(batch), rc2, mask(err2.strip()[:120])))
        elif live:
            errs.append("copy: %d/%d failed rc=%s %s"
                        % (len(live), len(batch), rc, mask(err.strip()[:120])))
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
    if m is not None and st.get("_map_ck", 0) > m.get("__ck", 0):
        # R13 map-stick canary: STATE remembers the last SUCCESSFUL map
        # save's __ck; a loaded map older than that means a fuse flush
        # LOST a save (invisible until now — the map would silently roll
        # back and re-copy). Not fatal: this cycle re-copies the changed
        # set. But it must be visible in the log.
        log("map save didn't persist (fuse flush loss?) label=%s "
            "state_ck=%.0f loaded_ck=%.0f" % (label, st["_map_ck"],
                                               m.get("__ck", 0)))
        m = None                    # treat as stale -> rebuild
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
        # R13-b P2: align only when the source stamp is NOT newer than what
        # the mirror provably holds — a same-size rewrite landing between
        # the last successful copy and ANY rebuild cycle (daily reconcile,
        # sampler damage, canary trip) would otherwise be blessed as synced
        # forever (audit-proven: reconcile cycles swallowed a same-size
        # edit; mirror kept old content while the map claimed source
        # stamps). The second-granularity classifier keeps the tar-restore
        # alignment purpose intact: a preserved-stamp mirror entry and its
        # ns-zeroed restored source share the same second, so they classify
        # as unchanged even when this condition refuses the align.
        for k, v in files.items():
            if k in m and m[k][1] == v[1] and m[k][0] <= v[0]:
                m[k] = [v[0], v[1]]
    # R13: the platform tar-restore ZEROES the ns half of every mtime
    # (live-proven 2026-10-11: a first cycle re-copied 2252 files = 57% of
    # the tree — 1103 fresh git objects + ~1100 never-re-touched entries —
    # ALL same-second+same-size, i.e. pure-ns). Classify at SECOND
    # granularity; the content still rides leg B (git hashes it) and the
    # sampler checks size, so the only loss vs ns-exact is a same-second
    # same-size in-place rewrite — vanishingly rare and git-covered.
    changed = [k for k, v in files.items()
               if k not in m or m[k][0] // 10 ** 9 != v[0] // 10 ** 9
               or m[k][1] != v[1]]
    mapped, partial, errs = _copy_batches(src, mirror, changed, files)
    for k in mapped:
        m[k] = [files[k][0], files[k][1]]
    m["__ck"] = now
    if changed or rebuilt:                              # P2-9: no-op cycles
        save_map(label, m)                              # write NOTHING to fuse
        st["_map_ck"] = now                             # R13 canary bookkeeping
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
    # change? (and: does the PREVIOUS push need a retry? — R14: a failed push
    # on a quiet tree must not wait for the next content change; a token
    # outage would otherwise leave snapshots local-only until something edits)
    rc, _, _ = run([GIT, "--git-dir", sb, "diff", "--quiet", "--cached"], timeout=60)
    head_rc, _, _ = run([GIT, "--git-dir", sb, "rev-parse", "--verify", "HEAD"],
                        timeout=10)
    has_head = head_rc == 0
    prev = st.get("sideband") if isinstance(st.get("sideband"), dict) else {}
    prev_push_failed = (str(prev.get("push_gh", "")).startswith("FAIL") or
                        str(prev.get("push_gl", "")).startswith("FAIL"))
    quiet = rc == 0 and has_head
    if rc == 0 and not has_head:
        # R14-A (pre-existing gap): an empty repo (git init, no commits,
        # nothing staged) used to error EVERY cycle at `git commit` ("nothing
        # to commit") — noisy and wrong; there is honestly nothing to snapshot.
        return True, {"changed": False, "commits": 0,
                      "note": "empty repo — nothing to snapshot yet"}
    if quiet and not prev_push_failed:
        return True, {"changed": False, "commits": st.get("commits", 0)}
    st.setdefault("_push_counter", 0)
    st["_push_counter"] += 1
    branch = "refs/heads/auto/%s/%s" % (label, run_id)
    st["branch"] = branch
    if quiet:   # retry path: nothing new to commit — re-push the existing HEAD
        rc, sha, _ = run([GIT, "--git-dir", sb, "rev-parse", "--short", "HEAD"],
                         timeout=10)
        sha = sha.strip()
        out = {"changed": False, "commit": sha, "commits": st.get("commits", 0),
               "branch": branch, "push_retry": True}
    else:
        rc, _, err = run([GIT, "--git-dir", sb, "commit", "-qm",
                          "auto %s src=%s" % (utc(), label)], timeout=120)
        if rc != 0:
            return False, "commit rc=%s %s" % (rc, mask(err.strip()[:160]))
        rc, sha, _ = run([GIT, "--git-dir", sb, "rev-parse", "--short", "HEAD"],
                         timeout=10)
        sha = sha.strip()
        st["commits"] = st.get("commits", 0) + 1
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
    if gl and (st["_push_counter"] % GL_PUSH_EVERY == 0 or
               (isinstance(prev, dict) and
                str(prev.get("push_gl", "")).startswith("FAIL"))):
        # R14-A P2: the cadence must never suppress a RETRY of a previously
        # failed GL push — parity alone used to strand GL-only failures
        # (first retry lands odd, records "skip cadence", chain ends).
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
                                  # R14-A P2: carry the masked stderr — the
                                  # bare "rc=N" form could never match the
                                  # auth-alert regex, so a revoked GitLab PAT
                                  # read as WAF noise forever.
                                  "FAIL(waf?) %s" % mask(err.strip()[:140]))
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
        d = json.load(open(CHATID_FILE))
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


def _proc_uptime():
    """Seconds since container boot (R12 boot-race defer gate)."""
    try:
        return float(open("/proc/uptime").read().split()[0])
    except Exception:
        return 1e9


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
    _adopt_session_creds()   # R14: seed the session file BEFORE resolving —
    pats = load_pats()       # never overwrites an existing (externally
    alerts = []              # rotated) session file
    discovered = set()
    ran, deferred = set(), set()          # R13: health-line truth — a
    excepted = set()                      # skipped source must not echo
    for src, label in discover_sources():  # the last full cycle's numbers
        if _STOP["flag"]:
            break
        discovered.add(label)
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
            # R12 boot-race defer: at container boot the platform's tar
            # restore runs ~2-3 min; a cycle that walks the tree mid-extract
            # sees a partial file set (live 2026-10-11: the un-extracted tail
            # missed the rebuild alignment and re-copied 1119 files next
            # cycle; a fresh-mirror boot would even commit a partial-tree
            # snapshot). Defer while the tree is still filling AND we are
            # inside the boot window; sig stays untouched so the next cycle
            # re-evaluates; capped so it can never wedge protection.
            # R12-b P1-1: the budget is per-BOOT — STATE survives recycles,
            # so an unkeyed counter would disarm the feature after the very
            # boot it was built for.
            # R13: the trigger is the walked-count being BELOW the last-boot
            # sig — on this platform build the restore is PRE-daemon (start.sh
            # is sequential: rm tree -> tar xf (~1-2s at uptime ~6s, proven by
            # /tmp/boot-timeline.log + a ctime census) -> skills -> dev.sh),
            # so a below-count tree means a failed/short pre-stop tar or a
            # boot-window mass deletion: do NOT snapshot that as the newest
            # branch for a few minutes. Session GROWTH never defers (the
            # R13.0 growth clause delayed real work 3-5 min; audit P2).
            # R12-b P1-1: the budget is per-BOOT (epoch-keyed).
            boot = int(time.time() - _proc_uptime())
            if st.get("_bd_boot") != boot:
                st["_bd_boot"] = boot
                st["_boot_defers"] = 0
                st.pop("_bd_n", None)     # legacy R13.0 key, no longer used
            last_n = (list(st.get("sig") or [None]) + [None])[0]
            if (_proc_uptime() < 300 and last_n is not None
                    and sig[0] < last_n
                    and st.get("_boot_defers", 0) < 5):
                st["_boot_defers"] = st.get("_boot_defers", 0) + 1
                deferred.add(label)
                log("boot-window defer label=%s walked=%d last-boot=%s "
                    "defers=%d (tree below last-boot count — failed restore "
                    "or mass deletion?)" % (label, sig[0], last_n,
                                            st["_boot_defers"]))
                continue
            ran.add(label)
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
            st["sideband"] = info if ok else {"error": info}   # R12-b P2-1:
            st["sideband_at"] = utc()                          # error strings
            if not ok:                                         # never flow into
                errs.append("sideband: %s" % info)             # STATE raw
            alerts += _push_auth_alerts(label, st["sideband"])  # R14: an
            # auth-rejected push must name the rotation path, not read as
            # generic push noise
            if not errs:                      # R13-b P1: a cycle with errors
                st["sig"] = sig               # must NOT advance the gate —
                st["last_full"] = time.time() # the failed files (and failed
            else:                             # pushes) retry on the NEXT
                pass                          # cycle, not at the 30-min
                                             # heartbeat (audit-proven: an
                                             # error cycle gate-skipped and
                                             # left the mirror stale <=30min)
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
            ran.discard(label)               # R13-b P2: an exceptioned
            excepted.add(label)              # source must not echo the
    # R12 orphan telemetry: discovery only lists sources that EXIST, so a
    # vanished outside-my-project repo used to freeze silently in STATE with
    # no ORPHANED flag (live: testrepo/zck-mirror/zck-v2 sat stale since
    # Oct 5-7). Stamp the truth — mirror kept on /home/sync — so `zenv
    # status` points the next agent straight at `zenv restore`.
    for label, st2 in list(state["sources"].items()):
        if label in discovered:
            continue
        src2 = st2.get("src") or ""
        if src2 and not os.path.isdir(src2) and not st2.get("orphaned_since"):
            st2["orphaned_since"] = utc()
            st2["mirror_kept"] = True
            alerts.append("source vanished, mirror kept: %s (zenv restore)" % label)
    state["last_cycle"] = utc()
    state["run_id"] = run_id
    state["version"] = VERSION
    # R14-A P3: rotate-me alerts STICK — re-raise from the persisted
    # per-source sideband so a gate-skip cycle (quiet tree) cannot clear
    # ALERT.txt 60s after the failure; it clears only when a push succeeds.
    for label3, st3 in state["sources"].items():
        if isinstance(st3, dict):
            alerts += _push_auth_alerts(label3, st3.get("sideband"))
    alerts = list(dict.fromkeys(alerts))   # dedupe, order-preserving
    # PAT-channel health
    if not pats[0]:
        alerts.append("no GITHUB_PAT in any channel (leg B github disabled) — "
                      "run: zenv pat <gh-token> [gl-token]")
    write_state(state)
    set_alerts(alerts)
    # R12-a: one durable health line per cycle (survives recycles — the
    # Oct-10 daily-reconcile watch evidence died with the container; wall-
    # clock watches must be verifiable post-hoc from /home/sync).
    try:
        h = BACKUP_ROOT + "/health.log"
        line = "%s run=%s" % (utc(), run_id)
        for label, s2 in sorted(state["sources"].items()):
            m2 = s2.get("mirror")
            b2 = s2.get("sideband")
            # R13: per-cycle TRUTH — a gate-skipped source used to echo the
            # last full cycle's cp/push (a 30-min run of "cp=16" lines that
            # were all skips nearly read as a mount incident). skip = gate,
            # defer = boot-race defer, ORPHAN = source gone, mirror kept.
            if label in excepted:
                val = "EXC"                 # cycle exceptioned; values below
            elif label in ran:              # are the previous cycle's
                if isinstance(m2, dict) and "copied" in m2:
                    cpv = "cp=%s" % m2["copied"]
                else:
                    cpv = "mirror=ERR"
                if isinstance(b2, dict) and "push_gh" in b2:
                    puv = "push=%s" % b2["push_gh"]
                elif isinstance(b2, dict) and b2.get("changed") is False:
                    puv = "push=none"       # nothing to push — not an error
                else:
                    puv = "sbd=ERR"
                val = "%s %s" % (cpv, puv)
            elif label in deferred:
                val = "cp=defer"
            elif s2.get("orphaned_since"):
                val = "ORPHAN"
            else:
                val = "skip"
            line += " | %s: %s" % (label, val)
        with open(h, "a") as f:
            f.write(mask(line) + "\n")
        if os.path.getsize(h) > (1 << 20):      # 1MB cap, keep the tail half
            with open(h) as f:
                lines = f.read().splitlines(True)
            with open(h, "w") as f:
                f.writelines(lines[len(lines) // 2:])
    except OSError:
        pass
    return alerts


def foreground(interval):
    signal.signal(signal.SIGTERM, _sigterm)
    os.makedirs(ZENV, exist_ok=True)
    # R12: were we spawned by a supervisor? (manual --foreground runs have a
    # shell/agent parent — never auto-respawn for those). If OUR supervisor
    # dies, re-spawn supervision instead of orphaning with a free lock: a
    # free lock lets the next `zenv start` (or boot hook) create a SECOND
    # worker — a dual-writer race on STATE/map/sideband (live-confirmed
    # 2026-10-11).
    _sup_pid = os.getppid()
    _supervised = pid_cmdline_has(_sup_pid, "--daemon")
    with open(DAEMON_PID, "w") as f:
        f.write(str(os.getpid()))
    state = read_state()
    cfg = load_config()
    run_id = run_id_of()
    state["daemon_pid"] = os.getpid()
    state["started"] = utc()
    state["interval"] = cfg["interval"]
    log("foreground start v%s pid=%d run_id=%s interval=%ss" %
        (VERSION, os.getpid(), run_id, cfg["interval"]))
    while not _STOP["flag"]:
        if _supervised and (os.getppid() != _sup_pid
                            or not pid_cmdline_has(_sup_pid, "--daemon")):
            # R12-b P2-4: getppid()!=_sup_pid catches reparenting (the
            # supervisor is DEAD even if its pid was reused by another
            # --daemon process — the cached-pid cmdline check alone would
            # falsely pass and leave the worker lock-free forever).
            if os.path.exists(ZENV + "/stop.flag"):
                log("supervisor pid %d gone but stop-flag present — exiting "
                    "without re-spawn" % _sup_pid)
                break
            log("supervisor pid %d vanished — re-spawning supervision, exiting"
                % _sup_pid)
            try:
                subprocess.Popen([sys.executable, os.path.abspath(__file__),
                                  "--daemon"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError as e:
                log("re-supervision failed %r (keep cycling unsupervised)" % e)
            else:
                # bounded handoff (R12-b P2-2): confirm the new supervisor
                # took over before exiting — fire-and-forget left a ~1s
                # zero-chain window and a supervisor dying pre-spawn meant
                # silent total death.
                for _ in range(20):
                    time.sleep(0.5)
                    try:
                        nsup = int(open(SUP_PID).read())
                        if nsup != _sup_pid and os.path.exists("/proc/%d" % nsup):
                            break
                    except (OSError, ValueError):
                        pass
                else:
                    log("handoff wait timed out — exiting anyway "
                        "(supervisor may have crash-looped)")
                break          # clean exit: the new chain takes over
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
        # R12-b P3: only remove OUR pidfile — a respawned worker may have
        # already written its own (the exiting orphan used to delete it).
        if open(DAEMON_PID).read().strip() == str(os.getpid()):
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
    try:
        os.remove(ZENV + "/stop.flag")   # R12-b P1-2: a deliberate stop must
    except OSError:                       # never outlive the next start
        pass
    log("supervisor start v%s pid=%d" % (VERSION, os.getpid()))
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


def pid_cmdline_has(pid, needle):
    """True iff /proc/pid/cmdline (NUL-joined) contains needle."""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return needle.encode() in f.read().replace(b"\x00", b" ")
    except OSError:
        return False


def status():
    sup = pid_alive(SUP_PID, "zbackupd")
    fg = pid_alive(DAEMON_PID, "zbackupd")
    st = read_state()
    print("zbackupd %s  %s" % (VERSION, utc()))
    print("supervisor: %s   foreground: %s" %
          ("pid %d ALIVE" % sup if sup else "not running",
           "pid %d ALIVE" % fg if fg else "not running"))
    gh, gl, prov = resolve_pats()

    def _ps(k, tok, missing):
        if not tok:
            return missing
        ch, age = prov.get(k) or ("?", None)
        a = ("?" if age is None else
             "%dd" % (age / 86400) if age >= 86400 else
             "%dh" % (age / 3600) if age >= 3600 else "%dm" % (age / 60))
        return "%s …%s@%s" % (ch, tok[-4:], a)

    print("PAT: github %s | gitlab %s" %
          (_ps("gh", gh, "MISSING (zenv pat <gh> [gl])"),
           _ps("gl", gl, "absent (optional)")))
    sp = sess_pat_path()
    print("rotate externally: %s%s" %
          (sp or CANON_PAT_FILE,
           "" if sp else "  [chatId not yet known — session file appears after "
                        "the first message]"))
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
        sbd = s.get("sideband", {})
        # R12-b: error payloads are normalized to {"error": ...} at the
        # producer (cycle(), 1.2.2). These guards remain defense-in-depth
        # for legacy STATE files — a 1.1.x sideband error STRING crashed
        # `zenv status` (found by the battery's F test, not by review).
        if not isinstance(m, dict):
            m = {}
        if not isinstance(sbd, dict):
            sbd = {}
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
            print("    ORPHANED since %s (mirror kept on /home/sync — "
                  "zenv restore %s)" % (s["orphaned_since"], label))
    print("state: %s | mirror root: %s" % (STATE_PATH, BACKUP_ROOT))


def stop():
    """zenv stop: SIGTERM supervisor (verified), grace, force — AND the
    worker (R12-b P1-2: after a supervisor SIGKILL the orphaned worker used
    to resurrect a full chain ~1 interval after 'stopped cleanly'). The
    stop-flag keeps the worker's re-supervision path from resurrecting the
    chain mid-stop; daemon() clears the flag on the next start."""
    try:
        os.makedirs(ZENV, exist_ok=True)
        with open(ZENV + "/stop.flag", "w") as f:
            f.write(utc() + "\n")
    except OSError:
        pass
    stopped = []
    pid = pid_alive(SUP_PID, "zbackupd")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            if pid_alive(SUP_PID, "zbackupd") is None:
                stopped.append("supervisor %d" % pid)
                break
            time.sleep(0.5)
        pid = pid_alive(SUP_PID, "zbackupd")
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)    # last resort (cmdline verified)
            except OSError:
                pass
            stopped.append("supervisor %d (force)" % pid)
    wpid = pid_alive(DAEMON_PID, "zbackupd")
    if wpid:
        try:
            os.kill(wpid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            if pid_alive(DAEMON_PID, "zbackupd") is None:
                stopped.append("worker %d" % wpid)
                break
            time.sleep(0.5)
        wpid = pid_alive(DAEMON_PID, "zbackupd")
        if wpid:
            try:
                os.kill(wpid, signal.SIGKILL)
            except OSError:
                pass
            stopped.append("worker %d (force)" % wpid)
    if stopped:
        print("zbackupd: stopped (%s)" % ", ".join(stopped))
    else:
        print("zbackupd: not running")
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
