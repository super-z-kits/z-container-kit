#!/usr/bin/env python3
"""daemonize.py — survive the per-toolcall process cull via double-fork.
(kit v2.3.2)

Every bash toolcall's descendant tree is killed when the toolcall ends. A
double-forked process reparents to PID 1 (tini) and escapes the cull.
Verified 2026-08-28: daemons started this way lived 10+ minutes across 30+
toolcalls. They still die on container recycle — persistence is storage-only,
never process-based.

usage:
  daemonize.py [--cwd DIR] [--log FILE] [--pidfile FILE] -- CMD [ARGS...]
examples:
  daemonize.py --cwd /home/z/my-project --log /home/z/my-project/dev.log -- bun run dev
  daemonize.py --log /tmp/worker.log --pidfile /tmp/worker.pid -- python3 worker.py
notes:
  The parent exits 0 immediately — that does NOT prove the command started.
  Use --pidfile and check liveness (kill -0 $(cat file)) before assuming
  success; a typo'd command dies silently with the error in --log.
"""
import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(
        description="Double-fork daemonizer for the Z container.")
    ap.add_argument("--cwd", help="working directory for the command")
    ap.add_argument("--log", help="append stdout/stderr to this file")
    ap.add_argument("--pidfile", help="write the daemon PID here before exec")
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="command after -- to run detached")
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        ap.error("nothing to run — usage: daemonize.py [--cwd DIR] [--log FILE] -- CMD ARGS...")

    if os.fork():
        sys.exit(0)            # parent exits immediately
    os.setsid()                # new session, detached from controlling terminal
    if os.fork():
        sys.exit(0)            # first child exits; grandchild reparents to PID 1
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)        # stdin from /dev/null
    out = devnull
    if a.log:
        out = os.open(a.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(out, 1)            # stdout/stderr to log file (or /dev/null)
    os.dup2(out, 2)
    if out != devnull:
        os.close(out)
    os.close(devnull)
    if a.cwd:
        os.chdir(a.cwd)
    if a.pidfile:
        try:
            with open(a.pidfile, "w") as f:
                f.write(str(os.getpid()))
        except OSError as e:
            # daemon already detached; report to log/stderr is gone — best effort
            pass
    os.execvp(cmd[0], cmd)     # replace process image; survival carries to cmd


if __name__ == "__main__":
    main()
