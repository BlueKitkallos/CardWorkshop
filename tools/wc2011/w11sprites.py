#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
import struct
import sys
from concurrent.futures import ProcessPoolExecutor

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bustup
import numpy as np
import game
import nsbmd
import nttx
import w11gfx

ROM = None
CHAR_PACS = {
    'Data_arc_pac/duel2d/BustupR.pac': ('duel', re.compile(r'bu(\d+)(b?)_r(?:_([ej]))?$')),
    'Data_arc_pac/duel2d/BustupL.pac': ('duel', re.compile(r'bu(\d+)(b?)_l(?:_([ej]))?$')),
    'Data_arc_pac/RPG2D_BU.pac': ('story', re.compile(r'npc(\d+)_(bu\d+)_[lr](?:_([ej]))?$')),
}
AVATAR_PACS = ['Data_arc_pac/CharaMake/face.pac', 'Data_arc_pac/CharaMake/hair.pac', 'Data_arc_pac/CharaMake/wear.pac',
               'Data_arc_pac/CharaMake/disc.pac', 'Data_arc_pac/CharaMake/skin.pac']
AVATAR_RPG2D = re.compile(r'[fm]_(face|hair|wear)\d+$')
STORY_CG = re.compile(r'(bg|evbg|epi|staffroll_bg|end_)')
MONSTER_PACS = ('Data_arc_pac/duel2d/BattleMonster1.pac', 'Data_arc_pac/duel2d/BattleMonster2.pac',
                'Data_arc_pac/duel2d/BattleMonster3.pac')
NPC_3D = re.compile(r'npc(\d+)(?:_[a-z]+)?$')
AVATAR_3D = re.compile(r'(pc[fm][bfh]\d+|player\d+_[a-z]+)$')


def files(pac):
    return game.container_files(ROM, pac)


def stems(fs):
    out = {}
    for n in fs:
        m = re.match(r'(.*)\.lz(ncgr|nclr|ncer|nscr|5bg)$', n)
        if m:
            out.setdefault(m.group(1), set()).add(m.group(2))
    return out


def cell_set(fs, stem, aligned):
    get = lambda e: nttx.lz_decompress(fs[f'{stem}.lz{e}'])
    ncgr, nclr, ncer = get('ncgr'), get('nclr'), get('ncer')
    pal = w11gfx.palette(nclr)
    ts, bpp4 = w11gfx.tiles(ncgr)
    n = struct.unpack_from('<H', ncer, bustup.section(ncer, b'KBEC') + 8)[0]
    seen, ims = set(), []
    for k in range(n):
        im = w11gfx.cell(ts, bpp4, pal, ncer, k)
        if not im.getbbox():
            continue
        h = hashlib.md5(im.tobytes()).digest()
        if h not in seen:
            seen.add(h)
            ims.append((k, im))
    if not aligned:
        return [(k, im.crop(im.getbbox())) for k, im in ims]
    if not ims:
        return []
    boxes = [im.getbbox() for _, im in ims]
    big = max((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
    if len(ims) > 1:
        ims = [(k, im) for (k, im), b in zip(ims, boxes) if (b[2] - b[0]) * (b[3] - b[1]) * 4 > big] or ims
        boxes = [im.getbbox() for _, im in ims]
    u = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    return [(k, im.crop(u)) for k, im in ims]


def screen(fs, stem):
    get = lambda e: nttx.lz_decompress(fs[f'{stem}.lz{e}'])
    return w11gfx.screen(get('ncgr'), get('nclr'), get('nscr'))


def tile_px(data, n, bpp8):
    raw = np.frombuffer(data[:n * (64 if bpp8 else 32)], np.uint8)
    if not bpp8:
        raw = np.stack([raw & 15, raw >> 4], 1).reshape(-1)
    return raw.reshape(n, 8, 8)


def rgba(idx, bank, b):
    ncol = struct.unpack_from('<I', b['PALT'], 0)[0]
    pal = np.zeros((max(256, ncol), 4), np.uint8)
    pal[:ncol, :3] = [nttx.bgr555(c) for c in struct.unpack_from(f'<{ncol}H', b['PALT'], 4)]
    pal[:, 3] = 255
    full = np.where(idx > 0, idx + bank * 16, 0).astype(np.int64)
    out = pal[np.minimum(full, len(pal) - 1)]
    out[idx == 0] = 0
    return Image.fromarray(out, 'RGBA')


def bg5(fs, stem):
    raw = nttx.lz_decompress(fs[f'{stem}.lz5bg'])
    b = nttx.blocks(raw)
    if 'BGDT' in b:
        g = b['BGDT']
        fmt, = struct.unpack_from('<H', g, 0)
        if fmt not in (0xff00, 0xff01):
            raise ValueError(f'BGDT format {fmt:#x}')
        bpp8 = fmt == 0xff01
        msz, w, h = struct.unpack_from('<IHH', g, 4)
        csz = struct.unpack_from('<I', g, 16)[0]
        tmap = np.array(struct.unpack_from(f'<{msz // 2}H', g, 20)[:w * h], np.int64).reshape(h, w)
        ts = tile_px(g[20 + msz:], csz // (64 if bpp8 else 32), bpp8)
        t = np.minimum(tmap & 0x3ff, len(ts) - 1)
        px = ts[t]
        px = np.where((tmap >> 10 & 1)[..., None, None] == 1, px[..., ::-1], px)
        px = np.where((tmap >> 11 & 1)[..., None, None] == 1, px[..., ::-1, :], px)
        bank = np.zeros_like(px) if bpp8 else np.broadcast_to((tmap >> 12)[..., None, None], px.shape)
        f = lambda a: a.transpose(0, 2, 1, 3).reshape(h * 8, w * 8)
        return rgba(f(px), f(bank), b)
    o = b['OBJD']
    fmt, = struct.unpack_from('<H', o, 0)
    bpp8 = fmt & 1
    fw, fh = bustup.OBJ_SIZES[(fmt >> 10 & 3, fmt >> 8 & 3)]
    gw, gh = struct.unpack_from('<HH', o, 8)
    n = gw * gh
    tpf = fw * fh // 64
    data = o[24 + 4 * n:]
    ts = tile_px(data, n * tpf, bpp8)
    banks = (np.frombuffer(b['DFPL'][4:4 + n * tpf], np.uint8) if 'DFPL' in b and not bpp8
             else np.zeros(n * tpf, np.uint8))
    banks = np.pad(banks, (0, n * tpf - len(banks)))
    tx, ty = fw // 8, fh // 8
    px = ts.reshape(gh, gw, ty, tx, 8, 8).transpose(0, 2, 4, 1, 3, 5).reshape(gh * fh, gw * fw)
    bk = np.broadcast_to(banks.reshape(gh, gw, ty, tx, 1, 1), (gh, gw, ty, tx, 8, 8))
    bk = bk.transpose(0, 2, 4, 1, 3, 5).reshape(gh * fh, gw * fw)
    return rgba(px, bk, b)


def save(im, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path)
    return path


def job_cells(pac, stem, out_dir, prefix):
    fs = files(pac)
    return [save(im, os.path.join(out_dir, f'{prefix}{stem}_{k}.png')) for k, im in cell_set(fs, stem, prefix in ('duel_', 'story_'))]


def job_screen(pac, stem, out_dir, prefix):
    im = screen(files(pac), stem)
    return [save(im, os.path.join(out_dir, f'{prefix}{stem}.png'))] if im.getbbox() else []


def job_bg5(pac, stem, out_dir, prefix):
    im = bg5(files(pac), stem)
    return [save(im, os.path.join(out_dir, f'{prefix}{stem}.png'))] if im.getbbox() else []


def job_3d(pac, name, out_dir, prefix):
    ir = nsbmd.parse_bmd(nsbmd.load_model(name, ROM, pac))
    if not ir['tex']:
        return []
    pals = {p['name']: p['data'] for p in ir['tex']['palettes']}
    m = ir['models'][0]
    out, done = [], set()
    texs = {t['name']: t for t in ir['tex']['textures']}
    for mi in range(len(m['materials'])):
        tn, pn = nsbmd.mat_texture(m, mi)
        if tn in texs and tn not in done:
            done.add(tn)
            im = Image.fromarray(nsbmd.decode_texture(texs[tn], pals.get(pn, b'')))
            out.append(save(im, os.path.join(out_dir, f'{prefix}{name}_{tn}.png')))
    return out


JOBS = {'cells': job_cells, 'screen': job_screen, 'bg5': job_bg5, '3d': job_3d}


def init(rom_path):
    global ROM
    ROM = game.open_rom(rom_path)


def run(task):
    kind, pac, stem, out_dir, prefix = task
    try:
        return task, JOBS[kind](pac, stem, out_dir, prefix), None
    except Exception as e:
        return task, [], f'{type(e).__name__}: {e}'


def safe(s):
    return re.sub(r'[^\w.-]+', '_', s).strip('_')


def char_names(rom_path):
    import wc2011opponents
    w11 = wc2011opponents.Wc2011(rom_path)
    out = {}
    for char, deck in w11.char_deck.items():
        n = (w11.display_name(deck)[2] or {}).get('e')
        if n:
            out[char] = n
    return out


def char_dir(root, names, cid):
    n = names.get(cid)
    return os.path.join(root, 'characters', f'{cid:03d}_{safe(n)}' if n else f'{cid:03d}')


def plan(rom_path, root, everything):
    names = char_names(rom_path)
    tasks, claimed = [], set()
    for pac, (kind, pat) in CHAR_PACS.items():
        for stem, ext in sorted(stems(files(pac)).items()):
            m = pat.match(stem)
            if m and {'ncgr', 'nclr', 'ncer'} <= ext:
                tasks.append(('cells', pac, stem, char_dir(root, names, int(m.group(1))), f'{kind}_'))
                claimed.add((pac, stem))
    pac3d = 'Data_arc_pac/RPG3D.pac'
    for n in sorted(files(pac3d)):
        if not n.endswith('.lznsbmd'):
            continue
        stem = n[:-len('.lznsbmd')]
        m = NPC_3D.match(stem)
        if m:
            tasks.append(('3d', pac3d, stem, char_dir(root, names, int(m.group(1))), '3d_'))
        elif AVATAR_3D.match(stem):
            tasks.append(('3d', pac3d, stem, os.path.join(root, 'avatar', '3d'), ''))
    for pac in AVATAR_PACS:
        for stem, ext in sorted(stems(files(pac)).items()):
            if {'ncgr', 'nclr', 'ncer'} <= ext:
                tasks.append(('cells', pac, stem, os.path.join(root, 'avatar', os.path.basename(pac)[:-4]), ''))
                claimed.add((pac, stem))
    rpg2d = 'Data_arc_pac/RPG2D.pac'
    for stem, ext in sorted(stems(files(rpg2d)).items()):
        if AVATAR_RPG2D.match(stem) and 'ncer' in ext:
            tasks.append(('cells', rpg2d, stem, os.path.join(root, 'avatar', 'story_player'), ''))
            claimed.add((rpg2d, stem))
        elif STORY_CG.match(stem) and 'nscr' in ext:
            tasks.append(('screen', rpg2d, stem, os.path.join(root, 'story_cg'), ''))
            claimed.add((rpg2d, stem))
    if everything:
        for fid in range(len(ROM.files)):
            pac = ROM.filenames.filenameOf(fid)
            if not pac or not pac.endswith('.pac') or pac in MONSTER_PACS:
                continue
            od = os.path.join(root, 'other', safe(pac[len('Data_arc_pac/'):-4]))
            for stem, ext in sorted(stems(files(pac)).items()):
                if (pac, stem) in claimed:
                    continue
                if {'ncgr', 'nclr', 'ncer'} <= ext:
                    tasks.append(('cells', pac, stem, od, ''))
                elif {'ncgr', 'nclr', 'nscr'} <= ext:
                    tasks.append(('screen', pac, stem, od, ''))
                if '5bg' in ext:
                    tasks.append(('bg5', pac, stem, od, ''))
    return tasks


def sheet(paths, out, pad=4, width=1400):
    ims = [Image.open(p) for p in paths]
    rows, row, x = [], [], 0
    for im in ims:
        if row and x + im.width > width:
            rows.append(row)
            row, x = [], 0
        row.append(im)
        x += im.width + pad
    rows.append(row)
    W = max(sum(i.width + pad for i in r) for r in rows)
    H = sum(max(i.height for i in r) + pad for r in rows)
    o = Image.new('RGBA', (W, H), (48, 48, 48, 255))
    y = 0
    for r in rows:
        x = 0
        for i in r:
            o.paste(i, (x, y), i)
            x += i.width + pad
        y += max(i.height for i in r) + pad
    o.save(out)


def main():
    ap = argparse.ArgumentParser(description='Export WC2011 sprites to PNG. Default: every character (duel and story '
                                             'bust-ups with all expressions, 3D NPC textures, one folder and a '
                                             'contact sheet per character), the player avatar parts and the story '
                                             'CG screens. --all adds every other 2D graphic in the ROM except '
                                             'the in-duel monster pictures.')
    ap.add_argument('rom', help='WC2011 ROM')
    ap.add_argument('--out', default='build/w11sprites')
    ap.add_argument('--all', action='store_true', help='also every menu, duel and minigame graphic, under other/')
    ap.add_argument('-j', type=int, default=4)
    a = ap.parse_args()
    init(a.rom)
    tasks = plan(a.rom, a.out, a.all)
    print(f'{len(tasks)} sets', flush=True)
    made, by_task, fails = {}, [], []
    with ProcessPoolExecutor(a.j, initializer=init, initargs=(a.rom,)) as ex:
        for i, (task, paths, err) in enumerate(ex.map(run, tasks, chunksize=4), 1):
            if err:
                fails.append(f'{task[1]} {task[2]}: {err}')
            made.setdefault(task[3], []).extend(paths)
            by_task.append((task, paths))
            if i % 100 == 0 or i == len(tasks):
                print(f'{i}/{len(tasks)} sets, {sum(map(len, made.values()))} PNGs', flush=True)
    for d, paths in made.items():
        if paths and os.sep + 'characters' + os.sep in d + os.sep:
            sheet(sorted(paths), os.path.join(d, '_sheet.png'))
    with open(os.path.join(a.out, 'index.tsv'), 'w', encoding='utf-8') as fh:
        fh.write('png\tpac\tstem\n')
        for task, paths in by_task:
            for p in paths:
                fh.write(f'{os.path.relpath(p, a.out)}\t{task[1]}\t{task[2]}\n')
    fail_path = os.path.join(a.out, 'failed.txt')
    if fails:
        with open(fail_path, 'w') as fh:
            fh.write('\n'.join(fails) + '\n')
    elif os.path.exists(fail_path):
        os.remove(fail_path)
    print(f'{sum(map(len, made.values()))} PNGs in {a.out}, {len(fails)} sets failed'
          + (f' (list in {a.out}/failed.txt)' if fails else ''))


if __name__ == '__main__':
    main()
