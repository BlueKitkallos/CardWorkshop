import os
import struct
import sys


def parse(d):
    nblocks = d[2]
    names_end = struct.unpack_from('<H', d, 0)[0] if nblocks == 0 else nblocks * 0x200
    names = []
    for b in range(max(1, nblocks)):
        p = b * 0x200 + 3
        while p < min(names_end, (b + 1) * 0x200) and d[p] != 0:
            n = d[p]
            names.append(d[p + 2:p + 2 + n].decode('latin1'))
            p += 2 + n
    n = len(names)
    ents = [struct.unpack_from('<II', d, names_end + (i // 63) * 0x200 + 8 + (i % 63) * 8) for i in range(n)]
    base = (names_end + ((n - 1) // 63) * 0x200 + 8 + ((n - 1) % 63 + 1) * 8 + 0x1ff) & ~0x1ff
    return names, ents, base


def name_hash(name):
    h = 0
    for c in name.encode('latin1'):
        h ^= c
    return h


def _align(n):
    return (n + 0x1ff) & ~0x1ff


INDEX_SECTORS = 64
POOL_MAX = 254
BLOCK_ROOM = 0x200 - 4


def index_sectors(names):
    blocks, used = 1, 0
    for nm in names:
        size = 2 + len(nm.encode('latin1'))
        if used + size > BLOCK_ROOM:
            blocks, used = blocks + 1, 0
        used += size
    return blocks + (max(len(names), 1) + 62) // 63


def tight_order(names):
    bins = []
    for nm in sorted(names, key=lambda x: -len(x.encode('latin1'))):
        size = 2 + len(nm.encode('latin1'))
        fit = [b for b in bins if b[0] + size <= BLOCK_ROOM]
        if fit:
            b = max(fit, key=lambda x: x[0])
            b[0] += size
            b[1].append(nm)
        else:
            bins.append([size, [nm]])
    return [nm for _, group in bins for nm in group]


def build(entries):
    names = list(entries)
    if index_sectors(names) > INDEX_SECTORS:
        packed = tight_order(names)
        if index_sectors(packed) < index_sectors(names):
            names = packed
    n = len(names)
    recs = [bytes([len(nm), name_hash(nm)]) + nm.encode('latin1') for nm in names]
    short_len = 3 + sum(map(len, recs)) + 1
    short = short_len + 8 + 8 * n <= 0x200
    if short:
        out = bytearray(struct.pack('<HB', short_len, 0) + b''.join(recs) + b'\0')
    else:
        blocks = [b'']
        for rec in recs:
            if 3 + len(blocks[-1]) + len(rec) + 1 > 0x200:
                blocks.append(b'')
            blocks[-1] += rec
        out = bytearray(b''.join((bytes([0, 0, len(blocks)]) + blk).ljust(0x200, b'\0') for blk in blocks))
    offs, off = [], 0
    for nm in names:
        offs.append((off, len(entries[nm])))
        off += _align(len(entries[nm]))
    for i in range(0, max(n, 1), 63):
        chunk = offs[i:i + 63]
        cnt = 0xffff if i + 63 < n else len(chunk)
        out += struct.pack('<HHI', 0, cnt, 0) + b''.join(struct.pack('<II', o, sz) for o, sz in chunk)
        if not short:
            out = out.ljust(_align(len(out)), b'\0')
    out = out.ljust(_align(len(out)), b'\0')
    for nm in names:
        out += entries[nm].ljust(_align(len(entries[nm])), b'\0')
    return bytes(out)


def files(d):
    names, ents, base = parse(d)
    return {nm: bytes(d[base + o:base + o + s]) for nm, (o, s) in zip(names, ents)}


def extract(rom, out, loose_dirs=()):
    for fid in range(len(rom.files)):
        path = rom.filenames.filenameOf(fid)
        if not path:
            continue
        d = rom.files[fid]
        if path.endswith('.pac'):
            names, ents, base = parse(d)
            end = base + max(o + s for o, s in ents)
            print(f'{path} ({len(names)} files, data@{base:#x}, end {end:#x} / {len(d):#x})')
            for nm, (o, s) in zip(names, ents):
                print(f'   {nm:40s} off={o:#9x} size={s}')
            if out:
                dst = os.path.join(out, path[:-4])
                os.makedirs(dst, exist_ok=True)
                for nm, blob in files(d).items():
                    with open(os.path.join(dst, nm), 'wb') as f:
                        f.write(blob)
        elif any(path.startswith(ld.rstrip('/') + '/') for ld in loose_dirs):
            print(f'{path} ({len(d)} bytes)')
            if out:
                dst = os.path.join(out, path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, 'wb') as f:
                    f.write(d)


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description='List every .pac archive of a ROM and, with OUTDIR, extract each one to '
                    'OUTDIR/<archive path without .pac>/<file>. For games that keep their data in loose '
                    'files (profile storage "loose"), the loose data folders are copied instead.')
    ap.add_argument('rom', help='ROM (.nds), read only')
    ap.add_argument('outdir', nargs='?', help='extraction folder, e.g. extracted (omit to only list)')
    a = ap.parse_args()
    if not os.path.isfile(a.rom):
        sys.exit(f'ROM not found: {a.rom}')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import game
    rom = game.open_rom(a.rom)
    try:
        prof = game.for_rom(rom)
        loose = prof.get('loose_dirs', []) if prof.get('storage') == 'loose' else []
    except game.UnknownGame as e:
        print(f'warning: {e}; extracting .pac archives only', file=sys.stderr)
        loose = []
    extract(rom, a.outdir, loose)


if __name__ == '__main__':
    main()
