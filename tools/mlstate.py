import os
import re
import signal
import struct
import subprocess
import sys
import time

from reaper import die_with_parent

MAIN = 0x02000000
MELON = os.environ.get('MELON', os.path.expanduser('~/tools/melonds/squashfs-root/AppRun'))
MELON_CFG = os.environ.get('GYM_MELON_CFG', os.path.expanduser('~/tools/melonds/cfg_k'))
MIN_STATE = 1 << 20
THINK_BOX, THINK_MAGIC = 0x01fff520, 0x4b4e4854
TICK_HZ = 33513982 / 64


def main_ram(path):
    with open(path, 'rb') as f:
        d = f.read()
    p = 0x10
    while p < len(d) - 8:
        tag, ln = d[p:p + 4], struct.unpack_from('<I', d, p + 4)[0]
        if tag == b'NDSG':
            return d[p + 0x14:p + 0x14 + 0x400000]
        p += ln
    raise SystemExit('no NDSG section')


def u32(ram, addr):
    return struct.unpack_from('<I', ram, addr - MAIN)[0]


def section_of(state, name):
    p = 0x10
    while p < len(state) - 8:
        tag, ln = state[p:p + 4], struct.unpack_from('<I', state, p + 4)[0]
        if tag == name:
            return p
        if not ln:
            return None
        p += ln
    return None


def ram_of(state):
    p = section_of(state, b'NDSG')
    if p is None:
        raise ValueError('no NDSG section')
    return p + 0x14


class Ram:
    def __init__(self, data):
        self.base = ram_of(data)
        self.d = data

    def u32(self, a):
        return struct.unpack_from('<I', self.d, self.base + a - MAIN)[0]

    def u16(self, a):
        return struct.unpack_from('<H', self.d, self.base + a - MAIN)[0]

    def block(self, a, n):
        return self.d[self.base + a - MAIN:self.base + a - MAIN + n]

    def think_box(self):
        o = section_of(self.d, b'CP15')
        if o is None:
            return None
        box = struct.unpack_from('<5I', self.d, o + 0x1c + (THINK_BOX & 0x7fff))
        return box[1:] if box[0] == THINK_MAGIC else None

    def think_drops(self):
        box = self.think_box()
        return box and box[0]

    def think_max_s(self):
        box = self.think_box()
        return box and [round(t / TICK_HZ, 2) for t in box[1:]]


def symbols(work):
    syms = {}
    with open(os.path.join(work, 'code.map')) as f:
        for line in f:
            m = re.match(r'\s+0x([0-9a-f]+)\s+(\w+)$', line)
            if m:
                syms[m.group(2)] = int(m.group(1), 16)
    return syms


def xvfb(screen='800x600x24'):
    r, w = os.pipe()
    p = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0', screen], pass_fds=(w,),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    die_with_parent(p.pid)
    os.close(w)
    with os.fdopen(r) as f:
        return p, ':' + f.readline().strip()


class Melon:
    def __init__(self, rom, cfg):
        self.xvfb, self.display = xvfb()
        self.env = dict(os.environ, DISPLAY=self.display, XDG_CONFIG_HOME=cfg, SDL_AUDIODRIVER='dummy')
        self.proc = subprocess.Popen([MELON, rom], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        die_with_parent(self.proc.pid)
        self.win = None
        for _ in range(100):
            time.sleep(0.1)
            r = subprocess.run(['xdotool', 'search', '--name', 'melonDS'], env=self.env, capture_output=True, text=True)
            if r.stdout.split():
                self.win = r.stdout.split()[0]
                break
        if not self.win:
            self.stop()
            raise RuntimeError('melonDS window not found')
        time.sleep(0.5)
        self.xdo('windowmove', self.win, '0', '0')

    def xdo(self, *args):
        subprocess.run(['xdotool', *args], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def key(self, k):
        self.xdo('windowfocus', '--sync', self.win, 'keydown', k)
        time.sleep(0.12)
        self.xdo('keyup', k)
        time.sleep(0.2)

    def tap(self, x, y):
        self.xdo('mousemove', str(x), str(y), 'mousedown', '1')
        time.sleep(0.15)
        self.xdo('mouseup', '1')

    def snapshot(self, path, slot):
        before = os.path.getmtime(path) if os.path.exists(path) else 0
        self.key(f'shift+F{slot}')
        for _ in range(50):
            if os.path.exists(path) and os.path.getmtime(path) != before:
                size = -1
                while size != os.path.getsize(path):
                    size = os.path.getsize(path)
                    time.sleep(0.05)
                with open(path, 'rb') as f:
                    data = f.read()
                return data if len(data) >= MIN_STATE else None
            time.sleep(0.05)
        return None

    def stop(self):
        for p in (self.proc, self.xvfb):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in (self.proc, self.xvfb):
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)


def melon_config(d, fast):
    cfg = os.path.join(d, 'cfg_fast' if fast else 'cfg_walk')
    os.makedirs(os.path.join(cfg, 'melonDS'), exist_ok=True)
    with open(os.path.join(MELON_CFG, 'melonDS', 'melonDS.toml')) as f:
        t = f.read()
    t = re.sub(r'(?m)^RecentROM = .*$', 'RecentROM = []', t)
    t = re.sub(r'(?m)^Volume = .*$', 'Volume = 0', t)
    t = re.sub(r'(?m)^LimitFPS = .*$', f'LimitFPS = {"false" if fast else "true"}', t)
    t = re.sub(r'(?m)^(\[JIT\]\n(?:[^\[\n].*\n)*?)Enable = \w+', lambda m: m.group(1) + f'Enable = {"true" if fast else "false"}', t)
    with open(os.path.join(cfg, 'melonDS', 'melonDS.toml'), 'w') as f:
        f.write(t)
    return cfg


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Read u32 words of main RAM from a melonDS savestate (.mln).')
    ap.add_argument('state', help='melonDS savestate file')
    ap.add_argument('addr', nargs='+', help='hex address, optionally :count of words, e.g. 02114682:4')
    args = ap.parse_args()
    if not os.path.isfile(args.state):
        sys.exit(f'savestate not found: {args.state}')
    ram = main_ram(args.state)
    for a in args.addr:
        addr, _, n = a.partition(':')
        addr = int(addr, 16)
        print(f'{addr:08x}: ' + ' '.join(f'{u32(ram, addr + 4 * i):08x}' for i in range(int(n or 1))))
