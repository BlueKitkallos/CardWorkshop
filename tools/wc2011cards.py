#!/usr/bin/env python3
import argparse
import collections
import json
import os
import re
import struct
import sys

import ndspy.lz10
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carddb
import game
import nttx

PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'games', 'BYYP.json')
LANGS = 'efgijrs'
FRAMES = {15: ('normal', True), 16: ('effect', True), 17: ('synchro', False), 18: ('synchro_effect', False),
          19: ('synchro_effect', True)}
RACES = {21: 'psychic', 22: 'divine_beast', 23: 'spell', 24: 'trap'}
GENRE_BITS = len(carddb.GENRES)
ART_ENTRY = 2820
FRAME_ART = {'normal': 'nomal', 'effect': 'kouka', 'fusion': 'yugo', 'fusion_effect': 'yugo', 'ritual': 'gisiki',
             'ritual_effect': 'gisiki', 'synchro': 'sync', 'synchro_effect': 'sync', 'token': 'token',
             'spell': 'mahou', 'trap': 'wana', 'toon': 'kouka', 'spirit': 'kouka', 'union': 'kouka',
             'gemini': 'kouka', 'god': 'kouka'}
FRAME_CROP = (4, 6, 92, 134)
ART_AT = (12, 26)
ICON_BOX = (70, 7, 81, 17)
ICON_AT = (70, 4)
OV03 = 0x02141700
TUNER_PAIRS, TUNER_PAIRS_N = 0x02275b04, 23
MIN3, MIN3_N = 0x02275ad8, 21
EXACT, EXACT_N = 0x02275ab8, 16
SPRITE_PACS = [f'Data_arc_pac/duel2d/BattleMonster{n}.pac' for n in (1, 2, 3)]
SPRITE_ZOOM = 4
W10_CODE = 'BYX'
CUTOUT_CACHE = os.path.join('build', 'cache', 'cutouts')
JIS_FIX = str.maketrans({'Ⅰ': 'Ｉ', 'Ⅱ': 'ＩＩ', 'Ⅲ': 'ＩＩＩ', 'Ⅳ': 'ＩＶ', 'Ⅴ': 'Ｖ', 'Ⅵ': 'ＶＩ', 'Ⅶ': 'ＶＩＩ',
                         'Ⅷ': 'ＶＩＩＩ', 'Ⅸ': 'ＩＸ', 'Ⅹ': 'Ｘ'})
STOCK_ICON_CARD = {'light': 'Mystical Elf', 'dark': 'Dark Magician', 'water': 'Fortress Whale',
                   'fire': 'Flame Swordsman', 'earth': 'Giant Soldier of Stone', 'wind': 'Harpie Lady',
                   'divine': 'The Winged Dragon of Ra'}


def palette(palt):
    n = struct.unpack_from('<I', palt, 0)[0]
    return np.array([nttx.bgr555(v) for v in struct.unpack_from(f'<{n}H', palt, 4)], np.uint8)


def bgdt_image(raw):
    b = nttx.blocks(raw)
    g, pal = b['BGDT'], palette(b['PALT'])
    flags, _, msize, w, h, _, _, tsize = struct.unpack_from('<HHIHHHHI', g, 0)
    tmap = struct.unpack_from(f'<{msize // 2}H', g, 20)
    tiles = g[20 + msize:20 + msize + tsize]
    rgb = np.zeros((h * 8, w * 8, 3), np.uint8)
    alpha = np.zeros((h * 8, w * 8), np.uint8)
    for k, e in enumerate(tmap):
        t, (ty, tx) = e & 0x3ff, divmod(k, w)
        if flags & 1:
            px = np.frombuffer(tiles[t * 64:t * 64 + 64], np.uint8).reshape(8, 8).astype(int)
        else:
            nib = np.frombuffer(tiles[t * 32:t * 32 + 32], np.uint8)
            px = np.stack([nib & 15, nib >> 4], 1).reshape(8, 8).astype(int)
            px = np.where(px > 0, px + 16 * (e >> 12), 0)
        if e & 0x400:
            px = px[:, ::-1]
        if e & 0x800:
            px = px[::-1]
        rgb[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = pal[px]
        alpha[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = (px != 0) * 255
    return Image.fromarray(np.dstack([rgb, alpha]), 'RGBA')


def sprite_file(sprites, cid):
    return sprites.get(f'{cid}.lz5bg') or sprites.get(f'{cid}_l.lz5bg')


def battle_sprite(sprites, cid):
    raw = sprite_file(sprites, cid)
    if raw is None:
        return None
    im = bgdt_image(nttx.lz_decompress(raw))
    im = im.crop(im.getchannel('A').getbbox())
    return im.resize((im.width * SPRITE_ZOOM, im.height * SPRITE_ZOOM), Image.NEAREST)


class Wc2010:
    def __init__(self, rom_path):
        rom = game.open_rom(rom_path)
        code = bytes(rom.idCode).decode('latin1')
        if not code.startswith(W10_CODE):
            raise SystemExit(f'{rom_path}: game code {code}, expected {W10_CODE}x (WC2010)')
        self.sprites = {}
        for p in SPRITE_PACS:
            self.sprites.update(game.container_files(rom, p))

    def monster_sprite(self, cid):
        return battle_sprite(self.sprites, cid)


class Wc2011:
    def __init__(self, rom_path):
        if not rom_path or not os.path.isfile(rom_path):
            raise SystemExit(f'WC2011 ROM not found: {rom_path} (set ROM11)')
        rom = game.open_rom(rom_path)
        with open(PROFILE, encoding='utf-8') as f:
            self.db = carddb.CardDB.load(game.container_files(rom, 'Data_arc_pac/bin2.pac'), json.load(f))
        self.index = {c.id: i for i, c in enumerate(self.db.cards) if i}
        self.duel2d = game.container_files(rom, 'Data_arc_pac/duel2d.pac')
        self.art = game.container_files(rom, 'Data_arc_pac/card.pac')['card_5bg64x64.bin']
        self.sprites = {}
        for p in SPRITE_PACS:
            self.sprites.update(game.container_files(rom, p))
        ov03 = bytes(rom.loadArm9Overlays([3])[3].data)
        u16s = lambda a, n: struct.unpack_from(f'<{n}H', ov03, a - OV03)
        pairs = u16s(TUNER_PAIRS, 2 * TUNER_PAIRS_N)
        self.tuner_of = dict(zip(pairs[0::2], pairs[1::2]))
        self.min3 = set(u16s(MIN3, MIN3_N))
        self.exact = set(u16s(EXACT, EXACT_N))

    def synchro_fields(self, cid, where):
        out = {}
        if cid in self.tuner_of:
            t = self.tuner_of[cid]
            if t not in self.index:
                raise SystemExit(f'{where}: its Tuner (WC2011 id {t}) is not a card')
            out['synchro_tuner'] = self.db.cards[self.index[t]].names['e']
        if cid in self.min3:
            out['synchro_materials'] = 3
        if cid in self.exact:
            out['synchro_exact'] = True
        return out

    def card(self, konami_id, where):
        if konami_id not in self.index:
            raise SystemExit(f'{where}: no WC2011 card has id {konami_id}')
        return self.index[konami_id], self.db.cards[self.index[konami_id]]

    def art_image(self, i):
        return bgdt_image(self.art[i * ART_ENTRY:(i + 1) * ART_ENTRY])

    def monster_sprite(self, cid):
        return battle_sprite(self.sprites, cid)

    def frame_image(self, frame):
        return bgdt_image(nttx.lz_decompress(self.duel2d[f'card_frame128_{FRAME_ART[frame]}.lz5bg'])).crop(FRAME_CROP)


def spec_fields(c, where):
    out = {'password': c.password}
    if c.frame in FRAMES:
        out['frame'], tuner = FRAMES[c.frame]
        if tuner:
            out['tuner'] = True
    elif c.frame in carddb.FRAMES and c.frame != 12:
        out['frame'] = carddb.FRAMES[c.frame]
    else:
        raise SystemExit(f'{where}: WC2011 frame {c.frame} has no WC2008 equivalent')
    race = RACES.get(c.race, carddb.RACES.get(c.race))
    if out['frame'] in ('spell', 'trap'):
        out['icon'] = carddb.ICONS[c.icon]
    else:
        out.update(attribute=carddb.ATTRIBUTES[c.attribute], race=race, level=c.level, atk=c.atk, def_=c.def_)
    out['genres'] = [carddb.GENRES[b] for b in range(GENRE_BITS) if c.genre >> b & 1]
    out['kana'] = c.kana.to_bytes(2, 'big').decode('cp932') if c.kana else 'あ'
    out['names'] = {l: c.names[l].translate(JIS_FIX) if l in 'jr' else c.names[l] for l in LANGS}
    out['descs'] = {l: c.descs[l].translate(JIS_FIX) if l in 'jr' else c.descs[l] for l in LANGS}
    return out


def stock_db(extracted):
    return carddb.CardDB.load(os.path.join(extracted, 'Data_arc_pac', 'bin2'))


def stock_icons(extracted, db):
    d = os.path.join(extracted, 'Data_arc_pac', 'card')
    arts, _ = nttx.entries(os.path.join(d, 'card_5tx128.bin'), os.path.join(d, 'card_5tx128_idx.bin'))
    out = {}
    for attr, name in STOCK_ICON_CARD.items():
        i = next(k for k, c in enumerate(db.cards) if k and c.names['e'] == name)
        tex = nttx.decode(ndspy.lz10.decompress(arts[i])).convert('RGBA')
        out[attr] = tex.crop((ICON_BOX[0] + 20, ICON_BOX[1], ICON_BOX[2] + 20, ICON_BOX[3]))
    return out


def card_image(w11, idx, fields, icons):
    img = w11.frame_image(fields['frame'])
    img.alpha_composite(w11.art_image(idx).convert('RGBA'), ART_AT)
    draw = ImageDraw.Draw(img)
    big = ImageFont.load_default(24)
    name = fields['names']['e']
    box = big.getbbox(name)
    text = Image.new('RGBA', (box[2] + 2, 30), (0, 0, 0, 0))
    ImageDraw.Draw(text).text((1, 0), name, font=big, fill=(20, 20, 20, 255))
    width = min(56, max(1, text.width * 9 // 30))
    img.alpha_composite(text.resize((width, 9), Image.LANCZOS), (8, 6))
    if 'attribute' in fields and fields['attribute'] in icons:
        img.alpha_composite(icons[fields['attribute']], ICON_AT)
    for k in range(fields.get('level', 0)):
        x = 74 - 6 * k
        draw.ellipse((x, 17, x + 5, 22), fill=(222, 64, 24), outline=(250, 196, 60))
    return img.convert('RGB')


def pool_cards(w11, stock, spec, where):
    stock_ids = {c.id for c in stock.cards[1:]}
    stock_names = {c.names['e'] for c in stock.cards[1:]}
    over = {}
    for o in spec.get('cards', []):
        if 'konami_id' not in o:
            raise SystemExit(f'{where}: {o.get("name")}: an entry of the WC2011 pool needs its konami_id')
        over[o['konami_id']] = o
    out = []
    for c in w11.db.cards[1:]:
        if c.id in stock_ids:
            continue
        e = {'name': c.names['e'], 'konami_id': c.id, 'source': 'wc2011'}
        if c.names['e'] in stock_names:
            e.update(name=f"{c.names['e']} ({c.id})", alt_art=True)
        e.update(over.pop(c.id, {}))
        out.append(e)
    if over:
        raise SystemExit(f'{where}: konami_id {next(iter(over))} is not a WC2011 card that WC2008 lacks')
    return out


def md_name(name):
    return re.sub(r'[^0-9A-Za-z]', '', re.sub(r' \(\d+\)$', '', name))


def is_monster(frame):
    return frame not in ('spell', 'trap')


def cutout(w11, idx, c, name, cache, w10=None):
    for game_, tag in ((w10, 'wc2010'), (w11, 'wc2011')):
        im = game_ and game_.monster_sprite(c.id)
        if im is not None:
            return im, tag
    path = os.path.join(cache, md_name(name) + '.png')
    if os.path.isfile(path):
        return Image.open(path).convert('RGBA'), 'master_duel'
    return w11.art_image(idx).convert('RGBA'), 'art'


def verified_at_import(fields):
    return fields['frame'] in ('normal', 'token')


def expand(spec_path, w11, stock, out_dir, icons, scans, cutouts=CUTOUT_CACHE, w10=None):
    with open(spec_path, encoding='utf-8') as f:
        spec = json.load(f)
    pool = spec.pop('source', None) == 'wc2011'
    if pool:
        spec['cards'] = pool_cards(w11, stock, spec, spec_path)
        spec['expanded_from'] = os.path.relpath(spec_path)
        verified = set(spec.pop('verified', []))
    art = os.path.join(out_dir, 'art')
    os.makedirs(os.path.join(art, 'cards'), exist_ok=True)
    os.makedirs(os.path.join(art, 'cutouts'), exist_ok=True)
    cards, status, scanned, sources = [], [], 0, collections.Counter()
    import effectport
    ported = {c['id']: c for c in effectport.load_port_json()['cards']} if pool else {}
    if pool:
        verified |= {cid for cid, c in ported.items() if c.get('verified')}
    for sc in spec.get('cards', []):
        if sc.get('source') != 'wc2011':
            cards.append(sc)
            continue
        where = f'{spec_path}: {sc.get("name")}'
        if 'konami_id' not in sc:
            raise SystemExit(f'{where}: a WC2011 card needs its konami_id')
        idx, c = w11.card(sc['konami_id'], where)
        if c.names['e'] != sc['name'] and not sc.get('alt_art'):
            raise SystemExit(f'{where}: WC2011 id {sc["konami_id"]} is {c.names["e"]!r}')
        fields = spec_fields(c, where)
        if fields['frame'].startswith('synchro'):
            fields.update(w11.synchro_fields(c.id, where))
        full = dict(fields, **sc)
        full.setdefault('rarity', 'common')
        scan = os.path.join(scans, f'{c.password}.jpg')
        if c.password and not sc.get('alt_art') and os.path.isfile(scan):
            full['card_image'] = os.path.relpath(scan, art)
            scanned += 1
        else:
            full['card_image'] = f'cards/{c.id}.jpg'
            card_image(w11, idx, fields, icons).save(os.path.join(art, full['card_image']), quality=95)
        if is_monster(fields['frame']):
            im, src = cutout(w11, idx, c, sc['name'], cutouts, w10)
            full['cutout'] = f'cutouts/{c.id}.png'
            im.save(os.path.join(art, full['cutout']))
            sources[src] += 1
        if pool:
            effect = ai = 'no' if c.descs['e'] and fields['frame'] not in ('normal', 'token') else '-'
            port = ported.get(c.id)
            if port:
                effect = 'stock' if port.get('stock') else 'rows'
                ai = 'stock' if port.get('stock_ai') else 'rows' if port.get('ai') else 'no'
            full['verified'] = verified_at_import(fields) or sc['name'] in verified or c.id in verified
            status.append((c.id, sc['name'], fields['frame'], effect, ai, 'yes' if full['verified'] else 'no',
                           src if is_monster(fields['frame']) else '-'))
        else:
            full.setdefault('id', sc['konami_id'])
        cards.append(full)
    if pool:
        unknown = verified - {s[1] for s in status} - {s[0] for s in status}
        if unknown:
            raise SystemExit(f'{spec_path}: verified: {sorted(unknown, key=str)[0]!r} is not a card of the WC2011 pool')
        name = os.path.splitext(os.path.basename(spec_path))[0]
        with open(os.path.join(out_dir, f'{name}_status.tsv'), 'w', encoding='utf-8') as f:
            f.write('konami_id\tname\tframe\teffect\tai\tverified\tcutout\n')
            f.writelines('\t'.join(map(str, s)) + '\n' for s in status)
        print(f'{spec_path}: {len(status)} WC2011 cards, {sum(s[5] == "yes" for s in status)} verified, '
              f'{scanned} pictures from card images in {scans}, {len(status) - scanned} composed; cutouts: '
              f'{sources["wc2010"]} WC2010 sprites, {sources["wc2011"]} WC2011 sprites, {sources["master_duel"]} Master Duel images in {cutouts}, '
              f'{sources["art"]} whole card art')
    spec['cards'] = cards
    out = os.path.join(out_dir, 'cards', os.path.basename(spec_path))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    return out


def main():
    ap = argparse.ArgumentParser(
        description='Expand the WC2011 cards of card specs: an entry {"name", "konami_id", "source": "wc2011"} gets '
                    'its stats, frame, Tuner flag, names and texts in every language from the WC2011 ROM, its card picture '
                    'from the full card image <passcode>.jpg in --scans (filled by tools/fetch_cards.py) or, without '
                    'one (passcode 0, alternate arts), composed from WC2011\'s blank frame and card art, and for a monster a '
                    'field-sprite cutout <out>/art/cutouts/<konami_id>.png: WC2010\'s monster sprite (--rom10, '
                    'duel2d/BattleMonster*.pac, 144x208, most monsters whole), else WC2011\'s (256x96, many cut at '
                    'the waist), else the Master Duel image <CardName>.png in --cutouts (filled by '
                    'tools/fetch_cards.py), else the whole WC2011 art. A spec with "source": "wc2011" at its top level is the whole pool: every WC2011 card '
                    'WC2008 lacks, its "cards" entries (by konami_id) override fields, its "verified" list (names or '
                    'Konami ids) and "verified": true on a card\'s entry in mod/effects/*.json clear cards for packs, '
                    'decks and gifts; Normal monsters and tokens are verified at '
                    'import, and <out>/<spec>_status.tsv lists every card. Writes '
                    '<out>/cards/<spec>.json and <out>/art/{cards,cutouts}; nothing from the ROM is meant to be '
                    'committed.')
    ap.add_argument('rom11', help='WC2011 ROM (game code BYYP)')
    ap.add_argument('extracted', help='extracted WC2008 folder (attribute icons of the card picture)')
    ap.add_argument('out', help='output folder, e.g. build/wc2011')
    ap.add_argument('spec', nargs='+')
    ap.add_argument('--scans', default=os.path.join('build', 'cache', 'cards'),
                    help='full card images <passcode>.jpg, filled by tools/fetch_cards.py (default: %(default)s)')
    ap.add_argument('--rom10', help='WC2010 ROM (game code BYX*, .nds or a .zip holding it): its monster sprites '
                                    'come before WC2011\'s; a missing file only prints a note')
    ap.add_argument('--cutouts', default=CUTOUT_CACHE,
                    help='Master Duel monster images <CardName>.png, filled by tools/fetch_cards.py (default: %(default)s)')
    a = ap.parse_args()
    w11 = Wc2011(a.rom11)
    w10 = None
    if a.rom10 and os.path.isfile(a.rom10):
        w10 = Wc2010(a.rom10)
    elif a.rom10:
        print(f'WC2010 ROM not found: {a.rom10}; monster cutouts from WC2011 only')
    stock = stock_db(a.extracted)
    icons = stock_icons(a.extracted, stock)
    for p in a.spec:
        print(expand(p, w11, stock, a.out, icons, a.scans, a.cutouts, w10))


if __name__ == '__main__':
    main()
