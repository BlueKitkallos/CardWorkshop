#!/usr/bin/env python3
import argparse
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bustup
import game
import nttx

CELL_BOX = (-256, -128, 256, 128)


def palette(nclr):
    p = bustup.section(nclr, b'TTLP')
    depth, _, size, off = struct.unpack_from('<IIII', nclr, p + 8)
    return [nttx.bgr555(c) for c in struct.unpack_from(f'<{size // 2}H', nclr, p + 8 + off)]


def tiles(ncgr):
    p = bustup.section(ncgr, b'RAHC')
    depth = struct.unpack_from('<I', ncgr, p + 12)[0]
    size, off = struct.unpack_from('<II', ncgr, p + 0x18)
    data = ncgr[p + 8 + off:p + 8 + off + size]
    if depth == 3:
        data = bytes(v for b in data for v in (b & 15, b >> 4))
    return [data[i:i + 64] for i in range(0, len(data), 64)], depth == 3


def screen(ncgr, nclr, nscr):
    pal = palette(nclr)
    ts, bpp4 = tiles(ncgr)
    p = bustup.section(nscr, b'NRCS')
    w, h, _, size = struct.unpack_from('<HHII', nscr, p + 8)
    w, h = w // 8, h // 8
    m = struct.unpack_from(f'<{size // 2}H', nscr, p + 0x14)
    im = Image.new('RGBA', (w * 8, h * 8))
    px = im.load()
    for ty in range(h):
        for tx in range(w):
            e = m[ty * w + tx]
            t, hf, vf, pn = e & 0x3ff, e >> 10 & 1, e >> 11 & 1, e >> 12
            if t >= len(ts):
                continue
            for y in range(8):
                for x in range(8):
                    v = ts[t][(7 - y if vf else y) * 8 + (7 - x if hf else x)]
                    if v:
                        px[tx * 8 + x, ty * 8 + y] = pal[pn * 16 + v if bpp4 else v] + (255,)
    return im


def oams(ncer, cell):
    p = bustup.section(ncer, b'KBEC')
    ncells, _, cell_off = struct.unpack_from('<HHI', ncer, p + 8)
    c = p + 8 + cell_off
    noam, _, oam_off = struct.unpack_from('<HHI', ncer, c + 8 * cell)
    base = c + 8 * ncells + oam_off
    for i in range(noam):
        a0, a1, a2 = struct.unpack_from('<HHH', ncer, base + 6 * i)
        y = (a0 & 0xff) - (256 if a0 & 0x80 else 0)
        x = (a1 & 0x1ff) - (512 if a1 & 0x100 else 0)
        w, h = bustup.OBJ_SIZES[(a0 >> 14, a1 >> 14)]
        affine = a0 & 0x100
        yield x, y, w, h, a2 & 0x3ff, a2 >> 12, not affine and a1 >> 12 & 1, not affine and a1 >> 13 & 1


def cell(ts, bpp4, pal, ncer, k, box=CELL_BOX):
    im = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]))
    px = im.load()
    unit = 32 if bpp4 else bustup.UNIT
    for x, y, w, h, tile, pn, hf, vf in reversed(list(oams(ncer, k))):
        first = tile * unit // 64
        for ty in range(h // 8):
            for tx in range(w // 8):
                t = ts[first + ty * (w // 8) + tx]
                for j in range(64):
                    v = t[j]
                    if not v:
                        continue
                    dx, dy = tx * 8 + j % 8, ty * 8 + j // 8
                    X = x + (w - 1 - dx if hf else dx) - box[0]
                    Y = y + (h - 1 - dy if vf else dy) - box[1]
                    if 0 <= X < im.width and 0 <= Y < im.height:
                        px[X, Y] = pal[pn * 16 + v if bpp4 else v] + (255,)
    return im


def cells(ncgr, nclr, ncer):
    pal = palette(nclr)
    ts, bpp4 = tiles(ncgr)
    n = struct.unpack_from('<H', ncer, bustup.section(ncer, b'KBEC') + 8)[0]
    out = []
    for k in range(n):
        im = cell(ts, bpp4, pal, ncer, k)
        out.append(im.crop(im.getbbox()) if im.getbbox() else None)
    return out


def load(rom_path, pac, stem):
    files = game.container_files(game.open_rom(rom_path), pac)
    return lambda ext: nttx.lz_decompress(files[f'{stem}.lz{ext}'])


def main():
    ap = argparse.ArgumentParser(description='Export WC2011 2D graphics from a .pac to PNG: a BG screen '
                                             '(<stem>.lz{ncgr,nclr,nscr}) or every cell of a sprite '
                                             '(<stem>.lz{ncgr,nclr,ncer}, cropped to its pixels).',
                                 epilog='Examples: screen <rom> Data_arc_pac/RPG2D.pac end_title_logo_en logo.png; '
                                        'cells <rom> Data_arc_pac/duel2d/BustupR.pac bu205_r out/')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('screen', 'cells'):
        p = sub.add_parser(name)
        p.add_argument('rom', help='WC2011 ROM')
        p.add_argument('pac', help='container path in the ROM, e.g. Data_arc_pac/RPG2D.pac')
        p.add_argument('stem', help='file name without .lz<ext>')
        p.add_argument('out', help='PNG (screen) or folder (cells: <stem>_cell<N>.png)')
    a = ap.parse_args()
    get = load(a.rom, a.pac, a.stem)
    if a.cmd == 'screen':
        screen(get('ncgr'), get('nclr'), get('nscr')).save(a.out)
        print(a.out)
        return
    os.makedirs(a.out, exist_ok=True)
    for k, im in enumerate(cells(get('ncgr'), get('nclr'), get('ncer'))):
        if im:
            path = os.path.join(a.out, f'{a.stem}_cell{k}.png')
            im.save(path)
            print(path, im.size)


if __name__ == '__main__':
    main()
