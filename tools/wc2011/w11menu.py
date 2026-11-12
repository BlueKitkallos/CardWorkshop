#!/usr/bin/env python3
"""Build the Shop main-menu assets and labels from the user's WC2011 EU ROM."""
import argparse
from collections import Counter
from pathlib import Path
import struct
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
import bustup
import carddb
import game
import nttx
import ndspy.lz10
from PIL import Image, ImageDraw, ImageFont
import w11gfx
import w11lang
import w11sprites

PAC = 'Data_arc_pac/MainMenu.pac'
LABELS = {
    'SHOP': 'Shop', 'CARD_SHOP': 'Card Shop',
    'SHOP_DESC': 'Purchase booster packs or use a card password.',
    'LEGACY': 'Legacy Wi-Fi',
    'LEGACY_DESC': 'Open the original Wi-Fi communications menu.',
    'RESET': 'Soft Reset Story Mode',
    'RESET_ASK': 'Reset the story to chapter 0?\nYou will keep your cards and\ncontent unlocked.',
    'RESET_CONFIRM': 'Your story progress will be\nerased. Reset anyway?',
    'RESET_QUIZ': 'I understand you want to reset.\nPlease indicate the ATK of\nCeltic Guardian to confirm.',
    'QUIZ_1200': '1200', 'QUIZ_1500': '1500', 'QUIZ_1400': '1400', 'QUIZ_1800': '1800',
    'BONUS_KAIBA': 'Winning against Seto Kaiba',
    'BONUS_KAIBA_UNKNOWN': 'Winning against ???',
    'RATING_1000': 'Rating 1000 reached',
    'RATING_1500': 'Rating 1500 reached',
    'RATING_2000': 'Rating 2000 reached',
    'RATING_2500': 'Rating 2500 reached',
    'RATING_3000': 'Rating 3000 reached',
    'RATING_3500': 'Rating 3500 reached',
}
TRANSLATIONS = {
    'SHOP': {'f': 'Magasin', 'g': 'Shop', 'i': 'Negozio', 's': 'Tienda'},
    'CARD_SHOP': {'f': 'Magasin de cartes', 'g': 'Karten-Shop', 'i': 'Negozio carte', 's': 'Tienda de cartas'},
    'SHOP_DESC': {'f': 'Acheter des boosters ou utiliser un mot de passe de carte.',
                  'g': 'Kaufe Booster-Packs oder gib ein Kartenpasswort ein.',
                  'i': 'Acquista buste o usa la password di una carta.',
                  's': 'Compra packs de cartas o usa una contraseña de carta.'},
    'LEGACY': {'f': "Wi-Fi d'origine", 'g': 'Klassisches Wi-Fi', 'i': 'Wi-Fi classica', 's': 'Wi-Fi clásico'},
    'LEGACY_DESC': {'f': "Ouvrir le menu de communication Wi-Fi d'origine.",
                    'g': 'Öffne das ursprüngliche Wi-Fi-Kommunikationsmenü.',
                    'i': 'Apri il menu originale delle comunicazioni Wi-Fi.',
                    's': 'Abre el menú original de comunicaciones Wi-Fi.'},
    'RESET': {},
    'RESET_ASK': {},
    'RESET_CONFIRM': {},
    'RESET_QUIZ': {},
    'QUIZ_1200': {}, 'QUIZ_1500': {}, 'QUIZ_1400': {}, 'QUIZ_1800': {},
    'BONUS_KAIBA': {'f': 'Victoire contre Seto Kaiba', 'g': 'Sieg gegen Seto Kaiba', 'i': 'Vittoria contro Seto Kaiba',
                    's': 'Victoria contra Seto Kaiba'},
    'BONUS_KAIBA_UNKNOWN': {'f': 'Victoire contre ???', 'g': 'Sieg gegen ???', 'i': 'Vittoria contro ???',
                            's': 'Victoria contra ???'},
    'RATING_1000': {'f': 'Évaluation 1000 atteinte', 'g': 'Bewertung 1000 erreicht', 'i': 'Valutazione 1000 raggiunta',
                    's': 'Clasificación 1000 alcanzada'},
    'RATING_1500': {'f': 'Évaluation 1500 atteinte', 'g': 'Bewertung 1500 erreicht', 'i': 'Valutazione 1500 raggiunta',
                    's': 'Clasificación 1500 alcanzada'},
    'RATING_2000': {'f': 'Évaluation 2000 atteinte', 'g': 'Bewertung 2000 erreicht', 'i': 'Valutazione 2000 raggiunta',
                    's': 'Clasificación 2000 alcanzada'},
    'RATING_2500': {'f': 'Évaluation 2500 atteinte', 'g': 'Bewertung 2500 erreicht', 'i': 'Valutazione 2500 raggiunta',
                    's': 'Clasificación 2500 alcanzada'},
    'RATING_3000': {'f': 'Évaluation 3000 atteinte', 'g': 'Bewertung 3000 erreicht', 'i': 'Valutazione 3000 raggiunta',
                    's': 'Clasificación 3000 alcanzada'},
    'RATING_3500': {'f': 'Évaluation 3500 atteinte', 'g': 'Bewertung 3500 erreicht', 'i': 'Valutazione 3500 raggiunta',
                    's': 'Clasificación 3500 alcanzada'},
}
GAME_LABELS = ['SHOP', 'CARD_SHOP', 'SHOP_DESC', 'RESET', 'RESET_ASK', 'RESET_CONFIRM', 'RESET_QUIZ',
               'QUIZ_1200', 'QUIZ_1500', 'QUIZ_1400', 'QUIZ_1800', 'BONUS_KAIBA',
               'BONUS_KAIBA_UNKNOWN', 'RATING_1000', 'RATING_1500', 'RATING_2000', 'RATING_2500', 'RATING_3000',
               'RATING_3500']
WORKSHOP_LABELS = ['SHOP', 'CARD_SHOP', 'SHOP_DESC', 'LEGACY', 'LEGACY_DESC']


def render(fs, stem, cell):
    get = lambda ext: nttx.lz_decompress(fs[f'{stem}.lz{ext}'])
    tiles, four = w11gfx.tiles(get('ncgr'))
    pal = w11gfx.palette(get('nclr'))
    im = Image.new('RGBA', (256, 64))
    for x, y, w, h, tile, bank, hf, vf in reversed(list(w11gfx.oams(get('ncer'), cell))):
        first = tile * 128 // (32 if four else 64)
        for dy in range(h):
            for dx in range(w):
                v = tiles[first + dy // 8 * (w // 8) + dx // 8][dy % 8 * 8 + dx % 8]
                if v:
                    xx, yy = x + (w - 1 - dx if hf else dx), y + (h - 1 - dy if vf else dy)
                    if 0 <= xx < im.width and 0 <= yy < im.height:
                        im.putpixel((xx, yy), pal[bank * 16 + v if four else v] + (255,))
    return im


def paint(fs, stem, edits):
    """Encode edited cells in their existing native tiles, palette and OAM layout."""
    raw = bytearray(nttx.lz_decompress(fs[f'{stem}.lzncgr']))
    sec = bustup.section(raw, b'RAHC')
    size, off = struct.unpack_from('<II', raw, sec + 0x18)
    start = sec + 8 + off
    four = struct.unpack_from('<I', raw, sec + 12)[0] == 3
    pal = w11gfx.palette(nttx.lz_decompress(fs[f'{stem}.lznclr']))
    nc = nttx.lz_decompress(fs[f'{stem}.lzncer'])
    cache = {}
    for cell, im in edits.items():
        for x, y, w, h, tile, bank, hf, vf in w11gfx.oams(nc, cell):
            for dy in range(h):
                for dx in range(w):
                    xx, yy = x + (w - 1 - dx if hf else dx), y + (h - 1 - dy if vf else dy)
                    color = im.getpixel((xx, yy))
                    key = (bank, color)
                    if key not in cache:
                        choices = range(bank * 16 + 1, bank * 16 + 16) if four else range(1, len(pal))
                        cache[key] = 0 if color[3] == 0 else min(choices, key=lambda k: sum((pal[k][c] - color[c]) ** 2 for c in range(3))) - (bank * 16 if four and color[3] else 0)
                    v = cache[key]
                    pixel = (dy // 8 * (w // 8) + dx // 8) * 64 + dy % 8 * 8 + dx % 8
                    pos = start + tile * 128 + pixel // (2 if four else 1)
                    assert pos < start + size
                    if four:
                        shift = (pixel & 1) * 4
                        raw[pos] = (raw[pos] & ~(15 << shift)) | v << shift
                    else:
                        raw[pos] = v
    return ndspy.lz10.compress(raw)


def shop_icon(fs11):
    source = Image.open(Path(__file__).resolve().parents[2] / 'mod/art/ui/shop-building-v3.png').convert('RGBA')
    source.putalpha(source.getchannel('A').point(lambda a: a if a >= 16 else 0))
    source = source.crop(source.getbbox())
    source.thumbnail((33, 33), Image.Resampling.LANCZOS)
    weights = [(x + .5, y + .5, source.getpixel((x, y))[3])
               for y in range(source.height) for x in range(source.width)]
    mass = sum(a for _, _, a in weights)
    center = tuple(sum(p[i] * p[2] for p in weights) / mass for i in (0, 1))
    # The 49px cell includes the drop shadow; the button face is centred at (22,22).
    position = tuple(round(22 - c) for c in center)
    edits = {}
    for target in [7, 8]:
        native = render(fs11, 'sita_menu', target)
        peers = [render(fs11, 'sita_menu', cell)
                 for cell in range(3 if target == 7 else 4, 19, 2)]
        for y in range(6, 39):
            colors = Counter(c for im in peers for x in range(8, 42)
                             for c in [im.getpixel((x, y))]
                             if c[3] and c[0] >= 130 and c[1] >= 90
                             and c[0] >= c[1] and c[2] < c[1] * .9)
            if not colors:
                continue
            color = colors.most_common(1)[0][0]
            for x in range(6, 38):
                native.putpixel((x, y), color)
        native.alpha_composite(source, position)
        edits[target] = native
    return edits


def shop_header(fs, stem):
    im = render(fs, stem, 1)
    for y in range(3, 24):
        for x in range(28, 230):
            im.putpixel((x, y), im.getpixel((29, y)))
    path = str(Path(__file__).resolve().parents[2] / 'mod/art/fonts/cinzel/Cinzel.ttf')
    first = ImageFont.truetype(path, 26)
    rest = ImageFont.truetype(path, 20)
    for font in (first, rest):
        font.set_variation_by_axes([700])
    width = first.getlength('S') + rest.getlength('HOP')
    x = (256 - width) / 2
    mask = Image.new('L', im.size)
    md = ImageDraw.Draw(mask)
    draw = ImageDraw.Draw(im)
    for text, font in [('S', first), ('HOP', rest)]:
        draw.text((x + 1, 23), text, font=font, anchor='ls', fill=(16, 0, 0),
                  stroke_width=0, stroke_fill=(16, 0, 0))
        draw.text((x, 22), text, font=font, anchor='ls', fill=(98, 0, 0),
                  stroke_width=1, stroke_fill=(255, 230, 0))
        md.text((x, 22), text, font=font, anchor='ls', fill=255)
        x += font.getlength(text)
    for y in range(28):
        color = (16, 0, 0) if y < 17 else (98, 0, 0)
        for x in range(256):
            alpha = mask.getpixel((x, y))
            if alpha:
                before = im.getpixel((x, y))
                im.putpixel((x, y), tuple((color[i] * alpha + before[i] * (255 - alpha)) // 255 for i in range(3)) + (255,))
    return im


def shop_illustration(fs11):
    # Palette bank zero is shared with the gold BG: a new palette recolours the whole panel.
    template = nttx.blocks(nttx.lz_decompress(fs11['ue_mainimage02.lz5bg']))
    palette = struct.unpack_from('<256H', template['PALT'], 4)
    rgb = [nttx.bgr555(c) for c in palette]
    source = Image.open(Path(__file__).resolve().parents[2] / 'mod/art/ui/shop-building-v3.png').convert('RGBA')
    source.putalpha(source.getchannel('A').point(lambda a: a if a >= 16 else 0))
    source = source.crop(source.getbbox())
    source.thumbnail((96, 72), Image.Resampling.LANCZOS)
    image = Image.new('RGBA', (256, 88))
    image.alpha_composite(source, ((256 - source.width) // 2, (88 - source.height) // 2))
    cache = {}
    def pixel(x, y):
        color = image.getpixel((x, y))
        if color[3] < 128:
            return 0
        key = color[:3]
        if key not in cache:
            cache[key] = min(range(1, 256), key=lambda i: sum((rgb[i][j] - key[j]) ** 2 for j in range(3)))
        return cache[key]
    tw, th = image.width // 8, image.height // 8
    tiles = bytes(pixel(tx * 8 + x, ty * 8 + y)
                  for ty in range(th) for tx in range(tw) for y in range(8) for x in range(8))
    head = struct.pack('<HHIHHHHI', 0xff01, 2, tw * th * 2, tw, th, tw, th, len(tiles))
    bg = head + struct.pack(f'<{tw * th}H', *range(tw * th)) + tiles
    body = b''.join(tag + struct.pack('<I', len(data) + 8) + data for tag, data in
                    [(b'PALT', struct.pack('<I256H', 256, *palette)), (b'BGDT', bg)])
    return ndspy.lz10.compress(b'NTBG\xff\xfe\x00\x01' + struct.pack('<I', len(body) + 16) + b'\x10\x00\x02\x00' + body)


def assets(fs11):
    files = {'sita_menu.lzncgr': paint(fs11, 'sita_menu', shop_icon(fs11)),
             'ue_mainimage13.lz5bg': shop_illustration(fs11)}
    for lang in 'efgijks':
        stem = f'ue_title_{lang}'
        files[f'{stem}.lzncgr'] = paint(fs11, stem, {1: shop_header(fs11, stem)})
    return files


def label_texts():
    return {k: {'e': LABELS[k], **TRANSLATIONS[k]} for k in WORKSHOP_LABELS}


def build(target, variant, translations=None):
    if translations:
        w11lang.load(translations, 'build/w11menu')
    game.require(target, 'BYYP', 'w11menu target')
    r11 = game.open_rom(target)
    fs11 = game.container_files(r11, PAC)
    out = Path(variant) / 'pac/Data_arc_pac/MainMenu'
    out.mkdir(parents=True, exist_ok=True)
    for name, data in assets(fs11).items():
        (out / name).write_bytes(data)
    fs = game.container_files(r11, 'Data_arc_pac/bin2.pac')
    text_out = Path(variant) / 'pac/Data_arc_pac/bin2'
    text_out.mkdir(parents=True, exist_ok=True)
    ids = None
    rerun = False
    for lang in 'efgijksr':
        paths = [text_out / f'game_{kind}_{lang}.bin' for kind in ['indx', 'text']]
        idx, text = [bytes(p.read_bytes() if p.exists() else fs[p.name]) for p in paths]
        prefix, strings = carddb.read_strtab(idx, text, 1, 0, lang)
        values = [w11lang.tr(LABELS[k], lang, 'menu', {'at': f'w11menu {k}'}) for k in GAME_LABELS]
        if lang == 'e':
            rerun = strings[-len(values):] == values
        if rerun:
            strings = strings[:-len(values)]
        start = len(strings)
        text, offs = carddb.build_strtab(prefix, strings + values, lang)
        idx = carddb.write_index([offs])
        carddb.read_strtab(idx, text, 1, 0, lang)
        current = dict(zip(GAME_LABELS, range(start, start + len(GAME_LABELS))))
        if ids is None:
            ids = current
        assert ids == current, 'language string tables have different lengths'
        for p, data in zip(paths, [idx, text]):
            p.write_bytes(data)
    header = Path(variant) / 'src/menu11.h'
    header.write_text('/* Generated by tools/wc2011/w11menu.py. */\n' + ''.join(f'#define W11MENU_{key} {value}\n' for key, value in ids.items()))
    preview = Path('build/w11menu')
    preview.mkdir(parents=True, exist_ok=True)
    built = dict(fs11)
    built.update({p.name: p.read_bytes() for p in out.iterdir()})
    images = [render(built, 'sita_menu', c).crop((0, 0, 52, 52)) for c in [7, 8]]
    images.append(render(built, 'ue_title_e', 1).crop((0, 0, 256, 32)))
    sheet = Image.new('RGBA', (320, 120), '#777777')
    sheet.alpha_composite(images[0], (10, 10)); sheet.alpha_composite(images[1], (70, 10)); sheet.alpha_composite(images[2], (10, 75))
    sheet.resize((960, 360), Image.Resampling.NEAREST).save(preview / 'shop-assets.png')
    grid = Image.new('RGBA', (256, 144), '#a69850')
    for i, cell in enumerate(range(4, 19, 2)):
        icon = render(built, 'sita_menu', cell).crop((0, 0, 52, 52))
        grid.alpha_composite(icon, (8 + (i % 4) * 62, 8 + (i // 4) * 68))
    grid.resize((1024, 576), Image.Resampling.NEAREST).save(preview / 'icon-grid.png')
    panels = Image.new('RGBA', (512, 272), '#a69850')
    pd = ImageDraw.Draw(panels)
    examples = [('Shop revision', 13, 1, built), ('User Settings', 12, 2, fs11),
                ('Duelist Menu', 4, 3, fs11), ('Tutorial', 6, 5, fs11)]
    for i, (label, picture, heading, files) in enumerate(examples):
        x, y = i % 2 * 256, i // 2 * 136
        pd.text((x + 4, y + 2), label, fill='white')
        bg = w11sprites.bg5(fs11, 'ue_bg').crop((0, 0, 256, 88))
        bg.alpha_composite(w11sprites.bg5(files, f'ue_mainimage{picture:02}'))
        panels.alpha_composite(render(files, 'ue_title_e', heading).crop((0, 0, 256, 32)), (x, y + 16))
        panels.alpha_composite(bg, (x, y + 48))
    panels.resize((1536, 816), Image.Resampling.NEAREST).save(preview / 'panel-comparison.png')
    print(f'Shop menu assets: {out}; labels {ids}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('target', help='WC2011 EU ROM (BYYP)')
    ap.add_argument('variant', help='variant folder, e.g. variants/dimension-break')
    ap.add_argument('--translations', help='translation tables (<lang>.json) for the labels; the labels they lack '
                    'go to build/w11menu/translations-needed.json')
    args = ap.parse_args()
    build(args.target, args.variant, args.translations)
