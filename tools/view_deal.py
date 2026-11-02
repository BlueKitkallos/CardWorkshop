import json
import os
import re
import shutil
import socket
import struct
import threading
import time

JANKEN_RESULT = 0x021bb714
CHOICE_RAND = 0x021bbe48
JANKEN_EXIT = 0x021b9848
AFTER_SHUFFLE = 0x021e4c98
HAND_A = 0x021c4ec4
HAND_B = 0x021c4ec8
FIRST_CHOICE = 0x021c4ecc
JANKEN_SIDE = 0x02113dd4
VIEW_SEED = 0x02113dd0
VIEW_FIRST = 0x02113de8
SYS_RAND = 0x020fc978
PLAYERS = 0x022cdff0
PSIZE = 0xfac
DECK_COUNT = 0x10
DECK = 0x3a0
SIDES = {'bottom': 0, 'top': 1}
HAND = 5


class Rsp:
    def __init__(self, port, timeout=60):
        t0 = time.time()
        while True:
            try:
                self.s = socket.create_connection(('127.0.0.1', port), 2)
                break
            except OSError:
                if time.time() - t0 > 20:
                    raise SystemExit(f'no melonDS GDB stub on port {port}')
                time.sleep(0.3)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.s.settimeout(timeout)
        self.buf = b''
        self.ack = True
        self.s.sendall(b'+')
        time.sleep(0.2)
        self.cmd('qSupported:swbreak+;hwbreak+')
        self.ok('QStartNoAckMode')
        self.ack = False

    def reply(self):
        while True:
            i = self.buf.find(b'$')
            j = self.buf.find(b'#', i)
            if i >= 0 and j >= 0 and len(self.buf) >= j + 3:
                data = self.buf[i + 1:j]
                self.buf = self.buf[j + 3:]
                if self.ack:
                    self.s.sendall(b'+')
                return data.decode('latin1')
            try:
                chunk = self.s.recv(65536)
            except socket.timeout:
                raise SystemExit('melonDS GDB stub: no answer (breakpoint never reached?)')
            if not chunk:
                raise SystemExit('melonDS GDB stub closed the connection')
            self.buf += chunk

    def cmd(self, data, reply=True):
        raw = data.encode('latin1')
        self.s.sendall(b'$' + raw + b'#' + b'%02x' % (sum(raw) & 0xff))
        return self.reply() if reply else None

    def ok(self, data):
        r = self.cmd(data)
        if r != 'OK':
            raise SystemExit(f'melonDS GDB stub: {data[:24]} -> {r}')

    def read(self, addr, n):
        return bytes.fromhex(self.cmd(f'm{addr:x},{n:x}'))

    def u32(self, addr):
        return struct.unpack('<I', self.read(addr, 4))[0]

    def write(self, addr, data):
        self.ok(f'M{addr:x},{len(data):x}:{data.hex()}')

    def w32(self, addr, v):
        self.write(addr, struct.pack('<I', v))

    def reg(self, n):
        return struct.unpack('<I', bytes.fromhex(self.cmd(f'p{n:x}')))[0]

    def set_reg(self, n, v):
        self.ok(f'P{n:x}={struct.pack("<I", v).hex()}')

    def detach(self):
        try:
            self.cmd('D')
        finally:
            self.s.close()


def load(path, cards):
    with open(path) as f:
        spec = json.load(f)
    if not isinstance(spec, dict) or set(spec) - {'first', 'bottom', 'top'}:
        raise SystemExit(f'{path}: keys are "first", "bottom", "top"')
    if spec.get('first') not in (None, 'bottom', 'top'):
        raise SystemExit(f'{path}: "first" is "bottom" or "top"')
    for side in ('bottom', 'top'):
        s = spec.get(side, {})
        if not isinstance(s, dict) or set(s) - {'hand', 'deck'}:
            raise SystemExit(f'{path}: "{side}" holds "hand" and "deck"')
        if any(not isinstance(s.get(z, []), list) for z in ('hand', 'deck')):
            raise SystemExit(f'{path}: {side} "hand" and "deck" are lists of card names')
        if 'hand' in s and len(s['hand']) != HAND:
            raise SystemExit(f'{path}: {side} hand: {HAND} cards, not {len(s["hand"])}')
        for zone in ('hand', 'deck'):
            for i, name in enumerate(s.get(zone, [])):
                cards.index.resolve(name, f'{path}: {side} {zone}[{i}]')
    return spec


def gdb_config(src, dst, port):
    os.makedirs(os.path.join(dst, 'melonDS'), exist_ok=True)
    for f in os.listdir(os.path.join(src, 'melonDS')):
        if f != 'melonDS.toml':
            shutil.copy(os.path.join(src, 'melonDS', f), os.path.join(dst, 'melonDS', f))
    with open(os.path.join(src, 'melonDS', 'melonDS.toml')) as f:
        t = f.read()
    t = re.sub(r'(\[Instance0\.Gdb\]\n)Enabled = \w+', r'\1Enabled = true', t)
    for arm, p in (('ARM9', port), ('ARM7', port + 1)):
        t = re.sub(rf'(\[Instance0\.Gdb\.{arm}\]\n(?:[^\[\n].*\n)*?)Port = \d+', lambda m: m.group(1) + f'Port = {p}', t)
    t = re.sub(r'(?m)^(\[JIT\]\n(?:[^\[\n].*\n)*?)Enable = \w+', lambda m: m.group(1) + 'Enable = false', t)
    with open(os.path.join(dst, 'melonDS', 'melonDS.toml'), 'w') as f:
        f.write(t)


_ports = {'next': 23330, 'lock': threading.Lock()}


def free_port():
    with _ports['lock']:
        while True:
            port = _ports['next']
            _ports['next'] += 2
            try:
                for p in (port, port + 1):
                    with socket.socket() as s:
                        s.bind(('127.0.0.1', p))
                return port
            except OSError:
                continue


def order_deck(words, side, spec, cards):
    s = spec.get(side, {})
    rest = list(words)
    picked = {}
    for zone in ('hand', 'deck'):
        picked[zone] = []
        for name in s.get(zone, []):
            ids = set(cards.index.resolve(name, side))
            w = next((w for w in rest if w & 0x3fff in ids), None)
            if w is None:
                raise SystemExit(f'deal: {side} {zone}: {name!r} is not in that Deck '
                                 f'(or listed more times than the Deck holds it)')
            rest.remove(w)
            picked[zone].append(w)
    hand = picked['hand'] if 'hand' in s else rest[:HAND]
    if 'hand' not in s:
        rest = rest[HAND:]
    return hand + picked['deck'] + rest


def apply(port, spec, cards, seed, tap):
    if not 1 <= seed <= 0xffffffff:
        raise SystemExit(f'seed {seed}: 1 to 0xffffffff')
    want = None if spec.get('first') is None else SIDES[spec['first']]
    g = Rsp(port)
    log = {'seed': seed}
    try:
        bps = ([(JANKEN_RESULT, 4), (CHOICE_RAND, 4)] if want is not None else []) + [(JANKEN_EXIT, 4), (AFTER_SHUFFLE, 2)]
        for addr, kind in bps:
            g.ok(f'Z0,{addr:x},{kind}')
        g.cmd('c', reply=False)
        tap()
        while True:
            g.reply()
            pc = g.reg(15)
            if pc == JANKEN_RESULT:
                chooser = want ^ (g.u32(JANKEN_SIDE) & 1)
                a = g.u32(HAND_A)
                g.w32(HAND_B, (a + (2 if chooser else 1)) % 3)
                log.setdefault('janken', []).append([a, g.u32(HAND_B)])
            elif pc == CHOICE_RAND:
                g.set_reg(0, want ^ (g.u32(JANKEN_SIDE) & 1))
            elif pc == JANKEN_EXIT:
                first = (g.u32(FIRST_CHOICE) ^ g.u32(JANKEN_SIDE)) & 1
                if want is not None and first != want:
                    raise SystemExit(f'deal: the janken chose player {first}, not {want}')
                log['first'] = first
                g.w32(VIEW_SEED, seed)
            elif pc == AFTER_SHUFFLE:
                if g.u32(VIEW_SEED) != seed:
                    raise SystemExit(f'deal: seed {g.u32(VIEW_SEED):#x} at the shuffle, not {seed:#x}')
                g.w32(SYS_RAND, seed)
                for side, p in SIDES.items():
                    base = PLAYERS + p * PSIZE + DECK
                    n = g.u32(PLAYERS + p * PSIZE + DECK_COUNT)
                    words = list(struct.unpack(f'<{n}I', g.read(base, 4 * n)))
                    new = order_deck(words, side, spec, cards)
                    if new != words:
                        g.write(base, struct.pack(f'<{n}I', *new))
                    log[side] = [w & 0x3fff for w in new]
                return log
            else:
                raise SystemExit(f'deal: stopped at {pc:#x}')
            g.cmd('c', reply=False)
    finally:
        try:
            for addr, kind in bps:
                g.cmd(f'z0,{addr:x},{kind}')
        except (SystemExit, OSError):
            pass
        g.detach()
