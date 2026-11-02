import struct
import sys

import ndspy.lz10
import numpy as np
from PIL import Image


def bgr555(c):
    return ((c & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, ((c >> 10) & 31) * 255 // 31)


def to555(rgb):
    r, g, b = (min(31, (v * 31 + 127) // 255) for v in rgb[:3])
    return r | (g << 5) | (b << 10)


def lz_decompress(data):
    if data[0] == 0x10:
        return ndspy.lz10.decompress(data)
    if data[0] != 0x11:
        raise ValueError(f'not LZ10 or LZ11 (first byte {data[0]:#x})')
    size, p = int.from_bytes(data[1:4], 'little'), 4
    if size == 0:
        size, p = int.from_bytes(data[4:8], 'little'), 8
    out = bytearray()
    while len(out) < size:
        flags = data[p]
        p += 1
        for bit in range(7, -1, -1):
            if len(out) >= size:
                break
            if not flags >> bit & 1:
                out.append(data[p])
                p += 1
                continue
            b1 = data[p]
            ind = b1 >> 4
            if ind == 0:
                n, disp = ((b1 & 15) << 4 | data[p + 1] >> 4) + 0x11, ((data[p + 1] & 15) << 8 | data[p + 2]) + 1
                p += 3
            elif ind == 1:
                n = ((b1 & 15) << 12 | data[p + 1] << 4 | data[p + 2] >> 4) + 0x111
                disp = ((data[p + 2] & 15) << 8 | data[p + 3]) + 1
                p += 4
            else:
                n, disp = ind + 1, ((b1 & 15) << 8 | data[p + 1]) + 1
                p += 2
            for _ in range(n):
                out.append(out[-disp])
    return bytes(out[:size])


def blocks(raw):
    p, out = 0x10, {}
    while p + 8 <= len(raw):
        tag, sz = raw[p:p + 4].decode('latin1'), struct.unpack_from('<I', raw, p + 4)[0]
        if sz == 0:
            break
        out[tag] = raw[p + 8:p + sz]
        p += sz
    return out


def mix(a, b, wa, wb, div):
    return tuple((x * wa + y * wb) // div for x, y in zip(a, b))


def decode(raw):
    b = blocks(raw)
    ncol = struct.unpack_from('<I', b['PALT'], 0)[0]
    pal = [bgr555(c) for c in struct.unpack_from(f'<{ncol}H', b['PALT'], 4)]
    img = b['IMGE']
    fmt, w, h, size = img[0], *struct.unpack_from('<HHI', img, 4)
    if fmt != 5:
        raise ValueError(f'texture format {fmt}')
    data = img[12:]
    bw, bh = w // 4, h // 4
    tex = data[:bw * bh * 4]
    idx = data[bw * bh * 4:bw * bh * 6]
    im = Image.new('RGBA', (w, h))
    px = im.load()
    for by in range(bh):
        for bx in range(bw):
            n = by * bw + bx
            t = struct.unpack_from('<I', tex, n * 4)[0]
            pi = struct.unpack_from('<H', idx, n * 2)[0]
            base, mode = (pi & 0x3fff) * 2, pi >> 14
            c0, c1 = pal[base], pal[base + 1]
            if mode == 0:
                cols = [c0 + (255,), c1 + (255,), pal[base + 2] + (255,), (0, 0, 0, 0)]
            elif mode == 1:
                cols = [c0 + (255,), c1 + (255,), mix(c0, c1, 1, 1, 2) + (255,), (0, 0, 0, 0)]
            elif mode == 2:
                cols = [c + (255,) for c in (c0, c1, pal[base + 2], pal[base + 3])]
            else:
                cols = [c0 + (255,), c1 + (255,), mix(c0, c1, 5, 3, 8) + (255,), mix(c0, c1, 3, 5, 8) + (255,)]
            for y in range(4):
                for x in range(4):
                    px[bx * 4 + x, by * 4 + y] = cols[(t >> ((y * 4 + x) * 2)) & 3]
    return im


def _kmeans(pts, k):
    pts = sorted(set(pts))
    if len(pts) <= k:
        return pts + [pts[-1]] * (k - len(pts))
    lum = sorted(pts, key=lambda p: p[0] * 3 + p[1] * 6 + p[2])
    cent = [lum[(len(lum) - 1) * i // (k - 1)] for i in range(k)]
    for _ in range(6):
        groups = [[] for _ in range(k)]
        for p in pts:
            groups[min(range(k), key=lambda j: sum((a - b) ** 2 for a, b in zip(p, cent[j])))].append(p)
        cent = [tuple(sum(c) // len(g) for c in zip(*g)) if g else cent[j] for j, g in enumerate(groups)]
    return cent


def _sqerr(pixels, cols):
    return sum(min(sum((a - b) ** 2 for a, b in zip(p, c)) for c in cols) for p in pixels)


def _mode3(opaque):
    a, b = _kmeans(opaque, 2)
    best = None
    for f in (0.0, 0.25, 0.5):
        c0 = tuple(min(255, max(0, round(x + f * (x - y)))) for x, y in zip(a, b))
        c1 = tuple(min(255, max(0, round(y + f * (y - x)))) for x, y in zip(a, b))
        q0, q1 = bgr555(to555(c0)), bgr555(to555(c1))
        cols = [q0, q1, mix(q0, q1, 5, 3, 8), mix(q0, q1, 3, 5, 8)]
        e = _sqerr(opaque, cols)
        if best is None or e < best[0]:
            best = (e, [c0, c1])
    return best


def encode(im, header, max_colours=None):
    im = im.convert('RGBA')
    w, h = im.size
    px = im.load()
    bw, bh = w // 4, h // 4
    plan = []
    for by in range(bh):
        for bx in range(bw):
            blk = [px[bx * 4 + x, by * 4 + y] for y in range(4) for x in range(4)]
            opaque = [p[:3] for p in blk if p[3] >= 128]
            if not opaque:
                plan.append([blk, [(0, 0, 0)] * 2, 1, None])
            elif len(opaque) < 16:
                c = _kmeans(opaque, 3)
                plan.append([blk, c[:3] + [(0, 0, 0)], 0, None])
            else:
                plan.append([blk, _kmeans(opaque, 4), 2, opaque])

    def palette_size():
        seen = set()
        for _, cols, mode, _ in plan:
            q = tuple(to555(c) for c in cols)
            seen.add(q[:2] if mode in (1, 3) else q)
        return sum(4 if len(q) > 2 else 2 for q in seen)

    if max_colours is not None and palette_size() > max_colours:
        cands = []
        for n, (blk, cols, mode, opaque) in enumerate(plan):
            if mode == 2:
                e3, c3 = _mode3(opaque)
                cur = _sqerr(opaque, [bgr555(to555(c)) for c in cols])
                cands.append((e3 - cur, n, c3, 3))
        cands.sort(key=lambda c: c[:2])
        edges = []
        for n, (blk, cols, mode, _) in enumerate(plan):
            if mode == 0:
                opaque = [p[:3] for p in blk if p[3] >= 128]
                c2 = _kmeans(opaque, 2)
                e2 = _sqerr(opaque, [bgr555(to555(c)) for c in c2])
                edges.append((e2 - _sqerr(opaque, [bgr555(to555(c)) for c in cols[:3]]), n, c2))
        cands += [(e, n, c, 1) for e, n, c in sorted(edges, key=lambda c: c[:2])]
        k = 0
        while palette_size() > max_colours:
            if k >= len(cands):
                raise ValueError('palette budget unreachable')
            step = max(1, (palette_size() - max_colours) // 2)
            for _, n, cols, mode in cands[k:k + step]:
                plan[n][1], plan[n][2] = cols, mode
            k += step

    pal, palmap = [], {}
    tex, idx = bytearray(), bytearray()
    for blk, cols, mode, _ in plan:
        q = tuple(to555(c) for c in cols)
        if mode in (1, 3):
            q = q[:2]
        if q not in palmap:
            palmap[q] = len(pal) // 2
            pal.extend(q)
        if mode == 3:
            q0, q1 = bgr555(q[0]), bgr555(q[1])
            dec = [q0, q1, mix(q0, q1, 5, 3, 8), mix(q0, q1, 3, 5, 8)]
        else:
            dec = [bgr555(c) for c in q] + [(0, 0, 0)] * (4 - len(q))
        t = 0
        for n, p in enumerate(blk):
            if p[3] < 128 and mode in (0, 1):
                v = 3
            else:
                rng = range(3) if mode == 0 else (range(2) if mode == 1 else range(4))
                v = min(rng, key=lambda j: sum((a - b) ** 2 for a, b in zip(p[:3], dec[j])))
            t |= v << (n * 2)
        tex += struct.pack('<I', t)
        idx += struct.pack('<H', palmap[q] | (mode << 14))
    if len(pal) // 2 > 0x3fff:
        raise ValueError('palette too large')
    palt = struct.pack('<I', len(pal)) + struct.pack(f'<{len(pal)}H', *pal)
    imge = bytes(header) + bytes(tex) + bytes(idx)
    body = b'PALT' + struct.pack('<I', len(palt) + 8) + palt + b'IMGE' + struct.pack('<I', len(imge) + 8) + imge
    return b'NTTX\xff\xfe\x00\x01' + struct.pack('<I', len(body) + 16) + b'\x10\x00\x02\x00' + body


def _pair_colours(p):
    c0, c1 = p[:, 0:3], p[:, 3:6]
    m3 = np.stack([c0, c1, (c0 * 5 + c1 * 3) // 8, (c0 * 3 + c1 * 5) // 8], 1)
    m1 = np.stack([c0, c1, (c0 + c1) // 2, (c0 + c1) // 2], 1)
    return m3, m1


def _block_error(blocks, cols):
    d = ((blocks[:, None, :, None, :] - cols[None, :, None, :, :]) ** 2).sum(-1)
    return d.min(-1).sum(-1)


def _sqdist(a, b):
    return (a * a).sum(1)[:, None] - 2 * a @ b.T + (b * b).sum(1)[None, :]


def encode_budget(im, max_colours, candidates=16):
    rgb = np.asarray(im.convert('RGB'), np.int32)
    h, w = rgb.shape[:2]
    q = (rgb * 31 + 127) // 255
    blocks = q.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    n, k = len(blocks), max_colours // 2
    mean = blocks.mean(1)
    cen = blocks - mean[:, None]
    axis = np.linalg.svd(cen, full_matrices=False)[2][:, 0]
    t = np.einsum('bpc,bc->bp', cen, axis)
    lo = mean + axis * np.percentile(t, 8, axis=1)[:, None]
    hi = mean + axis * np.percentile(t, 92, axis=1)[:, None]
    swap = lo.sum(1) > hi.sum(1)
    lo[swap], hi[swap] = hi[swap], lo[swap].copy()
    feat = np.concatenate([lo, hi], 1)
    rng = np.random.default_rng(0)
    cent = feat[rng.choice(n, min(k, n), replace=False)]
    for _ in range(10):
        lab = _sqdist(feat, cent).argmin(1)
        cnt = np.bincount(lab, minlength=len(cent))
        sums = np.zeros_like(cent)
        np.add.at(sums, lab, feat)
        used = cnt > 0
        cent[used] = sums[used] / cnt[used, None]
    pairs = np.clip(np.rint(cent), 0, 31).astype(np.int32)
    m3, m1 = _pair_colours(pairs)
    near = np.argpartition(_sqdist(feat, pairs.astype(np.float64)), min(candidates, len(pairs) - 1), 1)[:, :candidates]
    best, mode = np.zeros(n, np.int32), np.zeros(n, np.int32)
    for i in range(n):
        c = near[i]
        b = blocks[i:i + 1]
        e3, e1 = _block_error(b, m3[c])[0], _block_error(b, m1[c][:, :3])[0]
        use1 = e1 < e3
        e = np.where(use1, e1, e3)
        j = e.argmin()
        best[i], mode[i] = c[j], 1 if use1[j] else 3
    cols = np.where((mode == 1)[:, None, None], m1[best], m3[best])
    d = ((blocks[:, :, None, :] - cols[:, None, :, :]) ** 2).sum(-1)
    d[mode == 1, :, 3] = 1 << 30
    sel = d.argmin(-1)
    texel = (sel << (2 * np.arange(16))).sum(1).astype('<u4')
    index = (best | (mode << 14)).astype('<u2')
    pal = (pairs[:, 0] | pairs[:, 1] << 5 | pairs[:, 2] << 10, pairs[:, 3] | pairs[:, 4] << 5 | pairs[:, 5] << 10)
    pal = np.stack(pal, 1).reshape(-1).astype('<u2')
    pal = np.concatenate([pal, np.zeros(max_colours - len(pal), '<u2')])
    return texel.tobytes(), index.tobytes(), pal.tobytes()


def card_texture(card_img_path):
    src = Image.open(card_img_path).convert('RGBA').resize((88, 128), Image.LANCZOS)
    canvas = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
    canvas.paste(src, (20, 0))
    return canvas


def entries(binpath, idxpath):
    idx = open(idxpath, 'rb').read()
    d = open(binpath, 'rb').read()
    offs = struct.unpack(f'<{len(idx) // 4}I', idx)
    return [d[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)], d[offs[-1]:]


if __name__ == '__main__':
    import argparse
    import os
    ap = argparse.ArgumentParser(description='Decode one card picture (NTTX, 128x128) from card_5tx128 to PNG.')
    ap.add_argument('bin', help='card_5tx128.bin (e.g. extracted/Data_arc_pac/card/card_5tx128.bin)')
    ap.add_argument('idx', help='card_5tx128_idx.bin')
    ap.add_argument('index', type=int, help='card DB index (not the card id; see `carddb.py show`)')
    ap.add_argument('png', help='output PNG')
    a = ap.parse_args()
    for f in (a.bin, a.idx):
        if not os.path.isfile(f):
            sys.exit(f'not found: {f}')
    arts, _ = entries(a.bin, a.idx)
    if not 0 <= a.index < len(arts):
        sys.exit(f'index {a.index} out of range 0..{len(arts) - 1}')
    decode(ndspy.lz10.decompress(arts[a.index])).save(a.png)
