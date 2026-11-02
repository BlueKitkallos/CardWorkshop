#!/usr/bin/env python3
"""Booster packs added to a WC2011-based build: card memberships and rarities, the pack name and
description in each language, the three pack pictures and the numbers the variant's C code needs."""
import argparse
import json
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import carddb
import game
import modspec
import nsbmd
import nttx
import w11textfix
import w11unlock

PK_FIRST = 97
PK_MAX = 20
SLOT = 2
STOCK_FIRST, STOCK_LAST = 1, 81
ALL_RANDOM = 60
SLOT1_PACKS = range(32, 43)
RARITY = {'ultra': 2, 'super': 3, 'rare': 4, 'common': 0}
LANGS = {'e': 'eng', 'f': 'fra', 'g': 'ger', 'i': 'ita', 's': 'spa', 'j': 'jpn', 'k': 'kor'}
PRICE = 150
ART_PAC = 'Data_arc_pac/pack.pac'
TEXT_PAC = 'Data_arc_pac/bin.pac'
FRAME_PACKS = range(1, 60)
STRUCTURE_PACKS = range(61, 81)
BOX_FACE = (10, 29, 64, 100)
BIG = (64, 128)
WORK = 4
RIM_PX = 6
RIM_ALPHA = 150
FADE = 0.2
CUT_MIN = 8
TITLE_BOX = (3, 103, 61, 112)
SERIF = os.environ.get('YGO_TITLE_FONT', '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf')
KEY = 0x03e0


def load(paths):
    specs, ids = [], {}
    for p in paths:
        with open(p, encoding='utf-8') as f:
            s = json.load(f)
        pid = s.get('id')
        stock = isinstance(pid, int) and STOCK_FIRST <= pid <= STOCK_LAST
        if not stock and (not isinstance(pid, int) or not PK_FIRST <= pid < PK_FIRST + PK_MAX):
            raise SystemExit(f'{p}: "id" is a stock pack from {STOCK_FIRST} to {STOCK_LAST} or an added pack from '
                             f'{PK_FIRST} to {PK_FIRST + PK_MAX - 1}')
        if pid in ids:
            raise SystemExit(f'{p}: id {pid} is also used by {ids[pid]}')
        ids[pid] = p
        for key in ('name', 'desc'):
            missing = [l for l in LANGS if not isinstance(s.get(key, {}).get(l), str) or not (stock or s[key][l])]
            if missing:
                raise SystemExit(f'{p}: "{key}" has no text for {", ".join(missing)} (languages {" ".join(LANGS)})')
        if stock:
            try:
                w11textfix.fix_pack_spec(s, p)
            except w11textfix.TextFixError as e:
                raise SystemExit(str(e))
        if stock and 'price' in s:
            raise SystemExit(f'{p}: a stock pack has no "price": WC2011 sells every booster at 150 and every '
                             'structure deck at 2000 (in code)')
        price = s.get('price', PRICE)
        if not isinstance(price, int) or not 1 <= price <= 0xffff:
            raise SystemExit(f'{p}: "price" is a number from 1 to 65535')
        cards = s.get('cards', {})
        if set(cards) - set(RARITY):
            raise SystemExit(f'{p}: "cards" takes the rarities {", ".join(RARITY)}')
        if pid == ALL_RANDOM and cards:
            raise SystemExit(f'{p}: pack {ALL_RANDOM} takes every card; it has no "cards" list')
        if s.get("structure_deck"):
            if stock or not isinstance(s["structure_deck"], str):
                raise SystemExit(f'{p}: "structure_deck" must name a deck JSON for an added pack')
            if price != 2000:
                raise SystemExit(f'{p}: a structure deck costs 2000 DP')
        elif not stock or pid < ALL_RANDOM:
            empty = [r for r in RARITY if not cards.get(r)]
            if empty:
                raise SystemExit(f'{p}: no {", ".join(empty)} card (the pack draw needs at least one card of each '
                                 'rarity)')
            if len(cards['common']) < 4:
                raise SystemExit(f'{p}: {len(cards["common"])} commons; a pack holds 4 different commons, so at '
                                 'least 4')
        if 'unlock' in s:
            if stock:
                raise SystemExit(f'{p}: a stock pack has no "unlock": WC2011 decides when it goes on sale')
            s['_unlock'] = w11unlock.words(s['unlock'], w11unlock.story_flags(p), p)
        seen = {}
        for r in RARITY:
            for n in cards.get(r, []):
                if n in seen:
                    raise SystemExit(f'{p}: {n!r} is listed as {seen[n]} and as {r}')
                seen[n] = r
        art = s.get('art')
        if (art is not None or not stock) and (not isinstance(art, dict) or not
                (art.get('image') or (art.get('background') and art.get('colour')))):
            raise SystemExit(f'{p}: "art" needs "image" (a finished texture), or "background" and "colour" (#rrggbb)')
        for k, c in enumerate((art or {}).get('cutouts', [])):
            if not c.get('image'):
                raise SystemExit(f'{p}: "art" "cutouts" {k}: needs "image", a transparent PNG')
        specs.append((p, s))
    return sorted(specs, key=lambda x: x[1]['id'])


def stock_slot(pid):
    return 1 if pid in SLOT1_PACKS else 0


def stock_members(c):
    out = {}
    if c.packs[0] and c.packs[0] not in SLOT1_PACKS:
        out[0] = (c.packs[0], c.pack_rarity[0])
    if c.packs[1]:
        out[1] = (c.packs[1], c.pack_rarity[1])
    return out


def resolve_all(index, specs):
    out, unknown = [], []
    for p, s in specs:
        rows = []
        for r, names in s.get('cards', {}).items():
            for n in names:
                try:
                    ids = index.resolve(n, f'{p}: {r}')
                except SystemExit as e:
                    unknown.append(str(e))
                    continue
                rows.append((n, r, index.deck_id(ids)))
        out.append((p, s, rows))
    if unknown:
        raise SystemExit('\n'.join(unknown) + f'\n{len(unknown)} card name(s) not in the game (WC2011 cards and the '
                                               'mod card specs)')
    return out


def apply_stock(db, resolved):
    cards = db.cards[1:]
    listed = {s['id'] for _, s, _ in resolved}
    want = {c.id: {k: v for k, v in stock_members(c).items() if v[0] not in listed} for c in cards}
    primary = {(c.id, k): v[0] for c in cards for k, v in stock_members(c).items()}
    entries = [(p, s, n, r, cid) for p, s, rows in resolved for n, r, cid in rows]
    entries.sort(key=lambda x: primary.get((x[4], stock_slot(x[1]['id']))) != x[1]['id'])
    for p, s, n, r, cid in entries:
        pid = s['id']
        slot = stock_slot(pid)
        if slot in want[cid]:
            continue
        want[cid][slot] = (pid, RARITY[r])
    changed = []
    for c in cards:
        m = want[c.id]
        if m == stock_members(c):
            continue
        changed.append(c)
        c.packs[1], c.pack_rarity[1] = m.get(1, (0, 0))
        top = m.get(0) or m.get(1)
        if top:
            c.packs[0], c.pack_rarity[0] = top
            c.rarity = top[1]
        else:
            c.packs[0] = 0
    return changed


def assign(db, specs):
    resolved = resolve_all(modspec.CardIndex(db), specs)
    changed = apply_stock(db, [x for x in resolved if x[1]['id'] < PK_FIRST])
    by_id = {c.id: c for c in db.cards[1:]}
    for p, s, rows in resolved:
        if s['id'] < PK_FIRST:
            continue
        for n, r, cid in rows:
            c = by_id[cid]
            if c.packs[SLOT]:
                continue  # Further memberships are emitted in the sparse extension table.
            c.packs[SLOT] = s['id']
            c.pack_rarity[SLOT] = RARITY[r]
    return changed


def korean_glyphs(db, pt):
    have = set()
    for c in db.cards[1:]:
        have.update(c.names.get('k', ''), c.descs.get('k', ''))
    for t in pt.names['kor'] + pt.descs['kor']:
        have.update(t)
    return have


def set_text(pt, db, specs):
    if len(pt.names['eng']) != PK_FIRST:
        raise SystemExit(f'the ROM has {len(pt.names["eng"])} pack names, expected {PK_FIRST}: wrong ROM?')
    top = max(s['id'] for _, s in specs) + 1
    glyphs = korean_glyphs(db, pt)
    for pl in LANGS.values():
        for store in (pt.names, pt.descs):
            store[pl] += [''] * (top - len(store[pl]))
    for p, s in specs:
        for l, pl in LANGS.items():
            for key, store in (('name', pt.names), ('desc', pt.descs)):
                text = s[key][l]
                try:
                    carddb.encode_text(text, l)
                except (ValueError, UnicodeEncodeError) as e:
                    raise SystemExit(f'{p}: {key} {l}: {e}')
                if l == 'k':
                    miss = sorted({ch for ch in text if '가' <= ch <= '힣'} - glyphs)
                    if miss:
                        raise SystemExit(f'{p}: {key} k: {"".join(miss)} never occurs in WC2011\'s Korean text '
                                         '(the font may lack it)')
                store[pl][s['id']] = text


def decode_bgdt(raw):
    b = nttx.blocks(raw)
    n = struct.unpack_from('<I', b['PALT'], 0)[0]
    pal = np.array([nttx.bgr555(c) for c in struct.unpack_from(f'<{n}H', b['PALT'], 4)], np.uint8)
    g = b['BGDT']
    _, _, msize, w, h, _, _, tsize = struct.unpack_from('<HHIHHHHI', g, 0)
    tmap = struct.unpack_from(f'<{msize // 2}H', g, 20)
    tiles = np.frombuffer(g[20 + msize:20 + msize + tsize], np.uint8).reshape(-1, 8, 8)
    out = np.zeros((h * 8, w * 8, 3), np.uint8)
    for i, e in enumerate(tmap):
        t = tiles[e & 0x3ff]
        if e & 0x400:
            t = t[:, ::-1]
        if e & 0x800:
            t = t[::-1]
        out[(i // w) * 8:(i // w) * 8 + 8, (i % w) * 8:(i % w) * 8 + 8] = pal[t]
    return out


def frame(files):
    ims = np.stack([decode_bgdt(nttx.lz_decompress(files[f'l_pack{n:02d}.lz5bg'])).astype(int) for n in FRAME_PACKS])
    med = np.median(ims, axis=0)
    mask = (np.abs(ims - med).sum(axis=3) < 60).mean(axis=0) > 0.6
    return med.astype(np.uint8), mask


def rgb(hex_colour):
    return np.array([int(hex_colour.lstrip('#')[k:k + 2], 16) for k in (0, 2, 4)], dtype=float)


def shade(c, k):
    return tuple(int(v) for v in np.clip(c * k if k <= 1 else c + (255 - c) * (k - 1), 0, 255))


def title_image(text, width, height, colour):
    font = ImageFont.truetype(SERIF, 96)
    big = Image.new('RGBA', (len(text) * 110 + 40, 150), (0, 0, 0, 0))
    ImageDraw.Draw(big).text((20, 10), text, font=font, fill=shade(colour, 1.1) + (255,), stroke_width=8,
                             stroke_fill=shade(colour, 1.92) + (255,))
    big = big.crop(big.getchannel('A').getbbox())
    w = min(width, round(big.width * height / big.height))
    return big.resize((w, height), Image.LANCZOS)


def background(art, colour, size):
    src = Image.open(art['background']).convert('RGB')
    w, h = src.size
    ch = min(h, w * size[1] / size[0]) / art.get('zoom', 1)
    cw = ch * size[0] / size[1]
    cx, cy = w * art.get('center_x', 0.5), h * art.get('center_y', 0.5)
    x0 = max(0, min(w - cw, cx - cw / 2))
    y0 = max(0, min(h - ch, cy - ch / 2))
    crop = src.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize(size, Image.LANCZOS)
    grey = ImageOps.autocontrast(crop.convert('L'), cutoff=2)
    bg = ImageOps.colorize(grey, shade(colour, 0.25), shade(colour, 1.7), shade(colour, 1.0))
    bg = Image.blend(crop, bg, art.get('colour_mix', 1.0))
    yy, xx = np.mgrid[0:size[1], 0:size[0]]
    r = np.hypot((xx / size[0] - 0.5) * 1.6, yy / size[1] - 0.4)
    light = np.clip(1.2 - 0.9 * r, 0.55, 1.2)[..., None]
    return Image.fromarray(np.clip(np.asarray(bg, dtype=float) * light, 0, 255).astype(np.uint8)).convert('RGBA')


def fade_cut_edges(im):
    a = np.asarray(im.getchannel('A'), dtype=float)
    h, w = a.shape
    sides = {'top': a[0], 'bottom': a[-1], 'left': a[:, 0], 'right': a[:, -1]}
    ramp_v = np.ones(h)
    ramp_h = np.ones(w)
    n = max(1, round(h * FADE))
    m = max(1, round(w * FADE))
    for side, line in sides.items():
        if (line > 128).sum() < CUT_MIN:
            continue
        if side == 'top':
            ramp_v[:n] = np.minimum(ramp_v[:n], np.linspace(0, 1, n))
        elif side == 'bottom':
            ramp_v[-n:] = np.minimum(ramp_v[-n:], np.linspace(1, 0, n))
        elif side == 'left':
            ramp_h[:m] = np.minimum(ramp_h[:m], np.linspace(0, 1, m))
        else:
            ramp_h[-m:] = np.minimum(ramp_h[-m:], np.linspace(1, 0, m))
    im = im.copy()
    im.putalpha(Image.fromarray((a * ramp_v[:, None] * ramp_h[None, :]).astype(np.uint8)))
    return im


def cutout_layer(c, size, rim):
    w, h = size
    fg = Image.open(c['image']).convert('RGBA')
    if c.get('fade_edges', True):
        fg = fade_cut_edges(fg)
    fg = fg.crop(fg.getchannel('A').getbbox())
    if c.get('flip'):
        fg = fg.transpose(Image.FLIP_LEFT_RIGHT)
    s = c.get('height', 0.7) * h / fg.height
    fg = fg.resize((max(1, round(fg.width * s)), max(1, round(fg.height * s))), Image.LANCZOS)
    layer = Image.new('RGBA', size, (0, 0, 0, 0))
    layer.paste(fg, (round(c.get('x', 0.5) * w - fg.width * c.get('anchor', 0.5)), round(c.get('y', 0.05) * h)), fg)
    solid = layer.getchannel('A').point(lambda v: 255 if v > 60 else 0)
    glow = solid.filter(ImageFilter.MaxFilter(RIM_PX * 2 + 1)).filter(ImageFilter.GaussianBlur(RIM_PX))
    out = Image.new('RGBA', size, rim + (0,))
    out.putalpha(glow.point(lambda v: v * RIM_ALPHA // 255))
    out.alpha_composite(layer)
    return out


def render(spec, files):
    art = spec['art']
    if art.get('image'):
        with Image.open(art['image']) as source:
            return source.convert('RGB').resize(BIG, Image.LANCZOS)
    colour = rgb(art['colour'])
    if art.get('box'):
        return render_box(art, colour, files)
    img = background(art, colour, (BIG[0] * WORK, BIG[1] * WORK))
    for c in art.get('cutouts', []):
        img.alpha_composite(cutout_layer(c, img.size, shade(colour, 1.85)))
    img = img.resize(BIG, Image.LANCZOS)
    med, mask = frame(files)
    px = np.asarray(img).copy()
    px[mask, :3] = med[mask]
    img = Image.fromarray(px)
    x0, y0, x1, y1 = TITLE_BOX
    t = title_image(art.get('title', spec['name']['e']), x1 - x0, y1 - y0, colour)
    img.alpha_composite(t, (x0 + (x1 - x0 - t.width) // 2, y0))
    return img.convert('RGB')


def render_box(art, colour, files):
    ims = np.stack([decode_bgdt(nttx.lz_decompress(files[f'l_pack{n:02d}.lz5bg'])) for n in STRUCTURE_PACKS])
    med = np.median(ims.astype(int), axis=0)
    common = (np.abs(ims - med).sum(axis=3) < 60).mean(axis=0) > 0.6
    px = decode_bgdt(nttx.lz_decompress(files[f'l_pack{art["box"]:02d}.lz5bg'])).astype(float)
    key = (px == (0, 255, 0)).all(axis=2)
    box = ~key & ~common
    hsv = np.asarray(Image.fromarray(px.astype(np.uint8)).convert('HSV')).copy()
    hsv[box, 0] = np.asarray(Image.fromarray(colour.astype(np.uint8)[None, None]).convert('HSV'))[0, 0, 0]
    px[box] = np.asarray(Image.fromarray(hsv, 'HSV').convert('RGB'))[box]
    x0, y0, x1, y1 = BOX_FACE
    face = background(art, colour, ((x1 - x0) * WORK, (y1 - y0) * WORK))
    for c in art.get('cutouts', []):
        face.alpha_composite(cutout_layer(c, face.size, shade(colour, 1.85)))
    face = np.asarray(face.convert('RGB').resize((x1 - x0, y1 - y0), Image.LANCZOS))
    region = px[y0:y1, x0:x1]
    keep = common[y0:y1, x0:x1]
    region[~keep] = face[~keep]
    return Image.fromarray(np.clip(px, 0, 255).astype(np.uint8))


def key_mask(img):
    return (np.asarray(img.convert('RGB')) == (0, 255, 0)).all(axis=2)


def palette_of(raw):
    b = nttx.blocks(raw)
    n = struct.unpack_from('<I', b['PALT'], 0)[0]
    return [nttx.bgr555(c) for c in struct.unpack_from(f'<{n}H', b['PALT'], 4)]


def quantize(img, pal):
    p = Image.new('P', (1, 1))
    flat = [v for c in pal for v in c]
    p.putpalette(flat + flat[-3:] * (256 - len(pal)))
    return np.asarray(img.convert('RGB').quantize(palette=p, dither=Image.Dither.NONE))


def ntbg(blocks):
    body = b''.join(tag + struct.pack('<I', len(data) + 8) + data for tag, data in blocks)
    return nsbmd.lz11_compress(b'NTBG\xff\xfe\x00\x01' + struct.pack('<I', len(body) + 16) + b'\x10\x00\x02\x00' + body)


def big_file(img, template):
    q = img.convert('RGB').quantize(255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    cols = q.getpalette()[:255 * 3]
    cols += [0] * (255 * 3 - len(cols))
    words = [KEY] + [nttx.to555(tuple(cols[i:i + 3])) for i in range(0, 255 * 3, 3)]
    idx = np.asarray(q).astype(np.uint8) + 1
    idx[key_mask(img)] = 0
    g = nttx.blocks(template)['BGDT']
    head = bytearray(g[:20])
    tw, th = BIG[0] // 8, BIG[1] // 8
    tiles = b''.join(idx[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8].tobytes() for ty in range(th) for tx in range(tw))
    struct.pack_into('<HHIHHHHI', head, 0, 0xff01, 2, tw * th * 2, tw, th, tw, th, len(tiles))
    bgdt = bytes(head) + struct.pack(f'<{tw * th}H', *range(tw * th)) + tiles
    palt = struct.pack('<I256H', 256, *words)
    return ntbg([(b'PALT', palt), (b'BGDT', bgdt)])


def icon_file(img, template, box):
    b = nttx.blocks(template)
    o = b['OBJD']
    tw, th = o[8], o[10]
    head = o[:len(o) - tw * th * 64]
    pal = palette_of(template)
    q = np.minimum(quantize(img.resize(box, Image.LANCZOS), pal[1:]), len(pal) - 2) + 1
    key = np.asarray(Image.fromarray(key_mask(img).astype(np.uint8) * 255).resize(box, Image.BOX)) > 127
    q[key] = 0
    if key.any():
        fill = Image.fromarray(np.pad(key, 1, constant_values=True).astype(np.uint8) * 255).copy()
        ImageDraw.floodfill(fill, (0, 0), 128)
        k = np.asarray(fill) == 128
        edge = ~key & (k[:-2, 1:-1] | k[2:, 1:-1] | k[1:-1, :-2] | k[1:-1, 2:])
        q[edge] = 1 + int(np.argmin([sum(c) for c in pal[1:]]))
    full = np.zeros((th * 8, tw * 8), np.uint8)
    full[:box[1], :box[0]] = q
    tiles = b''.join(full[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8].tobytes() for ty in range(th) for tx in range(tw))
    return ntbg([(b'PALT', b['PALT']), (b'OBJD', head + tiles)])


EXTRA_FILE = 'card_pack_extra.bin'
EXTRA_MAGIC = 0x324b5057  # WPK2


def extra_rows(db, specs):
    rows = []
    by_id = {c.id: c for c in db.cards[1:]}
    for _, spec, members in resolve_all(modspec.CardIndex(db), specs):
        slot = SLOT if spec['id'] >= PK_FIRST else stock_slot(spec['id'])
        for _, rarity, cid in members:
            card = by_id[cid]
            if card.packs[slot] != spec['id']:
                rows.append(cid | spec['id'] << 16 | RARITY[rarity] << 24)
    return sorted(set(rows), key=lambda row: row & 0xffffff)


def structure_deck(index, path):
    from ydc import Deck
    with open(path, encoding='utf-8') as f:
        spec = json.load(f)
    sections = []
    for section in ('main', 'extra', 'side'):
        sections.append([index.deck_id(index.resolve(name, f'{path}: {section}'))
                         for name in spec.get(section, [])])
    if not 40 <= len(sections[0]) <= 60 or len(sections[1]) > 15 or len(sections[2]) > 15:
        raise SystemExit(f'{path}: invalid Main/Extra/Side deck size')
    return Deck(*sections)


def deck_filename(pid):
    return f'mod_sd{pid}.ydc'


def write_header(src, specs, extra=()):
    rows = ''.join(f' \\\n    {{{s["id"]}, {s.get("price", PRICE)}}},' for _, s in specs)
    locks, words = [], []
    for _, spec in specs:
        if spec.get('_unlock'):
            locks.append(f'{{{spec["id"]}, {len(words)}}}, ')
            words += spec['_unlock']
    with open(os.path.join(src, 'w11packs.h'), 'w') as f:
        f.write(f'#define W11_PK_FIRST {PK_FIRST}\n#define W11_PK_MAX {PK_MAX}\n#define W11_PK_SLOT {SLOT}\n'
                f'#define W11_PK_COUNT {len(specs)}\n'
                f'#define W11_PK_TABLE{rows or " {0, 0},"}\n'
                f'#define W11_PK_LOCKS {"".join(locks)}{{0, 0}}\n'
                f'#define W11_PK_LOCK_FLAGS {", ".join(map(str, words or [0]))}\n'
                + ('#define W11_PK_STRUCTURE_COMPARE ' + ''.join(f'cmp r0, #{s["id"]}; bxeq lr; ' for _, s in specs if s.get('structure_deck'))).rstrip() + '\n'
                + '#define W11_PK_DECK_TABLE ' + ''.join('{%d, \"/deck/%s\"}, ' % (s['id'], deck_filename(s['id'])) for _, s in specs if s.get('structure_deck')) + '{0, 0}\n'
                + f'#define W11_PK_EXTRA_COUNT {len(extra)}\n'
                f'#define W11_PK_EXTRA_TABLE {EXTRA_MAGIC}, {len(extra)}'
                + ''.join(f', {r}' for r in extra) + '\n')
    with open(os.path.join(src, 'w11packs.asm'), 'w') as f:
        f.write(f'.definelabel W11_PK_FIRST, {PK_FIRST}\n.definelabel W11_PK_SLOT, {SLOT}\n'
                f'.definelabel W11_PK_COUNT, {len(specs)}\n')


def build(rom, prof, db, paths, mod, src, work):
    specs = load(paths)
    added = [x for x in specs if x[1]['id'] >= PK_FIRST]
    changed = assign(db, specs)
    extra = extra_rows(db, specs)
    write_header(src, added, extra)
    deck_out = os.path.join(mod, 'pac', game.container_dir('Data_arc_pac/deck.pac'))
    for _, spec in added:
        if spec.get('structure_deck'):
            os.makedirs(deck_out, exist_ok=True)
            structure_deck(modspec.CardIndex(db), spec['structure_deck']).save(
                os.path.join(deck_out, deck_filename(spec['id'])))
    text = game.container_files(rom, TEXT_PAC)
    art = game.container_files(rom, ART_PAC)
    out_text = os.path.join(mod, 'pac', game.container_dir(TEXT_PAC))
    out_art = os.path.join(mod, 'pac', game.container_dir(ART_PAC))
    extra_dir = os.path.join(mod, 'pac', game.container_dir(prof['card_db']['container']))
    os.makedirs(extra_dir, exist_ok=True)
    with open(os.path.join(extra_dir, EXTRA_FILE), 'wb') as f:
        f.write(struct.pack(f'<{len(extra) + 2}I', EXTRA_MAGIC, len(extra), *extra))
    pt = carddb.PackText.load(text, prof)
    names = {pt.name(k, pl) for k in ('indx', 'name', 'desc') for pl in pt.langs}
    for d in (out_text, out_art):
        if os.path.isdir(d):
            for n in os.listdir(d):
                if n in names or n.endswith('.lz5bg') and n.split('pack')[-1][:-6].isdigit():
                    os.remove(os.path.join(d, n))
    if not specs:
        return added
    set_text(pt, db, specs)
    os.makedirs(out_text, exist_ok=True)
    texts = 0
    for n, data in pt.files().items():
        if data != text[n]:
            texts += 1
            with open(os.path.join(out_text, n), 'wb') as f:
                f.write(data)
    os.makedirs(out_art, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    drawn = [x for x in specs if 'art' in x[1]]
    for p, s in drawn:
        source = s['art']
        images = [source['image']] if source.get('image') else \
            [source['background']] + [c['image'] for c in source.get('cutouts', [])]
        for f in images:
            if not os.path.isfile(f):
                raise SystemExit(f'{p}: art image {f} not found')
        img = render(s, art)
        pid = s['id']
        out = {f'l_pack{pid:02d}.lz5bg': big_file(img, nttx.lz_decompress(art['l_pack01.lz5bg'])),
               f'pack{pid:02d}.lz5bg': icon_file(img, nttx.lz_decompress(art['pack01.lz5bg']), (32, 64)),
               f's_pack{pid:02d}.lz5bg': icon_file(img, nttx.lz_decompress(art['s_pack01.lz5bg']), (20, 40))}
        for n, data in out.items():
            with open(os.path.join(out_art, n), 'wb') as f:
                f.write(data)
        preview(out, pid, work)
    stock = [s['id'] for _, s in specs if s['id'] < PK_FIRST]
    if stock:
        redrawn = [s['id'] for _, s in drawn if s['id'] < PK_FIRST]
        print(f'stock packs: {len(stock)} specs, {len(changed)} cards with other packs or rarities than WC2011, '
              f'{texts} of {len(names)} pack text files differ from WC2011, new pictures for '
              f'{" ".join(map(str, redrawn)) or "none"}')
    return added


def decode_objd(raw):
    b = nttx.blocks(raw)
    o = b['OBJD']
    tw, th = o[8], o[10]
    pal = np.array(palette_of(raw), np.uint8)
    tiles = np.frombuffer(o[len(o) - tw * th * 64:], np.uint8).reshape(th, tw, 8, 8)
    return pal[tiles.transpose(0, 2, 1, 3).reshape(th * 8, tw * 8)]


def preview(files, pid, work):
    ims = [decode_bgdt(nttx.lz_decompress(files[f'l_pack{pid:02d}.lz5bg'])),
           decode_objd(nttx.lz_decompress(files[f'pack{pid:02d}.lz5bg'])),
           decode_objd(nttx.lz_decompress(files[f's_pack{pid:02d}.lz5bg']))]
    sheet = Image.new('RGB', (sum(i.shape[1] for i in ims) * 4 + 16, 128 * 4), (48, 48, 48))
    x = 0
    for i in ims:
        sheet.paste(Image.fromarray(i).resize((i.shape[1] * 4, i.shape[0] * 4), Image.NEAREST), (x, 0))
        x += i.shape[1] * 4 + 8
    sheet.save(os.path.join(work, f'pack{pid}.png'))


def cmd_render(a):
    rom = game.open_rom(a.rom)
    art = game.container_files(rom, ART_PAC)
    built = a.built
    files = {n: open(os.path.join(built, n), 'rb').read() for n in os.listdir(built) if n.endswith(f'{a.id:02d}.lz5bg')}
    for n in (f'l_pack{a.id:02d}.lz5bg', f'pack{a.id:02d}.lz5bg', f's_pack{a.id:02d}.lz5bg'):
        files.setdefault(n, art.get(n))
        if files[n] is None:
            raise SystemExit(f'{n}: not in {built} nor in the ROM')
    os.makedirs(a.out, exist_ok=True)
    preview(files, a.id, a.out)
    print(os.path.join(a.out, f'pack{a.id}.png'))


def pack_cards(db, pid, extra=()):
    slot = SLOT if pid >= PK_FIRST else stock_slot(pid)
    return {r: {c.id for c in db.cards[1:] if c.packs[slot] == pid and c.pack_rarity[slot] == v}
            | {row & 0xffff for row in extra if (row >> 16) & 0xff == pid and row >> 24 == v}
            for r, v in RARITY.items()}


def slug(name):
    return '_'.join(''.join(ch if ch.isalnum() else ' ' for ch in name.lower()).split())


def name_of(index, cid):
    n = index.name(cid)
    try:
        return n if index.deck_id(index.resolve(n, '')) == cid else f'id:{cid}'
    except SystemExit:
        return f'id:{cid}'


def cmd_dump(a):
    rom = game.open_rom(a.rom)
    prof = game.for_rom(rom)
    db = carddb.CardDB.load(game.container_files(rom, prof['card_db']['container']), prof)
    pt = carddb.PackText.load(game.container_files(rom, TEXT_PAC), prof)
    index = modspec.CardIndex(db)
    os.makedirs(a.out, exist_ok=True)
    for pid in range(STOCK_FIRST, STOCK_LAST + 1):
        spec = {'id': pid, 'name': {l: pt.names[pl][pid] for l, pl in LANGS.items()},
                'desc': {l: pt.descs[pl][pid] for l, pl in LANGS.items()}}
        if pid != ALL_RANDOM:
            got = pack_cards(db, pid)
            spec['cards'] = {r: [name_of(index, c.id) for c in db.cards[1:] if c.id in got[r]] for r in RARITY}
        path = os.path.join(a.out, f'{pid:02d}_{slug(pt.names["eng"][pid])}.json')
        if os.path.exists(path) and not a.force:
            raise SystemExit(f'{path} exists; --force overwrites it')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
            f.write('\n')
    print(f'{STOCK_LAST - STOCK_FIRST + 1} stock packs in {a.out}')


def cmd_diff(a):
    rom = game.open_rom(a.rom)
    prof = game.for_rom(rom)
    bin2 = game.container_files(rom, prof['card_db']['container'])
    text = game.container_files(rom, TEXT_PAC)
    db = carddb.CardDB.load(bin2, prof)
    before = {c.id: (list(c.packs), list(c.pack_rarity), c.rarity) for c in db.cards[1:]}
    pt = carddb.PackText.load(text, prof)
    specs = load(a.spec)
    assign(db, specs)
    set_text(pt, db, specs)
    for c in db.cards[1:]:
        if before[c.id] != (c.packs, c.pack_rarity, c.rarity):
            print(f'card {c.id} {c.names["e"]}: packs {before[c.id][0]} -> {c.packs}, rarities {before[c.id][1]} -> '
                  f'{c.pack_rarity}, card rarity {before[c.id][2]} -> {c.rarity}')
    pack = db.name('pack')
    same = db.files()[pack] == bin2[pack]
    print(f'{pack}: {"identical to the ROM" if same else "differs from the ROM"}')
    for n, data in sorted(pt.files().items()):
        print(f'{n}: {"identical to the ROM" if data == text[n] else "differs from the ROM"}')


def cmd_check(a):
    rom = game.open_rom(a.rom)
    prof = game.for_rom(rom)
    db = carddb.CardDB.load(game.container_files(rom, prof['card_db']['container']), prof)
    extra_blob = game.container_files(rom, prof['card_db']['container']).get(EXTRA_FILE, b'')
    extra = ()
    if extra_blob:
        words = struct.unpack(f'<{len(extra_blob) // 4}I', extra_blob)
        if words[0] != EXTRA_MAGIC or words[1] != len(words) - 2:
            raise SystemExit('invalid added-pack membership extension')
        extra = words[2:]
        if extra and not any(extra_blob in bytes(section.data) for section in rom.loadArm9().sections):
            raise SystemExit('added-pack membership metadata differs from linked runtime table')
    pt = carddb.PackText.load(game.container_files(rom, TEXT_PAC), prof)
    art = game.container_files(rom, ART_PAC)
    ov10 = bytes(rom.loadArm9Overlays([10])[10].data)
    hooked = struct.unpack_from('<I', ov10, 0x0214dfbc - 0x0214c840)[0] >> 24 == 0xeb
    index = modspec.CardIndex(db)
    bad = stock_ok = 0
    for p, s in load(a.spec):
        pid = s['id']
        stock = pid < PK_FIRST
        got = pack_cards(db, pid, extra)
        want = {r: set() for r in RARITY}
        for r, names in s.get('cards', {}).items():
            for n in names:
                ids = index.resolve(n, f'{p}: {r}')
                want[r].add(next((i for i in ids if i in got[r]), index.deck_id(ids)))
        if pid == ALL_RANDOM:
            want = got
        cards = all(got[r] == want[r] for r in RARITY)
        text = all(pt.names[pl][pid] == s['name'][l] and pt.descs[pl][pid] == s['desc'][l] for l, pl in LANGS.items())
        files = all(f'{k}{pid:02d}.lz5bg' in art for k in ('pack', 'l_pack', 's_pack'))
        deck_ok = True
        if s.get('structure_deck'):
            decks = game.container_files(rom, 'Data_arc_pac/deck.pac')
            deck_ok = decks.get(deck_filename(pid)) == structure_deck(index, s['structure_deck']).build()
            # Every added deck must use the native loader and Extra Deck result hooks.
            deck_ok &= struct.unpack_from('<I', ov10, 0x02157dc0 - 0x0214c840)[0] == 0xe51ff004
            for site in (0x02153118, 0x02154158, 0x02154b4c, 0x021555e0):
                deck_ok &= struct.unpack_from('<I', ov10, site - 0x0214c840)[0] >> 24 == 0xeb
        ok = cards and text and files and deck_ok and (hooked or stock)
        bad += not ok
        stock_ok += ok and stock
        if ok and stock and not a.ids:
            continue
        slot = stock_slot(pid) if stock else SLOT
        print(f'pack {pid} {s["name"]["e"]}: {"ok" if ok else "FAIL"}; cards in slot {slot} '
              + ', '.join(f'{r} {len(got[r])}/{len(want[r])}' for r in RARITY)
              + f'{"" if cards else " (other cards)"}; text {"ok" if text else "differs"}; '
              f'pictures {"ok" if files else "missing"}'
              + (f'; native deck {"ok" if deck_ok else "FAIL"}' if s.get('structure_deck') else '')
              + ('' if stock else f'; store hook {"on" if hooked else "off"}'))
        for r in RARITY:
            if got[r] != want[r]:
                print(f'  {r}: in the ROM only {sorted(got[r] - want[r])}, in the spec only {sorted(want[r] - got[r])}')
            if a.ids:
                print(f'  {r}: {" ".join(map(str, sorted(got[r])))}')
    if any(s['id'] < PK_FIRST for _, s in load(a.spec)):
        print(f'stock packs: {stock_ok} ok (cards in card_pack slot 0, or 1 for packs 32-42, and text)')
    raise SystemExit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, epilog='The build runs from `tools/wc2011/w11cards.py build --packs` '
                                 '(make w11cards); dump writes specs, the other commands only read.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('render', help='decode the three pictures of a pack into one PNG (built files, else the ROM\'s)')
    p.add_argument('rom', help='WC2011 EU ROM (BYYP), for the stock pictures')
    p.add_argument('id', type=int, help='pack id, e.g. 97')
    p.add_argument('--built', default=os.path.join('variants', 'dimension-break', 'pac', 'Data_arc_pac', 'pack'))
    p.add_argument('--out', default=os.path.join('build', 'w11packs'))
    p = sub.add_parser('check', help='compare a built ROM with the pack specs: card_pack slots, text, pictures, store hook')
    p.add_argument('rom', help='built ROM, e.g. build/dimension-break.nds')
    p.add_argument('spec', nargs='+', help='pack specs')
    p.add_argument('--ids', action='store_true', help='also list the card ids of each rarity')
    p = sub.add_parser('dump', help='write one spec per stock pack (1-81) from a WC2011 ROM')
    p.add_argument('rom', help='WC2011 EU ROM (BYYP)')
    p.add_argument('out', help='folder, e.g. variants/dimension-break/packs/stock')
    p.add_argument('--force', action='store_true', help='overwrite existing specs')
    p = sub.add_parser('diff', help='apply pack specs to a WC2011 ROM in memory and list what changes: cards, '
                                    'card_pack and pack text bytes')
    p.add_argument('rom', help='WC2011 EU ROM (BYYP)')
    p.add_argument('spec', nargs='+', help='pack specs')
    a = ap.parse_args()
    {'render': cmd_render, 'check': cmd_check, 'dump': cmd_dump, 'diff': cmd_diff}[a.cmd](a)


if __name__ == '__main__':
    main()
