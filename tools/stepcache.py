#!/usr/bin/env python3
"""Content-addressed build cache shared by every checkout of the repo: whole build steps, items inside a tool, checks.

    python3 tools/stepcache.py run NAME -- CMD [ARG...]   run CMD, or restore its outputs from an entry
    python3 tools/stepcache.py stats                      entries and size per step
    python3 tools/stepcache.py prune                      keep the newest STEPCACHE_KEEP entries per step
    python3 tools/stepcache.py clear [NAME...]            delete every entry (or the named steps') and unused objects

A step's inputs are what CMD actually touched: strace records every file it opened, probed or listed under the repo
(through the rom/, extracted/ and build/cache links too), and every environment variable named in a script it read.
An entry is reused only when all of them are unchanged. A failing CMD is never stored, so checks rerun until they pass.

Inside a tool, Items caches one value per item:
    items = stepcache.Items('w11cards-art')
    key = items.key(spec, template_bytes, files=[picture])
    data = items.get(key)
    if data is None:
        data = encode(...)
        items.put(key, data)
The key holds the given values and files plus every repo module the tool has imported, so call key() after imports.
Items(namespace, code=[files]) keys on those source files instead, for a value that depends on nothing else: an edit
to any other module then keeps the items.

STEPCACHE=0 runs every command and skips every item lookup. STEPCACHE_DIR is the store (default build/cache/steps).
"""
import atexit
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

import buildwarn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.abspath(os.environ.get('STEPCACHE_DIR') or os.path.join(ROOT, 'build', 'cache', 'steps'))
KEEP = int(os.environ.get('STEPCACHE_KEEP', '3'))
ITEM_DAYS = float(os.environ.get('STEPCACHE_ITEM_DAYS', '14'))
MIN_FREE_GB = float(os.environ.get('STEPCACHE_MIN_FREE_GB', '20'))
VERSION = 1
ENABLED = os.environ.get('STEPCACHE', '1') != '0'
TRACE = 'trace=%file,getdents64,fchdir,clone,clone3,fork,vfork'
ENV_TEXT = ('.py', '.json', '.sh', '.mk', '.txt', '.cfg', '.toml')
ENV_TOKEN = re.compile(rb'\b[A-Z][A-Z0-9_]{2,}\b')
SESSION_ENV = {'PATH', 'HOME', 'PWD', 'OLDPWD', 'SHLVL', 'TERM', 'DISPLAY', 'USER', 'LOGNAME', 'SHELL', 'LANG',
               'LANGUAGE', 'TMPDIR', 'MAKEFLAGS', 'MAKELEVEL', 'MFLAGS', 'XDG_SESSION_TYPE', 'XDG_RUNTIME_DIR',
               'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'WAYLAND_DISPLAY', 'SSH_AUTH_SOCK', 'COLUMNS',
               'LINES', 'EDITOR', 'PAGER', 'HOSTNAME', 'MAIL', 'STEPCACHE', 'STEPCACHE_DIR', 'STEPCACHE_KEEP',
               'STEPCACHE_ITEM_DAYS', 'STEPCACHE_MIN_FREE_GB', 'BUILD_WARNINGS'}


def log(msg):
    print(f'stepcache: {msg}', file=sys.stderr, flush=True)


class Hasher:
    def __init__(self):
        os.makedirs(STORE, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(STORE, 'memo.sqlite'), timeout=120)
        self.db.execute('CREATE TABLE IF NOT EXISTS memo (path TEXT PRIMARY KEY, sig TEXT, sha TEXT)')
        self.memo = dict((p, (s, h)) for p, s, h in self.db.execute('SELECT path, sig, sha FROM memo'))
        self.new = {}

    def file(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        if not os.path.isfile(path):
            return None
        real = os.path.realpath(path)
        sig = f'{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}'
        got = self.new.get(real) or self.memo.get(real)
        if got and got[0] == sig:
            return got[1]
        h = hashlib.sha1()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        sha = h.hexdigest()
        if time.time_ns() - max(st.st_mtime_ns, st.st_ctime_ns) > 2_000_000_000:
            self.new[real] = (sig, sha)
        return sha

    def save(self):
        if self.new:
            with self.db:
                self.db.executemany('INSERT OR REPLACE INTO memo VALUES (?, ?, ?)',
                                    [(p, s, h) for p, (s, h) in self.new.items()])
            self.memo.update(self.new)
            self.new = {}


class Repo:
    def __init__(self):
        self.maps = [(os.path.realpath(ROOT), ''), (os.path.normpath(ROOT), '')]
        for d in (ROOT, os.path.join(ROOT, 'build')):
            if os.path.isdir(d):
                for e in os.scandir(d):
                    if e.is_symlink():
                        self.maps.append((os.path.realpath(e.path), os.path.relpath(e.path, ROOT)))
        self.maps.sort(key=lambda m: -len(m[0]))
        self.skip = [os.path.realpath(STORE), STORE, os.path.realpath(__file__), os.path.abspath(__file__)]

    def rel(self, path):
        p = os.path.normpath(path)
        if any(p == s or p.startswith(s + '/') for s in self.skip):
            return None
        for base, r in self.maps:
            if p == base or p.startswith(base + '/'):
                rest = p[len(base) + 1:]
                q = os.path.join(r, rest) if r and rest else (r or rest)
                parts = q.split('/')
                if not q or parts[0] in ('.git', '.claude') or '__pycache__' in parts:
                    return None
                return q
        return None


def names_hash(names):
    return hashlib.sha1('\0'.join(sorted(names)).encode('utf-8', 'surrogateescape')).hexdigest()


def listing(path, skip=()):
    try:
        return names_hash({n for n in os.listdir(path) if not n.endswith('.py')} - {'__pycache__'} - set(skip))
    except OSError:
        return None


def kind(path):
    if os.path.islink(path):
        return 'l'
    if os.path.isdir(path):
        return 'd'
    if os.path.exists(path):
        return 'f'
    return None


class Store:
    def __init__(self):
        for d in ('objects', 'steps', 'items', 'tmp'):
            os.makedirs(os.path.join(STORE, d), exist_ok=True)
        self.lockf = open(os.path.join(STORE, 'lock'), 'a')

    def lock(self, exclusive=False):
        fcntl.flock(self.lockf, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    def unlock(self):
        fcntl.flock(self.lockf, fcntl.LOCK_UN)

    def obj(self, sha):
        return os.path.join(STORE, 'objects', sha[:2], sha)

    def put_obj(self, src, sha):
        dst = self.obj(sha)
        if os.path.exists(dst):
            os.utime(dst)
            return 0
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = f'{dst}.{os.getpid()}.tmp'
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o444)
        os.replace(tmp, dst)
        return os.path.getsize(dst)

    def write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f'{path}.{os.getpid()}.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, separators=(',', ':'))
        os.replace(tmp, path)

    def disk_ok(self):
        return shutil.disk_usage(STORE).free > MIN_FREE_GB * 1e9


def unescape(s):
    out = bytearray()
    i = 0
    simple = {'n': 10, 't': 9, 'r': 13, 'v': 11, 'f': 12, '\\': 92, '"': 34}
    while i < len(s):
        c = s[i]
        if c != '\\':
            out += c.encode('utf-8', 'surrogateescape')
            i += 1
            continue
        n = s[i + 1]
        if n in simple:
            out.append(simple[n])
            i += 2
        elif n == 'x':
            out.append(int(s[i + 2:i + 4], 16))
            i += 4
        else:
            m = re.match(r'[0-7]{1,3}', s[i + 1:])
            out.append(int(m.group(0), 8))
            i += 1 + len(m.group(0))
    return os.fsdecode(bytes(out))


LINE = re.compile(r'^(\d+\.\d+) (\w+)\((.*)\) += (-?\d+|\?)(?:<((?:[^>\\]|\\.)*)>)?(?: (E\w+))?')
FD = re.compile(r'^(\d+|AT_FDCWD)<((?:[^>\\]|\\.)*)>$')
FD_HEAD = re.compile(r'^(\d+)<((?:[^>\\]|\\.)*)>,')
DNAME = re.compile(r'd_name="((?:[^"\\]|\\.)*)"')
PROBE_FAIL = ('ENOENT', 'ENOTDIR')
AT_CALLS = {'openat', 'openat2', 'newfstatat', 'statx', 'faccessat', 'faccessat2', 'readlinkat', 'mkdirat', 'mknodat',
            'unlinkat', 'fchmodat', 'fchmodat2', 'fchownat', 'utimensat', 'futimesat', 'execveat', 'name_to_handle_at'}
WRITE_META = {'chmod', 'fchmodat', 'fchmodat2', 'truncate', 'utime', 'utimes', 'utimensat', 'futimesat', 'chown',
              'lchown', 'fchownat', 'setxattr', 'lsetxattr', 'removexattr', 'lremovexattr'}


TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"(?:\.\.\.)?|(?:\d+|AT_FDCWD)<(?:[^>\\]|\\.)*>|[\[\]{}]|,|[^"\[\]{},]+')


def split_args(text):
    args, depth, cur = [], 0, []
    for m in TOKEN.finditer(text):
        t = m.group(0)
        if t in ('[', '{'):
            depth += 1
        elif t in (']', '}'):
            depth -= 1
        elif t == ',' and depth == 0:
            args.append(''.join(cur).strip())
            cur = []
            continue
        cur.append(t)
    if cur:
        args.append(''.join(cur).strip())
    return args


class Trace:
    def __init__(self, repo):
        self.repo = repo
        self.first = {}
        self.reads, self.written, self.deleted, self.rmdirs, self.made = set(), set(), set(), set(), set()
        self.listed, self.touched_dirs, self.problems = {}, {}, []

    def mark(self, rel, how):
        self.first.setdefault(rel, how)

    def change(self, rel, into):
        self.mark(rel, 'w')
        into.add(rel)
        self.touched_dirs.setdefault(os.path.dirname(rel), set()).add(os.path.basename(rel))

    def parse(self, prefix):
        lines = []
        for name in os.listdir(os.path.dirname(prefix)):
            if not name.startswith(os.path.basename(prefix) + '.'):
                continue
            pid = int(name.rsplit('.', 1)[1])
            with open(os.path.join(os.path.dirname(prefix), name), errors='surrogateescape') as f:
                for n, line in enumerate(f):
                    m = LINE.match(line)
                    if m:
                        lines.append((float(m.group(1)), pid, n, m))
        lines.sort(key=lambda x: (x[0], x[1], x[2]))
        cwd = {}
        for _, pid, _, m in lines:
            self.event(pid, m, cwd)

    def path(self, pid, cwd, args, i, dirfd=None):
        a = args[i] if i < len(args) else ''
        if not a.startswith('"'):
            return None
        p = unescape(a[1:-1] if not a.endswith('...') else a[1:-4])
        if not p:
            return None
        if os.path.isabs(p):
            return p
        base = cwd.get(pid, os.getcwd())
        if dirfd is not None:
            fm = FD.match(args[dirfd])
            if fm:
                base = unescape(fm.group(2))
                if fm.group(1) == 'AT_FDCWD':
                    cwd[pid] = base
        return os.path.join(base, p)

    def event(self, pid, m, cwd):
        call, text, ret, err = m.group(2), m.group(3), m.group(4), m.group(6)
        ok = ret != '?' and not ret.startswith('-')
        if call == 'getdents64':
            fm = FD_HEAD.match(text)
            if not fm:
                return
            rel = self.repo.rel(unescape(fm.group(2)))
            if rel is None:
                return
            if self.reset_under(rel):
                return
            own = self.touched_dirs.get(rel, set())
            names = self.listed.setdefault(rel, set())
            names.update(n for n in (unescape(x) for x in DNAME.findall(text))
                         if n not in ('.', '..', '__pycache__') and not n.endswith('.py') and n not in own)
            return
        args = split_args(text)
        if call in ('clone', 'clone3', 'fork', 'vfork'):
            if ok and int(ret) > 0:
                cwd[int(ret)] = cwd.get(pid, os.getcwd())
            return
        if call == 'chdir':
            if ok:
                cwd[pid] = os.path.normpath(self.path(pid, cwd, args, 0))
            return
        if call == 'fchdir':
            fm = FD.match(args[0]) if args else None
            if ok and fm:
                cwd[pid] = unescape(fm.group(2))
            return
        at = call in AT_CALLS
        if call in ('rename', 'renameat', 'renameat2', 'link', 'linkat'):
            two = call in ('renameat', 'renameat2', 'linkat')
            src = self.path(pid, cwd, args, 1 if two else 0, 0 if two else None)
            dst = self.path(pid, cwd, args, 3 if two else 1, 2 if two else None)
            if ok:
                rs, rd = self.repo.rel(src) if src else None, self.repo.rel(dst) if dst else None
                if rs is not None:
                    if call.startswith('rename'):
                        self.change(rs, self.deleted)
                    else:
                        self.read(rs)
                if rd is not None:
                    self.change(rd, self.written)
            return
        if call in ('symlink', 'symlinkat'):
            p = self.path(pid, cwd, args, 2 if call == 'symlinkat' else 1, 1 if call == 'symlinkat' else None)
            rel = self.repo.rel(p) if p else None
            if ok and rel is not None:
                self.change(rel, self.written)
            return
        p = self.path(pid, cwd, args, 1 if at else 0, 0 if at else None)
        if p is None:
            return
        rel = self.repo.rel(p)
        if rel is None:
            return
        if call in ('open', 'openat', 'openat2', 'creat'):
            if call == 'creat':
                flags = 'O_WRONLY|O_CREAT|O_TRUNC'
            else:
                flags = args[1 if call == 'open' else 2] if len(args) > 2 else ''
            fl = set(re.findall(r'O_\w+', flags))
            if not ok:
                if err == 'EEXIST':
                    self.mark(rel, 'p')
                elif err in PROBE_FAIL:
                    self.mark(rel, 'a')
                return
            if 'O_DIRECTORY' in fl or 'O_PATH' in fl:
                self.mark(rel, 'p')
                return
            if fl & {'O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC'}:
                if not fl & {'O_TRUNC', 'O_EXCL'}:
                    self.read(rel)
                self.change(rel, self.written)
            else:
                self.read(rel)
            return
        if call in ('unlink', 'unlinkat', 'rmdir'):
            if ok:
                if call == 'rmdir' or (call == 'unlinkat' and 'AT_REMOVEDIR' in text):
                    self.change(rel, self.rmdirs)
                else:
                    self.change(rel, self.deleted)
            elif err in PROBE_FAIL:
                self.mark(rel, 'a')
            return
        if call in ('mkdir', 'mkdirat', 'mknod', 'mknodat'):
            if ok:
                self.change(rel, self.made)
            elif err == 'EEXIST':
                self.mark(rel, 'p')
            elif err in PROBE_FAIL:
                self.mark(rel, 'a')
            return
        if call == 'execve':
            if ok:
                self.read(rel)
            elif err in PROBE_FAIL:
                self.mark(rel, 'a')
            return
        if call in WRITE_META:
            if ok:
                self.read(rel)
                self.change(rel, self.written)
            return
        if ok or err not in PROBE_FAIL:
            self.mark(rel, 'p')
        else:
            self.mark(rel, 'a')

    def read(self, rel):
        if self.first.get(rel) == 'p' and rel not in self.written and rel not in self.deleted and rel not in self.made:
            self.first[rel] = 'r'
        self.mark(rel, 'r')
        self.reads.add(rel)

    def reset_under(self, rel):
        while rel:
            if rel in self.rmdirs or rel in self.made:
                return True
            rel = os.path.dirname(rel)
        return False


class Step:
    def __init__(self, name, argv):
        self.name, self.argv = name, argv
        self.repo = Repo()
        self.hasher = Hasher()
        self.store = Store()
        exe = shutil.which(argv[0]) if argv and '/' not in argv[0] else argv[0] if argv else ''
        python = shutil.which('python3')
        if exe and python and argv[0] != 'python3' and os.path.realpath(exe) == os.path.realpath(python):
            argv = ['python3'] + argv[1:]
        self.key1 = hashlib.sha1(json.dumps([VERSION, name, argv, os.path.realpath(exe) if exe else '']).encode(
            'utf-8', 'surrogateescape')).hexdigest()[:16]
        self.dir = os.path.join(STORE, 'steps', name)
        self.why = None

    def abs(self, rel):
        return os.path.join(ROOT, rel)

    def dep_ok(self, d):
        t, rel = d[0], d[1]
        p = self.abs(rel)
        if t == 'f':
            return self.hasher.file(p) == d[2]
        if t == 'x':
            return not os.path.lexists(p)
        if t == 'e':
            k = kind(p)
            return k is not None and (d[2] == '*' or k == d[2])
        if t == 'l':
            return listing(p, d[3] if len(d) > 3 else ()) == d[2]
        return False

    def candidates(self):
        try:
            names = [n for n in os.listdir(self.dir) if n.startswith(self.key1 + '-') and n.endswith('.json')]
        except FileNotFoundError:
            return []
        paths = [os.path.join(self.dir, n) for n in names]
        return sorted(paths, key=lambda p: -os.path.getmtime(p))

    def lookup(self):
        for path in self.candidates():
            try:
                with open(path) as f:
                    man = json.load(f)
            except (OSError, ValueError):
                continue
            bad = next((f'environment {k}' for k, v in man['env'].items() if os.environ.get(k) != v), None)
            bad = bad or next((f'{d[1]} ({d[0]})' for d in man['deps'] if not self.dep_ok(d)), None)
            bad = bad or next((f'object {sha}' for _, sha, _ in man['files']
                               if not os.path.exists(self.store.obj(sha))), None)
            if bad is None:
                return path, man
            self.why = self.why or bad
        return None, None

    def restore(self, man):
        for rel in man['reset']:
            p = self.abs(rel)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            elif os.path.lexists(p):
                os.unlink(p)
        for rel in man['absent']:
            p = self.abs(rel)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            elif os.path.lexists(p):
                os.unlink(p)
        for rel in man['dirs']:
            os.makedirs(self.abs(rel), exist_ok=True)
        copied = 0
        for rel, target in man['links']:
            p = self.abs(rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.lexists(p):
                if os.path.islink(p) and os.readlink(p) == target:
                    continue
                shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)
            os.symlink(target, p)
        for rel, sha, mode in man['files']:
            p = self.abs(rel)
            if os.path.isfile(p) and not os.path.islink(p) and self.hasher.file(p) == sha:
                os.utime(p)
                if os.stat(p).st_mode & 0o777 != mode:
                    os.chmod(p, mode)
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = f'{p}.stepcache.{os.getpid()}'
            shutil.copyfile(self.store.obj(sha), tmp)
            os.chmod(tmp, mode)
            os.replace(tmp, p)
            copied += 1
        return copied

    def hints(self):
        try:
            with open(os.path.join(self.dir, f'{self.key1}.hints')) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def snapshot(self):
        out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True)
        if out.returncode:
            return {}
        snap = {}
        for rel in os.fsdecode(out.stdout).split('\0') + self.hints():
            if rel:
                sha = self.hasher.file(self.abs(rel))
                if sha:
                    snap[rel] = sha
        return snap

    def run(self):
        self.store.lock()
        try:
            path, man = self.lookup()
            if man:
                t = time.time()
                n = self.restore(man)
                os.utime(path)
        finally:
            self.store.unlock()
        if man:
            self.hasher.save()
            log(f'{self.name}: hit, {len(man["files"])} files ({n} copied) in {time.time() - t:.1f}s, '
                f'{man["seconds"]:.1f}s saved')
            warnings = man.get('warnings', [])
            if warnings:
                print('\n'.join(warnings), file=sys.stderr, flush=True)
                buildwarn.record(warnings)
            return 0
        if self.why:
            log(f'{self.name}: changed since the last run: {self.why}')
        snap = self.snapshot()
        self.hasher.save()
        tmpdir = tempfile.mkdtemp(prefix='stepcache-')
        try:
            prefix = os.path.join(tmpdir, 'trace')
            warn_file = os.path.join(tmpdir, 'warnings')
            t = time.time()
            rc = subprocess.call(['strace', '-f', '-ff', '-ttt', '-qq', '--seccomp-bpf', '-y', '-v', '-s', '65535',
                                  '-e', TRACE, '-o', prefix, '--'] + self.argv,
                                 env=dict(os.environ, BUILD_WARNINGS=warn_file))
            seconds = time.time() - t
            try:
                with open(warn_file) as f:
                    warnings = [line.rstrip('\n') for line in f if line.strip()]
            except FileNotFoundError:
                warnings = []
            buildwarn.record(warnings)
            if rc:
                return rc
            tr = Trace(self.repo)
            tr.parse(prefix)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        self.save(tr, snap, seconds, warnings)
        return 0

    def save(self, tr, snap, seconds, warnings):
        changed = tr.written | tr.deleted | tr.rmdirs | tr.made
        deps, problems, unsnapped = [], list(tr.problems), []

        def content(rel, p):
            sha = self.hasher.file(p)
            if snap.get(rel, sha) != sha:
                problems.append(f'{rel} changed while the command ran')
            return sha

        for rel, how in sorted(tr.first.items()):
            p = self.abs(rel)
            if how == 'r':
                if rel in changed:
                    if rel in snap:
                        deps.append(['f', rel, snap[rel]])
                    elif rel in tr.rmdirs or rel in tr.made or os.path.isdir(p):
                        continue
                    else:
                        unsnapped.append(rel)
                elif os.path.isdir(p):
                    deps.append(['e', rel, 'd'])
                elif os.path.isfile(p):
                    deps.append(['f', rel, content(rel, p)])
                else:
                    problems.append(f'read {rel}, now gone')
            elif how == 'p':
                k = kind(p)
                if rel in changed or k is None:
                    deps.append(['e', rel, '*'])
                elif k == 'f':
                    deps.append(['f', rel, content(rel, p)])
                else:
                    deps.append(['e', rel, k])
            elif how == 'a' and not (rel in tr.written | tr.made and os.path.lexists(p)):
                deps.append(['x', rel])
        for rel, names in sorted(tr.listed.items()):
            if rel in changed:
                continue
            deps.append(['l', rel, names_hash(names), sorted(tr.touched_dirs.get(rel, set()) - names)])
        if unsnapped:
            self.store.write_json(os.path.join(self.dir, f'{self.key1}.hints'), sorted(set(self.hints() + unsnapped)))
            problems.append(f'reads {len(unsnapped)} files before rewriting them ({unsnapped[0]}...), '
                            'stored on the next run')
        if problems:
            log(f'{self.name}: ran in {seconds:.1f}s, not stored: {"; ".join(problems[:3])}')
            return
        if not self.store.disk_ok():
            log(f'{self.name}: ran in {seconds:.1f}s, not stored: under {MIN_FREE_GB:g} GB free on the disk holding {STORE}')
            return
        env = self.env_deps(d[1] for d in deps if d[0] == 'f')
        files, dirs, links, absent = [], [], [], []
        outs = set(tr.written | tr.made)
        for rel in tr.written:
            p = self.abs(rel)
            if os.path.isdir(p) and not os.path.islink(p):
                for dirpath, dnames, fnames in os.walk(p):
                    dnames[:] = [d for d in dnames if d != '__pycache__']
                    outs.update(os.path.relpath(os.path.join(dirpath, n), ROOT) for n in dnames + fnames)
        for rel in sorted(outs):
            p = self.abs(rel)
            if os.path.islink(p):
                links.append([rel, os.readlink(p)])
            elif os.path.isdir(p):
                dirs.append(rel)
            elif os.path.isfile(p):
                files.append([rel, self.hasher.file(p), os.stat(p).st_mode & 0o777])
        for rel in sorted(changed):
            if not os.path.lexists(self.abs(rel)):
                absent.append(rel)
        reset = sorted(r for r in tr.rmdirs if os.path.isdir(self.abs(r)))
        man = {'name': self.name, 'argv': self.argv, 'created': time.time(), 'seconds': seconds, 'env': env,
               'deps': deps, 'files': files, 'dirs': dirs, 'links': links, 'absent': absent, 'reset': reset,
               'warnings': warnings}
        depkey = hashlib.sha1(json.dumps([deps, env]).encode('utf-8', 'surrogateescape')).hexdigest()[:16]
        added = 0
        self.store.lock()
        try:
            for rel, sha, _ in files:
                added += self.store.put_obj(self.abs(rel), sha)
            self.store.write_json(os.path.join(self.dir, f'{self.key1}-{depkey}.json'), man)
        finally:
            self.store.unlock()
        self.hasher.save()
        log(f'{self.name}: ran in {seconds:.1f}s, stored {len(files)} files ({added / 1e6:.1f} MB new), '
            f'{len(deps)} inputs')
        prune([self.name])

    def env_deps(self, rels):
        tokens = set()
        for rel in rels:
            if rel.endswith(ENV_TEXT) or '.' not in os.path.basename(rel):
                try:
                    with open(self.abs(rel), 'rb') as f:
                        tokens.update(t.decode() for t in ENV_TOKEN.findall(f.read()))
                except OSError:
                    pass
        return {n: os.environ.get(n) for n in sorted(tokens - SESSION_ENV)}


def manifests(names=None):
    root = os.path.join(STORE, 'steps')
    out = {}
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if names and name not in names:
            continue
        d = os.path.join(root, name)
        out[name] = sorted((os.path.join(d, n) for n in os.listdir(d) if n.endswith('.json')),
                           key=lambda p: -os.path.getmtime(p))
    return out


def gc(store):
    used = set()
    for paths in manifests().values():
        for p in paths:
            try:
                with open(p) as f:
                    used.update(sha for _, sha, _ in json.load(f)['files'])
            except (OSError, ValueError):
                pass
    freed = n = 0
    objdir = os.path.join(STORE, 'objects')
    for sub in os.listdir(objdir):
        for name in os.listdir(os.path.join(objdir, sub)):
            if name not in used:
                p = os.path.join(objdir, sub, name)
                freed += os.path.getsize(p)
                n += 1
                os.unlink(p)
    return n, freed


def prune(names=None, keep=KEEP):
    store = Store()
    store.lock(exclusive=True)
    try:
        dropped = []
        cutoff = time.time() - ITEM_DAYS * 86400
        for name, paths in manifests(names).items():
            groups = {}
            for p in paths:
                groups.setdefault(os.path.basename(p).split('-')[0], []).append(p)
            for group in groups.values():
                stale = group[keep:] if os.path.getmtime(group[0]) >= cutoff else group
                for p in stale:
                    os.unlink(p)
                    dropped.append(f'{name}/{os.path.basename(p)}')
        items = 0
        for dirpath, _, files in os.walk(os.path.join(STORE, 'items')) if dropped or not names else ():
            for f in files:
                p = os.path.join(dirpath, f)
                if os.path.getmtime(p) < cutoff:
                    os.unlink(p)
                    items += 1
        if dropped:
            n, freed = gc(store)
            log(f'pruned {len(dropped)} entries ({", ".join(dropped)}), {n} objects, {freed / 1e6:.1f} MB')
        if items:
            log(f'pruned {items} items unused for {ITEM_DAYS:g} days')
    finally:
        store.unlock()


def du(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def cmd_stats():
    for name, paths in manifests().items():
        secs = []
        for p in paths:
            with open(p) as f:
                secs.append(json.load(f)['seconds'])
        print(f'{name:24} {len(paths)} entries, run times {", ".join(f"{s:.0f}s" for s in secs)}')
    items = os.path.join(STORE, 'items')
    for ns in sorted(os.listdir(items)) if os.path.isdir(items) else []:
        print(f'item {ns:19} {sum(len(f) for _, _, f in os.walk(os.path.join(items, ns)))} values')
    print(f'store {STORE}: {du(STORE) / 1e6:.0f} MB')


def cmd_clear(names):
    store = Store()
    store.lock(exclusive=True)
    try:
        if names:
            for name in names:
                shutil.rmtree(os.path.join(STORE, 'steps', name), ignore_errors=True)
                shutil.rmtree(os.path.join(STORE, 'items', name), ignore_errors=True)
            n, freed = gc(store)
            log(f'cleared {", ".join(names)}: {n} objects, {freed / 1e6:.1f} MB')
        else:
            size = du(STORE)
            for d in ('steps', 'items', 'objects', 'tmp'):
                shutil.rmtree(os.path.join(STORE, d), ignore_errors=True)
            log(f'cleared {STORE}: {size / 1e6:.1f} MB')
    finally:
        store.unlock()


def blob(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v)
    if hasattr(v, 'tobytes'):
        meta = [type(v).__name__] + [str(getattr(v, a, '')) for a in ('shape', 'dtype', 'mode', 'size')]
        if hasattr(v, 'getpalette'):
            meta.append(str(v.getpalette()))
        return '|'.join(meta).encode() + b'\0' + v.tobytes()
    return json.dumps(v, sort_keys=True, default=repr).encode()


class Items:
    _code = None
    _used = []
    files = None

    def __init__(self, namespace, code=None):
        self.ns = namespace
        self.dir = os.path.join(STORE, 'items', namespace)
        self.hasher = None
        self.hits = self.misses = 0
        if code is not None:
            self._code = None
            self.files = sorted(os.path.abspath(f) for f in code)

    def code(self, hasher):
        cls = type(self) if self.files is None else self
        if cls._code is None:
            paths = {os.path.abspath(m.__file__) for m in list(sys.modules.values()) if getattr(m, '__file__', None)}
            files = self.files or sorted(p for p in paths
                                         if p.startswith(ROOT + os.sep) and p != os.path.abspath(__file__))
            h = hashlib.sha1(sys.version.encode())
            for f in files:
                h.update(f'{os.path.relpath(f, ROOT)}\0{hasher.file(f)}\0'.encode())
            for name, m in sorted(sys.modules.items()):
                v = getattr(m, '__version__', None) if '.' not in name else None
                if isinstance(v, str):
                    h.update(f'{name}={v}\0'.encode())
            cls._code = h.hexdigest()
        return cls._code

    def key(self, *values, files=()):
        if self.hasher is None:
            self.hasher = Hasher()
            Items._used.append(self)
        h = hashlib.sha1(f'{VERSION}\0{self.ns}\0{self.code(self.hasher)}\0'.encode())
        for v in values:
            b = blob(v)
            h.update(len(b).to_bytes(8, 'little') + b)
        for f in files:
            h.update(f'\0{os.path.basename(f)}\0{self.hasher.file(f)}'.encode())
        return h.hexdigest()

    def cached(self, fn):
        def wrap(*args):
            k = self.key(fn.__qualname__, *args)
            data = self.get(k)
            if data is None:
                data = bytes(fn(*args))
                self.put(k, data)
            return data
        wrap.__name__, wrap.__doc__ = fn.__name__, fn.__doc__
        return wrap

    def path(self, key):
        return os.path.join(self.dir, key[:2], key)

    def get(self, key):
        if not ENABLED:
            return None
        p = self.path(key)
        try:
            with open(p, 'rb') as f:
                data = f.read()
        except OSError:
            self.misses += 1
            return None
        os.utime(p)
        self.hits += 1
        return data

    def put(self, key, data):
        if not ENABLED:
            return
        if self.hasher:
            self.hasher.save()
        p = self.path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f'{p}.{os.getpid()}.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)


@atexit.register
def report_items():
    for it in Items._used:
        if it.hasher:
            it.hasher.save()
        if it.hits or it.misses:
            log(f'items {it.ns}: {it.hits} reused, {it.misses} made')


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    if a[0] == 'run':
        if len(a) < 3 or '--' not in a:
            raise SystemExit('usage: stepcache.py run NAME -- CMD [ARG...]')
        name, argv = a[1], a[a.index('--') + 1:]
        if not ENABLED or not shutil.which('strace'):
            if ENABLED:
                log('strace not found, running without the cache')
            return subprocess.call(argv)
        if os.path.realpath(os.getcwd()) != os.path.realpath(ROOT):
            raise SystemExit(f'stepcache.py run: start it from {ROOT}')
        return Step(name, argv).run()
    if a[0] == 'stats':
        cmd_stats()
    elif a[0] == 'prune':
        prune()
    elif a[0] == 'clear':
        cmd_clear(a[1:])
    else:
        raise SystemExit(f'unknown command {a[0]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
