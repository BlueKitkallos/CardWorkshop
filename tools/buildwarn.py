#!/usr/bin/env python3
"""Build warnings: problems that do not stop the build, collected for one list at the end of make rom.

    import buildwarn
    buildwarn.warn('pack 12: Raigeki (3 points) at common')

prints `WARNING: <text>` on stderr and appends the line to the file named by BUILD_WARNINGS (the Makefile sets it
per make run; tools/stepcache.py points it at a scratch file for each step and replays the lines on a cache hit).

    python3 tools/buildwarn.py report FILE      print the collected list with its count, copy it to build/warnings.txt
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, 'build', 'warnings.txt')
RUNS = os.path.join(ROOT, 'build', 'warnings')


def record(lines, path=None):
    path = path or os.environ.get('BUILD_WARNINGS')
    if not path or not lines:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'a') as f:
        f.write(''.join(f'{line}\n' for line in lines))


def warn(msg):
    lines = [f'WARNING: {line}' for line in str(msg).splitlines() or ['']]
    sys.stdout.flush()
    print('\n'.join(lines), file=sys.stderr, flush=True)
    record(lines)


def report(path):
    try:
        with open(path) as f:
            lines = [line.rstrip('\n') for line in f if line.strip()]
    except FileNotFoundError:
        lines = []
    os.makedirs(os.path.dirname(LATEST), exist_ok=True)
    with open(LATEST, 'w') as f:
        f.write(''.join(f'{line}\n' for line in lines))
    if os.path.abspath(path) != LATEST and os.path.exists(path):
        os.unlink(path)
    for name in os.listdir(RUNS) if os.path.isdir(RUNS) else ():
        p = os.path.join(RUNS, name)
        if os.path.isfile(p) and time.time() - os.path.getmtime(p) > 86400:
            os.unlink(p)
    rel = os.path.relpath(LATEST, os.getcwd())
    if not lines:
        print(f'build warnings: none ({rel})')
        return
    print(f'build warnings: {len(lines)} ({rel})')
    for line in lines:
        print(f'  {line}')


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'report':
        raise SystemExit(__doc__)
    report(sys.argv[2])
