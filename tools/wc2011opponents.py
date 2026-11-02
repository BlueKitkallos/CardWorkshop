#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bustup
import carddb
import game
from add_opponent import TALK_ENC, TALK_LANGS, TALK_LINES
from ydc import Deck

ARM9 = 0x02000000
CHAR_JUMP, CHAR_JUMP_N, CHAR_JUMP_R2 = 0x0201a480, 0x1d1, 0x1d0
CHAR_RET, CHAR_NEG = 0x0201ad94, 0x0201ad92
NAME_TABLE = 0x020aa7d4
DECK_NAME_TABLE = 0x020aa5d8
DECK_FILES, RENTAL_FIRST, RENTAL_N = 253, 0x11e, 15
CHAR_BASE = 1000
BUSTUP_TEMPLATE = 139
TALK_SITUATIONS = 56
FACE = (60, 50)
TURBO_IDS = (3400, 3600)
TURBO = 'Turbo-only cards (Speed Spells, Speed Worlds, Turbo traps)'
SYNCHRO_CORE = 'Synchro core (generic Tuners and Synchros)'
SYNCHRO_SETS = ('Synchro', 'Synchron')


def thumb_case(a9, addr):
    r2 = CHAR_JUMP_R2
    for _ in range(8):
        op = struct.unpack_from('<H', a9, addr - ARM9)[0]
        if op >> 8 == 0x22:
            r2 = op & 0xff
        elif op >> 8 == 0x3a:
            r2 -= op & 0xff
        elif op >> 8 == 0x32:
            r2 += op & 0xff
        elif op >> 8 == 0x4a:
            r2 = struct.unpack_from('<I', a9, ((addr + 4) & ~3) + (op & 0xff) * 4 - ARM9)[0]
        elif op >> 11 == 0x1c:
            off = (op & 0x7ff) << 1
            target = addr + 4 + (off - 0x1000 if off & 0x800 else off)
            if target == CHAR_RET:
                return r2
            if target == CHAR_NEG:
                return 0
            addr = target
            continue
        elif op == 0x1c10:
            return r2
        else:
            raise SystemExit(f'char table: unexpected Thumb op {op:#06x} at {addr:#x} (not the EU WC2011 arm9?)')
        addr += 2
    raise SystemExit(f'char table: case at {addr:#x} does not return')


def char_decks(a9):
    out = {}
    for c in range(CHAR_JUMP_N):
        rel = struct.unpack_from('<h', a9, CHAR_JUMP + 2 * c - ARM9)[0]
        deck = thumb_case(a9, CHAR_JUMP + 2 + rel)
        if deck > 1:
            out[c] = deck
    return out


def name_kind(deck, v):
    if deck < 0x71 or deck in (0x118, 0x119):
        return 'text'
    if deck < 0xfd or deck in (0x116, 0x117):
        return 'card'
    if deck > 0x115:
        return 'text'
    return 'text' if v < 1000 else 'card'


def nul_strings(data, n, where):
    out = data.split(b'\0')[:-1]
    if len(out) != n:
        raise SystemExit(f'{where}: {len(out)} strings, expected {n}')
    return out


class Wc2011:
    def __init__(self, rom_path):
        import ndspy.codeCompression
        if not rom_path or not os.path.isfile(rom_path):
            raise SystemExit(f'WC2011 ROM not found: {rom_path} (set ROM11)')
        rom, prof, dbfiles = carddb.load_from_rom(rom_path)
        if prof['game_code'] != 'BYYP':
            raise SystemExit(f'{rom_path}: game code {prof["game_code"]}, expected BYYP')
        self.db = carddb.CardDB.load(dbfiles, prof)
        self.cards = {c.id: c for c in self.db.cards[1:]}
        a9 = ndspy.codeCompression.decompress(bytes(rom.arm9))
        self.bin = game.container_files(rom, 'Data_arc_pac/bin.pac')
        bin2 = game.container_files(rom, 'Data_arc_pac/bin2.pac')
        self.decks = {k: Deck.parse(v) for k, v in game.container_files(rom, 'Data_arc_pac/deck.pac').items()
                      if k.endswith('.ydc')}
        self.bustups = game.container_files(rom, bustup.W11_PAC)
        fn, fi = self.bin['deck_filename.bin'], self.bin['deck_fileidx.bin']
        offs = struct.unpack(f'<{len(fi) // 2}H', fi)
        self.files = [fn[a:b].rstrip(b'\0').decode() for a, b in zip(offs, offs[1:])]
        st = self.bin['enemystatus.bin']
        self.status = [struct.unpack_from('<HHB5BH', st, i * 12) for i in range(len(st) // 12)]
        self.char_deck = char_decks(a9)
        self.name_ref = {d: struct.unpack_from('<H', a9, NAME_TABLE + 2 * d - ARM9)[0] for d in self.char_deck.values()}
        self.deck_name_ref = {d: struct.unpack_from('<H', a9, DECK_NAME_TABLE + 2 * d - ARM9)[0]
                              for d in self.char_deck.values() if DECK_NAME_TABLE + 2 * d < NAME_TABLE}
        self.text = {l: carddb.read_strtab(bin2[f'game_indx_{l}.bin'], bin2[f'game_text_{l}.bin'], 1, 0, l)[1]
                     for l in carddb.LANGS}
        self.talk = {}
        for l in TALK_LANGS:
            n = len(self.bin[f'talkost_{l}.bin']) // 4 - 1
            lines = nul_strings(self.bin[f'talkmsg_{l}.bin'], n, f'talkmsg_{l}')
            self.talk[l] = [s.decode(TALK_ENC.get(l, 'cp1252')) for s in lines]
        self.talk_sets = (len(self.talk['e']) - TALK_SITUATIONS) // TALK_LINES

    def deck_file(self, deck):
        if deck < DECK_FILES:
            return self.files[deck]
        if RENTAL_FIRST <= deck < RENTAL_FIRST + RENTAL_N:
            return f'RTL{deck - RENTAL_FIRST + 1:03d}'
        return None

    def display_name(self, deck):
        v = self.name_ref[deck]
        if name_kind(deck, v) == 'text':
            return 'text', v, {l: self.text[l][v] for l in carddb.LANGS}
        c = self.cards.get(v)
        return 'card', v, ({l: c.names[l] for l in carddb.LANGS} if c else {})

    def deck_name(self, deck):
        v = self.deck_name_ref.get(deck)
        if not v or not self.text['e'][v]:
            return None
        return {l: self.text[l][v] for l in carddb.LANGS}

    def talk_lines(self, s):
        at = TALK_SITUATIONS + s * TALK_LINES
        return {l: self.talk[l][at:at + TALK_LINES] for l in TALK_LANGS}


class Names:
    def __init__(self, extracted, pool_spec):
        stock = carddb.CardDB.load(os.path.join(extracted, 'Data_arc_pac', 'bin2'))
        self.stock = {c.id: c.names['e'] for c in stock.cards[1:]}
        stock_by_name = {n: i for i, n in self.stock.items()}
        self.pool, self.unverified, self.frame, self.tuner = {}, set(), {}, set()
        self.alt = {}
        for c in json.load(open(pool_spec, encoding='utf-8'))['cards']:
            k = c['konami_id']
            if c.get('alt_art'):
                self.alt[k] = stock_by_name[c['name'].rsplit(' (', 1)[0]]
                continue
            self.pool[k] = c['name']
            self.frame[k] = c['frame']
            if c.get('tuner'):
                self.tuner.add(k)
            if not c.get('verified'):
                self.unverified.add(k)
        counts = {}
        for n in list(self.stock.values()) + list(self.pool.values()):
            counts[n] = counts.get(n, 0) + 1
        self.dup = {n for n, k in counts.items() if k > 1}

    def base(self, cid):
        return self.alt.get(cid, cid)

    def name(self, cid, where):
        cid = self.base(cid)
        name = self.stock.get(cid) or self.pool.get(cid)
        if name is None:
            raise SystemExit(f'{where}: card id {cid} is in neither WC2008 nor the WC2011 pool')
        return name

    def key(self, cid, where):
        name = self.name(cid, where)
        return f'id:{self.base(cid)}' if name in self.dup else name

    def needs_port(self, cid):
        return self.base(cid) in self.unverified


def deck_spec(name, d, names, where):
    out = {'name': name}
    for sec in ('main', 'extra', 'side'):
        cnt = {}
        for cid in getattr(d, sec):
            k = names.key(cid, where)
            cnt[k] = cnt.get(k, 0) + 1
        out[sec] = cnt
    return out


def roster(w11):
    out = []
    for char, deck in sorted(w11.char_deck.items()):
        f = w11.deck_file(deck)
        if f is None or f'{f.lower()}.ydc' not in w11.decks:
            continue
        out.append((char, deck, f))
    return out


def merge(spec, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(spec.get(k), dict) and k != 'talk':
            merge(spec[k], v)
        else:
            spec[k] = v
    return spec


def opponent_spec(w11, names, char, deck, f, deck_path, portrait_dir):
    _, rating, talk1, *stats, key = w11.status[deck]
    kind, ref, disp = w11.display_name(deck)
    card = ref if kind == 'card' and names.base(ref) in {**names.stock, **names.pool} else key
    where = f'WC2011 opponent {f}'
    p = os.path.join(portrait_dir, f'bu{char:03d}.png')
    spec = {
        'char_id': CHAR_BASE + char,
        'card': names.name(card, where),
        'deck': deck_path,
        'deck_file': f'W11_{f}.ydc',
        'rating': rating,
        'stats': stats,
        'bustup_template': BUSTUP_TEMPLATE,
        'portrait': {'cutout': p, 'crop': [0, 0, bustup.BOX[2] - bustup.BOX[0], bustup.BOX[3] - bustup.BOX[1]],
                     'face_art': p, 'face': None},
        'deck_name': w11.deck_name(deck) or disp or {'e': f},
        'talk': w11.talk_lines(talk1 - 1),
        'wc2011': {'char': char, 'deck': deck, 'talk_set': talk1 - 1, 'key_card': names.name(key, where),
                   'name_' + kind: ref},
    }
    if kind == 'text':
        spec['name'] = disp
    return spec


def write_portrait(w11, char, cell, path):
    img = bustup.wc2011_portrait(w11.bustups, char, cell)
    box = bustup.head_crop(img)
    face = bustup.wc2011_face(w11.bustups, char)
    img = img.crop(tuple(box))
    img.save(path)
    if face:
        cx, cy = (face[0] + face[2]) // 2 - box[0], (face[1] + face[3]) // 2 - box[1]
    else:
        a = img.getchannel('A')
        top = a.getbbox()[1]
        head = a.crop((0, top, img.width, top + 48)).getbbox()
        cx = (head[0] + head[2]) // 2 if head else img.width // 2
        cy = top + 4 + FACE[1] // 2
    x = max(0, min(img.width - FACE[0], cx - FACE[0] // 2))
    y = max(0, min(img.height - FACE[1], cy - FACE[1] // 2))
    return [x, y, x + FACE[0], y + FACE[1]]


def expand(a):
    w11 = Wc2011(a.rom11)
    names = Names(a.extracted, a.pool_spec)
    cfg = json.load(open(a.spec, encoding='utf-8'))
    if cfg.get('source') != 'wc2011':
        raise SystemExit(f'{a.spec}: not a WC2011 opponent list ("source": "wc2011")')
    deck_dir, opp_dir, por_dir = (os.path.join(a.out, d) for d in ('decks', 'opponents', 'portraits'))
    for d in (deck_dir, opp_dir, por_dir):
        os.makedirs(d, exist_ok=True)
    stems = {}
    for k, d in sorted(w11.decks.items()):
        stem = k[:-4]
        label = next((f for f in w11.files if f.lower() == stem), stem.upper())
        path = os.path.join(deck_dir, f'{label}.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(deck_spec(label, d, names, f'deck.pac {k}'), fh, ensure_ascii=False, indent=1)
        stems[stem] = path
    ros = {f.lower(): (char, deck, f) for char, deck, f in roster(w11)}
    unknown = [e for e in cfg.get('enabled', []) + list(cfg.get('opponents', {})) if e.lower() not in ros]
    if unknown:
        raise SystemExit(f'{a.spec}: {unknown[0]!r} is not a WC2011 opponent (deck file names, e.g. WCS001_Moja; '
                         f'list in {os.path.join(a.out, "roster.tsv")})')
    over = {k.lower(): v for k, v in cfg.get('opponents', {}).items()}
    on = {e.lower() for e in cfg.get('enabled', [])}
    by_name = {n: k for k, n in names.pool.items()}

    def unverified(f):
        o = over.get(f.lower(), {})
        if 'deck' in o:
            spec = json.load(open(o['deck'], encoding='utf-8'))
            keys = [k for sec in ('main', 'extra', 'side') for k in spec.get(sec, {})]
            ids = [int(k[3:]) if k.startswith('id:') else by_name.get(k) for k in keys]
        else:
            d = w11.decks[f'{f.lower()}.ydc']
            ids = [names.base(c) for c in d.main + d.extra + d.side]
        return sorted({c for c in ids if c is not None and names.needs_port(c)})

    for k, o in sorted(over.items()):
        f = ros[k][2]
        if k in on or 'deck' not in o:
            continue
        held = unverified(f)
        if held:
            print(f'{f}: waiting on {len(held)} unverified cards of {o["deck"]}, first {names.pool[held[0]]}')
        else:
            print(f'{f}: every card of {o["deck"]} is verified; add it to "enabled"')
    enabled, enabled_decks, blocked = [], [], []
    for e in cfg.get('enabled', []):
        char, deck, f = ros[e.lower()]
        held = unverified(f)
        if held:
            blocked.append(f'{f}: {len(held)} unverified cards, first {names.pool[held[0]]} (id {held[0]})')
            continue
        o = over.get(f.lower(), {})
        spec = opponent_spec(w11, names, char, deck, f, stems[f.lower()], por_dir)
        cell = o['portrait_cell'] if 'portrait_cell' in o else bustup.wc2011_cell(w11.bustups, char)
        face = write_portrait(w11, char, cell, spec['portrait']['cutout'])
        spec['portrait']['face'] = face
        merge(spec, {k: v for k, v in o.items() if k != 'portrait_cell'})
        path = os.path.join(opp_dir, f'{f}.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=1)
        enabled.append(path)
        enabled_decks.append(spec['deck'])
    if blocked:
        raise SystemExit(f'{a.spec}: enabled opponents with unverified cards (verify the cards in '
                         'mod/cards/wc2011.json first):\n  ' + '\n  '.join(blocked))
    with open(os.path.join(a.out, 'roster.tsv'), 'w', encoding='utf-8') as fh:
        fh.write('opponent\tchar_id\twc2011_char\tdeck\tname\trating\tkey_card\tdeck_cards\tpool_cards\tunverified\n')
        for f, (char, deck, _) in sorted(ros.items(), key=lambda x: x[1][0]):
            d = w11.decks[f'{f}.ydc']
            ids = [names.base(c) for c in d.main + d.extra + d.side]
            _, rating, *_, key = w11.status[deck]
            fh.write('\t'.join(map(str, (ros[f][2], CHAR_BASE + char, char, deck,
                                         (w11.display_name(deck)[2] or {}).get('e', ''), rating,
                                         names.name(key, f), len(ids), sum(c in names.pool for c in ids),
                                         len({c for c in ids if names.needs_port(c)})))) + '\n')
    for name, lines in (('enabled.txt', enabled), ('decks.txt', enabled_decks)):
        with open(os.path.join(a.out, name), 'w', encoding='utf-8') as fh:
            fh.writelines(p + '\n' for p in lines)
    print(f'{a.spec}: {len(w11.decks)} WC2011 decks, {len(ros)} opponents, {len(enabled)} enabled')


def families(cdb, strings, pool_ids, pool_pw):
    sets = {}
    for line in open(strings, encoding='utf-8'):
        if line.startswith('!setname '):
            code, name = line[9:].strip().split(' ', 1)
            sets[int(code, 16)] = name.split('|')[0].strip()
    con = sqlite3.connect(cdb)
    rows = dict(con.execute('select id, setcode from datas'))
    out = {}
    for k in pool_ids:
        sc = rows.get(pool_pw.get(k) or -1, 0)
        out[k] = [sets.get(c, f'set {c:#x}') for c in (sc >> s & 0xffff for s in (0, 16, 32, 48)) if c]
    return out


def coverage(a):
    w11 = Wc2011(a.rom11)
    names = Names(a.extracted, a.pool_spec)
    pool_pw = {k: c.password for k, c in w11.cards.items()}
    fam = families(a.cdb, a.strings, names.pool, pool_pw)
    ros = {f.lower(): (char, deck) for char, deck, f in roster(w11)}
    unit_of = {}
    for k in names.unverified:
        own = [f for f in fam.get(k, []) if f not in SYNCHRO_SETS]
        if TURBO_IDS[0] <= k < TURBO_IDS[1]:
            unit_of[k] = TURBO
        elif own:
            unit_of[k] = own[0]
        elif k in names.tuner or names.frame.get(k, '').startswith('synchro'):
            unit_of[k] = SYNCHRO_CORE
        else:
            unit_of[k] = f'staple: {names.pool[k]}'
    decks = {}
    for k, d in sorted(w11.decks.items()):
        stem = k[:-4]
        need = {names.base(c) for c in d.main + d.extra + d.side if names.needs_port(c)}
        turbo = any(TURBO_IDS[0] <= c < TURBO_IDS[1] for c in need) or stem.startswith('wrd') or \
            stem.endswith('_rd') or stem.startswith('rtlr')
        decks[stem] = {'need': need, 'turbo': turbo, 'opponent': stem in ros,
                       'pool': len({names.base(c) for c in d.main + d.extra + d.side if names.base(c) in names.pool})}
    target = {s for s, d in decks.items() if not d['turbo']}
    synchro = {k for k in unit_of if k in names.tuner or names.frame.get(k, '').startswith('synchro')}
    for k, u in list(unit_of.items()):
        if u in (TURBO, SYNCHRO_CORE) or u.startswith('staple: ') or k not in synchro:
            continue
        using = [s for s in target if k in decks[s]['need']]
        kin = [s for s in using if any(unit_of[c] == u and c not in synchro for c in decks[s]['need'])]
        if len(using) >= 3 and len(kin) * 2 <= len(using):
            unit_of[k] = SYNCHRO_CORE
    sizes = {}
    for c in {c for s in target for c in decks[s]['need']}:
        sizes[unit_of[c]] = sizes.get(unit_of[c], 0) + 1
    for k, u in unit_of.items():
        if sizes.get(u, 0) == 1 and u not in (TURBO, SYNCHRO_CORE) and not u.startswith('staple: '):
            unit_of[k] = f'staple: {names.pool[k]}'
    units = {}
    for k, u in unit_of.items():
        units.setdefault(u, set()).add(k)
    used = {c for s in target for c in decks[s]['need']}
    done, steps = set(), []
    complete = {s for s in target if not decks[s]['need']}
    steps.append({'family': '(already playable)', 'cards': [], 'decks': sorted(complete)})
    order = [SYNCHRO_CORE] if SYNCHRO_CORE in units else []
    while True:
        left = {u: (cs & used) - done for u, cs in units.items()}
        left = {u: cs for u, cs in left.items() if cs and u != TURBO}
        if not left:
            break
        if order:
            u = order.pop()
        else:
            def score(u):
                cs = left[u]
                new = [s for s in target - complete if decks[s]['need'] <= done | cs]
                prog = sum(len(decks[s]['need'] & cs) / len(decks[s]['need'] - done)
                           for s in target - complete if decks[s]['need'] & cs)
                return (len(new) / len(cs), prog / len(cs), -len(cs))
            u = max(sorted(left), key=score)
        cs = left[u]
        done |= cs
        new = sorted(s for s in target - complete if decks[s]['need'] <= done)
        complete |= set(new)
        steps.append({'family': u, 'cards': sorted(cs), 'decks': new})
    merged = []
    for s in steps:
        if merged and s['family'].startswith('staple: ') and merged[-1]['family'].startswith('staples'):
            m = merged[-1]
            m['cards'] += s['cards']
            m['decks'] += s['decks']
            m['names'].append(s['family'][8:])
        elif s['family'].startswith('staple: '):
            merged.append({'family': 'staples', 'cards': list(s['cards']), 'decks': list(s['decks']),
                           'names': [s['family'][8:]]})
        else:
            merged.append(dict(s))
    total_c = total_d = 0
    for m in merged:
        total_c += len(m['cards'])
        total_d += len(m['decks'])
        m['cum_cards'], m['cum_decks'] = total_c, total_d
        m['opponent_decks'] = sum(decks[s]['opponent'] for s in m['decks'])
        m['card_names'] = [names.pool[c] for c in m['cards']]
    fam_usage = {}
    for s, d in decks.items():
        for c in d['need']:
            fam_usage.setdefault(unit_of[c], set()).add(s)
    os.makedirs(a.out, exist_ok=True)
    out = {
        'decks': {s: {'unverified_cards': sorted(d['need']), 'pool_cards': d['pool'], 'turbo': d['turbo'],
                      'opponent': d['opponent']} for s, d in decks.items()},
        'families': {u: {'cards': sorted(cs), 'decks_using': len(fam_usage.get(u, ()))} for u, cs in units.items()
                     if not u.startswith('staple: ')},
        'staples': {names.pool[next(iter(cs))]: len(fam_usage.get(u, ())) for u, cs in units.items()
                    if u.startswith('staple: ')},
        'waves': [{k: m[k] for k in ('family', 'card_names', 'cards', 'decks', 'cum_cards', 'cum_decks',
                                     'opponent_decks')} for m in merged],
    }
    with open(os.path.join(a.out, 'coverage.json'), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    n_t = sum(d['turbo'] for d in decks.values())
    print(f'{len(decks)} decks: {len(target)} regular, {n_t} Turbo; {len(used)} unverified pool cards in regular decks, '
          f'{len(names.unverified)} in the pool; already playable: {len(steps[0]["decks"])}')
    for share in (0.25, 0.5, 0.75, 1):
        m = next(m for m in merged if m['cum_decks'] >= share * len(target))
        print(f'{share:.0%} of regular decks ({m["cum_decks"]}): {m["cum_cards"]} cards')
    print()
    print('| family | cards in regular decks | regular decks using it | cards in the pool |')
    print('|---|---|---|---|')
    use = {}
    for s in target:
        for c in decks[s]['need']:
            use.setdefault(unit_of[c], set()).add(s)
    in_decks = {}
    for c in {c for s in target for c in decks[s]['need']}:
        in_decks[unit_of[c]] = in_decks.get(unit_of[c], 0) + 1
    for u in sorted((u for u in use if not u.startswith('staple: ')), key=lambda u: (-len(use[u]), u))[:30]:
        print(f'| {u} | {in_decks[u]} | {len(use[u])} | {len(units[u])} |')
    st = [u for u in use if u.startswith('staple: ')]
    print(f'| staples (no archetype, one card each) | {len(st)} | {len(set().union(*(use[u] for u in st)))} | '
          f'{sum(len(units[u]) for u in units if u.startswith("staple: "))} |')
    print()
    print('| step | family | cards | decks completed | cumulative cards | cumulative decks | of them opponents |')
    print('|---|---|---|---|---|---|---|')
    print(f'| 0 | (already playable) | 0 | {len(steps[0]["decks"])} | 0 | {len(steps[0]["decks"])} | '
          f'{merged[0]["opponent_decks"]} |')
    for i, m in enumerate(merged):
        if i == 0:
            continue
        label = m['family'] if m['family'] != 'staples' else f'staples ({", ".join(m["names"][:4])}' + \
            (f' +{len(m["names"]) - 4}' if len(m['names']) > 4 else '') + ')'
        print(f'| {i} | {label} | {len(m["cards"])} | {len(m["decks"])} | {m["cum_cards"]} | {m["cum_decks"]} | '
              f'{m["opponent_decks"]} |')


def main():
    ap = argparse.ArgumentParser(description='WC2011 CPU opponents for the Retro-Genesys build, read from the WC2011 ROM '
                                             'at build time (nothing from the ROM is committed).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, hlp in (('expand', 'deck specs for all 305 WC2011 decks, roster.tsv, and an opponent spec with its '
                                 'portrait for every enabled opponent; enabled.txt and decks.txt list them for '
                                 'add_opponent.py and banlist.py --decks'),
                      ('coverage', 'which unverified pool cards each deck needs, grouped by archetype; ranked '
                                   'port order to coverage.json')):
        p = sub.add_parser(name, help=hlp, description=hlp)
        p.add_argument('rom11', help='WC2011 ROM (game code BYYP)')
        p.add_argument('extracted', help='extracted WC2008 folder (stock card names)')
        p.add_argument('pool_spec', help='expanded pool spec, build/wc2011/cards/wc2011.json')
        if name == 'expand':
            p.add_argument('spec', help='opponent list, e.g. variants/retro-genesys/opponents/wc2011.json: '
                                        '{"source": "wc2011", "enabled": [deck file names], '
                                        '"opponents": {name: overrides}}')
        else:
            p.add_argument('--cdb', required=True, help='ProjectIgnis BabelCDB cards.cdb (archetype setcodes)')
            p.add_argument('--strings', required=True, help='ProjectIgnis strings.conf (setcode names)')
        p.add_argument('out', help='output folder, e.g. build/wc2011/opponents')
    a = ap.parse_args()
    expand(a) if a.cmd == 'expand' else coverage(a)


if __name__ == '__main__':
    main()
