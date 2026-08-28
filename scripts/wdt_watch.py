#!/usr/bin/env python3
"""Z-container HEAD-watchdog observer (forensic). (kit v2.3.0)

Double-forked daemon watching /home/z/my-project/.git/HEAD:
- inotify (ctypes) on the .git dir for HEAD*/HEAD.lock events -> write-mechanism forensics
- 4 Hz /proc scan -> logs process SPAWN/EXIT (catches short-lived `git ...` children)
- chain lifecycle -> logs when a bash toolcall chain (sh -> su z -> bash) is ACTIVE/IDLE
- heartbeat every 10s -> also proves double-fork survival across toolcalls

Usage:  python3 wdt_watch.py        (self-daemonizes; logs to /tmp/wdt-watch.log)
Stop:   touch /tmp/wdt-watch.stop   (or auto-exit after 1200 s)
"""
import ctypes
import ctypes.util
import os
import select
import struct
import sys
import time

REPO = "/home/z/my-project"
GITDIR = os.path.join(REPO, ".git")
HEAD = os.path.join(GITDIR, "HEAD")
LOG = "/tmp/wdt-watch.log"
STOP = "/tmp/wdt-watch.stop"
MAX_S = 1200

IN_MODIFY = 0x02
IN_ATTRIB = 0x04
IN_CLOSE_WRITE = 0x08
IN_MOVED_FROM = 0x40
IN_MOVED_TO = 0x80
IN_CREATE = 0x100
IN_DELETE = 0x200
MASK = (IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM |
        IN_MOVED_TO | IN_CREATE | IN_DELETE)
EVNAME = {IN_MODIFY: "MODIFY", IN_ATTRIB: "ATTRIB", IN_CLOSE_WRITE: "CLOSE_WRITE",
          IN_MOVED_FROM: "MOVED_FROM", IN_MOVED_TO: "MOVED_TO",
          IN_CREATE: "CREATE", IN_DELETE: "DELETE"}


def log_line(log, s):
    log.write("%s.%03d %s\n" % (time.strftime("%F %T"),
                                int(time.time() * 1000) % 1000, s))


def daemonize():
    if os.fork():
        sys.exit(0)
    os.setsid()
    if os.fork():
        sys.exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    dn = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(dn, fd)


def read_head():
    try:
        with open(HEAD) as f:
            return f.read().strip()
    except OSError as e:
        return "<err%d>" % e.errno


def head_stat():
    try:
        st = os.stat(HEAD)
        return "ino=%d mtime=%d owner=%d:%d mode=%o" % (
            st.st_ino, st.st_mtime_ns, st.st_uid, st.st_gid, st.st_mode)
    except OSError:
        return "<nostat>"


def proc_scan(seen, born, log):
    """One /proc pass. Returns True while a bash toolcall chain is alive."""
    active = False
    now = time.time()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return False
    cur = {}
    for p in entries:
        if not p.isdigit():
            continue
        pid = int(p)
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                c = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
            cur[pid] = c
        except OSError:
            cur[pid] = ""
    for pid, c in cur.items():
        if pid not in seen:
            seen.add(pid)
            born[pid] = now
            if c:
                log_line(log, "SPAWN pid=%d cmd=%r" % (pid, c[:180]))
        if "su z -c" in c or ("bash" in c and "--noprofile" in c):
            active = True
    for pid in list(seen):
        if pid not in cur:
            seen.discard(pid)
            b = born.pop(pid, None)
            if b is not None and now - b < 60:
                log_line(log, "EXIT pid=%d lifetime=%.2fs" % (pid, now - b))
    return active


def main():
    daemonize()
    log = open(LOG, "a", buffering=1)
    log_line(log, "=== watcher start pid=%d ===" % os.getpid())
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    ifd = None
    try:
        fd = libc.inotify_init()
        if fd < 0:
            log_line(log, "inotify_init failed errno=%d" % ctypes.get_errno())
        else:
            wd = libc.inotify_add_watch(fd, GITDIR.encode(), MASK)
            if wd < 0:
                log_line(log, "inotify_add_watch failed errno=%d (gitdir gone? poll-only)"
                         % ctypes.get_errno())
                libc.close(fd)
            else:
                ifd = fd
                log_line(log, "inotify watch armed on %s" % GITDIR)
    except Exception as e:
        log_line(log, "inotify setup error: %r" % e)
        ifd = None

    head = read_head()
    log_line(log, "init head=%r %s" % (head, head_stat()))
    seen, born = set(), {}
    active = proc_scan(seen, born, log)
    log_line(log, "init chain_active=%s" % active)

    t0 = time.time()
    last_hb = t0
    last_scan = 0.0
    while time.time() - t0 < MAX_S:
        if os.path.exists(STOP):
            log_line(log, "stop-file seen, exiting")
            break
        now = time.time()
        if ifd is not None:
            r, _, _ = select.select([ifd], [], [], 0.05)
            if r:
                try:
                    data = os.read(ifd, 65536)
                except OSError:
                    data = b""
                off = 0
                while off + 16 <= len(data):
                    _wd, mask, cookie, ln = struct.unpack_from("iIII", data, off)
                    off += 16
                    name = data[off:off + ln].split(b"\0", 1)[0].decode(
                        errors="replace")
                    off += ln
                    if name.startswith("HEAD"):
                        evs = [v for k, v in sorted(EVNAME.items()) if mask & k]
                        log_line(log, "INOTIFY name=%s events=%s cookie=%d head=%r %s"
                                 % (name, evs, cookie, read_head(), head_stat()))
        else:
            time.sleep(0.05)

        h = read_head()
        if h != head:
            log_line(log, "HEADCHANGE %r -> %r %s" % (head, h, head_stat()))
            head = h

        if now - last_scan >= 0.25:
            a = proc_scan(seen, born, log)
            if a != active:
                log_line(log, "CHAIN %s head=%r" % ("ACTIVE" if a else "IDLE", head))
                active = a
            last_scan = now

        if now - last_hb >= 10:
            log_line(log, "HEARTBEAT head=%r chain_active=%s uptime=%.0fs"
                     % (head, active, now - t0))
            last_hb = now

    log_line(log, "=== watcher end ===")
    log.close()


if __name__ == "__main__":
    main()
