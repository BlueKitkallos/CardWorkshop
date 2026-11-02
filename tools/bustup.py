import os
import struct

import ndspy.lz10
from PIL import Image

import nttx

OBJ_SIZES = {
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}
UNIT = 128
BOX = (-80, -96, 48, 96)
W11_PAC = 'Data_arc_pac/duel2d/BustupR.pac'
W11_BOX = (-96, -96, 64, 96)
W11_CELL = 1


def rgb555(c):
    return ((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31)


def to555(r, g, b):
    return (r * 31 + 127) // 255 | (g * 31 + 127) // 255 << 5 | (b * 31 + 127) // 255 << 10


def section(d, magic):
    p = struct.unpack_from('<H', d, 12)[0]
    while p < len(d):
        tag, size = d[p:p + 4], struct.unpack_from('<I', d, p + 4)[0]
        if tag == magic:
            return p
        p += size
    raise ValueError(f'no {magic!r} section')


def nitro(magic, version, sections):
    body = b''.join(sections)
    return magic + struct.pack('<HHIHH', 0xfeff, version, 16 + len(body), 16, len(sections)) + body


def parse_oams(ncer, cell=None):
    p = section(ncer, b'KBEC')
    ncells, _, cell_off = struct.unpack_from('<HHI', ncer, p + 8)
    if cell is None and ncells != 1:
        raise ValueError(f'{ncells} cells, expected 1')
    cell = cell or 0
    if cell >= ncells:
        raise ValueError(f'cell {cell}: the file has {ncells}')
    c = p + 8 + cell_off
    noam, _, oam_off = struct.unpack_from('<HHI', ncer, c + 8 * cell)
    base = c + 8 * ncells + oam_off
    oams = []
    for i in range(noam):
        a0, a1, a2 = struct.unpack_from('<HHH', ncer, base + 6 * i)
        y = a0 & 0xff
        y = y - 256 if y >= 128 else y
        x = a1 & 0x1ff
        x = x - 512 if x >= 256 else x
        w, h = OBJ_SIZES[(a0 >> 14, a1 >> 14)]
        oams.append((x, y, w, h, a2 & 0x3ff, bool(a0 & 0x2000)))
    return oams


def decode(ncgr, nclr, ncer, cell=None, box=BOX):
    pal = [rgb555(v) for v in struct.unpack_from('<256H', nclr, section(nclr, b'TTLP') + 0x18)]
    p = section(ncgr, b'RAHC')
    size, off = struct.unpack_from('<II', ncgr, p + 0x18)
    tiles = ncgr[p + 8 + off:p + 8 + off + size]
    img = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
    px = img.load()
    for x, y, w, h, tile, bpp8 in reversed(parse_oams(ncer, cell)):
        if not bpp8:
            raise ValueError('4bpp OAM')
        base = tile * UNIT
        for ty in range(h // 8):
            for tx in range(w // 8):
                t = base + (ty * (w // 8) + tx) * 64
                for j in range(64):
                    v = tiles[t + j]
                    if v:
                        X, Y = x + tx * 8 + j % 8 - box[0], y + ty * 8 + j // 8 - box[1]
                        if 0 <= X < img.width and 0 <= Y < img.height:
                            px[X, Y] = pal[v] + (255,)
    return img


def load(dirpath, n):
    rd = lambda e: ndspy.lz10.decompress(open(os.path.join(dirpath, f'bu{n:03d}.lz{e}'), 'rb').read())
    return rd('ncgr'), rd('nclr'), rd('ncer'), rd('nanr')


def wc2011_files(rom_path):
    import game
    return game.container_files(game.open_rom(rom_path), W11_PAC)


def load_wc2011(files, n, alt=''):
    for name in (f'bu{n:03d}{alt}_r', f'bu{n:03d}{alt}_r_e'):
        if f'{name}.lzncgr' in files:
            return tuple(nttx.lz_decompress(files[f'{name}.lz{e}']) for e in ('ncgr', 'nclr', 'ncer', 'nanr'))
    raise KeyError(f'{W11_PAC}: no bu{n:03d}{alt}_r')


def wc2011_portrait(files, n, cell=W11_CELL, alt=''):
    return decode(*load_wc2011(files, n, alt)[:3], cell=cell, box=W11_BOX)


def seam_score(ncgr, nclr, ncer, cell, box=W11_BOX):
    img = decode(ncgr, nclr, ncer, cell, box)
    px = img.load()
    tot = cnt = 0
    for x, y, w, h, *_ in parse_oams(ncer, cell):
        edges = [((x, y + k), (x - 1, y + k)) for k in range(h)] + \
            [((x + w - 1, y + k), (x + w, y + k)) for k in range(h)] + \
            [((x + k, y), (x + k, y - 1)) for k in range(w)] + \
            [((x + k, y + h - 1), (x + k, y + h)) for k in range(w)]
        for a, b in edges:
            a, b = (a[0] - box[0], a[1] - box[1]), (b[0] - box[0], b[1] - box[1])
            if all(0 <= p[0] < img.width and 0 <= p[1] < img.height for p in (a, b)):
                p, q = px[a], px[b]
                if p[3] and q[3]:
                    tot += sum(abs(p[i] - q[i]) for i in range(3))
                    cnt += 1
    return tot / max(cnt, 1)


def wc2011_cell(files, n, alt=''):
    f = load_wc2011(files, n, alt)[:3]
    return min((W11_CELL, 0), key=lambda c: seam_score(*f, c, box=(-256, -128, 128, 128)))


def wc2011_face(files, n, alt=''):
    ncer = load_wc2011(files, n, alt)[2]
    base = set(parse_oams(ncer, W11_CELL))
    best = None
    for cell in range(W11_CELL + 1, struct.unpack_from('<H', ncer, section(ncer, b'KBEC') + 8)[0]):
        diff = [o for o in parse_oams(ncer, cell) if o not in base]
        if not diff:
            continue
        box = (min(o[0] for o in diff), min(o[1] for o in diff), max(o[0] + o[2] for o in diff),
               max(o[1] + o[3] for o in diff))
        if best is None or (box[2] - box[0]) * (box[3] - box[1]) < (best[2] - best[0]) * (best[3] - best[1]):
            best = box
    if best is None:
        return None
    return [best[0] - W11_BOX[0], best[1] - W11_BOX[1], best[2] - W11_BOX[0], best[3] - W11_BOX[1]]


def head_crop(img, rows=48):
    w, h = BOX[2] - BOX[0], BOX[3] - BOX[1]
    a = img.getchannel('A')
    top = a.getbbox()[1]
    head = a.crop((0, top, img.width, min(img.height, top + rows))).getbbox()
    cx = (head[0] + head[2]) // 2 if head else img.width // 2
    x = max(0, min(img.width - w, cx - w // 2))
    return [x, img.height - h, x + w, img.height]


def quantize(img):
    img = img.convert('RGBA')
    alpha = img.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
    rgb = Image.new('RGB', img.size, (0, 0, 0))
    rgb.paste(img.convert('RGB'), mask=alpha)
    used = sorted({c for c, a in zip(rgb.getdata(), alpha.getdata()) if a})
    if len(used) <= 255:
        slot = {c: i + 1 for i, c in enumerate(used)}
        idx = bytes(slot[c] if a else 0 for c, a in zip(rgb.getdata(), alpha.getdata()))
        return idx, [(0, 0, 0)] + used + [(0, 0, 0)] * (255 - len(used))
    q = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    pal = q.getpalette()[:255 * 3]
    idx = bytes((v + 1) if a else 0 for v, a in zip(q.tobytes(), alpha.tobytes()))
    colors = [(0, 0, 0)] + [tuple(pal[i * 3:i * 3 + 3]) for i in range(len(pal) // 3)]
    colors += [(0, 0, 0)] * (256 - len(colors))
    return idx, colors


def encode(img, template_nanr):
    w, h = BOX[2] - BOX[0], BOX[3] - BOX[1]
    if img.size != (w, h):
        raise ValueError(f'portrait must be {w}x{h}')
    idx, colors = quantize(img)
    data = bytearray()
    oams = []
    for by in range(0, h, 64):
        for bx in range(0, w, 64):
            block = [idx[(by + y) * w + bx:(by + y) * w + bx + 64] for y in range(64)]
            if not any(any(r) for r in block):
                continue
            tile = len(data) // UNIT
            for ty in range(8):
                for tx in range(8):
                    for y in range(8):
                        data += block[ty * 8 + y][tx * 8:tx * 8 + 8]
            x, y = bx + BOX[0], by + BOX[1]
            oams.append(struct.pack('<HHH', (y & 0xff) | 0x2000, (x & 0x1ff) | 3 << 14, tile))
    char = struct.pack('<HHIIIII', 0xffff, 0xffff, 4, 0x00200010, 0, len(data), 0x18) + bytes(data)
    ncgr = nitro(b'RGCN', 0x0101, [b'RAHC' + struct.pack('<I', 8 + len(char)) + char])
    pal = struct.pack('<IIII', 4, 0, 0x200, 0x10) + struct.pack('<256H', *(to555(*c) for c in colors))
    nclr = nitro(b'RLCN', 0x0100, [b'TTLP' + struct.pack('<I', 8 + len(pal)) + pal])
    oam = b''.join(oams)
    cells = struct.pack('<HHI', len(oams), 0x1f, 0) + oam
    cebk = struct.pack('<HHIIIII', 1, 0, 0x18, 2, 0, 0, 0) + cells
    cebk += b'\0' * (-len(cebk) % 4)
    lbal = b'LBAL' + struct.pack('<II', 0x17, 0) + b'CellAnime0\0'
    uext = b'TXEU' + struct.pack('<II', 12, 0)
    ncer = nitro(b'RECN', 0x0100, [b'KBEC' + struct.pack('<I', 8 + len(cebk)) + cebk, lbal, uext])
    return ncgr, nclr, ncer, template_nanr


def portrait(cutout, crop=None, alpha_min=128):
    w, h = BOX[2] - BOX[0], BOX[3] - BOX[1]
    im = Image.open(cutout).convert('RGBA')
    im = im.crop(tuple(crop) if crop else im.getchannel('A').getbbox())
    s = min(w / im.width, h / im.height)
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.paste(im, ((w - im.width) // 2, h - im.height), im)
    out.putalpha(out.getchannel('A').point(lambda a: 255 if a >= alpha_min else 0))
    return out


def face(img, box, size=(48, 40)):
    return img.crop(tuple(box)).resize(size, Image.LANCZOS)


def write(files, outdir, n):
    os.makedirs(outdir, exist_ok=True)
    for ext, d in zip(('ncgr', 'nclr', 'ncer', 'nanr'), files):
        open(os.path.join(outdir, f'bu{n:03d}.lz{ext}'), 'wb').write(ndspy.lz10.compress(d))


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Opponent portraits (Bustup.pac bu<char>.lz{ncgr,nclr,ncer,nanr}, '
                                             '128x192, one 256-colour palette).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('show', help='decode a stock portrait to PNG')
    p.add_argument('bustup_dir', help='extracted Bustup folder, e.g. extracted/Data_arc_pac/Bustup, or the WC2011 ROM '
                                      '(BYYP: LZ11, 5 cells per portrait, 160x192)')
    p.add_argument('n', type=int, help='character number (bu<n>)')
    p.add_argument('png', help='output PNG')
    p.add_argument('--cell', type=int, default=W11_CELL, help='WC2011 cell: 1 neutral (default), 2-4 expressions')
    p.add_argument('--fit', action='store_true', help='WC2011: crop to the 128x192 WC2008 cell, centred on the head')
    p = sub.add_parser('cutout', help='cut the background out of an image (needs the rembg package, local model)')
    p.add_argument('image', help='input image')
    p.add_argument('png', help='output PNG with alpha')
    p = sub.add_parser('build', help='encode a cutout PNG as a portrait')
    p.add_argument('cutout', help='PNG with alpha; scaled to fit 128x192, bottom-aligned')
    p.add_argument('bustup_dir', help='extracted Bustup folder (the animation file is copied from a template)')
    p.add_argument('template', type=int, help='character number whose bu<n>.lznanr is reused')
    p.add_argument('outdir', help='output folder')
    p.add_argument('n', type=int, help='character number to write (bu<n>)')
    p.add_argument('preview', nargs='?', help='optional PNG preview of the encoded portrait')
    a = ap.parse_args()
    for path in [getattr(a, k) for k in ('bustup_dir', 'image', 'cutout') if getattr(a, k, None)]:
        if not os.path.exists(path):
            raise SystemExit(f'not found: {path}')
    if a.cmd == 'show' and os.path.isfile(a.bustup_dir):
        img = wc2011_portrait(wc2011_files(a.bustup_dir), a.n, a.cell)
        (img.crop(tuple(head_crop(img))) if a.fit else img).save(a.png)
    elif a.cmd == 'show':
        ncgr, nclr, ncer, _ = load(a.bustup_dir, a.n)
        decode(ncgr, nclr, ncer).save(a.png)
    elif a.cmd == 'cutout':
        try:
            from rembg import new_session, remove
        except ImportError:
            raise SystemExit('cutout needs rembg: pip install "rembg[cpu]"')
        remove(Image.open(a.image).convert('RGB'), session=new_session('isnet-anime')).save(a.png)
    else:
        img = portrait(a.cutout)
        files = encode(img, load(a.bustup_dir, a.template)[3])
        write(files, a.outdir, a.n)
        if a.preview:
            decode(*files[:3]).save(a.preview)


if __name__ == '__main__':
    main()
