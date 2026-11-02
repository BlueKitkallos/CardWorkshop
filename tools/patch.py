#!/usr/bin/env python3
import argparse
import hashlib
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import game

MAGIC = b'BPS1'
SOURCE_READ, TARGET_READ, SOURCE_COPY, TARGET_COPY = range(4)
BLOCK = 32
STEP = 16
MIN_MATCH = 16
HASH_MUL = np.uint64(0x9E3779B97F4A7C15)


class PatchError(Exception):
    pass


def varint(n):
    out = bytearray()
    while True:
        x = n & 0x7f
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return out
        out.append(x)
        n -= 1


def read_varint(buf, pos):
    n, shift = 0, 1
    while True:
        if pos >= len(buf):
            raise PatchError('truncated patch')
        x = buf[pos]
        pos += 1
        n += (x & 0x7f) * shift
        if x & 0x80:
            return n, pos
        shift <<= 7
        n += shift


def block_hashes(arr):
    words = arr[:len(arr) // 4 * 4].view('<u4').astype(np.uint64)
    n = len(words) - BLOCK // 4 + 1
    if n <= 0:
        return np.zeros(0, np.uint64)
    h = words[:n].copy()
    for i in range(1, BLOCK // 4):
        h *= HASH_MUL
        h ^= words[i:i + n]
    return h


def candidates(src, tgt):
    sh = block_hashes(src)
    th = block_hashes(tgt)[::STEP // 4]
    cand = np.full(len(th), -1, np.int64)
    if not len(sh) or not len(th):
        return cand
    mask = np.uint64((1 << max(1, (max(len(sh), len(th)) - 1).bit_length())) - 1)
    skey = np.sort((sh & ~mask) | np.arange(len(sh), dtype=np.uint64))
    del sh
    tkey = np.sort((th & ~mask) | np.arange(len(th), dtype=np.uint64))
    idx = np.searchsorted(skey, tkey & ~mask)
    np.minimum(idx, len(skey) - 1, out=idx)
    hit = (skey[idx] & ~mask) == (tkey & ~mask)
    cand[(tkey[hit] & mask).astype(np.int64)] = (skey[idx[hit]] & mask).astype(np.int64) * 4
    return cand


def forward_len(a, ai, b, bi, limit):
    n, step = 0, 256
    while n < limit:
        k = min(step, limit - n)
        x, y = a[ai + n:ai + n + k], b[bi + n:bi + n + k]
        if np.array_equal(x, y):
            n += k
            step = min(step * 4, 1 << 22)
            continue
        return n + int(np.argmax(x != y))
    return n


def backward_len(a, ai, b, bi, limit):
    n, step = 0, 64
    while n < limit:
        k = min(step, limit - n)
        x, y = a[ai - n - k:ai - n], b[bi - n - k:bi - n]
        if np.array_equal(x, y):
            n += k
            step = min(step * 4, 1 << 22)
            continue
        return n + int(np.argmax((x != y)[::-1]))
    return n


def create(source, target):
    src = np.frombuffer(source, np.uint8)
    tgt = np.frombuffer(target, np.uint8)
    cand = candidates(src, tgt)
    hits = np.flatnonzero(cand >= 0)
    sn, tn = len(src), len(tgt)
    out = bytearray(MAGIC)
    out += varint(sn) + varint(tn) + varint(0)
    rel = 0
    lit = 0
    t = 0
    delta = None
    stats = [0, 0, 0]

    def best_at(p):
        options = []
        if p < sn:
            options.append(p)
        if delta is not None and 0 <= p + delta < sn:
            options.append(p + delta)
        w = p // STEP
        if p % STEP == 0 and w < len(cand) and cand[w] >= 0:
            options.append(int(cand[w]))
        best = None
        for s in options:
            if src[s] != tgt[p]:
                continue
            f = forward_len(tgt, p, src, s, min(tn - p, sn - s))
            if f < MIN_MATCH:
                continue
            if best is None or f > best[1]:
                best = (s, f)
        return best

    while t < tn:
        i = np.searchsorted(hits, (t + STEP - 1) // STEP)
        found = None
        while i < len(hits):
            p = int(hits[i]) * STEP
            m = best_at(p)
            if m:
                found = (p, *m)
                break
            i += 1
        if found is None:
            break
        p, s, f = found
        b = backward_len(tgt, p, src, s, min(p - lit, s))
        p, s, f = p - b, s - b, f + b
        if p > lit:
            out += varint((p - lit - 1) << 2 | TARGET_READ) + target[lit:p]
            stats[0] += p - lit
        if s == p:
            out += varint((f - 1) << 2 | SOURCE_READ)
            stats[1] += f
        else:
            d = s - rel
            out += varint((f - 1) << 2 | SOURCE_COPY) + varint(abs(d) << 1 | (d < 0))
            rel = s + f
            stats[2] += f
        delta = s - p
        t = lit = p + f
    if lit < tn:
        out += varint((tn - lit - 1) << 2 | TARGET_READ) + target[lit:tn]
        stats[0] += tn - lit
    out += zlib.crc32(source).to_bytes(4, 'little') + zlib.crc32(target).to_bytes(4, 'little')
    out += zlib.crc32(out).to_bytes(4, 'little')
    return bytes(out), stats


def header(patch):
    if patch[:4] != MAGIC:
        raise PatchError('not a BPS patch')
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], 'little'):
        raise PatchError('the patch file is damaged (patch CRC32 mismatch)')
    sn, pos = read_varint(patch, 4)
    tn, pos = read_varint(patch, pos)
    mn, pos = read_varint(patch, pos)
    return {'source_size': sn, 'target_size': tn, 'metadata': patch[pos:pos + mn],
            'source_crc': int.from_bytes(patch[-12:-8], 'little'),
            'target_crc': int.from_bytes(patch[-8:-4], 'little'), 'actions': pos + mn}


def apply(source, patch):
    h = header(patch)
    if len(source) != h['source_size'] or zlib.crc32(source) != h['source_crc']:
        raise PatchError(f'wrong source ROM: this patch needs a {h["source_size"]}-byte file with CRC32 '
                         f'{h["source_crc"]:08x}, got {len(source)} bytes with CRC32 {zlib.crc32(source):08x}')
    out = bytearray(h['target_size'])
    end = len(patch) - 12
    pos, op, src_rel, tgt_rel = h['actions'], 0, 0, 0
    while pos < end:
        data, pos = read_varint(patch, pos)
        cmd, n = data & 3, (data >> 2) + 1
        if op + n > len(out):
            raise PatchError('patch writes past the end of the target')
        if cmd == SOURCE_READ:
            out[op:op + n] = source[op:op + n]
        elif cmd == TARGET_READ:
            out[op:op + n] = patch[pos:pos + n]
            pos += n
        else:
            d, pos = read_varint(patch, pos)
            d = -(d >> 1) if d & 1 else d >> 1
            if cmd == SOURCE_COPY:
                src_rel += d
                if src_rel < 0 or src_rel + n > len(source):
                    raise PatchError('patch reads outside the source')
                out[op:op + n] = source[src_rel:src_rel + n]
                src_rel += n
            else:
                tgt_rel += d
                if tgt_rel < 0 or tgt_rel >= op:
                    raise PatchError('patch reads outside the written target')
                left, o = n, op
                while left:
                    k = min(left, o - tgt_rel)
                    out[o:o + k] = out[tgt_rel:tgt_rel + k]
                    o += k
                    tgt_rel += k
                    left -= k
        op += n
    if op != len(out):
        raise PatchError(f'patch wrote {op} of {len(out)} bytes')
    if zlib.crc32(out) != h['target_crc']:
        raise PatchError('the patched ROM does not match the target CRC32')
    return bytes(out)


def check_clean(path):
    try:
        prof = game.for_path(path)
    except (game.UnknownGame, ValueError) as e:
        sys.exit(f'{path}: {e}')
    want = prof.get('clean_sha1')
    h = game.sha1(path)
    if want and h != want:
        sys.exit(f'{path}: sha1 {h} is not the clean {prof["game_code"]} dump ({want}); '
                 f'the patch only applies to an unmodified {prof["title"]} ROM')
    return prof, h


def version():
    try:
        r = subprocess.run(['git', 'describe', '--always', '--dirty', '--tags'], cwd=ROOT,
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def cmd_create(a):
    prof, src_sha1 = check_clean(a.clean)
    t0 = time.time()
    source, target = read(a.clean), read(a.rom)
    patch, (lit, same, moved) = create(source, target)
    t1 = time.time()
    if apply(source, patch) != target:
        sys.exit('internal error: the patch does not rebuild the ROM; nothing written')
    t2 = time.time()
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    with open(a.out, 'wb') as f:
        f.write(patch)
    info = a.info or str(Path(a.out).with_suffix('')) + '.patch.txt'
    Path(info).write_text(
        f'patch: {Path(a.out).name} (BPS, {len(patch)} bytes)\n'
        f'mod version: {version()}\n'
        f'game: {prof["title"]} ({prof["game_code"]})\n'
        f'source sha1: {src_sha1}  crc32: {zlib.crc32(source):08x}  size: {len(source)}\n'
        f'target sha1: {hashlib.sha1(target).hexdigest()}  crc32: {zlib.crc32(target):08x}  size: {len(target)}\n',
        encoding='utf-8')
    print(f'{a.out}: {len(patch)} bytes ({lit} new, {same} unchanged in place, {moved} moved); '
          f'created in {t1 - t0:.1f}s, checked in {t2 - t1:.1f}s')
    print(f'{info}: written')


def cmd_apply(a):
    if os.path.abspath(a.clean) == os.path.abspath(a.out):
        sys.exit('refusing to overwrite the clean ROM: choose another output path')
    check_clean(a.clean)
    t0 = time.time()
    try:
        out = apply(read(a.clean), read(a.patch))
    except PatchError as e:
        sys.exit(f'{a.patch}: {e}')
    with open(a.out, 'wb') as f:
        f.write(out)
    print(f'{a.out}: {len(out)} bytes, sha1 {hashlib.sha1(out).hexdigest()}, target CRC32 ok '
          f'({time.time() - t0:.1f}s)')


def main():
    ap = argparse.ArgumentParser(
        description='Write or apply a BPS patch (the Flips format) that turns the clean ROM into the modded one.',
        epilog='Both commands refuse a source ROM that is not the clean dump named in tools/games/<code>.json.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('create', help='clean ROM + modded ROM -> .bps and a .patch.txt with hashes and mod version')
    p.add_argument('clean', help='clean ROM (.nds)')
    p.add_argument('rom', help='modded ROM, e.g. build/dimension-break.nds')
    p.add_argument('out', help='patch path, e.g. build/dimension-break.bps')
    p.add_argument('--info', help='info file (default: <out without .bps>.patch.txt)')
    p.set_defaults(fn=cmd_create)
    p = sub.add_parser('apply', help='clean ROM + .bps -> modded ROM, checking source and target CRC32')
    p.add_argument('clean', help='clean ROM (.nds)')
    p.add_argument('patch', help='.bps patch')
    p.add_argument('out', help='output ROM path')
    p.set_defaults(fn=cmd_apply)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
