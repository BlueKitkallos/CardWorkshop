#!/usr/bin/env python3
import argparse
import json
import os
import struct
import sys

import ndspy.lz10

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import bustup
import carddb
import game
import nsbmd
import nttx
import w11lang
import w11unlock
from ydc import Deck

SCRIPT_PAC = 'Data_arc_pac/RPG_SCRIPT_J'
MES_IDX_PAC = 'Data_arc_pac/RPG_SCRIPT_MES_IDX'
MES_TXT_PAC = 'Data_arc_pac/RPG_SCRIPT_MES_TXT'
MES_LANGS = 'jegfisk'
TALK_BU_PAC = 'Data_arc_pac/RPG2D_BU'
DUEL_BU_PAC = 'Data_arc_pac/duel2d/BustupR'
MODEL_PAC = 'Data_arc_pac/RPG3D'
BIN_PAC = 'Data_arc_pac/bin'
BIN2_PAC = 'Data_arc_pac/bin2'
DECK_PAC = 'Data_arc_pac/deck'
DUEL_BU_L_PAC = 'Data_arc_pac/duel2d/BustupL'
WEAR_PAC = 'Data_arc_pac/CharaMake/wear'
JP_ART = [(DUEL_BU_PAC, 'bu129_r'), (DUEL_BU_PAC, 'bu129b_r'), (DUEL_BU_L_PAC, 'bu129_l'), (DUEL_BU_L_PAC, 'bu129b_l'),
          (TALK_BU_PAC, 'npc129_bu01_l'), (TALK_BU_PAC, 'npc129_bu01_r'), (WEAR_PAC, 'f_wear08_l'), (WEAR_PAC, 'f_wear08_r')]
JP_ART_EXTS = ('lznanr', 'lzncer', 'lzncgr', 'lznclr')
PLAYER_MOTION_FIXES = {'mpa12.lznsbca': (27, 28)}
YDC_HEADER = bytes.fromhex('01cccccc808f9947')

STORY_CHARS = 0x12d
STOCK_CHARAS = 465
STOCK_DECK_FILES = 253
CHAR_DECK_FN = 0x0201a428
CHAR_IDS = 0x10000
PLAYER_DECKS = 2
RENTAL_FIRST, RENTAL_N = 0x11e, 15
NEW_DECK_FIRST = RENTAL_FIRST + RENTAL_N
TALK_LANGS = 'efgijks'
TALK_ENC = {'j': 'cp932', 'k': 'euc-kr'}
TALK_GENERIC = 56
TALK_SET_LINES = 28
TALK_SET_MAX = 254
FREE_LIST_CAP = 256
FREE_LIST_STOCK = 60
DECK_MAX = 0xfffe
DS_DATA = 0xc000
RESULT_VAR = 4

SYS_END = 0x1
SYS_FLAG_SET = 0x900
SYS_FLAG_GET = 0x901
SYS_CHARA = 0x302
SYS_POS = 0x308
SYS_DIR = 0x30c
SYS_FACE = 0x312
SYS_TALKABLE = 0x318
SYS_SHADOW = 0x32f
SYS_BU_LOAD = 0x550
SYS_BU_FREE = 0x551
SYS_BU_POSE = 0x552
SYS_BU_SHOW = 0x554
SYS_MSG = 0x882
SYS_MSG_CLOSE = 0x888
SYS_WAIT = 0xa01
SYS_DUEL = 0xa81

EV_INIT = (0, 1)
EV_ENTER = 3
EV_TALK = (0xc, 0x14)


def char_deck(a9, char, fn=CHAR_DECK_FN):
    rd = lambda a: struct.unpack_from('<H', a9, a - 0x02000000)[0]
    s32 = lambda v: (v & 0xffffffff) - (1 << 32) if v & 0x80000000 else v & 0xffffffff
    r = [char, 0, 0, 0, 0, 0, 0, 0]
    flags = (0, 0)
    pc = fn
    for _ in range(256):
        op = rd(pc)
        nxt = pc + 2
        if op >> 9 == 0x5a:
            pass
        elif op >> 9 == 0x5e:
            return r[0]
        elif op >> 11 == 0x09:
            r[op >> 8 & 7] = struct.unpack_from('<I', a9, ((pc + 4) & ~3) + (op & 0xff) * 4 - 0x02000000)[0]
        elif op >> 11 == 0x05:
            flags = (s32(r[op >> 8 & 7]), op & 0xff)
        elif op >> 6 == 0x10a:
            flags = (s32(r[op & 7]), s32(r[op >> 3 & 7]))
        elif op >> 11 == 0x04:
            r[op >> 8 & 7] = op & 0xff
        elif op >> 11 == 0x00:
            r[op & 7] = (r[op >> 3 & 7] << (op >> 6 & 31)) & 0xffffffff
        elif op >> 11 == 0x02:
            r[op & 7] = (s32(r[op >> 3 & 7]) >> (op >> 6 & 31)) & 0xffffffff
        elif op >> 9 in (0x0e, 0x0f):
            v = op >> 6 & 7
            r[op & 7] = (r[op >> 3 & 7] + (v if op >> 9 == 0x0e else -v)) & 0xffffffff
        elif op >> 9 == 0x0c:
            r[op & 7] = (r[op >> 3 & 7] + r[op >> 6 & 7]) & 0xffffffff
        elif op >> 11 in (0x06, 0x07):
            k = op >> 8 & 7
            r[k] = (r[k] + ((op & 0xff) if op >> 11 == 0x06 else -(op & 0xff))) & 0xffffffff
        elif op & 0xff87 == 0x4487:
            pc = pc + 4 + s32(r[op >> 3 & 7])
            continue
        elif op & 0xff78 == 0x4478:
            k = op & 7 | (op >> 4 & 8)
            r[k] = (r[k] + pc + 4) & 0xffffffff
        elif op >> 11 == 0x11:
            r[op & 7] = rd(r[op >> 3 & 7] + (op >> 6 & 31) * 2)
        elif op >> 12 == 0xd and op >> 8 & 15 < 14:
            a, b = flags
            ua, ub = a & 0xffffffff, b & 0xffffffff
            ok = {0: a == b, 1: a != b, 2: ua >= ub, 3: ua < ub, 8: ua > ub, 9: ua <= ub,
                  10: a >= b, 11: a < b, 12: a > b, 13: a <= b}.get(op >> 8 & 15)
            if ok is None:
                raise SystemExit(f'char table: condition {op >> 8 & 15} at {pc:#x}')
            off = op & 0xff
            pc = pc + 4 + 2 * (off - 0x100 if off & 0x80 else off) if ok else nxt
            continue
        elif op >> 11 == 0x1c:
            off = op & 0x7ff
            pc = pc + 4 + 2 * (off - 0x800 if off & 0x400 else off)
            continue
        elif op >> 11 == 0x1e and rd(pc + 2) >> 11 == 0x1f:
            hi = op & 0x7ff
            pc = pc + 4 + ((hi - 0x800 if hi & 0x400 else hi) << 12) + ((rd(pc + 2) & 0x7ff) << 1)
            continue
        else:
            raise SystemExit(f'char table: Thumb op {op:#06x} at {pc:#x} not handled (not the EU WC2011 arm9?)')
        pc = nxt
    raise SystemExit(f'char table: char {char:#x} does not return')


def stock_char_decks(a9):
    used = {}
    for c in range(CHAR_IDS):
        d = char_deck(a9, c)
        if d >= PLAYER_DECKS:
            used.setdefault(d, []).append(c)
    return used


def lz11_literal(data):
    out = bytearray(b'\x11' + struct.pack('<I', len(data))[:3]) if len(data) < 1 << 24 else None
    if out is None:
        raise SystemExit('file over 16 MB')
    for i in range(0, len(data), 8):
        out.append(0)
        out += data[i:i + 8]
    out += b'\0' * (-len(out) % 4)
    return bytes(out)


class Asm:
    REG = {'ax': 0, 'cx': 1, 'dx': 2, 'bx': 3, 'sp': 4, 'bp': 5, 'si': 6, 'di': 7}

    def __init__(self, base):
        self.base = base
        self.b = bytearray()
        self.labels = {}
        self.fix = []

    def here(self):
        return self.base + len(self.b)

    def label(self, name):
        if name in self.labels:
            raise SystemExit(f'asm: label {name} twice')
        self.labels[name] = self.here()

    def w(self, *bs):
        self.b += bytes(bs)

    def w16(self, v):
        self.b += struct.pack('<H', v & 0xffff)

    def mov_r(self, r, v):
        self.w(0xb8 + self.REG[r])
        self.w16(v)

    def mov_m(self, addr, v):
        self.w(0xc7, 0x06)
        self.w16(addr)
        self.w16(v)

    def load_ax(self, addr):
        self.w(0xa1)
        self.w16(addr)

    def store_ax(self, addr):
        self.w(0xa3)
        self.w16(addr)

    def cmp_ax(self, v):
        self.w(0x3d)
        self.w16(v)

    def test_ax(self):
        self.w(0x85, 0xc0)

    def push(self, r):
        self.w(0x50 + self.REG[r])

    def pop(self, r):
        self.w(0x58 + self.REG[r])

    def cwd(self):
        self.w(0x99)

    def ret(self):
        self.w(0xc3)

    def _rel16(self, op, target):
        self.w(op)
        self.fix.append((len(self.b), target))
        self.w16(0)

    def jmp(self, target):
        self._rel16(0xe9, target)

    def call(self, target):
        self._rel16(0xe8, target)

    def jcc_over(self, op, target):
        self.w(op ^ 1, 3)
        self.jmp(target)

    def je(self, target):
        self.jcc_over(0x74, target)

    def jne(self, target):
        self.jcc_over(0x75, target)

    def resolve(self):
        for at, target in self.fix:
            t = self.labels[target] if isinstance(target, str) else target
            struct.pack_into('<H', self.b, at, (t - (self.base + at + 2)) & 0xffff)
        return bytes(self.b)


class Script:
    def __init__(self, raw, name):
        self.name = name
        self.d = bytearray(raw)
        if self.d[:4] != b'(C)2' or b'SCRIPT DATA' not in self.d[:0x20]:
            raise SystemExit(f'{name}: not a WC2011 story script')
        self.hdr = list(struct.unpack_from('<6I', self.d, 0x20))
        if self.hdr[0] != 0:
            raise SystemExit(f'{name}: code offset {self.hdr[0]:#x}, expected 0')
        self.code_end = 0x200 + self.hdr[1]
        self.ds = self.code_end & ~0xf
        self.blk = self.code_end - self.ds
        self.stubs = self._stubs()
        self.handlers = self._handlers()

    def ip(self, off):
        return off - 0x200

    def _stubs(self):
        from capstone import Cs, CS_ARCH_X86, CS_MODE_16
        md = Cs(CS_ARCH_X86, CS_MODE_16)
        self.ins = list(md.disasm(bytes(self.d[0x200:self.code_end]), 0))
        key = f'word ptr [{self.blk if self.blk < 10 else hex(self.blk)}], '
        stubs = {}
        for i, a in enumerate(self.ins):
            if a.mnemonic == 'mov' and a.op_str.startswith(key):
                j = i
                while j > 0 and self.ins[j - 1].mnemonic not in ('ret', 'jmp'):
                    j -= 1
                stubs.setdefault(int(a.op_str.split(', ')[1], 0), self.ins[j].address)
        return stubs

    def _handlers(self):
        main = (struct.unpack_from('<h', self.d, 0x203)[0] + 0x205 - 0x200) & 0xffff
        if self.d[0x202] != 0xe8:
            raise SystemExit(f'{self.name}: entry does not call main')
        reg = self.stubs.get(4)
        if reg is None:
            raise SystemExit(f'{self.name}: no event registration stub')
        out = {}
        idx = {a.address: k for k, a in enumerate(self.ins)}
        k = idx[main]
        while self.ins[k].mnemonic != 'ret':
            a = self.ins[k]
            if a.mnemonic == 'call' and int(a.op_str, 0) & 0xffff == reg:
                ev, h = self.ins[k - 2], self.ins[k - 1]
                evv = 0 if ev.op_str == 'ax, ax' else int(ev.op_str.split(', ')[1], 0)
                if not h.op_str.startswith('bx, '):
                    raise SystemExit(f'{self.name}: unexpected registration at {a.address:#x}')
                out[evv] = (int(h.op_str.split(', ')[1], 0), 0x200 + h.address + 1)
            k += 1
        return out

    def insert(self, code):
        a = 0x200 + (self.hdr[1] & ~0xf)
        tail = self.code_end - a
        n = (len(code) + tail + 0xf) & ~0xf
        new = bytearray(bytes(self.d[:self.code_end]) + code + b'\xc3' * (n - tail - len(code)) + bytes(self.d[a:]))
        hdr = list(self.hdr)
        hdr[1] += n
        hdr[2] += n
        hdr[4] += n
        struct.pack_into('<6I', new, 0x20, *hdr)
        return new


def u32(v):
    return v & 0xffffffff


def fx(v):
    return u32(round(float(v) * 0x1000))


def angle(deg):
    return round(float(deg) / 360 * 0x10000) & 0xffff


class Emitter:
    def __init__(self, script, asm, strings):
        self.s = script
        self.a = asm
        self.str = strings

    def sys(self, cmd, args):
        a, blk = self.a, self.s.blk
        for i, v in enumerate(args):
            if isinstance(v, str):
                v = self.str[v]
            v = u32(v)
            a.mov_m(blk + 4 + 4 * i, v & 0xffff)
            a.mov_m(blk + 6 + 4 * i, v >> 16)
        a.mov_m(blk, cmd)
        a.mov_m(blk + 2, 0)
        a.load_ax(blk + 0x104)


def stock(rom):
    out = {}
    for arc in (SCRIPT_PAC, MES_IDX_PAC, MES_TXT_PAC, TALK_BU_PAC, DUEL_BU_PAC, DUEL_BU_L_PAC, WEAR_PAC, BIN_PAC,
                BIN2_PAC, DECK_PAC):
        out[arc] = game.container_files(rom, arc + '.pac')
    out[MODEL_PAC] = {k: None for k in game.container_files(rom, MODEL_PAC + '.pac')}
    return out


def mes_append(idx, txt, lines):
    offs = list(struct.unpack(f'<{len(idx) // 4}I', idx))
    if not offs or offs[-1] != len(txt):
        raise SystemExit('message index: the last offset is not the end of the text file')
    offs.pop()
    body = bytearray(txt)
    first = len(offs)
    for s in lines:
        offs.append(len(body))
        raw = s.encode('latin1')
        body += raw + b'\0' * (4 - len(raw) % 4)
    offs.append(len(body))
    return struct.pack(f'<{len(offs)}I', *offs), bytes(body), first


def check_line(s, where):
    if not s:
        raise SystemExit(f'{where}: empty line')
    rows = s.split('\n')
    if len(rows) > 3:
        raise SystemExit(f'{where}: {len(rows)} rows, the message box holds 3')
    for r in rows:
        if len(r) > 36:
            raise SystemExit(f'{where}: row "{r}" is {len(r)} characters, the box holds about 36')
    try:
        s.encode('latin1')
    except UnicodeEncodeError:
        raise SystemExit(f'{where}: only Latin-1 characters')


OAM_WIDTH = ((8, 16, 32, 64), (16, 32, 32, 64), (8, 8, 16, 32))


def alias_portrait_poses(nanr, aliases):
    """Reuse an original NANR sequence without changing its cells or artwork."""
    original = bytes(nanr)
    out = bytearray(original)
    p = bustup.section(original, b'KNBA') + 8
    count, _, offset = struct.unpack_from('<HHI', original, p)
    for alias, source in aliases.items():
        alias, source = int(alias), int(source)
        if not (0 <= alias < count and 0 <= source < count):
            raise ValueError(f'portrait pose alias {alias} -> {source}: only {count} sequences')
        dst, src = p + offset + alias * 16, p + offset + source * 16
        out[dst:dst + 16] = original[src:src + 16]
    return bytes(out)


def mirror_ncer(ncer):
    d = bytearray(ncer)
    p = bustup.section(d, b'KBEC')
    n, attr, off = struct.unpack_from('<HHI', d, p + 8)
    tab = p + 8 + off
    rec = 16 if attr & 1 else 8
    oams = tab + n * rec
    for i in range(n):
        no, ca, o = struct.unpack_from('<HHI', d, tab + i * rec)
        if no:
            struct.pack_into('<H', d, tab + i * rec + 2, ca ^ 0x100)
        if attr & 1:
            xmax, ymax, xmin, ymin = struct.unpack_from('<4h', d, tab + i * rec + 8)
            struct.pack_into('<4h', d, tab + i * rec + 8, -xmin, ymax, -xmax, ymin)
        for j in range(no):
            q = oams + o + j * 6
            a0, a1 = struct.unpack_from('<HH', d, q)
            if a0 & 0x100:
                raise SystemExit('mirror_ncer: affine OAM not handled')
            x = a1 & 0x1ff
            x = x - 512 if x >= 256 else x
            x = -x - OAM_WIDTH[a0 >> 14][a1 >> 14]
            struct.pack_into('<H', d, q + 2, (a1 & ~0x11ff) | (~a1 & 0x1000) | (x & 0x1ff))
    return bytes(d)


def bustup_cells(img, box):
    idx, colors = bustup.quantize(img)
    w, h = img.size
    data = bytearray()
    oams = []
    for by in range(0, h, 64):
        for bx in range(0, w, 64):
            block = [idx[(by + y) * w + bx:(by + y) * w + min(w, bx + 64)].ljust(64, b'\0') if by + y < h else bytes(64)
                     for y in range(64)]
            if not any(any(r) for r in block):
                continue
            tile = len(data) // bustup.UNIT
            for ty in range(8):
                for tx in range(8):
                    for y in range(8):
                        data += block[ty * 8 + y][tx * 8:tx * 8 + 8]
            x, y = bx + box[0], by + box[1]
            oams.append(struct.pack('<HHH', (y & 0xff) | 0x2000, (x & 0x1ff) | 3 << 14, tile))
    return bytes(data), colors, oams


def bustup_files(img, box, template):
    t_ncer, t_nanr, t_nclr = template
    ncells = struct.unpack_from('<H', t_ncer, bustup.section(t_ncer, b'KBEC') + 8)[0]
    data, colors, oams = bustup_cells(img, box)
    char = struct.pack('<HHIIIII', 0xffff, 0xffff, 4, 0x00200010, 0, len(data), 0x18) + data
    ncgr = bustup.nitro(b'RGCN', 0x0101, [b'RAHC' + struct.pack('<I', 8 + len(char)) + char])
    nclr = bytearray(t_nclr)
    p = bustup.section(nclr, b'TTLP')
    off = p + 8 + struct.unpack_from('<I', nclr, p + 8 + 0xc)[0]
    struct.pack_into('<256H', nclr, off, *(bustup.to555(*c) for c in colors))
    nclr = bytes(nclr)
    oam = b''.join(oams)
    table = b''.join(struct.pack('<HHI', len(oams), 0x1f, 0) for _ in range(ncells))
    cebk = struct.pack('<HHIIIII', ncells, 0, 0x18, 2, 0, 0, 0) + table + oam
    cebk += b'\0' * (-len(cebk) % 4)
    names = b''.join(f'CellAnime{i}\0'.encode() for i in range(ncells))
    offs = []
    p = 0
    for i in range(ncells):
        offs.append(p)
        p += len(f'CellAnime{i}') + 1
    lbal = b'LBAL' + struct.pack('<I', 8 + 4 * ncells + len(names)) + struct.pack(f'<{ncells}I', *offs) + names
    uext = b'TXEU' + struct.pack('<II', 12, 0)
    ncer = bustup.nitro(b'RECN', 0x0100, [b'KBEC' + struct.pack('<I', 8 + len(cebk)) + cebk, lbal, uext])
    return {'ncgr': ncgr, 'nclr': nclr, 'ncer': ncer, 'nanr': t_nanr}


def head_offset(body, face, rows=45, reach=12):
    import numpy as np
    b, f = np.asarray(body).astype(int), np.asarray(face).astype(int)
    y0 = face.getbbox()[1]
    src = f[y0:y0 + rows]
    mask = src[..., 3] > 0
    best = None
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            dst = np.roll(b, (dy, dx), axis=(0, 1))[y0:y0 + rows]
            both = mask & (dst[..., 3] > 0)
            if not both.any():
                continue
            cost = (np.abs(src[..., :3] - dst[..., :3]).sum(axis=2)[both].mean()
                    + 255 * (mask != (dst[..., 3] > 0)).mean())
            if best is None or cost < best[0]:
                best = (cost, dx, dy)
    return best


def merge_colours(images, limit=255, fixed=frozenset()):
    from collections import Counter
    pixels = [p[:3] for im in images for p in im.get_flattened_data() if p[3] >= 128]
    count = Counter(pixels)
    alive, target = set(count), {c: c for c in count}
    if len(alive & set(fixed)) > limit:
        raise ValueError(f'{len(alive & set(fixed))} colours must stay, over the {limit} of one palette')
    while len(alive) > limit:
        best = None
        for c in alive - set(fixed):
            d, o = min((sum(abs(x - y) for x, y in zip(c, o)), o) for o in alive if o != c)
            if best is None or count[c] * d < best[0]:
                best = (count[c] * d, c, o)
        _, c, o = best
        alive.discard(c)
        count[o] += count[c]
        for k, v in target.items():
            if v == c:
                target[k] = o
    out = []
    for im in images:
        px = [target[p[:3]] + (255,) if p[3] >= 128 else (0, 0, 0, 0) for p in im.get_flattened_data()]
        m = im.copy()
        m.putdata(px)
        out.append(m)
    return out


def hue_in(h, rng):
    lo, hi = rng
    return (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)


def hls_planes(a):
    import colorsys
    import numpy as np
    cols, inv = np.unique(a[..., :3].reshape(-1, 3), axis=0, return_inverse=True)
    hls = np.array([colorsys.rgb_to_hls(*(c / 255)) for c in cols]).reshape(-1, 3)[inv.reshape(-1)]
    hls = hls.reshape(a.shape[:2] + (3,))
    return hls[..., 0] * 360, hls[..., 1], hls[..., 2]


def set_hls(a, sel, h, light, sat):
    import colorsys
    import numpy as np
    for y, x in zip(*np.nonzero(sel)):
        rgb = colorsys.hls_to_rgb(h[y, x] / 360 % 1, min(light[y, x], 1), min(sat[y, x], 1))
        a[y, x, :3] = nttx.bgr555(bustup.to555(*(round(v * 255) for v in rgb)))


def near(mask):
    import numpy as np
    p = np.pad(mask, 1)
    h, w = mask.shape
    return np.any([p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)


def recolor_rgba(a, rules, parts, origin_y=None, keep=None):
    import numpy as np
    h, light, sat = hls_planes(a)
    alpha = a[..., 3] >= 128
    if keep is not None:
        alpha &= ~keep
    out, masks = a.copy(), {}
    if not alpha.any():
        return out, masks
    sk = rules['skin']
    masks['skin'] = alpha & hue_in(h, sk['hue']) & (light >= sk['min_light'])
    if 'outfit' in parts:
        o = rules['outfit']
        m = masks['outfit'] = alpha & (sat > o['min_sat']) & hue_in(h, o['hue'])
        set_hls(out, m, np.full_like(h, o['to_hue']), light * o['light'], sat * o['sat'])
    if 'hair' in parts:
        r = rules['hair']
        m = alpha & hue_in(h, r['hue']) & (sat > r['min_sat']) & (light < r['max_light']) & ~near(masks['skin'])
        if origin_y is not None:
            m[max(0, origin_y + r['max_y']):] = False
        masks['hair'] = m
        set_hls(out, m, np.full_like(h, r['to_hue']), light * r['light'], sat)
    return out, masks


def recolor_image(im, rules, origin_y, keep=None, unchanged=None):
    import numpy as np
    from PIL import Image
    a = np.array(im.convert('RGBA'))
    out, _ = recolor_rgba(a, rules, ('outfit', 'hair'), origin_y, keep)
    if unchanged is not None:
        same = np.all(out == a, axis=2) & (a[..., 3] >= 128)
        unchanged.update(map(tuple, a[same][:, :3].tolist()))
    return Image.fromarray(out, 'RGBA')


def recolor_tex4x4(t, pal_data, rules, parts):
    import collections
    import functools
    import numpy as np
    rgba = nsbmd.decode_texture(t, pal_data)
    _, masks = recolor_rgba(rgba, rules, parts)
    w, h = nsbmd.tex_dims(t['param'])
    pal = list(struct.unpack(f'<{len(pal_data) // 2}H', pal_data[:len(pal_data) // 2 * 2]))
    pal += [0] * (len(pal) % 2)
    groups = {}
    words = struct.unpack(f'<{w * h // 16}I', t['data'])
    idx = list(struct.unpack(f'<{w * h // 16}H', t['idx']))

    @functools.cache
    def change(c, part):
        px = np.array([[[*nsbmd.expand(nsbmd.c555(c)), 255]]], np.uint8)
        new, m = recolor_rgba(px, {**rules, 'skin': {'hue': [0, 0], 'min_light': 2}}, (part,))
        return nsbmd.pack555(nsbmd.to5(new[0, 0, :3].astype(np.int32))) if m[part][0, 0] else c

    for b in range(len(idx)):
        bx, by = (b % (w // 4)) * 4, (b // (w // 4)) * 4
        addr, mode = (idx[b] & 0x3fff) << 1, idx[b] >> 14
        n = 4 if mode in (0, 2) else 2
        base = [pal[addr + k] if addr + k < len(pal) else 0 for k in range(n)]
        votes = [collections.Counter() for _ in range(n)]
        for k in range(16):
            slot = (words[b] >> (2 * k)) & 3
            if mode in (0, 1) and slot == 3:
                continue
            part = next((q for q in parts if masks[q][by + k // 4, bx + k % 4]), None)
            for j in [slot] if slot < n else [0, 1]:
                votes[j][part] += 1
        new = [change(c, v.most_common(1)[0][0]) if v and v.most_common(1)[0][0] else c
               for c, v in zip(base, votes)]
        if new != base:
            key = tuple(new)
            if key not in groups:
                groups[key] = len(pal)
                pal += list(key) + [0] * (len(key) % 2)
            idx[b] = (idx[b] & 0xc000) | (groups[key] >> 1)
    out = {**t, 'idx': struct.pack(f'<{len(idx)}H', *idx)}
    return out, struct.pack(f'<{len(pal)}H', *pal), masks, rgba


def recolor_model(data, rules):
    import numpy as np
    ir = nsbmd.parse_bmd(data)
    pals = {p['name']: p for p in ir['tex']['palettes']}
    report = {}
    for i, t in enumerate(ir['tex']['textures']):
        parts = rules['textures'].get(t['name'])
        if not parts:
            continue
        if (t['param'] >> 26) & 7 != 5:
            raise SystemExit(f'model recolor: texture {t["name"]} is not 4x4 compressed')
        p = pals[t['name'] + '_pl']
        if sum(q['data'] == p['data'] for q in ir['tex']['palettes']) > 1:
            raise SystemExit(f'model recolor: palette {p["name"]} is shared')
        new, p['data'], masks, before = recolor_tex4x4(t, p['data'], rules, parts)
        ir['tex']['textures'][i] = new
        after = nsbmd.decode_texture(new, p['data'])
        diff = np.any(after != before, axis=2)
        report[t['name']] = {k: int(v.sum()) for k, v in masks.items()} | {
            'changed': int(diff.sum()), 'skin_changed': int((diff & masks['skin']).sum())}
    return nsbmd.build_bmd(ir), report


def duel_composite(body, disk, disk_offset, pose, faces, head_rows=65):
    import numpy as np
    from PIL import Image, ImageChops, ImageFilter
    base = body.copy()
    base.alpha_composite(ImageChops.offset(disk, *disk_offset))
    top = body.getbbox()[1]
    cells, offsets = [], []
    for face in faces:
        cost, dx, dy = head_offset(body, face)
        offsets.append((dx, dy, round(float(cost), 1)))
        f = ImageChops.offset(face, -dx, -dy)
        diff = np.abs(np.asarray(f).astype(int) - np.asarray(body).astype(int)).sum(axis=2) > 40
        diff[:top] = False
        diff[top + head_rows:] = False
        mask = Image.fromarray((diff * 255).astype('uint8')).filter(ImageFilter.MaxFilter(3))
        im = base.copy()
        im.paste(f, (0, 0), mask)
        cells.append(im)
    pose_dx = pose[0].getbbox()[0] - pose[1].getbbox()[0]
    if ImageChops.difference(ImageChops.offset(pose[1], pose_dx, 0), pose[0]).getbbox():
        raise ValueError('stock duel cell 0 is not cell 1 shifted sideways')
    return [ImageChops.offset(cells[0], pose_dx, 0)] + cells, offsets, pose_dx


def portrait_image(spec, where, size, flip=False):
    from PIL import Image
    src = spec.get('portrait')
    if not src:
        raise SystemExit(f'{where}: "portrait" is required')
    if 'wc2008' in src:
        d = os.path.join(src.get('extracted', 'extracted'), 'Data_arc_pac', 'Bustup')
        img = bustup.decode(*bustup.load(d, int(src['wc2008']))[:3])
    elif 'png' in src:
        img = bustup.portrait(src['png'], src.get('crop'), src.get('alpha_min', 128))
    else:
        raise SystemExit(f'{where}: portrait needs "wc2008": <bu number> or "png": <path>')
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    out.paste(img, ((size[0] - img.width) // 2 + src.get('dx', 0), size[1] - img.height), img)
    if flip:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    return out


class Builder:
    def __init__(self, rom_path, out):
        self.rom_path = rom_path
        self.rom = game.open_rom(rom_path)
        if bytes(self.rom.idCode) != b'BYYP':
            raise SystemExit(f'{rom_path}: game code {bytes(self.rom.idCode)!r}, expected BYYP (WC2011 EU)')
        self.out = out
        self.files = stock(self.rom)
        self.changed = {}
        self.tables = {'story': [], 'chara': [], 'free': [], 'deckname': [], 'charname': []}
        self.free_rating = {}
        self.free_unlock = {}
        self.card_specs = []
        self.card_names = {}
        self.base_pac = None
        self.text = None
        import ndspy.codeCompression
        self.stock_decks = stock_char_decks(ndspy.codeCompression.decompress(bytes(self.rom.arm9)))
        rows = len(self.files[BIN_PAC]['enemystatus.bin']) // 12
        if rows != NEW_DECK_FIRST:
            raise SystemExit(f'enemystatus.bin has {rows} rows, expected {NEW_DECK_FIRST} (decks 0-{NEW_DECK_FIRST - 1})')
        self.reserved = set()
        self.claimed = {}

    def claim_deck(self, want, where):
        def owner(d):
            if d < PLAYER_DECKS:
                return 'the player'
            if d in self.stock_decks:
                return 'stock character(s) ' + ', '.join(f'{c:#x}' for c in self.stock_decks[d])
            if RENTAL_FIRST <= d < NEW_DECK_FIRST:
                return 'a rental deck'
            if d in self.claimed:
                return self.claimed[d]
            return None
        kind = f'story NPCs and Free Duel opponents take new deck slots {NEW_DECK_FIRST}-{DECK_MAX}'
        if want is None:
            want = next((d for d in range(NEW_DECK_FIRST, DECK_MAX + 1) if owner(d) is None and d not in self.reserved),
                        None)
            if want is None:
                raise SystemExit(f'{where}: no free deck slot left ({kind})')
        else:
            want = int(want)
            who = owner(want)
            if who:
                raise SystemExit(f'{where}: deck_slot {want} is already used by {who}')
            if not NEW_DECK_FIRST <= want <= DECK_MAX:
                raise SystemExit(f'{where}: deck_slot {want}: {kind}')
        self.claimed[want] = where
        return want

    def get(self, arc, name):
        if (arc, name) in self.changed:
            return self.changed[(arc, name)]
        if self.base_pac:
            p = os.path.join(self.base_pac, arc, name)
            if os.path.isfile(p):
                with open(p, 'rb') as f:
                    return f.read()
        f = self.files[arc]
        if name not in f:
            raise SystemExit(f'{arc}.pac has no {name}')
        return f[name]

    def put(self, arc, name, data):
        self.changed[(arc, name)] = data

    def jp_art(self):
        for arc, stem in JP_ART:
            for ext in JP_ART_EXTS:
                self.put(arc, f'{stem}_e.{ext}', self.get(arc, f'{stem}_j.{ext}'))

    def player_motions(self):
        pac = game.container_files(self.rom, MODEL_PAC + '.pac')
        for name, drop in PLAYER_MOTION_FIXES.items():
            d = bytearray(nttx.lz_decompress(self.get(MODEL_PAC, name) or pac[name]))
            so = struct.unpack_from('<I', d, 16)[0]
            ao = so + struct.unpack('<I', nsbmd.read_dict(d, so + 8)[1][0])[0]
            n = struct.unpack_from('<H', d, ao + 6)[0]
            if n == 30:
                continue
            if n != 32:
                raise SystemExit(f'{name}: {n} nodes, expected 32')
            tags = struct.unpack_from(f'<{n}H', d, ao + 0x14)
            keep = [t for i, t in enumerate(tags) if i not in drop]
            struct.pack_into('<H', d, ao + 6, len(keep))
            struct.pack_into(f'<{n}H', d, ao + 0x14, *keep, *[0] * (n - len(keep)))
            for i, t in enumerate(keep):
                flag = struct.unpack_from('<I', d, ao + t)[0]
                struct.pack_into('<I', d, ao + t, flag & 0xffffff | i << 24)
            self.put(MODEL_PAC, name, lz11_literal(bytes(d)))

    def cards(self):
        if not hasattr(self, '_cards'):
            rom, prof, dbfiles = carddb.load_from_rom(self.rom_path)
            db = carddb.CardDB.load(dbfiles, prof)
            self._cards = {}
            in_pack = set()
            for c in db.cards[1:]:
                k = c.names['e'].lower()
                if any(c.packs) and self._cards.get(k) not in in_pack:
                    self._cards[k] = c.id
                    in_pack.add(c.id)
                self._cards.setdefault(k, c.id)
                self._cards[f'id:{c.id}'] = c.id
                self.card_names.setdefault(c.id, dict(c.names))
            for path in self.card_specs:
                with open(path, encoding='utf-8') as f:
                    for c in json.load(f).get('cards', []):
                        if c.get('source') != 'wc2011' and 'id' in c:
                            self._cards.setdefault(c['name'].lower(), int(c['id']))
                            self.card_names.setdefault(int(c['id']), dict(c.get('names') or {'e': c['name']}))
        return self._cards

    def deck(self, path, where):
        from deck_paths import resolve_deck
        path = resolve_deck(path)
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
        cards = self.cards()
        secs = {}
        for sec, cap in (('main', 60), ('extra', 15), ('side', 15)):
            ids = []
            for name, n in spec.get(sec, {}).items():
                cid = cards.get(name.lower())
                if cid is None:
                    raise SystemExit(f'{path}: {sec} card "{name}" is not in the WC2011 card database')
                ids += [cid] * int(n)
            if len(ids) > cap:
                raise SystemExit(f'{path}: {sec} has {len(ids)} cards, WC2011 holds {cap}')
            secs[sec] = ids
        if not 40 <= len(secs['main']) <= 60:
            raise SystemExit(f'{path}: main deck has {len(secs["main"])} cards, 40-60 allowed')
        return Deck(secs['main'], secs['extra'], secs['side'], YDC_HEADER), spec

    def stock_deck_source(self, path):
        """Apply a selected stock JSON, preserving untouched native deck bytes."""
        from collections import Counter
        deck, spec = self.deck(str(path), str(path))
        name = spec['stock_file'].lower()
        if name not in self.files[DECK_PAC]:
            raise SystemExit(f'{path}: no stock WC2011 deck file {name!r}')
        original = Deck.parse(self.files[DECK_PAC][name])
        if all(Counter(getattr(deck, s)) == Counter(getattr(original, s)) for s in ('main', 'extra', 'side')):
            return False  # Retain the stock order/header when only the location changed.
        if (DECK_PAC, name) in self.changed:
            raise SystemExit(f'{path}: {name} is already overridden by another deck/opponent spec')
        deck.header = original.header
        self.put(DECK_PAC, name, deck.build())
        return True

    def game_text(self, strings, where=None):
        bin2 = self.files[BIN2_PAC]
        langs = sorted(k[len('game_text_'):-4] for k in bin2 if k.startswith('game_text_'))
        tables = {}
        for lang in langs:
            ik, tk = f'game_indx_{lang}.bin', f'game_text_{lang}.bin'
            tables[lang] = carddb.read_strtab(self.get(BIN2_PAC, ik), self.get(BIN2_PAC, tk), 1, 0, lang)
        first = max(len(cur) for _, cur in tables.values())
        for lang, (prefix, cur) in tables.items():
            mine = [w11lang.tr(v, lang, 'name', where) if isinstance(v, str)
                    else v.get(lang) or v.get('j' if lang == 'r' else 'e') or w11lang.tr(v['e'], lang, 'name', where)
                    for v in strings]
            data, offs = carddb.build_strtab(prefix, cur + [''] * (first - len(cur)) + mine, lang)
            self.put(BIN2_PAC, f'game_indx_{lang}.bin', carddb.write_index([offs]))
            self.put(BIN2_PAC, f'game_text_{lang}.bin', data)
        return first

    def system_name(self, name, where=None):
        first = None
        for lang in MES_LANGS:
            ik, tk = f'system_idx_{lang}.bin', f'system_txt_{lang}.bin'
            idx, txt, n = mes_append(self.get(MES_IDX_PAC, ik), self.get(MES_TXT_PAC, tk),
                                     [w11lang.tr(name, lang, 'system', where)])
            self.put(MES_IDX_PAC, ik, idx)
            self.put(MES_TXT_PAC, tk, txt)
            if first not in (None, n):
                raise SystemExit(f'system_{lang}: name index {n}, other languages {first}')
            first = n
        return first

    def script_lines(self, mapname, lines, where=None):
        first = None
        for lang in MES_LANGS:
            ik, tk = f'{mapname}_idx_{lang}.bin', f'{mapname}_txt_{lang}.bin'
            idx, txt, n = mes_append(self.get(MES_IDX_PAC, ik), self.get(MES_TXT_PAC, tk),
                                     [w11lang.tr(x, lang, 'story', where) for x in lines])
            self.put(MES_IDX_PAC, ik, idx)
            self.put(MES_TXT_PAC, tk, txt)
            if first not in (None, n):
                raise SystemExit(f'{mapname}_{lang}: first new line {n}, other languages {first}')
            first = n
        return first

    def deck_slot(self, deck_file, deck, deck_no):
        self.put(DECK_PAC, f'{deck_file.lower()}.ydc', deck.build())
        fi, fn = self.get(BIN_PAC, 'deck_fileidx.bin'), self.get(BIN_PAC, 'deck_filename.bin')
        offs = list(struct.unpack(f'<{len(fi) // 2}H', fi))
        if offs[-1] != len(fn):
            raise SystemExit('deck_fileidx.bin: last offset is not the end of deck_filename.bin')
        names = [fn[a:b] for a, b in zip(offs, offs[1:])]
        while len(names) <= deck_no:
            names.append(b'\0')
        names[deck_no] = deck_file.encode('ascii') + b'\0'
        blob, offs = b'', []
        for nm in names:
            offs.append(len(blob))
            blob += nm
        offs.append(len(blob))
        self.put(BIN_PAC, 'deck_fileidx.bin', struct.pack(f'<{len(offs)}H', *offs))
        self.put(BIN_PAC, 'deck_filename.bin', blob)

    def stock_override(self, spec, base_dir, where):
        chara = int(spec['stock_chara'])
        decks = [d for d, cs in self.stock_decks.items() if chara in cs]
        if not 0 <= chara < STOCK_CHARAS or not decks:
            raise SystemExit(f'{where}: stock_chara {chara} is not a stock character with a deck')
        deck_no = decks[0]
        if self.stock_decks[deck_no] != [chara]:
            raise SystemExit(f'{where}: deck {deck_no} is shared by stock characters '
                             + ', '.join(str(c) for c in self.stock_decks[deck_no]))
        if deck_no in self.claimed:
            raise SystemExit(f'{where}: deck {deck_no} is also overridden by {self.claimed[deck_no]}')
        fi, fn = self.get(BIN_PAC, 'deck_fileidx.bin'), self.get(BIN_PAC, 'deck_filename.bin')
        offs = struct.unpack(f'<{len(fi) // 2}H', fi)
        deck_file = fn[offs[deck_no]:offs[deck_no + 1]].rstrip(b'\0').decode('ascii') if deck_no < len(offs) - 1 else ''
        name = f'{deck_file.lower()}.ydc'
        if not deck_file or name not in self.files[DECK_PAC]:
            raise SystemExit(f'{where}: deck {deck_no} of stock_chara {chara} has no deck file')
        rp = spec['deck'] if os.path.isabs(spec['deck']) else os.path.normpath(os.path.join(base_dir, spec['deck']))
        deck, _ = self.deck(rp, where)
        deck.header = self.files[DECK_PAC][name][:8]
        self.claimed[deck_no] = where
        self.put(DECK_PAC, name, deck.build())
        if 'rating' in spec:
            if not 0 <= int(spec['rating']) <= 0xffff:
                raise SystemExit(f'{where}: rating {spec["rating"]}: 0-65535')
            st = bytearray(self.get(BIN_PAC, 'enemystatus.bin'))
            struct.pack_into('<H', st, deck_no * 12 + 2, int(spec['rating']))
            self.put(BIN_PAC, 'enemystatus.bin', bytes(st))
            self.tables['free'].append((chara, 0x4000))
            self.free_rating[chara] = int(spec['rating'])
        if 'deck_name' in spec:
            self.tables['deckname'].append((deck_no + 1, self.game_text([spec['deck_name']], {'at': where})))
        return {'stock_chara': chara, 'chara': chara, 'deck_slot': deck_no, 'deck_file': deck_file,
                'deck': spec['deck'], 'deck_cards': [len(deck.main), len(deck.extra)]}

    def status_row(self, status, deck_no, where, talk1=None, stats=None):
        st = bytearray(self.get(BIN_PAC, 'enemystatus.bin'))
        tpl = int(status['template_deck'])
        if not 0 <= tpl < NEW_DECK_FIRST:
            raise SystemExit(f'{where}: template_deck {tpl}: a stock deck 0-{NEW_DECK_FIRST - 1}')
        st += bytes(max(0, (deck_no + 1) * 12 - len(st)))
        ch = bytearray(self.get(BIN_PAC, 'character.bin'))
        ch += bytes(max(0, deck_no + 1 - len(ch)))
        if deck_no >= NEW_DECK_FIRST:
            ch[deck_no] = ch[tpl]
        self.put(BIN_PAC, 'character.bin', bytes(ch))
        row = list(struct.unpack_from('<HHB5BH', st, tpl * 12))
        row[0] = deck_no
        if 'rating' in status:
            row[1] = int(status['rating'])
        if talk1 is not None:
            row[2] = talk1
        if stats is not None:
            if len(stats) != 5 or not all(0 <= int(v) <= 255 for v in stats):
                raise SystemExit(f'{where}: stats: 5 values 0-255')
            row[3:8] = [int(v) for v in stats]
        key = status.get('key_card')
        if key:
            cid = self.cards().get(key.lower())
            if cid is None:
                raise SystemExit(f'{where}: key card "{key}" is not in the WC2011 card database')
            row[8] = cid
        struct.pack_into('<HHB5BH', st, deck_no * 12, *row)
        self.put(BIN_PAC, 'enemystatus.bin', bytes(st))

    def talk_set(self, lines, where):
        first = None
        for lang in TALK_LANGS:
            src = lines.get(lang) or [{**x, 'text': w11lang.tr(x.get('text'), lang, 'talk',
                                                                 {'at': where, 'situation': x.get('situation')})}
                                      if isinstance(x, dict) else w11lang.tr(x, lang, 'talk', {'at': where})
                                      for x in lines['e']]
            if len(src) != TALK_SET_LINES:
                raise SystemExit(f'{where}: talk.{lang} has {len(src)} lines, a talk set has {TALK_SET_LINES}')
            ok, mk = f'talkost_{lang}.bin', f'talkmsg_{lang}.bin'
            o, m = self.get(BIN_PAC, ok), bytearray(self.get(BIN_PAC, mk))
            offs = list(struct.unpack(f'<{len(o) // 4}I', o))
            n = len(offs) - 1
            if n < TALK_GENERIC or (n - TALK_GENERIC) % TALK_SET_LINES or not m.endswith(b'\0'):
                raise SystemExit(f'{ok}: {n} lines, not {TALK_GENERIC} + n * {TALK_SET_LINES}')
            offs[-1] = len(m)
            for i, line in enumerate(src):
                if isinstance(line, dict):
                    line = line.get('text')
                if not isinstance(line, str):
                    raise SystemExit(f'{where}: talk.{lang}[{i}]: expected a string or an object with "text"')
                try:
                    raw = line.encode(TALK_ENC.get(lang, 'cp1252'))
                except UnicodeEncodeError:
                    raise SystemExit(f'{where}: talk.{lang}[{i}] does not encode as {TALK_ENC.get(lang, "cp1252")}')
                if not raw or b'\0' in raw:
                    raise SystemExit(f'{where}: talk.{lang}[{i}] is empty or holds a NUL')
                m += raw + b'\0'
                offs.append(len(m))
            self.put(BIN_PAC, ok, struct.pack(f'<{len(offs)}I', *offs))
            self.put(BIN_PAC, mk, bytes(m))
            k = (n - TALK_GENERIC) // TALK_SET_LINES
            if first not in (None, k):
                raise SystemExit(f'talk_{lang}: new set {k}, other languages {first}')
            first = k
        if first > TALK_SET_MAX:
            raise SystemExit(f'{where}: talk set {first}: the status row holds sets 0-{TALK_SET_MAX}')
        return first

    def opponent(self, spec, base_dir):
        rp = lambda p: p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))
        if 'base' in spec:
            with open(rp(spec['base']), encoding='utf-8') as f:
                spec = {**json.load(f), **spec}
        where = spec.get('name') or spec.get('card', '?')
        chara = int(spec['chara'])
        if chara < STOCK_CHARAS:
            raise SystemExit(f'{where}: chara {chara} is a stock character (0-{STOCK_CHARAS - 1})')
        if chara in (c for c, _ in self.tables['chara']):
            raise SystemExit(f'{where}: chara {chara} is used twice')
        if len(self.tables['free']) >= FREE_LIST_CAP - FREE_LIST_STOCK:
            raise SystemExit(f'{where}: the CPU Duel list holds {FREE_LIST_CAP} entries, {FREE_LIST_STOCK} of them stock: '
                             f'{FREE_LIST_CAP - FREE_LIST_STOCK} Free Duel opponents at most')
        deck_no = self.claim_deck(spec.get('deck_slot'), where)
        cid = self.cards().get(spec['card'].lower())
        if cid is None:
            raise SystemExit(f'{where}: "card" must be a WC2011 or mod card (the name shown)')
        deck, _ = self.deck(rp(spec['deck']), where)
        self.deck_slot(spec.get('deck_file11', f'MOD{chara:03d}'), deck, deck_no)
        talk1 = self.talk_set(spec['talk'], where) + 1 if 'talk' in spec else None
        self.status_row(opponent_status(spec), deck_no, where, talk1, spec.get('stats'))
        name = spec.get('name') or self.card_names.get(cid, spec['card'])
        name_text = self.game_text([name, spec.get('deck_name') or name], {'at': where})
        self.tables['charname'].append((deck_no, name_text))
        self.tables['deckname'].append((deck_no + 1, name_text + 1))
        self.tables['chara'].append((chara, deck_no))
        self.tables['free'].append((chara, 0x8000 if spec.get('turbo') else 0))
        self.free_rating[chara] = int(opponent_status(spec)['rating'])
        if 'unlock' in spec:
            self.free_unlock[chara] = w11unlock.words(spec['unlock'], w11unlock.story_flags(base_dir), where)
        p = dict(spec['portrait'])
        if 'bundle' in p:
            self.portrait_bundle(rp(p['bundle']), chara)
        elif 'wc2011' in p:
            for ext in ('ncgr', 'ncer', 'nanr', 'nclr'):
                k = f'bu{int(p["wc2011"]):03d}_r.lz{ext}'
                if k not in self.files[DUEL_BU_PAC]:
                    raise SystemExit(f'{where}: portrait wc2011 {p["wc2011"]}: no {k} in BustupR.pac')
                self.put(DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', self.files[DUEL_BU_PAC][k])
        else:
            src = {'png': rp(p.get('png') or p['cutout']), 'crop': p.get('crop'), 'alpha_min': p.get('alpha_min', 128),
                   'dx': p.get('dx', 0)}
            tpl_duel = spec.get('duel_bustup_template', 'bu206_r')
            d = self.files[DUEL_BU_PAC]
            dt = tuple(nttx.lz_decompress(d[f'{tpl_duel}.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
            img = portrait_image({'portrait': src}, where, (160, 192))
            for ext, data in bustup_files(img, (-96, -96), dt).items():
                self.put(DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', lz11_literal(data))
        return {'card': spec['card'], 'chara': chara, 'deck_slot': deck_no, 'name_card': cid,
                'talk_set': None if talk1 is None else talk1 - 1, 'deck_cards': [len(deck.main), len(deck.extra)]}

    def story_copy(self, spec, opponent, base_dir, talk_set):
        where = spec['duel_name']
        chara = int(spec['chara'])
        if chara < STOCK_CHARAS or chara in (c for c, _ in self.tables['chara']):
            raise SystemExit(f'{where}: chara {chara} is a stock character or used twice')
        deck_no = self.claim_deck(spec['deck_slot'], where)
        deck, _ = self.deck(os.path.normpath(os.path.join(base_dir, opponent['deck'])), where)
        deck_file = f'MOD{chara:03d}'
        self.deck_slot(deck_file, deck, deck_no)
        self.status_row(opponent_status(opponent), deck_no, where, None if talk_set is None else talk_set + 1,
                        opponent.get('stats'))
        name_text = self.game_text([spec['duel_name'], opponent.get('deck_name') or spec['duel_name']], {'at': where})
        self.tables['charname'].append((deck_no, name_text))
        self.tables['deckname'].append((deck_no + 1, name_text + 1))
        self.tables['chara'].append((chara, deck_no))
        return {'map': None, 'chara': chara, 'story_index': int(spec['story_index']), 'deck_slot': deck_no,
                'name_text': name_text, 'deck_file': deck_file, 'deck_cards': [len(deck.main), len(deck.extra)]}

    def duel_composite(self, c, raw, chara, where, rules=None):
        import w11gfx
        import w11portraits

        def layer(files, stem, k):
            g = {e: nttx.lz_decompress(files[f'{stem}.lz{e}']) for e in ('ncgr', 'nclr', 'ncer')}
            ts, bpp4 = w11gfx.tiles(g['ncgr'])
            return w11gfx.cell(ts, bpp4, w11gfx.palette(g['nclr']), g['ncer'], k)

        body = layer({f'.lz{e}': v for e, v in raw.items()}, '', c.get('body_cell', 0))
        disc = game.container_files(self.rom, 'Data_arc_pac/CharaMake/disc.pac')
        if f'{c["disk"]}.lzncgr' not in disc:
            raise SystemExit(f'{where}: duel_composite disk {c["disk"]}: not in CharaMake/disc.pac')
        disk = layer(disc, c['disk'], 0)
        d = self.files[DUEL_BU_PAC]
        bu = f'bu{int(c["faces"]):03d}_r'
        if f'{bu}.lzncgr' not in d:
            raise SystemExit(f'{where}: duel_composite faces {c["faces"]}: no {bu} in BustupR.pac')
        stock = [layer(d, bu, k) for k in range(5)]
        disk_offset = tuple(c.get('disk_offset', (0, 0)))
        cells, offsets, pose_dx = duel_composite(body, disk, disk_offset, stock[:2], stock[1:])
        x0, y0 = -w11gfx.CELL_BOX[0] - 96, -w11gfx.CELL_BOX[1] - 96
        crop = (x0, y0, x0 + 160, y0 + 192)
        frames = merge_colours([im.crop(crop) for im in cells])
        if rules:
            import numpy as np
            from PIL import ImageChops
            disk_at = ImageChops.offset(disk, *disk_offset)
            keeps = [np.asarray(im.crop(crop))[..., 3] > 0 for im in [ImageChops.offset(disk_at, pose_dx, 0)] + [disk_at] * 4]
            unchanged = set()
            frames = merge_colours([recolor_image(im, rules, 96, keep, unchanged) for im, keep in zip(frames, keeps)],
                                   fixed=unchanged)
        template = tuple(nttx.lz_decompress(d[f'{bu}.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
        files = w11portraits.encode(frames, (-96, -96), template)
        ts, bpp4 = w11gfx.tiles(files['ncgr'])
        pal = w11gfx.palette(files['nclr'])
        for k, want in enumerate(frames):
            got = w11gfx.cell(ts, bpp4, pal, files['ncer'], k, (-96, -96, 64, 96))
            if got.get_flattened_data() != want.get_flattened_data():
                raise SystemExit(f'{where}: duel_composite cell {k} does not decode to its source frame')
        for ext, data in files.items():
            self.put(DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', lz11_literal(data))
        print(f'{where}: duel portrait composite, head offsets {offsets}, pose shift {pose_dx}')

    def recolor_talk(self, raw, rules, where):
        import w11gfx
        import w11portraits
        g = {e: nttx.lz_decompress(v) for e, v in raw.items()}
        ts, bpp4 = w11gfx.tiles(g['ncgr'])
        pal = w11gfx.palette(g['nclr'])
        count = struct.unpack_from('<H', g['ncer'], bustup.section(g['ncer'], b'KBEC') + 8)[0]
        box = (-64, -96, 64, 96)
        frames, unchanged = [], set()
        ox, oy = -w11gfx.CELL_BOX[0], -w11gfx.CELL_BOX[1]
        for k in range(count):
            full = w11gfx.cell(ts, bpp4, pal, g['ncer'], k)
            im = full.crop((box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy))
            if sum(full.getchannel('A').histogram()[1:]) != sum(im.getchannel('A').histogram()[1:]):
                raise SystemExit(f'{where}: talk cell {k} reaches outside {box}')
            frames.append(recolor_image(im, rules, -box[1], unchanged=unchanged))
        frames = merge_colours(frames, fixed=unchanged)
        files = w11portraits.encode(frames, box[:2], (g['ncer'], g['nanr'], g['nclr']), dialogue=True)
        files['nanr'] = g['nanr']
        ts, bpp4 = w11gfx.tiles(files['ncgr'])
        pal = w11gfx.palette(files['nclr'])
        for k, want in enumerate(frames):
            if w11gfx.cell(ts, bpp4, pal, files['ncer'], k, box).get_flattened_data() != want.get_flattened_data():
                raise SystemExit(f'{where}: recoloured talk cell {k} does not decode to its source frame')
        print(f'{where}: talk portrait recoloured, {count} cells')
        return {e: lz11_literal(v) for e, v in files.items()}

    def portrait_bundle(self, path, chara):
        import w11portraits
        t, d = self.files[TALK_BU_PAC], self.files[DUEL_BU_PAC]
        tt = tuple(nttx.lz_decompress(t[f'npc129_bu01_r.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
        dt = tuple(nttx.lz_decompress(d[f'bu046_r.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
        for outfit, files in w11portraits.bundle(path, tt, dt):
            for side in ('right', 'left'):
                stem = f'{outfit["stem"]}_bu01_{side[0]}'
                for ext, data in files[side].items():
                    self.put(TALK_BU_PAC, f'{stem}.lz{ext}', lz11_literal(data))
            for ext, data in files['duel'].items():
                self.put(DUEL_BU_PAC, f'bu{chara:03d}{outfit.get("suffix", "")}_r.lz{ext}', lz11_literal(data))

    def add_model(self, name, path, where):
        if not os.path.isfile(path):
            raise SystemExit(f'{where}: model file {path} not found')
        raw = open(path, 'rb').read()
        packed = raw if raw[:1] in (b'\x10', b'\x11') else lz11_literal(raw)
        if nttx.lz_decompress(packed)[:4] != b'BMD0':
            raise SystemExit(f'{path}: not an NSBMD (BMD0), plain or LZ-compressed')
        if f'{name}.lznsbmd' in self.files[MODEL_PAC]:
            raise SystemExit(f'{where}: model name {name} is a stock RPG3D model')
        self.put(MODEL_PAC, f'{name}.lznsbmd', packed)

    def add_motion(self, name, path, where):
        if not os.path.isfile(path):
            raise SystemExit(f'{where}: motion file {path} not found')
        raw = open(path, 'rb').read()
        packed = raw if raw[:1] in (b'\x10', b'\x11') else lz11_literal(raw)
        if nttx.lz_decompress(packed)[:4] != b'BCA0':
            raise SystemExit(f'{path}: not an NSBCA (BCA0), plain or LZ-compressed')
        if f'{name}.lznsbca' in self.files[MODEL_PAC]:
            raise SystemExit(f'{where}: motion name {name} is a stock RPG3D motion')
        self.put(MODEL_PAC, f'{name}.lznsbca', packed)

    def cast_models(self, spec, base_dir):
        where = spec.get('name', spec.get('id', '?'))
        rp = lambda p: p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))
        names = []
        for name, path in spec.get('models', {}).items():
            self.add_model(name.lower(), rp(path), where)
            names.append(name.lower())
        for name, path in spec.get('motion_files', {}).items():
            self.add_motion(name.lower(), rp(path), where)
        model = spec.get('model') or {}
        if model.get('recolor_from'):
            base = model['recolor_from'].split('/')[-1].replace('.nsbmd', '.lznsbmd').lower()
            if base not in self.files[MODEL_PAC] or 'recolor' not in spec or not model.get('path'):
                raise SystemExit(f'{where}: model.recolor_from needs a stock RPG3D model, model.path and recolor')
            stock_model = game.container_files(self.rom, MODEL_PAC + '.pac')[base]
            data, report = recolor_model(nttx.lz_decompress(stock_model), spec['recolor'])
            os.makedirs(os.path.dirname(rp(model['path'])), exist_ok=True)
            with open(rp(model['path']), 'wb') as f:
                f.write(data)
            print(f'{where}: model {base} recoloured: {report}')
        if model.get('path'):
            stem = spec.get('file_stem') or f'npc{int(spec["chara"]):03d}'
            self.add_model(stem, rp(model['path']), where)
            names.append(stem)
        return names

    def npc(self, spec, base_dir, player_cpu=False):
        where = spec.get('name', '?')
        rp = lambda p: p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))
        mapname = spec.get('map')
        chara = int(spec['chara'])
        story = int(spec['story_index'])
        if chara < STOCK_CHARAS:
            raise SystemExit(f'{where}: chara {chara} is a stock character (0-{STOCK_CHARAS - 1})')
        if story < STORY_CHARS:
            raise SystemExit(f'{where}: story_index {story} is a stock story duelist (0-{STORY_CHARS - 1})')
        if chara in (c for c, _ in self.tables['chara']):
            raise SystemExit(f'{where}: chara {chara} is used twice')
        if story in (s for s, _ in self.tables['story']):
            raise SystemExit(f'{where}: story_index {story} is used twice')
        deck_no = self.claim_deck(spec.get('deck_slot'), where)
        if mapname:
            slot = int(spec['slot'])
            player = int(spec.get('player_slot', 0))
            flag = int(spec['flag'])
            if not 10000 <= flag < 0x2c0f:
                raise SystemExit(f'{where}: flag {flag} outside the story flag range 10000-11278')
            if not 1 <= slot < 0x26:
                raise SystemExit(f'{where}: slot {slot}: 1-37')
            talk = spec['talk']
            for k in ('intro', 'win', 'lose'):
                if not talk.get(k):
                    raise SystemExit(f'{where}: talk.{k} needs at least one line')
                for i, s in enumerate(talk[k]):
                    check_line(s, f'{where}: talk.{k}[{i}]')

        deck, deck_spec = self.deck(rp(spec['deck']), where)
        deck_file = spec.get('deck_file', f'MOD{chara:03d}')
        self.deck_slot(deck_file, deck, deck_no)
        self.status_row(spec['status'], deck_no, where)

        name_text = self.game_text([spec['name'], spec.get('deck_name') or deck_spec.get('deck_name', spec['name'] + "'s Deck")],
                                   {'at': where})
        self.tables['charname'].append((deck_no, name_text))
        self.tables['deckname'].append((deck_no + 1, name_text + 1))
        self.tables['story'].append((story, chara))
        self.tables['chara'].append((chara, deck_no))

        stem = spec.get('file_stem', f'npc{chara:03d}')
        t = self.files[TALK_BU_PAC]
        d = self.files[DUEL_BU_PAC]
        if 'bundle' in (spec.get('portrait') or {}):
            self.portrait_bundle(rp(spec['portrait']['bundle']), chara)
        elif 'wc2011' in (spec.get('portrait') or {}):
            src = int(spec['portrait']['wc2011'])
            npc = next((f'npc{src:0{w}d}' for w in (3, 2) if f'npc{src:0{w}d}_bu01_r.lzncgr' in t), f'npc{src:03d}')
            bu = next((f'bu{src:0{w}d}' for w in (3, 2) if f'bu{src:0{w}d}_r.lzncgr' in d), f'bu{src:03d}')
            for ext in ('ncgr', 'ncer', 'nanr', 'nclr'):
                for k in (f'{npc}_bu01_r.lz{ext}', f'{bu}_r.lz{ext}'):
                    if k not in (t if k.startswith('npc') else d):
                        raise SystemExit(f'{where}: portrait wc2011 {src}: no {k}')
                self.put(DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', d[f'{bu}_r.lz{ext}'])
                r = t[f'{npc}_bu01_r.lz{ext}']
                left = t.get(f'{npc}_bu01_l.lz{ext}')
                if left is None:
                    left = r if ext != 'ncer' else lz11_literal(mirror_ncer(nttx.lz_decompress(r)))
                self.put(TALK_BU_PAC, f'{stem}_bu01_r.lz{ext}', r)
                self.put(TALK_BU_PAC, f'{stem}_bu01_l.lz{ext}', left)
        elif 'nitro' in (spec.get('portrait') or {}):
            import w11gfx
            from PIL import Image
            prefix = rp(spec['portrait']['nitro'])
            raw = {}
            for ext in ('ncgr', 'ncer', 'nanr', 'nclr'):
                if not os.path.isfile(f'{prefix}.lz{ext}'):
                    raise SystemExit(f'{where}: portrait nitro: {prefix}.lz{ext} not found')
                raw[ext] = open(f'{prefix}.lz{ext}', 'rb').read()
            talk = self.recolor_talk(raw, spec['recolor'], where) if 'recolor' in spec else raw
            if spec['portrait'].get('pose_aliases'):
                talk = dict(talk)
                talk['nanr'] = lz11_literal(alias_portrait_poses(
                    nttx.lz_decompress(talk['nanr']), spec['portrait']['pose_aliases']))
            for ext in ('ncgr', 'ncer', 'nanr', 'nclr'):
                self.put(TALK_BU_PAC, f'{stem}_bu01_r.lz{ext}', talk[ext])
                left = talk[ext] if ext != 'ncer' else lz11_literal(mirror_ncer(nttx.lz_decompress(talk[ext])))
                self.put(TALK_BU_PAC, f'{stem}_bu01_l.lz{ext}', left)
            if 'duel_composite' in spec['portrait']:
                self.duel_composite(spec['portrait']['duel_composite'], raw, chara, where, spec.get('recolor'))
            else:
                d = {e: nttx.lz_decompress(v) for e, v in raw.items()}
                ts, bpp4 = w11gfx.tiles(d['ncgr'])
                im = w11gfx.cell(ts, bpp4, w11gfx.palette(d['nclr']), d['ncer'], 0, (-128, -96, 128, 96))
                im = im.crop(im.getbbox())
                duel_img = Image.new('RGBA', (160, 192), (0, 0, 0, 0))
                duel_img.paste(im, ((160 - im.width) // 2, 192 - im.height), im)
                tpl_duel = spec.get('duel_bustup_template', 'bu206_r')
                dt = tuple(nttx.lz_decompress(self.files[DUEL_BU_PAC][f'{tpl_duel}.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
                for ext, data in bustup_files(duel_img, (-96, -96), dt).items():
                    self.put(DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', lz11_literal(data))
        else:
            bu_r = portrait_image(spec, where, (128, 192))
            bu_l = portrait_image(spec, where, (128, 192), flip=True)
            tpl_bu = spec.get('talk_bustup_template', 'npc206_bu01_r')
            tt = tuple(nttx.lz_decompress(t[f'{tpl_bu}.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
            for side, img in (('r', bu_r), ('l', bu_l)):
                for ext, data in bustup_files(img, (-64, -96), tt).items():
                    self.put(TALK_BU_PAC, f'{stem}_bu01_{side}.lz{ext}', lz11_literal(data))
            tpl_duel = spec.get('duel_bustup_template', 'bu206_r')
            dt = tuple(nttx.lz_decompress(d[f'{tpl_duel}.lz{e}']) for e in ('ncer', 'nanr', 'nclr'))
            duel_img = portrait_image(spec, where, (160, 192))
            for ext, data in bustup_files(duel_img, (-96, -96), dt).items():
                self.put(DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', lz11_literal(data))

        self.cast_models(spec, base_dir)
        model = spec['model']
        if model.get('path'):
            model_ref = f'data/{stem}.nsbmd'
        else:
            model_ref = model['file']
            base = model_ref.split('/')[-1].replace('.nsbmd', '.lznsbmd').lower()
            if base not in self.files[MODEL_PAC]:
                raise SystemExit(f'{where}: model {model_ref}: RPG3D.pac has no {base}')
        motions = model['motions']
        if len(motions) != 3:
            raise SystemExit(f'{where}: model.motions: [idle, walk, run], 3 names')
        for m in motions:
            base = m.split('/')[-1].replace('.nsbca', '.lznsbca').lower()
            if base not in self.files[MODEL_PAC]:
                raise SystemExit(f'{where}: motion {m}: RPG3D.pac has no {base}')

        if not mapname:
            return {'map': None, 'chara': chara, 'story_index': story, 'deck_slot': deck_no, 'name_text': name_text,
                    'model': model_ref, 'deck_file': deck_file, 'deck_cards': [len(deck.main), len(deck.extra)]}

        name_id = self.system_name(spec['name'], {'at': where})
        lines = talk['intro'] + talk['win'] + talk['lose']
        first = self.script_lines(mapname, lines, {'at': where, 'script': mapname})
        ids = {'intro': list(range(first, first + len(talk['intro'])))}
        ids['win'] = list(range(ids['intro'][-1] + 1, ids['intro'][-1] + 1 + len(talk['win'])))
        ids['lose'] = list(range(ids['win'][-1] + 1, ids['win'][-1] + 1 + len(talk['lose'])))

        duel = spec.get('duel', {})
        block = [0] * 30
        block[0] = 1
        block[1] = 1
        block[2] = story
        block[5] = 1 if player_cpu else 0
        block[6] = 1
        block[9] = 0 if player_cpu else int(duel.get('first', 2))
        block[12] = 3
        block[22] = int(duel.get('bgm', 5))
        for i in range(23, 30):
            block[i] = 0xffff

        raw = self.get(SCRIPT_PAC, f'{mapname}.lzws')
        script = Script(nttx.lz_decompress(raw), mapname)
        for ev in EV_INIT + (EV_ENTER,) + EV_TALK:
            if ev not in script.handlers:
                raise SystemExit(f'{mapname}: no handler for event {ev:#x}')
        if 1 not in script.stubs:
            raise SystemExit(f'{mapname}: no end stub')
        end_stub = script.stubs[1]
        if bytes(script.d[0x200 + end_stub:0x200 + end_stub + 3]) != bytes([0x52, 0x99, 0xa3]):
            raise SystemExit(f'{mapname}: end stub at {end_stub:#x} has an unexpected prologue')

        strings = {}
        blob = bytearray()

        def add(k, data):
            strings[k] = DS_DATA + len(blob)
            blob.extend(data)
            blob.extend(b'\0' * (-len(blob) % 2))

        for k, v in (('model', model_ref), ('m0', motions[0]), ('m1', motions[1]), ('m2', motions[2]),
                     ('bu', f'data/{stem}_bu01_R'), ('ret', f'data/{mapname}.ws')):
            add(k, v.encode('ascii') + b'\0')
        add('block', struct.pack('<30H', *block))
        pending = DS_DATA - 2
        pos = [fx(v) for v in spec['position']]
        facing = angle(spec.get('facing', 0))

        def code(a):
            e = Emitter(script, a, strings)
            h_init = script.handlers[1][0]
            h_enter = script.handlers[EV_ENTER][0]
            h_talk = script.handlers[0x14][0]
            if script.handlers[0][0] != h_init or script.handlers[0xc][0] != h_talk:
                raise SystemExit(f'{mapname}: events 0/1 or 0xc/0x14 use different handlers; not supported yet')

            a.label('init')
            for i in range(0, len(blob), 2):
                a.mov_m(DS_DATA + i, struct.unpack_from('<H', blob, i)[0])
            a.mov_m(pending, 1)
            a.jmp(h_init)

            a.label('end')
            a.push('ax')
            a.load_ax(pending)
            a.test_ax()
            a.je('end_stock')
            a.mov_m(pending, 0)
            e.sys(SYS_CHARA, [slot, 'model', 'm0', 'm1', 'm2', 0, 1])
            e.sys(SYS_SHADOW, [slot, 3])
            e.sys(SYS_POS, [slot] + pos)
            e.sys(SYS_DIR, [slot, 0, facing, 0])
            e.sys(SYS_TALKABLE, [slot, 0, 1])
            a.label('end_stock')
            a.pop('ax')
            a.push('dx')
            a.cwd()
            a.store_ax(script.blk + 4)
            a.jmp(end_stub + 5)

            def say(msgs):
                e.sys(SYS_BU_LOAD, ['bu', 1])
                e.sys(SYS_BU_POSE, [1, 0, -1, -1, -1])
                e.sys(SYS_BU_SHOW, [1, 2])
                e.sys(SYS_WAIT, [0x14])
                for m in msgs:
                    e.sys(SYS_MSG, [name_id, m, -1, 0, 1])
                e.sys(SYS_BU_SHOW, [1, 3])
                e.sys(SYS_WAIT, [0x14])
                e.sys(SYS_BU_FREE, [1])
                e.sys(SYS_MSG_CLOSE, [0])

            a.label('talk')
            a.cmp_ax(slot)
            a.jne(h_talk)
            e.sys(SYS_FACE, [slot, player])
            e.sys(SYS_FACE, [player, slot])
            say(ids['intro'])
            e.sys(SYS_FLAG_SET, [flag, 1])
            e.sys(SYS_DUEL, ['block', 'ret'])
            a.mov_r('ax', 0)
            a.jmp(end_stub)

            a.label('enter')
            e.sys(SYS_FLAG_GET, [flag])
            a.test_ax()
            a.je(h_enter)
            e.sys(SYS_FLAG_SET, [flag, 0])
            e.sys(SYS_FLAG_GET, [RESULT_VAR])
            a.cmp_ax(1)
            a.jne('enter_lost')
            say(ids['win'])
            a.jmp(h_enter)
            a.label('enter_lost')
            say(ids['lose'])
            a.jmp(h_enter)

            for ev, lab in ((0, 'init'), (1, 'init'), (EV_ENTER, 'enter'), (0xc, 'talk'), (0x14, 'talk')):
                a.patches.append((script.handlers[ev][1], ('label', lab)))
            a.patches.append((0x200 + end_stub, ('jmp', 'end')))

        asm = Asm(script.ip(script.code_end))
        asm.patches = []
        code(asm)
        body = asm.resolve()
        new = script.insert(body)
        for at, (kind, lab) in asm.patches:
            t = asm.labels[lab]
            if kind == 'label':
                struct.pack_into('<H', new, at, t)
            else:
                ip = at - 0x200
                new[at:at + 3] = bytes([0xe9]) + struct.pack('<H', (t - (ip + 3)) & 0xffff)
        self.put(SCRIPT_PAC, f'{mapname}.lzws', ndspy.lz10.compress(bytes(new)))
        return {'map': mapname, 'slot': slot, 'chara': chara, 'story_index': story, 'deck_slot': deck_no,
                'name_text': name_text, 'system_name': name_id, 'lines': ids, 'code_bytes': len(body),
                'ds_strings': {k: hex(v) for k, v in strings.items()}, 'deck_file': deck_file,
                'deck_cards': [len(deck.main), len(deck.extra)]}

    def write(self, report):
        import shutil
        pac_dir = os.path.join(self.out, 'pac')
        for d in (pac_dir, os.path.join(self.out, 'src')):
            if os.path.isdir(d):
                shutil.rmtree(d)
        for (arc, name), data in sorted(self.changed.items()):
            p = os.path.join(pac_dir, arc, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(data)
        src = os.path.join(self.out, 'src')
        os.makedirs(src, exist_ok=True)
        count = max([STORY_CHARS - 1] + [s for s, _ in self.tables['story']]) + 1
        with open(os.path.join(src, 'w11npc_gen.asm'), 'w') as f:
            f.write(f'.definelabel W11NPC_STORY_COUNT, {count:#x}\n')
        with open(os.path.join(src, 'w11npc_gen.S'), 'w') as f:
            f.write('    .section .rodata\n    .balign 4\n')
            free = sorted(self.tables['free'], key=lambda r: self.free_rating.get(r[0], 0))
            for name, rows in (('w11npc_story', self.tables['story']), ('w11npc_chara', self.tables['chara']),
                               ('w11npc_free', free),
                               ('w11npc_deckname', self.tables['deckname']),
                               ('w11npc_charname', self.tables['charname'])):
                f.write(f'    .global {name}\n{name}:\n')
                for k, v in rows:
                    f.write(f'    .hword {k:#x}, {v:#x}\n')
                f.write(f'    .global {name}_n\n{name}_n:\n    .word {len(rows)}\n')
            lock, words = [], []
            for chara, _ in free:
                lock.append(len(words) if chara in self.free_unlock else 0xffff)
                words += self.free_unlock.get(chara, [])
            for name, rows in (('w11npc_free_lock', lock), ('w11npc_lock_flags', words or [0])):
                f.write(f'    .global {name}\n{name}:\n' + ''.join(f'    .hword {v:#x}\n' for v in rows))
            f.write('    .balign 4\n')
        with open(os.path.join(self.out, 'report.json'), 'w') as f:
            json.dump(report, f, indent=1)


def opponent_status(spec):
    status = dict(spec.get('status', {}))
    status.setdefault('template_deck', 0x71)
    status.setdefault('rating', spec.get('rating', 1000))
    status.setdefault('key_card', spec['card'])
    return status


def load_opponent(path):
    with open(path, encoding='utf-8') as f:
        spec = json.load(f)
    if 'base' in spec:
        with open(os.path.join(os.path.dirname(path), spec['base']), encoding='utf-8') as f:
            spec = {**json.load(f), **spec}
    return spec


def cmd_build(a):
    if a.translations:
        w11lang.load(a.translations, a.out)
    b = Builder(a.rom, a.out)
    b.card_specs = a.cards
    b.base_pac = a.base_pac
    report = []
    copies = []
    talk_sets = {}
    for path in a.specs + a.opponents:
        with open(path, encoding='utf-8') as f:
            want = json.load(f).get('deck_slot')
        if want is not None:
            if int(want) in b.reserved:
                raise SystemExit(f'{path}: deck_slot {want} is given by two specs')
            b.reserved.add(int(want))
    for path in a.specs:
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
        if 'story_index' not in spec:
            added = b.cast_models(spec, os.path.dirname(os.path.abspath(path)))
            if added:
                print(f'{path}: {spec.get("id", "?")}: story cast only, models {", ".join(added)}')
            else:
                print(f'{path}: {spec.get("id", "?")}: story cast only (stock model {spec["model"].get("file")}), nothing to build')
            continue
        if spec.get('shared_opponent'):
            ref = os.path.normpath(os.path.join(os.path.dirname(path), spec['shared_opponent']))
            if os.path.abspath(ref) not in {os.path.abspath(x) for x in a.opponents}:
                raise SystemExit(f'{path}: shared_opponent must be included in --opponents')
            opponent = load_opponent(ref)
            chara, story = int(spec['chara']), int(spec['story_index'])
            if story < STORY_CHARS or story in dict(b.tables['story']):
                raise SystemExit(f'{path}: invalid shared story index')
            if spec.get('duel_name'):
                if chara == int(opponent['chara']) or 'deck_slot' not in spec:
                    raise SystemExit(f'{path}: duel_name needs its own chara and deck_slot')
                copies.append((path, spec, ref, opponent))
            elif chara != int(opponent['chara']) or 'deck_slot' in spec:
                raise SystemExit(f'{path}: shared_opponent owns chara and deck_slot')
            b.tables['story'].append((story, chara))
            b.cast_models(spec, os.path.dirname(os.path.abspath(path)))
            if spec.get('portrait', {}).get('bundle'):
                bundle = os.path.join(os.path.dirname(path), spec['portrait']['bundle'])
                b.portrait_bundle(os.path.abspath(bundle), chara)
            if not spec.get('duel_name'):
                print(f'{path}: story duelist {story:#x} shares Free Duel character {chara}')
            continue
        r = b.npc(spec, os.path.dirname(os.path.abspath(path)), a.player_cpu)
        report.append(r)
        where = f'on {r["map"]} slot {r["slot"]}' if r['map'] else f'(story duelist only, model {r["model"]})'
        print(f'{path}: {spec["name"]} {where}, chara {r["chara"]}, story duelist '
              f'{r["story_index"]:#x}, deck slot {r["deck_slot"]} ({r["deck_file"]}, {r["deck_cards"][0]}+'
              f'{r["deck_cards"][1]})' + (f', {sum(len(v) for v in r["lines"].values())} lines, {r["code_bytes"]} B of '
                                          f'script code' if r['map'] else ''))
    for path in a.opponents:
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
        if 'stock_chara' in spec:
            r = b.stock_override(spec, os.path.dirname(os.path.abspath(path)), path)
            report.append(r)
            print(f'{path}: stock character {r["chara"]} plays {spec["deck"]} as deck {r["deck_slot"]} '
                  f'({r["deck_file"]}.ydc, {r["deck_cards"][0]}+{r["deck_cards"][1]})')
            continue
        r = b.opponent(spec, os.path.dirname(os.path.abspath(path)))
        report.append(r)
        talk_sets[os.path.abspath(path)] = r['talk_set']
        print(f'{path}: Free Duel opponent {r["card"]}, chara {r["chara"]}, deck slot {r["deck_slot"]} '
              f'({r["deck_cards"][0]}+{r["deck_cards"][1]}), talk set {"of the template deck" if r["talk_set"] is None else r["talk_set"]}')
    for path, spec, ref, opponent in copies:
        r = b.story_copy(spec, opponent, os.path.dirname(os.path.abspath(ref)), talk_sets[os.path.abspath(ref)])
        report.append(r)
        print(f'{path}: story duelist {r["story_index"]:#x} "{spec["duel_name"]}", chara {r["chara"]}, deck slot '
              f'{r["deck_slot"]}: copy of {ref}')
    if getattr(a, 'decks', None):
        from deck_paths import stock_sources
        sources = stock_sources(a.decks)
        changed = 0
        for path in sources:
            if b.stock_deck_source(path):
                changed += 1
                print(f'{path}: stock deck replaced')
        print(f'Stock deck sources: {len(sources)} checked, {changed} modified')
    b.jp_art()
    print(f'Japanese art over the western variant: {", ".join(stem for _, stem in JP_ART)}')
    b.player_motions()
    print(f'Male player motions fitted to the 30-node skeleton: {", ".join(PLAYER_MOTION_FIXES)}')
    b.write(report)
    print(f'{a.out}: {len(b.changed)} files')


def cmd_info(a):
    rom = game.open_rom(a.rom)
    files = game.container_files(rom, SCRIPT_PAC + '.pac')
    s = Script(nttx.lz_decompress(files[f'{a.map}.lzws']), a.map)
    print(f'{a.map}: code {s.hdr[1]:#x} B, data {s.hdr[3]:#x} B, syscall block DS:{s.blk:#x}')
    for ev, (h, _) in sorted(s.handlers.items()):
        print(f'  event {ev:#04x} -> handler {h:#06x}')
    print(f'  {len(s.stubs)} syscall stubs: ' + ' '.join(f'{c:#x}' for c in sorted(s.stubs)))


def main():
    ap = argparse.ArgumentParser(
        description='WC2011 story mode NPCs: add a character to a map of the 3D story mode (model, idle/walk motions, '
                    'talk with portrait, story duel against a new duelist with its own deck, win/lose lines); '
                    'Free Duel opponents in the CPU Duel list. '
                    'Format: docs/modding/story-npcs.md and docs/modding/opponents-and-decks.md; findings: docs/findings/story-mode.md.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('build', help='build the files of every NPC spec')
    p.add_argument('rom', help='clean WC2011 EU ROM (BYYP)')
    p.add_argument('out', help='output folder, e.g. build/w11npc: pac/ overrides for build_rom.py --pac, src/ for --src')
    p.add_argument('specs', nargs='*', help='NPC specs (JSON)')
    p.add_argument('--opponents', nargs='*', default=[], help='Free Duel opponent specs (JSON): CPU Duel list entry, '
                   'duel portrait, card name, deck name, talk set, deck')
    p.add_argument('--base-pac', help='pac overrides made earlier in the build (the variant\'s pac/ folder): files there '
                   'are the starting point instead of the ROM\'s, so game_text keeps the point list strings')
    p.add_argument('--cards', nargs='*', default=[], help='mod card specs, so decks and names can use the mod cards')
    p.add_argument('--decks', help='variant decks directory; read stock JSONs here and in base game/, with this folder taking priority')
    p.add_argument('--player-cpu', action='store_true', help='test builds: the CPU plays the player side of the duel, '
                   'player goes first (no janken)')
    p.add_argument('--translations', help='translation tables (<lang>.json) for names and talk; the lines they lack '
                   'go to <out>/translations-needed.json')
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser('info', help='event handlers and syscall stubs of a map script')
    p.add_argument('rom')
    p.add_argument('map', help='script name, e.g. hom01')
    p.set_defaults(fn=cmd_info)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
