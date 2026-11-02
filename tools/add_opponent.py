import os
import struct
import sys
from collections import Counter

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bustup
import carddb
import modspec
from ydc import Deck

TALK_LANGS = 'efgijks'
TALK_ENC = {'j': 'cp932', 'k': 'euc-kr'}
TALK_LINES = 28
TALK_MOMENTS = ('field_spell', 'effect_fusion', 'mill', 'summon')
MAIN_MAX, EXTRA_MAX, SIDE_MAX = 160, 60, 15
DECK_NAME_BASE = 0x8bd
CHAR_NAME_TOP = 2999
PAIR_COUNT = 0xfd
ORG = {'orgchr.pac': (0xa00, 64, 40), 'orgchr_tag.pac': (0x500, 32, 40)}
ORG_LAST = 218
ORG_FIRST = 220
CHAR_MIN, CHAR_MAX = 220, 0xfff
STORY_CHARS = (0xe0, 0xfe)
TALK_SET_MAX = 254


def rd(path):
    with open(path, 'rb') as f:
        return f.read()


def wr(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def layered(name, ext_dir, mod_dir):
    p = os.path.join(mod_dir, name)
    return rd(p) if os.path.exists(p) else rd(os.path.join(ext_dir, name))


def build_deck(spec_deck, db, limits):
    index = modspec.CardIndex(db)
    deck = modspec.load_json(spec_deck)
    out = {}
    for sec in ('main', 'extra', 'side'):
        lst = []
        for name, n in deck.get(sec, {}).items():
            lst += [index.resolve(name, spec_deck)[0]] * n
        out[sec] = lst
    if not 40 <= len(out['main']) <= MAIN_MAX or len(out['extra']) > EXTRA_MAX or len(out['side']) > SIDE_MAX:
        raise SystemExit(f"{spec_deck}: {len(out['main'])}/{len(out['extra'])}/{len(out['side'])} cards")
    total = {}
    for lst in out.values():
        for cid in lst:
            total[cid] = total.get(cid, 0) + 1
    names = {c.id: c.names['e'] for c in db.cards[1:]}
    for cid, n in total.items():
        if n > min(3, limits.get(cid, 3)):
            raise SystemExit(f'{spec_deck}: {n} x {names[cid]}, banlist allows {limits.get(cid, 3)}')
    return Deck(out['main'], out['extra'], out['side'])


def banlist_limits(data):
    n = struct.unpack_from('<H', data, 0)[0]
    return {v & 0x3fff: v >> 14 for v in struct.unpack_from(f'<{n}H', data, 8)}


def talk_extra(spec, db):
    ids = {c.names['e']: c.id for c in db.cards[1:]}
    out = []
    for key, texts in spec.items():
        moment, _, card = key.partition(':')
        if moment not in TALK_MOMENTS or bool(card) != (moment == 'summon') or (card and card not in ids):
            raise SystemExit(f'talk_extra: bad moment {key!r} (moments: {", ".join(TALK_MOMENTS)}; summon:<card name>)')
        out.append((moment, ids.get(card, 0), texts))
    return out


def icon_palette(E):
    import ndspy.lz10
    d = ndspy.lz10.decompress(rd(os.path.join(E, 'duel2d', 'MOBJ', 'lp_bar.lz5bg')))
    p = d.find(b'PALT')
    n = struct.unpack_from('<I', d, p + 8)[0]
    return [bustup.rgb555(v) for v in struct.unpack_from(f'<{n}H', d, p + 12)]


def icon_backgrounds(data, size, w, h):
    face = min(w, 48)

    def px(char, block, x, y):
        return data[(char * 3 + block) * size + ((y // 8) * (w // 8) + x // 8) * 64 + (y % 8) * 8 + x % 8]

    return [[Counter(px(c, k, x, y) for c in range(ORG_LAST) for x in (0, 1, face - 2, face - 1)).most_common(1)[0][0]
             for y in range(h)] for k in range(3)]


def icon(art, pal, w, h, box, bg):
    face = Image.open(art).convert('RGBA').crop(tuple(box)).resize((48, h), Image.LANCZOS)
    if w < 48:
        face = face.crop(((48 - w) // 2, 0, (48 + w) // 2, h))
    pix = [tuple(p) for p in pal]
    cache = {}
    out = bytearray(w * h)
    fw = face.width
    fp = face.load()
    for y in range(h):
        for x in range(fw):
            r, g, b, a = fp[x, y]
            if a < 128:
                out[y * w + x] = bg[y]
                continue
            k = (r, g, b)
            if k not in cache:
                cache[k] = min(range(1, len(pix)), key=lambda i: (pix[i][0] - r) ** 2 + (pix[i][1] - g) ** 2 + (pix[i][2] - b) ** 2)
            out[y * w + x] = cache[k]
    tiles = bytearray()
    for ty in range(h // 8):
        for tx in range(w // 8):
            for y in range(8):
                tiles += out[(ty * 8 + y) * w + tx * 8:(ty * 8 + y) * w + tx * 8 + 8]
    return bytes(tiles)


def check_specs(spec_paths, ebin):
    pairs = rd(os.path.join(ebin, 'charid2deckid.bin'))
    stock_chars = {struct.unpack_from('<H', pairs, i)[0] for i in range(0, len(pairs), 4)}
    stock_files = {f.decode().lower() for f in rd(os.path.join(ebin, 'deck_filename.bin')).split(b'\0') if f}
    specs, chars, files = [], {}, {}
    for p in spec_paths:
        s = modspec.load_json(p)
        c, f = s['char_id'], s['deck_file'].lower()
        if not isinstance(c, int) or c in stock_chars or c <= ORG_LAST or not CHAR_MIN <= c <= CHAR_MAX \
                or STORY_CHARS[0] <= c <= STORY_CHARS[1]:
            raise SystemExit(f'{p}: char_id {c}: use {CHAR_MIN}-{CHAR_MAX} (219 and {STORY_CHARS[0]}-'
                             f'{STORY_CHARS[1]} belong to the stock game and the story builder)')
        if f in stock_files:
            raise SystemExit(f'{p}: deck_file {s["deck_file"]} is a stock deck file')
        if c in chars:
            raise SystemExit(f'char_id {c} is used by {chars[c]} and {p}')
        if f in files:
            raise SystemExit(f'deck_file {s["deck_file"]} is used by {files[f]} and {p}')
        chars[c], files[f] = p, p
        specs.append((p, s))
    return specs


def write_headers(mod, rows, talk_rows):
    os.makedirs(os.path.join(mod, 'src'), exist_ok=True)
    with open(os.path.join(mod, 'src', 'talk_extra.h'), 'w') as f:
        f.write('enum TalkMoment { ' + ', '.join(f'TALK_{m.upper()}' for m in TALK_MOMENTS) + ' };\n')
        f.write('#define TALK_EXTRA_ROWS' + ''.join(f' \\\n    {{{ch}, TALK_{m.upper()}, {c}, {s}}},'
                                                    for ch, m, c, s in talk_rows) + '\n')
    with open(os.path.join(mod, 'src', 'opponent.h'), 'w') as f:
        f.write(f'#define OP_COUNT {len(rows)}\n#define OP_CHAR {rows[0][0] if rows else 0}\n'
                f'#define OP_PAIRS {PAIR_COUNT + len(rows)}\n#define OP_ROWS' +
                ''.join(f' \\\n    {{{ch}, {card}, {text}}},' for ch, card, text in rows) + '\n')


def main(spec_paths, ext, mod, decks=()):
    ebin = os.path.join(ext, 'Data_arc_pac', 'bin')
    used = set()
    specs = check_specs(spec_paths, ebin)
    st = State(ext, mod) if specs else None
    for _, spec in specs:
        add(st, spec)
        used.add(os.path.abspath(spec['deck']))
    if st:
        st.finish()
    else:
        print('opponent: none')
    write_headers(mod, st.rows if st else [], st.talk_rows if st else [])
    db = modspec.load_db(os.path.join(ext, 'Data_arc_pac', 'bin2'), os.path.join(mod, 'pac', 'Data_arc_pac', 'bin2'))
    for d in decks:
        if os.path.abspath(d) not in used:
            build_deck(d, db, {})


class State:
    def __init__(self, ext, mod):
        self.E = os.path.join(ext, 'Data_arc_pac')
        self.M = os.path.join(mod, 'pac', 'Data_arc_pac')
        self.ebin, self.mbin = os.path.join(self.E, 'bin'), os.path.join(self.M, 'bin')
        self.e2, self.m2 = os.path.join(self.E, 'bin2'), os.path.join(self.M, 'bin2')
        self.db = modspec.load_db(self.e2, self.m2)
        self.pairs = rd(os.path.join(self.ebin, 'charid2deckid.bin'))
        if len(self.pairs) != PAIR_COUNT * 4:
            raise SystemExit('charid2deckid.bin: unexpected size')
        self.fname = rd(os.path.join(self.ebin, 'deck_filename.bin'))
        fidx = rd(os.path.join(self.ebin, 'deck_fileidx.bin'))
        self.offs = list(struct.unpack(f'<{len(fidx) // 2}H', fidx))
        self.status = rd(os.path.join(self.ebin, 'enemystatus.bin'))
        if self.offs[-1] != len(self.fname) or len(self.status) != (len(self.offs) - 1) * 12:
            raise SystemExit('deck tables: unexpected layout')
        self.talk = {}
        for lang in TALK_LANGS:
            ost = rd(os.path.join(self.ebin, f'talkost_{lang}.bin'))
            msg = rd(os.path.join(self.ebin, f'talkmsg_{lang}.bin'))
            offs = list(struct.unpack(f'<{len(ost) // 4}I', ost))
            if offs[-1] != len(msg) or (len(offs) - 1) % TALK_LINES:
                raise SystemExit(f'talkost_{lang}: unexpected layout')
            self.talk[lang] = [msg[a:b] for a, b in zip(offs, offs[1:])]
        self.sets = (len(self.talk['e'])) // TALK_LINES - 2
        self.talk_sets = {}
        self.extra = []
        self.texts = {}
        for lang in carddb.LANGS:
            idx = layered(f'game_indx_{lang}.bin', self.e2, self.m2)
            txt = layered(f'game_text_{lang}.bin', self.e2, self.m2)
            prefix, strings = carddb.read_strtab(idx, txt, 1, 0, lang)
            orig = carddb.read_strtab(rd(os.path.join(self.e2, f'game_indx_{lang}.bin')),
                                      rd(os.path.join(self.e2, f'game_text_{lang}.bin')), 1, 0, lang)[1]
            self.texts[lang] = prefix, strings, orig
        self.org = {}
        for name, (size, w, h) in ORG.items():
            data = rd(os.path.join(self.E, 'duel2d', name))
            if len(data) != ORG_LAST * 3 * size:
                raise SystemExit(f'{name}: unexpected size')
            self.org[name] = bytearray(data + data[-3 * size:])
        self.pal = icon_palette(self.E)
        self.icon_bg = {name: icon_backgrounds(data, *ORG[name]) for name, data in self.org.items()}
        self.rows, self.talk_rows = [], []

    def finish(self):
        base = 56 + TALK_LINES * self.sets
        for k, (char, m, c, texts) in enumerate(self.extra):
            self.talk_rows.append((char, m, c, base + k))
            for lang in TALK_LANGS:
                self.talk[lang].append(texts.get(lang, texts['e']).encode(TALK_ENC.get(lang, 'cp1252')) + b'\0')
        for lang, lines in self.talk.items():
            offs, n = [], 0
            for s in lines:
                offs.append(n)
                n += len(s)
            offs.append(n)
            wr(os.path.join(self.mbin, f'talkost_{lang}.bin'), struct.pack(f'<{len(offs)}I', *offs))
            wr(os.path.join(self.mbin, f'talkmsg_{lang}.bin'), b''.join(lines))
        wr(os.path.join(self.mbin, 'charid2deckid.bin'), self.pairs)
        wr(os.path.join(self.mbin, 'enemystatus.bin'), self.status)
        wr(os.path.join(self.mbin, 'deck_filename.bin'), self.fname)
        wr(os.path.join(self.mbin, 'deck_fileidx.bin'), struct.pack(f'<{len(self.offs)}H', *self.offs))
        for lang, (prefix, strings, _) in self.texts.items():
            data, offs = carddb.build_strtab(prefix, strings, lang)
            wr(os.path.join(self.m2, f'game_indx_{lang}.bin'), carddb.write_index([offs]))
            wr(os.path.join(self.m2, f'game_text_{lang}.bin'), data)
        for name, data in self.org.items():
            wr(os.path.join(self.M, 'duel2d', name), bytes(data))


def add(st, spec):
    char = spec['char_id']
    db = st.db
    card = next((c.id for c in db.cards[1:] if c.names['e'] == spec['card']), None)
    if card is None:
        raise SystemExit(f'opponent {char}: no card named {spec["card"]!r}')
    limits = banlist_limits(layered(spec['banlist_file'], st.ebin, st.mbin)) if spec.get('banlist_file') else {}
    deck = build_deck(spec['deck'], db, limits)
    deck_id = len(st.offs) - 1

    extra = talk_extra(spec.get('talk_extra', {}), db)
    talk = {}
    for lang in TALK_LANGS:
        lines = spec['talk'].get(lang, spec['talk']['e'])
        if len(lines) != TALK_LINES:
            raise SystemExit(f'talk {lang}: {len(lines)} lines, expected {TALK_LINES}')
        talk[lang] = tuple(x.encode(TALK_ENC.get(lang, 'cp1252')) + b'\0' for x in lines)
    key = tuple(talk[lang] for lang in TALK_LANGS)
    set_id = st.talk_sets.get(key, st.sets)
    if set_id > TALK_SET_MAX:
        raise SystemExit(f'opponent {char}: talk set {set_id}, sets are 8 bits (at most {TALK_SET_MAX})')
    if set_id == st.sets:
        for lang in TALK_LANGS:
            at = (set_id + 2) * TALK_LINES
            st.talk[lang][at:at] = list(talk[lang])
        st.talk_sets[key] = set_id
        st.sets += 1
    st.extra += [(char, m, c, t) for m, c, t in extra]

    st.pairs += struct.pack('<HH', char, deck_id)
    s = spec['stats']
    st.status += struct.pack('<HHB5BH', deck_id, spec['rating'], set_id + 1, *s, card)
    st.fname += spec['deck_file'].encode() + b'\0'
    st.offs.append(len(st.fname))
    wr(os.path.join(st.M, 'deck', spec['deck_file'].lower()), deck.build())

    for lang in carddb.LANGS:
        name = spec['deck_name'].get(lang) or spec['deck_name'].get('j' if lang == 'r' else 'e') or spec['deck_name']['e']
        prefix, strings, orig = st.texts[lang]
        index = deck_id + DECK_NAME_BASE
        if index >= len(orig) or orig[index]:
            raise SystemExit(f'game_text_{lang}[{index}] is not a free slot')
        strings[index] = name

    text = 0
    if spec.get('name'):
        text = CHAR_NAME_TOP - sum(1 for r in st.rows if r[2])
        for lang in carddb.LANGS:
            prefix, strings, orig = st.texts[lang]
            if text < len(orig) and orig[text] or strings[text]:
                raise SystemExit(f'game_text_{lang}[{text}] is not a free slot for the name of opponent {char}')
            strings[text] = spec['name'].get(lang) or spec['name'].get('j' if lang == 'r' else 'e') or spec['name']['e']

    p = spec['portrait']
    img = bustup.portrait(p['cutout'], p.get('crop'), p.get('alpha_min', 128))
    files = bustup.encode(img, bustup.load(os.path.join(st.E, 'Bustup'), spec['bustup_template'])[3])
    bustup.write(files, os.path.join(st.M, 'Bustup'), char)
    prev = os.path.join('build', 'preview')
    os.makedirs(prev, exist_ok=True)
    bustup.decode(*files[:3]).save(os.path.join(prev, f'opponent_bu{char:03d}.png'))

    for name, (size, w, h) in ORG.items():
        blocks = [icon(p['face_art'], st.pal, w, h, p['face'], bg) for bg in st.icon_bg[name]]
        st.org[name] += b''.join(blocks)
        tile = blocks[1]
        pv = Image.new('RGB', (w, h))
        for t in range(len(tile) // 64):
            for j in range(64):
                pv.putpixel(((t % (w // 8)) * 8 + j % 8, (t // (w // 8)) * 8 + j // 8), st.pal[tile[t * 64 + j]])
        pv.save(os.path.join(prev, f'opponent_{name[:-4]}_{char:03d}.png'))

    st.rows.append((char, card, text))
    print(f'opponent {spec.get("name", {}).get("e") or spec["card"]}: char {char}, icon slot {ORG_FIRST + len(st.rows) - 1}, deck {deck_id} '
          f'({len(deck.main)}/{len(deck.extra)}), talk set {set_id}, card {card}')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Add a Free Duel opponent from an opponent spec: deck, status row, '
                                             'dialogue (28 lines per language), deck name, portrait and icons.',
                                 epilog='Writes into <mod>/pac/Data_arc_pac/{bin,bin2,deck,Bustup,duel2d}, '
                                        '<mod>/src/opponent.h, <mod>/src/talk_extra.h (extra dialogue moments) and previews in build/preview. Run after the card '
                                        'and banlist steps (it reads their output in <mod>/pac).')
    ap.add_argument('spec', nargs='*', help='opponent specs, e.g. variants/retro-genesys/opponents/*.json (char_id and '
                                            'deck_file must be unique); none: headers with OP_CHAR 0, the opponent hooks stay off')
    ap.add_argument('extracted', help='extraction folder from `make extract`')
    ap.add_argument('mod', help='variant folder, e.g. variants/retro-genesys')
    ap.add_argument('--decks', nargs='*', default=[], help='deck specs to check (card names, deck sizes) even if '
                                                             'no opponent uses them, e.g. variants/retro-genesys/decks/*.json')
    a = ap.parse_args()
    if not os.path.isdir(os.path.join(a.extracted, 'Data_arc_pac')):
        sys.exit(f'{a.extracted}/Data_arc_pac not found: run `make extract` first')
    main(a.spec, a.extracted, a.mod, a.decks)
