"""Widen the in-duel card word of WC2008: patch the code sites listed in engine/cardword_sites.txt, then rescan."""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITES = os.path.join(HERE, 'engine', 'cardword_sites.txt')
ALLOW = os.path.join(HERE, 'engine', 'cardword_allow.txt')
BASES = {'arm9.bin': 0x02000000, 'itcm.bin': 0x01ff8000, 'ov03.bin': 0x021aef60, 'ov04.bin': 0x021d08a0}
WINDOW = 12

THUMB_PAIRS = {
    'owner': ('lsl', 18, ('lsr', 'asr'), 31),
    'owner-insert': ('lsl', 31, ('lsr',), 18),
    'id': ('lsl', 19, ('lsr', 'asr'), 19),
    'uid-counter': ('lsl', 17, ('lsr',), 30),
}
ARM_PAIRS = {
    'owner': (18, ('lsr', 'asr'), 31),
    'owner-insert': (31, ('lsr',), 18),
    'id': (19, ('lsr', 'asr'), 19),
}
LITERALS = {
    0xffffdfff: 'owner-clear',
    0xffffe000: 'id-clear',
    0x00001fff: 'id-mask',
}
MASK_BASES = (0xffffe000, 0xffffc000, 0xffffdfff, 0xbfffffff)
THUMB_SHIFT = {0: 'lsl', 1: 'lsr', 2: 'asr'}
ARM_SHIFT = {0: 'lsl', 1: 'lsr', 2: 'asr', 3: 'ror'}


def read_table(path, cols):
    rows = []
    with open(path) as f:
        for n, line in enumerate(f, 1):
            p = line.rstrip("\n").split(None, cols - 1)
            if not p:
                continue
            if len(p) < cols:
                raise SystemExit(f'{path}:{n}: expected {cols} columns')
            rows.append((n, p))
    return rows


def load_sites(path=SITES):
    sites = []
    for n, (addr, kind, old, new) in read_table(path, 4):
        if len(old) != len(new) or len(old) not in (4, 8):
            raise SystemExit(f'{path}:{n}: old and new must both be 4 or 8 hex digits')
        sites.append((int(addr, 16), kind, int(old, 16), int(new, 16), len(old) // 2))
    return sites


def load_allow(path=ALLOW):
    allow = {}
    for n, (addr, kind, reason) in read_table(path, 3):
        allow[(int(addr, 16), kind)] = reason.strip()
    return allow


def locate(blobs, addr, size):
    for name, data in blobs.items():
        base = BASES[name]
        if base <= addr and addr + size <= base + len(data):
            return name, addr - base
    raise SystemExit(f'{addr:#010x}: not inside {", ".join(sorted(blobs))}')


def get(data, off, size):
    return struct.unpack_from('<H' if size == 2 else '<I', data, off)[0]


def put(data, off, size, value):
    struct.pack_into('<H' if size == 2 else '<I', data, off, value)


def apply(blobs, sites=None):
    sites = load_sites() if sites is None else sites
    bad = []
    for addr, kind, old, new, size in sites:
        name, off = locate(blobs, addr, size)
        cur = get(blobs[name], off, size)
        if cur == new:
            continue
        if cur != old:
            bad.append(f'{addr:#010x} {kind}: found {cur:0{size * 2}x}, expected {old:0{size * 2}x}')
            continue
        put(blobs[name], off, size, new)
    if bad:
        raise SystemExit('cardword: code differs from the site list (wrong ROM, or a hook overwrote a site first):\n  '
                         + '\n  '.join(bad))
    return len(sites)


def thumb_shift(h):
    if h >> 13 == 0 and (h >> 11) & 3 != 3:
        return THUMB_SHIFT[(h >> 11) & 3], (h >> 6) & 31, (h >> 3) & 7, h & 7
    return None


def thumb_writes(h, reg):
    top5 = h >> 11
    if top5 <= 3 or top5 == 0b01000 and (h >> 10) & 1 == 0 and (h >> 6) & 15 not in (8, 10, 11):
        return h & 7 == reg
    if 4 <= top5 <= 7:
        return top5 != 5 and (h >> 8) & 7 == reg
    if h >> 10 == 0b010001:
        op = (h >> 8) & 3
        return op in (0, 2) and ((h & 7) | ((h >> 4) & 8)) == reg
    if top5 == 0b01001 or top5 in (0b10011, 0b10100, 0b10101):
        return (h >> 8) & 7 == reg
    if h >> 12 == 0b0101:
        return (h >> 9) & 7 >= 3 and h & 7 == reg
    if top5 in (0b01101, 0b01111, 0b10001):
        return h & 7 == reg
    if h >> 9 == 0b1011110 or top5 == 0b11001:
        return bool(h & (1 << reg))
    return top5 in (0b11100, 0b11110, 0b11111)


def arm_mov_shift(w):
    if w & 0x0fef0010 == 0x01a00000:
        return ARM_SHIFT[(w >> 5) & 3], (w >> 7) & 31, w & 15, (w >> 12) & 15
    return None


def arm_shifted_operand(w):
    if (w >> 26) & 3 == 0 and not (w >> 25) & 1 and not (w >> 4) & 1:
        return ARM_SHIFT[(w >> 5) & 3], (w >> 7) & 31, w & 15
    return None


def arm_writes(w, reg):
    if (w >> 26) & 3 == 0 and (w >> 21) & 15 not in (8, 9, 10, 11):
        return (w >> 12) & 15 == reg
    if (w >> 26) & 3 == 1 and (w >> 20) & 1:
        return (w >> 12) & 15 == reg
    return False


def scan(blobs):
    hits = []
    for name, data in blobs.items():
        base = BASES[name]
        hw = struct.unpack_from(f'<{len(data) // 2}H', data)
        for i, h in enumerate(hw):
            s = thumb_shift(h)
            for kind, (op1, imm1, op2, imm2) in THUMB_PAIRS.items():
                if not s or s[0] != op1 or s[1] != imm1:
                    continue
                rd = s[3]
                for g in hw[i + 1:i + 1 + WINDOW]:
                    t = thumb_shift(g)
                    if t and t[0] in op2 and t[1] == imm2 and t[2] == rd:
                        hits.append((base + 2 * i, kind))
                        break
                    if thumb_writes(g, rd):
                        break
            if h >> 11 == 9:
                tgt = ((base + 2 * i + 4) & ~3) + (h & 0xff) * 4
                off = tgt - base
                if 0 <= off <= len(data) - 4:
                    v = get(data, off, 4)
                    if v in LITERALS:
                        hits.append((tgt, LITERALS[v]))
                    if v in MASK_BASES:
                        rp = (h >> 8) & 7
                        for j, g in enumerate(hw[i + 1:i + 1 + 2 * WINDOW], i + 1):
                            if g == 0x1e40 | rp << 3 | (g & 7) or g == 0x3801 | rp << 8:
                                hits.append((base + 2 * j, 'owner-clear'))
                            elif g == 0x0cc0 | rp << 3 | (g & 7):
                                hits.append((base + 2 * j, 'id-mask'))
                            if thumb_writes(g, rp):
                                break
        words = struct.unpack_from(f'<{len(data) // 4}I', data)
        for i, w in enumerate(words):
            m = arm_mov_shift(w)
            if m and m[0] == 'lsl':
                for kind, (imm1, op2, imm2) in ARM_PAIRS.items():
                    if m[1] != imm1:
                        continue
                    for g in words[i + 1:i + 9]:
                        o = arm_shifted_operand(g)
                        if o and o[0] in op2 and o[1:] == (imm2, m[3]):
                            hits.append((base + 4 * i, kind))
                            break
                        if arm_writes(g, m[3]):
                            break
            if w & 0xffff0000 == 0xe59f0000:
                tgt = base + 4 * i + 8 + (w & 0xfff)
                off = tgt - base
                if 0 <= off <= len(data) - 4:
                    v = get(data, off, 4)
                    if v in LITERALS:
                        hits.append((tgt, LITERALS[v]))
    return sorted(set(hits))



def check(blobs, allow=None):
    allow = load_allow() if allow is None else allow
    hits = scan(blobs)
    left = [h for h in hits if h not in allow]
    if left:
        raise SystemExit(f'cardword: {len(left)} old card-word patterns left after patching, not in '
                         f'{os.path.relpath(ALLOW)}:\n  ' + '\n  '.join(f'{a:08x} {k}' for a, k in left))
    stale = sorted(set(allow) - set(hits))
    if stale:
        raise SystemExit(f'cardword: {os.path.relpath(ALLOW)} lists sites the scan no longer finds:\n  '
                         + '\n  '.join(f'{a:08x} {k}' for a, k in stale))
    return len(hits)


def rom_blobs(path):
    import ndspy.rom
    rom = ndspy.rom.NintendoDSRom.fromFile(path)
    arm9 = rom.loadArm9()
    blobs = {'arm9.bin': bytearray(arm9.sections[0].data)}
    for sec in arm9.sections[1:]:
        if sec.ramAddress == BASES['itcm.bin']:
            blobs['itcm.bin'] = bytearray(sec.data)
    ovs = rom.loadArm9Overlays()
    for i in (3, 4):
        blobs[f'ov{i:02d}.bin'] = bytearray(ovs[i].data)
    return blobs


def main():
    ap = argparse.ArgumentParser(description=__doc__ + ' build_rom.py runs this on every build; run it alone to check '
                                 'a ROM.')
    ap.add_argument('rom', help='a clean ROM (patched in memory, then rescanned) or a built ROM (rescanned)')
    ap.add_argument('--hits', action='store_true', help='print every old pattern the scan finds, before patching')
    a = ap.parse_args()
    blobs = rom_blobs(a.rom)
    if a.hits:
        for addr, kind in scan(blobs):
            print(f'{addr:08x} {kind}')
        return
    n = apply(blobs)
    k = check(blobs)
    print(f'{a.rom}: {n} sites patched, {k} old patterns left, all in {os.path.relpath(ALLOW)}')


if __name__ == '__main__':
    main()
