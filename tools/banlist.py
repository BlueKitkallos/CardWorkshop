import hashlib
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildwarn
import carddb
import modspec
from point_rules import story_free_cards, story_point_allowance

STATUS = {'forbidden': 0, 'limited': 1, 'semi_limited': 2, 'unlimited': 3}
UNLIMITED = 3
NAME_BASE = 0x514
ROM_LIST = 'limit200709.bin'
GODS = 3
DOWNLOAD_ENTRIES = 248
SECTION_MIN = 248
POINT_MAGIC = b'PNT1'
POINT_MAX = 30
OV06_RAM = os.path.join(HERE, '..', 'mod', 'src', 'ov06_ram.h')
ARRAY_KINDS = ('DATA', 'FILT', 'DISP', 'ALT')
OLD_KEY = 'new_cards_forbidden_in_stock_lists'
WC2011_BASE = 'wc2011:'
FIRST_INDEX = 3
MAX_LISTS = 2
POINT_LIST = {'e': 'Point List', 'f': 'Liste à points', 'g': 'Punkteliste', 'i': 'Lista a punti',
              's': 'Lista de puntos', 'j': 'ポイントリスト'}
POINT_MSG = {
    'e': 'Your Deck\'s points (%s) exceed the limit of the current Point List.',
    'f': 'Les points de votre Deck (%s) dépassent la limite de la Liste à points actuelle.',
    'g': 'Die Punkte deines Decks (%s) übersteigen das Limit der aktuellen Punkteliste.',
    'i': 'I punti del tuo Deck (%s) superano il limite dell\'attuale Lista a punti.',
    's': 'Los puntos de tu Deck (%s) exceden el límite de la Lista de puntos actual.',
    'j': 'デッキのポイント（%s）が\n現在のポイントリストの\n上限を超えています。',
}
POINT_PACK_MSG = {
    'e': 'Adding\n"%s"\nwould exceed the point limit of the current Point List.',
    'f': 'Ajouter\n"%s"\ndépasserait la limite de points de la Liste à points actuelle.',
    'g': 'Das Hinzufügen von\n„%s“\nwürde das Punktelimit der aktuellen Punkteliste überschreiten.',
    'i': 'Aggiungere\n"%s"\nsupererebbe il limite di punti dell\'attuale Lista a punti.',
    's': 'Añadir\n"%s"\nexcedería el límite de puntos de la Lista de puntos actual.',
    'j': '「%s」\nを入れると、現在のポイントリストの\n上限を超えます。',
}
POINT_LABELS = {
    983: POINT_LIST,
    1030: POINT_LIST,
    3035: POINT_LIST,
    1123: {'e': 'The number of copies of \n"%s"\nexceeds the number permitted by the current Point List.',
           'f': 'Le nombre d\'exemplaire de\n"%s"\ndépasse le nombre permis par la Liste à points actuelle.',
           'g': 'Die Anzahl der Exemplare von\n„%s“\nübersteigt die erlaubte Anzahl der aktuellen Punkteliste.',
           'i': 'Il numero di copie di\n"%s"\nsupera il numero consentito dall\'attuale Lista a punti.',
           's': 'El número de copias de\n"%s"\nexcede el número permitido por la Lista de puntos actual.',
           'j': '「%s」\nが、現在のポイントリストの\n制限枚数を超えています。'},
    1181: {'e': 'The number of copies of \n"%s"\nexceeds the number permitted by the current Point List. OK?',
           'f': 'Le nombre d\'exemplaire de\n"%s"\ndépasse le nombre permis par la Liste à points actuelle. '
                'Accepter ?',
           'g': 'Die Anzahl der Exemplare von\n„%s“\nübersteigt die erlaubte Anzahl der aktuellen Punkteliste. OK?',
           'i': 'Il numero di copie di\n"%s"\nsupera il numero consentito dall\'attuale Lista a punti. Va bene?',
           's': 'El número de copias de\n"%s"\nexcede el número permitido por la Lista de puntos actual. '
                '¿Aceptar?',
           'j': '「%s」\nが、現在のポイントリストの\n制限枚数を超えています。\nよろしいですか？'},
    1141: {'e': 'Your Deck fits the current Point List limits.',
           'f': 'Votre Deck respecte les restrictions de la Liste à points.',
           'g': 'Dein Deck erfüllt die aktuellen Bedingungen der Punkteliste.',
           'i': 'Il tuo Deck è conforme all\'attuale Lista a punti.',
           's': 'Tu Deck se ajusta a los límites de la Lista de puntos actual.',
           'j': 'デッキ内容は、\n現在のポイントリストの\n制限枚数に合っています。'},
    1169: {'e': 'Change Point List', 'f': 'Changer la Liste à points', 'g': 'Punkteliste ändern',
           'i': 'Cambia la Lista a punti', 's': 'Cambiar Lista de puntos', 'j': 'ポイントリストの切り替え'},
    3067: {'e': 'Check/change the Point List.', 'f': 'Consulter ou changer la Liste à points.',
           'g': 'Prüfe oder ändere die Punkteliste.', 'i': 'Controlla o cambia la Lista a punti.',
           's': 'Comprueba o cambia la Lista de puntos.', 'j': 'ポイントリストの確認と変更ができます。'},
    1174: {'e': 'This is the current Point List.',
           'f': 'Liste à points actuelle.',
           'g': 'Dies ist die aktuelle Punkteliste.',
           'i': 'Questa è l\'attuale Lista a punti.',
           's': 'Esta es la Lista de puntos actual.',
           'j': 'このリストは、現在の\nポイントリストです。'},
}


def parse(d):
    n = struct.unpack_from('<H', d, 0)[0]
    return [(v & 0x3fff, v >> 14) for v in struct.unpack_from(f'<{n}H', d, 8)], d[2:8]


def build(entries, hdr):
    entries = sorted(entries, key=lambda e: e[1])
    return struct.pack('<H', len(entries)) + hdr + struct.pack(f'<{len(entries)}H', *((i | s << 14) for i, s in entries))


def point_table(cap, points):
    ids = sorted(points)
    data = POINT_MAGIC + struct.pack(f'<HH{len(ids)}H', cap, len(ids), *ids) + bytes(points[i] for i in ids)
    return data + bytes(-len(data) % 4)


def game_text(ext2, lang):
    idx = open(os.path.join(ext2, f'game_indx_{lang}.bin'), 'rb').read()
    txt = open(os.path.join(ext2, f'game_text_{lang}.bin'), 'rb').read()
    prefix, strings = carddb.read_strtab(idx, txt, 1, 0, lang)
    data, offs = carddb.build_strtab(prefix, strings, lang)
    if data != txt or carddb.write_index([offs]) != idx:
        raise SystemExit(f'game_text_{lang}: rebuild mismatch')
    return prefix, strings


def add_texts(texts, ext2, out2):
    text_id = None
    os.makedirs(out2, exist_ok=True)
    for lang in carddb.LANGS:
        prefix, strings = game_text(ext2, lang)
        if text_id is None:
            text_id = len(strings)
        elif text_id != len(strings):
            raise SystemExit(f'game_text_{lang}: {len(strings)} strings, expected {text_id}')
        added = [t.get(lang) or t.get('j' if lang == 'r' else 'e') or t['e'] for t in texts]
        data, offs = carddb.build_strtab(prefix, strings + added, lang)
        open(os.path.join(out2, f'game_text_{lang}.bin'), 'wb').write(data)
        open(os.path.join(out2, f'game_indx_{lang}.bin'), 'wb').write(carddb.write_index([offs]))
    return [text_id + k for k in range(len(texts))]


def fingerprint(points, cap):
    text = ''.join(f'{name}\t{n}\n' for name, n in sorted(points.items()) if n) + f'cap\t{cap}\n'
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]


def fingerprint_line(points, cap):
    return f'points: {len(points)} cards, cap {cap}, fingerprint {fingerprint(points, cap)}'


def with_rom_only(spec_path, bl, points):
    extra = bl.get('rom_only_points', {})
    if not extra:
        return points
    both = sorted(set(extra) & set(points or {}))
    if both:
        raise SystemExit(f'{spec_path}: "rom_only_points" and the point list both price {", ".join(both)}')
    return {**(points or {}), **extra}


def point_source(spec_path, bl):
    path = bl.get('points_file')
    if path is None:
        return with_rom_only(spec_path, bl, bl.get('points')), bl.get('point_cap')
    if 'points' in bl:
        raise SystemExit(f'{spec_path}: "points" and "points_file" together, keep one')
    data = modspec.load_json(path)
    cap = bl.get('point_cap', data.get('point_cap'))
    if 'point_cap' in data and data['point_cap'] != cap:
        raise SystemExit(f'{spec_path}: "point_cap" is {cap} but {path} says {data["point_cap"]}')
    return with_rom_only(spec_path, bl, data.get('points')), cap


def read_list(path, d=None):
    d = open(path, 'rb').read() if d is None else d
    entries, hdr = parse(d)
    if build(entries, hdr) != d:
        raise SystemExit(f'{os.path.basename(path)}: rebuild mismatch')
    return entries, hdr


def wc2011_list(spec_path, name, rom11):
    import ndspy.rom
    import game
    if not rom11 or not os.path.isfile(rom11):
        raise SystemExit(f'{spec_path}: base {WC2011_BASE}{name} needs the WC2011 ROM (--rom11, ROM11): {rom11}')
    files = game.container_files(ndspy.rom.NintendoDSRom.fromFile(rom11), 'Data_arc_pac/bin.pac')
    if name not in files:
        stock = sorted(f for f in files if f.startswith('limit'))
        raise SystemExit(f'{spec_path}: base {WC2011_BASE}{name} not found, WC2011 lists: {", ".join(stock)}')
    return read_list(name, files[name])


def obtainable(db, new_ids, index, decks, stories):
    found = {c.id for c in db.cards[1:] if c.id in new_ids and any(c.packs)}
    for path in decks:
        deck = modspec.load_json(path)
        for part in ('main', 'extra', 'side'):
            for key in deck.get(part, {}):
                found.update(i for i in index.resolve(key, f'{path}: {part}')[:1] if i in new_ids)
    for root in stories:
        path = os.path.join(root, 'database', 'characters.json')
        if not os.path.isfile(path):
            continue
        for npc in modspec.load_json(path):
            for key in (npc.get('offer') or {}).get('gift', []):
                found.update(i for i in index.resolve(key, f'{path}: {npc.get("id")}.offer.gift')[:1] if i in new_ids)
    return sorted(found)


def check_verified(forbid, card_specs, index):
    if not card_specs:
        return
    held = {c['id'] for _, c in modspec.CardSpecs(card_specs).cards if c.get('verified') is False}
    blocked = [i for i in forbid if i in held]
    if blocked:
        buildwarn.warn(f'{len(blocked)} unverified cards are in a pack, CPU deck or story gift: '
                       + ', '.join(f'{index.name(i)} ({i})' for i in blocked)
                       + '; add each to "verified" in its spec once its effect and CPU use are checked')


def stock_lists(ext, out, skip, forbid):
    lists = {}
    for name in sorted(f for f in os.listdir(ext) if f.startswith('limit') and f.endswith('.bin') and f not in skip):
        entries, hdr = read_list(os.path.join(ext, name))
        listed = {i for i, _ in entries}
        added = [(i, 0) for i in forbid if i not in listed]
        dst = os.path.join(out, name)
        if added:
            entries = entries + added
            os.makedirs(out, exist_ok=True)
            open(dst, 'wb').write(build(entries, hdr))
            print(f'stock list {name}: {len(listed)} -> {len(entries)} entries ({len(added)} obtainable new cards '
                  f'forbidden)')
        elif os.path.exists(dst):
            os.remove(dst)
        lists[name] = entries, hdr
    return lists


def enc_round(x):
    v = x
    while True:
        if any(((v >> s) & ~0xff) == 0 and (v >> s) << s == v for s in range(0, 25, 2)):
            return v
        v += 1


def section_sizes(lists):
    sec = [SECTION_MIN] * 3
    most = DOWNLOAD_ENTRIES
    for name, (entries, hdr) in lists.items():
        total = len(entries) + GODS
        most = max(most, total)
        counts = [sum(1 for _, s in entries if s == k) for k in range(3)]
        counts[1] += GODS
        flags = struct.unpack_from('<H', hdr, 4)[0]
        if name == ROM_LIST or flags & 1:
            counts[0] = total
        sec = [max(a, b) for a, b in zip(sec, counts)]
    return most, sec


def ov06_ram():
    with open(OV06_RAM) as f:
        return {k: int(v, 16) for k, v in re.findall(r'#define (\w+) (0x[0-9a-fA-F]+)', f.read())}


def layout(sec_bytes, cards):
    r = ov06_ram()
    ed = r['OV06_EDITOR']
    cc_n = (cards + 63) & ~63
    used = sorted([(r['OV06_LIST'], 4 * cc_n), (r['OV06_VIEW'], 4 * cc_n), (r['OV06_SORT'], 4 * cc_n),
                   (r['OV06_DECKCNT'], cc_n), (r['OV06_PACKBUF'], 4 * cc_n)])
    free, lo = [], r['OV06_FREE_LO']
    for start, size in used:
        free.append([lo, start])
        lo = start + size
    free.append([lo, r['OV06_FREE_HI']])
    arrays = [(f'BL_{k}{s + 1}', sec_bytes[s]) for s in range(3) for k in ARRAY_KINDS]
    room = sum(hi - lo for lo, hi in free)
    placed = {}
    for name, size in sorted(arrays, key=lambda a: -a[1]):
        for chunk in free:
            start = ed + ((chunk[0] - ed + 0x3f) & ~0x3f)
            if start + size <= chunk[1]:
                placed[name] = start
                chunk[0] = start + size
                break
        else:
            need = sum(s for _, s in arrays)
            raise SystemExit(f'Forbidden/Limited viewer: the 12 section arrays need {need} bytes '
                             f'({", ".join(str(b // 4) for b in sec_bytes)} entries for forbidden, limited and '
                             f'semi-limited) and the free ov06 RAM next to {cards} cards holds about {room}; '
                             f'make the largest lists smaller')
    for name, addr in placed.items():
        if addr - ed >= 0x400000:
            raise SystemExit(f'{name} at {addr:#x} is out of reach of the editor code ({ed:#x} + 4 MiB)')
    return placed


def write_header(path, files, most, sec, id_end, points, msg_text, point_index, text_map, cards):
    if not path:
        return
    list_bytes = enc_round(8 + 2 * most)
    sec_bytes = [enc_round(4 * n) for n in sec]
    arrays = layout(sec_bytes, cards)
    paths = ''.join(f'Bin/{f}\\000' for f in files)
    lines = [f'#define BL_EXT {len(files)}',
             f'#define BL_PATHS "{paths}"',
             f'#define BL_LIST_BYTES {list_bytes:#x}',
             f'#define BL_ID_END {id_end}',
             f'#define BL_POINT_MAX {points}',
             f'#define BL_POINT_TEXT {msg_text}',
             f'#define BL_POINT_INDEX {point_index}',
             '#define BL_TEXT_MAP ' + ' '.join(f'X({a}, {b})' for a, b in text_map)]
    lines += [f'#define BL_SEC_BYTES{s + 1} {b:#x}' for s, b in enumerate(sec_bytes)]
    lines += [f'#define {n} {arrays[n]:#010x}' for n in sorted(arrays)]
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'banlist RAM: list buffer {list_bytes} bytes ({most} entries), viewer sections '
          f'{"/".join(str(b // 4) for b in sec_bytes)} entries')


def changes_of(spec_path, bl, index):
    changes, src = {}, {}
    for key, st in bl.get('cards', {}).items():
        if st not in STATUS:
            raise SystemExit(f'{spec_path}: {key!r}: status {st!r}, use one of {", ".join(STATUS)}')
        try:
            ids = index.resolve(key, spec_path)
        except SystemExit as e:
            buildwarn.warn(f'{e}; left out of the list')
            continue
        for cid in ids:
            if cid in changes:
                raise SystemExit(f'{spec_path}: {index.name(cid)} (id {cid}) is set twice: {src[cid]!r} and {key!r}')
            changes[cid], src[cid] = STATUS[st], key
    return changes


def mod_card_changes(spec_path, bl, index, stock_ids):
    rule = bl.get('mod_cards_by_points')
    if rule is None:
        return {}
    lim, semi = rule.get('limited'), rule.get('semi_limited')
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in (lim, semi)) or not 1 <= semi <= lim:
        raise SystemExit(f'{spec_path}: "mod_cards_by_points" needs "spec", "limited" and "semi_limited" '
                         f'(points, 1 <= semi_limited <= limited)')
    _, points, _ = points_of(rule['spec'], load_spec(rule['spec']), index)
    out = {}
    for cid in index.by_id:
        n = points.get(cid, 0)
        turbo_only = index.by_id[cid].frame in (13, 'spell') and not index.by_id[cid].password
        if cid and cid not in stock_ids and n >= semi and not turbo_only:
            out[cid] = STATUS['limited'] if n >= lim else STATUS['semi_limited']
    return out


def in_game(index, key):
    k = str(key).strip()
    if k.lower().startswith('id:'):
        return k[3:].isdigit() and int(k[3:]) in index.by_id
    if k.isdigit():
        return int(k) in index.by_pw
    return k in index.by_name or k.lower() in index.by_lower


def not_in_game(pts, names, index):
    return sorted(key for key in pts if not in_game(index, names.get(key, key)))


def points_of(spec_path, bl, index):
    pts, cap = point_source(spec_path, bl)
    if pts is None and cap is None:
        return None, {}, None
    if not isinstance(pts, dict) or not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= 0xffff:
        raise SystemExit(f'{spec_path}: a point format needs "points" ({{card: 0-{POINT_MAX}}}) or "points_file", '
                         f'and "point_cap" (1-65535)')
    names = bl.get('point_names', {})
    unused = sorted(set(names) - set(pts))
    if unused:
        buildwarn.warn(f'{spec_path}: "point_names" lists {unused[0]!r}, which has no points')
    out, src = {}, {}
    missing = not_in_game(pts, names, index)
    if missing:
        print(f'{spec_path}: {len(missing)} cards of the point list are not in the game, ignored: {", ".join(missing)}')
    for key, n in pts.items():
        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= POINT_MAX:
            raise SystemExit(f'{spec_path}: points of {key!r}: {n!r}, use 0 to {POINT_MAX}')
        if key in missing or not n:
            continue
        for cid in index.resolve(names.get(key, key), f'{spec_path}: points'):
            if cid in out:
                raise SystemExit(f'{spec_path}: points: {index.name(cid)} (id {cid}) is set twice: {src[cid]!r} '
                                 f'and {key!r}')
            out[cid], src[cid] = n, key
    public = {k: v for k, v in pts.items() if k not in bl.get('rom_only_points', {})}
    return cap, out, fingerprint_line(public, cap)


def deck_points(bl, cap, points, decks, index):
    tag = bl.get('deck_banlist')
    if not tag:
        return
    for path in decks:
        deck = modspec.load_json(path)
        if deck.get('banlist') != tag:
            continue
        total, copies = 0, {}
        for part in ('main', 'extra', 'side'):
            for key, n in deck.get(part, {}).items():
                cid = index.resolve(key, f'{path}: {part}')[0]
                total += points.get(cid, 0) * n
                copies[cid] = copies.get(cid, 0) + n
        over = ''.join(f', {index.name(c)} x{n}' for c, n in copies.items() if n > 3)
        print(f'points deck {deck.get("name", os.path.basename(path))}: {total}/{cap}{over}')


def load_spec(spec_path):
    bl = modspec.load_json(spec_path)
    for k in ('name', 'file'):
        if k not in bl:
            raise SystemExit(f'{spec_path}: no "{k}"')
    if 'base' not in bl and 'points' not in bl and 'points_file' not in bl:
        raise SystemExit(f'{spec_path}: no "base" (a list to start from) and no point format')
    if OLD_KEY in bl:
        raise SystemExit(f'{spec_path}: "{OLD_KEY}" is gone: every new card the player can obtain (pack, CPU '
                         f'deck, story gift) is now forbidden in the stock lists, hidden cards are left out')
    return bl


def base_list(spec_path, bl, ext, lists, index_ids, rom11):
    base = bl.get('base')
    if base is None:
        return [], struct.pack('<HHH', 0, 0, 0)
    if base.startswith(WC2011_BASE):
        entries, hdr = wc2011_list(spec_path, base[len(WC2011_BASE):], rom11)
        unknown = [i for i, _ in entries if i not in index_ids]
        if unknown:
            raise SystemExit(f"{spec_path}: base {base} lists {len(unknown)} cards missing from the database, "
                             f"first id {unknown[0]}")
        return entries, hdr
    if base not in lists:
        stock = sorted(f for f in os.listdir(ext) if f.startswith('limit'))
        raise SystemExit(f"{spec_path}: base {base!r} not found, stock lists: {', '.join(stock)} "
                         f"(or {WC2011_BASE}<file> for a WC2011 list)")
    return read_list(os.path.join(ext, base))


def main(spec_paths, ext, out, header=None, decks=(), stories=(), card_specs=(), rom11=None):
    if len(spec_paths) > MAX_LISTS:
        raise SystemExit(f'{MAX_LISTS} new banlists at most (mod/src/banlist_ext.S adds them to the menu): '
                         + ', '.join(spec_paths))
    ext2 = os.path.join(os.path.dirname(os.path.normpath(ext)), 'bin2')
    out2 = os.path.join(os.path.dirname(os.path.normpath(out)), 'bin2')
    db = modspec.load_db(ext2, out2)
    index = modspec.CardIndex(db)
    cards = len(db.cards)
    index_ids = {c.id for c in db.cards[1:]}
    stock_ids = {c.id for c in modspec.load_db(ext2).cards[1:]}
    new_ids = {c.id for c in db.cards[1:] if c.id not in stock_ids}
    forbid = obtainable(db, new_ids, index, decks, stories)
    check_verified(forbid, card_specs, index)
    specs = [(p, load_spec(p)) for p in spec_paths]
    files = [bl['file'] for _, bl in specs]
    if len(set(files)) != len(files):
        raise SystemExit('two banlist specs write the same "file": ' + ', '.join(spec_paths))
    lists = stock_lists(ext, out, set(files), forbid)
    built = []
    for spec_path, bl in specs:
        changes = changes_of(spec_path, bl, index)
        cap, points, line = points_of(spec_path, bl, index)
        entries, hdr = base_list(spec_path, bl, ext, lists, index_ids, rom11)
        entries = [e for e in entries if e[0] not in changes] + [(i, s) for i, s in changes.items() if s != UNLIMITED]
        built.append((spec_path, bl, entries, hdr, cap, points, line))
    texts = [bl['name'] for _, bl, *_ in built]
    point_at = [k for k, b in enumerate(built) if b[5]]
    view_stride = w11_view_stride(built)
    if len(point_at) > 1:
        raise SystemExit('one point list at most: ' + ', '.join(built[k][0] for k in point_at))
    with_points = bool(point_at)
    labels = sorted(POINT_LABELS) if with_points else []
    ids = add_texts(texts + ([POINT_MSG] if with_points else []) + [POINT_LABELS[i] for i in labels], ext2, out2)
    text_map = list(zip(labels, ids[len(texts) + 1:]))
    point_max = 0
    os.makedirs(out, exist_ok=True)
    for (spec_path, bl, entries, hdr, cap, points, line), text_id in zip(built, ids):
        hdr = struct.pack('<H', text_id - NAME_BASE) + hdr[2:]
        data = build(entries, hdr)
        if points:
            data += point_table(cap, points)
            point_max = max(point_max, len(points))
        open(os.path.join(out, bl['file']), 'wb').write(data)
        lists[bl['file']] = entries, hdr
        pts = f', {len(points)} point values, cap {cap}' if points else ''
        print(f"banlist {bl['name']['e']}: {len(entries)} entries in {bl['file']}{pts}")
        if points:
            print(line)
            deck_points(bl, cap, points, decks, index)
    for name, (entries, _) in lists.items():
        if len(entries) > cards:
            raise SystemExit(f'{name}: {len(entries)} entries, more than the {cards} cards of the database')
    most, sec = section_sizes(lists)
    id_end = max([c.id for c in db.cards[1:]] + [i for e, _ in lists.values() for i, _ in e]) + 1
    point_index = FIRST_INDEX + point_at[0] if with_points else 0
    write_header(header, files, most, sec, id_end, point_max, ids[len(texts)] if with_points else 0, point_index,
                 text_map, cards)


def w11_index(cards, card_specs, ext2):
    from types import SimpleNamespace
    names = {c.names['e'] for c in cards}
    extra = [SimpleNamespace(id=c['id'], names={'e': c['name']}, password=c.get('password', 0), frame=c.get('frame', ''))
             for path in card_specs for c in modspec.load_json(path).get('cards', []) if c['name'] not in names]
    index = modspec.CardIndex(SimpleNamespace(cards=[None] + list(cards) + extra))
    for path in card_specs:
        for o in modspec.load_json(path).get('stock_cards', []):
            index.by_name[o['names']['e']] = sorted(o['ids'], key=lambda i: not index.by_id[i].pwcost)
            index.by_lower[o['names']['e'].lower()] = o['names']['e']
    if ext2:
        for c in modspec.load_db(ext2).cards[1:]:
            ids = index.by_pw.get(c.password)
            if ids and c.names['e'] not in index.by_name:
                index.by_name[c.names['e']] = ids
    return index


def spec_total(path, points, index, free=None):
    from deck_paths import resolve_deck
    path = resolve_deck(path)
    deck = modspec.load_json(path)
    free = {k.casefold(): n for k, n in (free or {}).items()}
    total = 0
    for part in ('main', 'extra', 'side'):
        for key, n in deck.get(part, {}).items():
            n -= min(n, free.pop(key.casefold(), 0))
            total += points.get(index.resolve(key, f'{path}: {part}')[0], 0) * n
    return deck.get('name', os.path.basename(path)), total


def w11_deck_check(w11, index, cap, points, decks, info_decks, mode, report, stock_decks=None):
    sources = {}
    if stock_decks:
        from deck_paths import stock_sources
        for path in stock_sources(stock_decks):
            spec = modspec.load_json(path)
            sources[spec['stock_file'].lower()] = path
    users = {}
    for char, deck, f in w11_roster(w11):
        users.setdefault(f.lower(), []).append((w11.display_name(deck)[2] or {}).get('e') or f)
    rows = []
    for k, d in sorted(w11.decks.items()):
        stem = k[:-4]
        label = next((f for f in w11.files if f.lower() == stem), stem.upper())
        total = sum(points.get(c, 0) for c in d.main + d.extra + d.side)
        if k.lower() in sources:
            _, total = spec_total(sources[k.lower()], points, index)
        rows.append(('wc2011', f'{label}.ydc', ', '.join(users.get(stem, [])), total))
    for path in decks:
        name, total = spec_total(path, points, index)
        rows.append(('variant', path, name, total))
    allowances = {path: story_point_allowance(path) for path in decks}
    exempt = [r for r in rows if r[0] == 'variant' and allowances.get(r[1])
              and (story_free_cards(r[1]) is None or spec_total(r[1], points, index, story_free_cards(r[1]))[1] <= cap)]
    over = [r for r in rows if r[3] > cap and r not in exempt]
    if report:
        os.makedirs(os.path.dirname(report) or '.', exist_ok=True)
        with open(report, 'w', encoding='utf-8') as f:
            f.write('source\tdeck\topponent\tpoints\tpoint_rule\n')
            f.writelines('\t'.join(map(str, (*r, allowances.get(r[1]) or f'cap {cap}'))) + '\n'
                         for r in sorted(rows, key=lambda r: (-r[3], r[1])))
    for _, path, name, total in exempt:
        print(f'points deck {name}: {total}/{cap} ({allowances[path]})')
    for path in info_decks:
        try:
            name, total = spec_total(path, points, index)
        except SystemExit as e:
            print(f'points deck {path}: not counted ({e})')
            continue
        print(f'points deck {name}: {total}/{cap} (not shipped yet)')
    print(f'CPU decks: {len(rows)} checked ({len(rows) - len(decks)} WC2011, {len(decks)} of the variant), '
          f'{len(over)} over {cap} points' + (f', all totals in {report}' if report else ''))
    if over and mode == 'refuse':
        for src, deck, who, total in sorted(over, key=lambda r: (-r[3], r[1])):
            print(f'  over the cap: {deck}{f" ({who})" if who else ""}: {total}/{cap}')
        raise SystemExit(f'{len(over)} CPU decks are over the {cap}-point cap (DECK_CHECK=refuse); change the deck '
                         f'lists or build with DECK_CHECK=warn')
    for src, deck, who, total in sorted(over, key=lambda r: (-r[3], r[1])):
        line = f'{deck}{f" ({who})" if who else ""}: {total}/{cap}'
        if src == 'variant':
            buildwarn.warn(f'CPU deck over the {cap}-point cap: {line}')
        else:
            print(f'  over the cap: {line}')
    stock_over = [r for r in over if r[0] != 'variant']
    if stock_over:
        buildwarn.warn(f'{len(stock_over)} WC2011 CPU decks over the {cap}-point cap'
                       + (f', totals in {report}' if report else ''))


def w11_extra_deck(card):
    frame = getattr(card, 'frame', '')
    if isinstance(frame, int):
        frame = carddb.LAYOUT_NAMES['wc2011']['frames'].get(frame) or carddb.FRAMES.get(frame, '')
    return frame.startswith(('fusion', 'synchro'))


def w11_starter(path, index, entries, cap, points):
    deck = modspec.load_json(path)
    unknown = sorted(set(deck) - {'name', 'main', 'extra', 'side'})
    if unknown:
        raise SystemExit(f'{path}: unknown key {unknown[0]!r} (name, main, extra, side)')
    status = dict(entries)
    parts, copies, allowed, total = {}, {}, {}, 0
    for part, (lo, hi) in W11_STARTER_SIZES.items():
        ids = []
        for key, n in deck.get(part, {}).items():
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                raise SystemExit(f'{path}: {part}: {key!r}: {n!r} copies, use a number from 1')
            same = index.resolve(key, f'{path}: {part}')
            cid = index.deck_id(same)
            name = index.name(cid)
            if part != 'side' and w11_extra_deck(index.by_id[cid]) != (part == 'extra'):
                raise SystemExit(f'{path}: {name} is ' + ('not an Extra Deck monster, list it under "main"'
                                 if part == 'extra' else 'an Extra Deck monster, list it under "extra"'))
            ids += [cid] * n
            copies[name] = copies.get(name, 0) + n
            allowed[name] = min(status.get(i, UNLIMITED) for i in same)
            total += points.get(cid, 0) * n
        if not lo <= len(ids) <= hi:
            raise SystemExit(f'{path}: {part} holds {len(ids)} cards, the game takes {lo}-{hi}')
        parts[part] = ids
    for name, n in copies.items():
        if n > allowed[name]:
            buildwarn.warn(f'{path}: {n} copies of {name}, the list a new game starts on allows {allowed[name]}')
    if points and total > cap:
        buildwarn.warn(f'{path}: {total} points, over the {cap}-point cap of the list a new game starts on')
    print(f'starter deck {deck.get("name", os.path.basename(path))}: main {len(parts["main"])}, '
          f'extra {len(parts["extra"])}, side {len(parts["side"])}' + (f', {total}/{cap} points' if points else ''))
    return parts


def w11_list_words(most):
    return max(W11_STOCK_LIST_BYTES, 8 + 2 * most + 3 & ~3) // 2


def w11_band_labels():
    bands = W11_POINT_BANDS
    if len(set(bands)) != len(bands) or min(bands) < 1 or len(bands) != W11_VIEW_TABS:
        raise SystemExit(f'W11_POINT_BANDS {bands}: {W11_VIEW_TABS} distinct lower bounds of at least 1')
    top = {lo: min([b for b in bands if b > lo], default=None) for lo in bands}
    labels = [f'{lo}+' if top[lo] is None else f'{lo}' if top[lo] == lo + 1 else f'{lo}-{top[lo] - 1}'
              for lo in bands]
    return top, labels


def w11_tabs(entries, points):
    if points:
        top, _ = w11_band_labels()
        return [sum(1 for i, v in points.items() if i not in W11_VIEW_HIDDEN and v >= lo and (top[lo] is None or v < top[lo]))
                for lo in W11_POINT_BANDS]
    return [None] + [sum(1 for _, st in entries if st == k) for k in range(W11_VIEW_TABS - 1)]


def w11_view_stride(built):
    tabs = [(spec_path, bl, points, w11_tabs(entries, points)) for spec_path, bl, entries, _, _, points, _ in built]
    need = max(c for *_, t in tabs for c in t[2:])
    stride = W11_VIEW_STOCK_BYTES
    while stride < 4 * need:
        stride *= 2
    caps = (None, W11_VIEW_SEC1, stride // 4, stride // 4)
    _, labels = w11_band_labels()
    for spec_path, bl, points, t in tabs:
        names = labels if points else ('all', 'forbidden', 'limited', 'semi-limited')
        print(f'banlist {bl["name"]["e"]}: viewer tabs ' + ', '.join(
            f'{n} {c}' + (f'/{cap}' if cap else '') for n, c, cap in zip(names, t, caps) if c is not None))
        if t[1] > W11_VIEW_SEC1:
            raise SystemExit(f'{spec_path}: Forbidden/Limited viewer: the {names[1]} tab holds {t[1]} cards, '
                             f'it holds {W11_VIEW_SEC1}')
    print(f'banlist RAM: viewer sections 2-3 hold {stride // 4} cards each ({8 * stride} bytes past ov08)')
    return stride


def w11_band_lines():
    _, labels = w11_band_labels()
    return [f'#define BL11_BAND_MIN {", ".join(map(str, W11_POINT_BANDS))}',
            '#define BL11_BAND_LABELS ' + ' '.join(f'"{l}\\000"' for l in labels),
            f'#define BL11_VIEW_HIDDEN {", ".join(map(str, W11_VIEW_HIDDEN))}']


def w11_starter_lines(parts):
    ids = parts['main'] + parts['side'] + parts['extra'] if parts else []
    return [f'#define BL11_STARTER_MAIN {len(parts["main"]) if parts else 0}',
            f'#define BL11_STARTER_SIDE {len(parts["side"]) if parts else 0}',
            f'#define BL11_STARTER_EXTRA {len(parts["extra"]) if parts else 0}',
            '#define BL11_STARTER_IDS ' + ''.join(f'{i}, ' for i in ids)]


def w11_roster(w11):
    import wc2011opponents
    return wc2011opponents.roster(w11)


def main11(argv):
    import argparse
    import wc2011opponents
    ap = argparse.ArgumentParser(prog='banlist.py wc2011',
                                 description='Lists for the WC2011-based build: checks every CPU deck the build ships '
                                             '(the WC2011 ROM\'s decks and --decks) against the point list of the '
                                             'specs.')
    ap.add_argument('rom11', help='WC2011 ROM (game code BYYP)')
    ap.add_argument('spec', nargs='+', help='banlist specs in menu order')
    ap.add_argument('--cards', nargs='*', default=[], help='mod card specs (names of the cards WC2011 lacks)')
    ap.add_argument('--decks', nargs='*', default=[], help='deck specs the build ships as CPU decks')
    ap.add_argument('--info-decks', nargs='*', default=[], help='deck specs whose totals are printed only')
    ap.add_argument('--stock-decks', help='stock deck JSON source root, including its base game/ library')
    ap.add_argument('--deck-check', choices=('warn', 'refuse'), default='refuse',
                    help='a CPU deck over the cap: warn prints it and goes on, refuse stops (default: %(default)s)')
    ap.add_argument('--report', help='TSV of every checked deck\'s total')
    ap.add_argument('--starter', help='deck spec of the new game\'s deck (main, extra, side; the copies are added to '
                                      'the stock new game\'s cards); checked against the list a new game starts on')
    ap.add_argument('--wc2008-names', metavar='BIN2', help='WC2008 card DB folder (extracted/Data_arc_pac/bin2): deck '
                                                           'specs may name a card as WC2008 does')
    ap.add_argument('--out', help='pac folder of the variant (variants/dimension-break/pac/Data_arc_pac): the lists '
                                  'go to <out>/bin, the game_text files with the list names to <out>/bin2')
    ap.add_argument('--header', help='C header for the variant code (BL11_*); an armips file with the same stem and '
                                     '_def.asm holds BL11_EXT and BL11_START')
    ap.add_argument('--text-fixes', help='JSON {lang: {stock game_text string: replacement}} applied to the stock '
                                         'strings written to <out>/bin2; no more rows than the stock string, no row '
                                         'wider than its stock rows (one-row strings: than any western language\'s)')
    a = ap.parse_args(argv)
    if len(a.spec) > W11_MAX_LISTS:
        raise SystemExit(f'{W11_MAX_LISTS} new lists at most (the list menu holds 88 rows): ' + ', '.join(a.spec))
    w11 = wc2011opponents.Wc2011(a.rom11)
    index = w11_index(w11.db.cards[1:], a.cards, a.wc2008_names)
    index_ids = set(index.by_id)
    stock_ids = {c.id for c in w11.db.cards[1:]}
    specs = [(p, load_spec(p)) for p in a.spec]
    files = [bl['file'] for _, bl in specs]
    if len(set(files)) != len(files):
        raise SystemExit('two banlist specs write the same "file": ' + ', '.join(a.spec))
    built = []
    for spec_path, bl in specs:
        changes = {**mod_card_changes(spec_path, bl, index, stock_ids), **changes_of(spec_path, bl, index)}
        cap, points, line = points_of(spec_path, bl, index)
        entries, hdr = base_list(spec_path, bl, None, {}, index_ids, a.rom11)
        entries = [e for e in entries if e[0] not in changes] + [(i, s) for i, s in changes.items() if s != UNLIMITED]
        wide = sorted(i for i, _ in entries if i >= W11_ID_END)
        if wide:
            raise SystemExit(f'{spec_path}: card ids {wide} do not fit a list entry (ids under {W11_ID_END})')
        built.append((spec_path, bl, entries, hdr, cap, points, line))
    point_at = [k for k, b in enumerate(built) if b[5]]
    view_stride = w11_view_stride(built)
    if len(point_at) > 1:
        raise SystemExit('one point list at most: ' + ', '.join(built[k][0] for k in point_at))
    for spec_path, bl, entries, hdr, cap, points, line in built:
        if points:
            print(f'banlist {bl["name"]["e"]}: {len(points)} card ids with points, cap {cap}')
            print(line)
            w11_deck_check(w11, index, cap, points, a.decks, a.info_decks, a.deck_check, a.report, a.stock_decks)
    starter = None
    if a.starter:
        if point_at:
            _, _, entries, _, cap, points, _ = built[point_at[0]]
        else:
            (entries, _), cap, points = wc2011_list(a.starter, W11_STOCK_LIST, a.rom11), None, {}
        starter = w11_starter(a.starter, index, entries, cap, points)
    if not a.out:
        return
    import game
    bin2 = game.container_files(carddb.load_from_rom(a.rom11)[0], 'Data_arc_pac/bin2.pac')
    labels = sorted(POINT_LABELS) if point_at else []
    texts = [bl['name'] for _, bl, *_ in built]
    ids = w11_add_texts(texts + ([POINT_MSG] if point_at else []) + [w11_label(bin2, i) for i in labels]
                        + ([POINT_PACK_MSG] if point_at else []),
                        bin2, os.path.join(a.out, 'bin2'), w11_text_fixes(a.text_fixes, bin2))
    out = os.path.join(a.out, 'bin')
    os.makedirs(out, exist_ok=True)
    point_max = 0
    for (spec_path, bl, entries, hdr, cap, points, line), text_id in zip(built, ids):
        hdr = struct.pack('<H', text_id - NAME_BASE) + hdr[2:]
        data = build(entries, hdr)
        if points:
            data += point_table(cap, points)
            point_max = len(points)
        open(os.path.join(out, bl['file']), 'wb').write(data)
        print(f"banlist {bl['name']['e']}: {len(entries)} entries in {bl['file']}"
              + (f', {len(points)} point values' if points else ''))
    if a.header:
        point_index = FIRST_INDEX + point_at[0] if point_at else 0
        text_map = list(zip(labels, ids[len(texts) + 1:]))
        paths = ''.join(f'Bin/{f}\\000' for f in files)
        most = max(len(b[2]) for b in built)
        list_words = w11_list_words(most)
        print(f'banlist RAM: list buffer {2 * list_words} bytes ({most} entries in the largest list)')
        lines = [f'#define BL11_EXT {len(files)}', f'#define BL11_PATHS "{paths}"',
                 f'#define BL11_LIST_WORDS {list_words}', f'#define BL11_VIEW_STRIDE {view_stride:#x}',
                 f'#define BL11_POINT_MAX {max(point_max, 1)}',
                 f'#define BL11_POINT_TEXT {ids[len(texts)] if point_at else 0}',
                 f'#define BL11_PACK_TEXT {ids[-1] if point_at else 0}',
                 f'#define BL11_POINT_INDEX {point_index if point_at else 0xff}',
                 '#define BL11_TEXT_MAP ' + ' '.join(f'X({x}, {y})' for x, y in text_map)] + \
                w11_band_lines() + w11_starter_lines(starter)
        with open(a.header, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        with open(os.path.splitext(a.header)[0] + '_def.asm', 'w') as f:
            f.write(f'.definelabel BL11_EXT, {len(files)}\n.definelabel BL11_START, {point_index}\n'
                    f'.definelabel BL11_VIEW_STRIDE, {view_stride:#x}\n')


W11_MAX_LISTS = 2
W11_ID_END = 0x4000
W11_STOCK_LIST_ENTRIES = (0x280 - 8) // 2
W11_STOCK_LIST_BYTES = 0x284
W11_LANGS = 'efgijkrs'
W11_LIMIT_TEXT = 1123
W11_LIMIT_ASK = 1181
W11_STOCK_LIST = 'limit201009.bin'
W11_POINT_BANDS = (1, 3, 7, 15)
W11_VIEW_TABS = 4
W11_VIEW_SEC1 = 256
W11_VIEW_STOCK_BYTES = 0x200
W11_VIEW_HIDDEN = (3858, 3859)
W11_STARTER_SIZES = {'main': (40, 60), 'extra': (0, 15), 'side': (0, 15)}
W11_POINT_COST = {'e': 'Point Cost', 'f': 'Coût en points', 'g': 'Punktekosten', 'i': 'Costo in punti',
                  's': 'Coste en puntos', 'j': '消費ポイント'}


def w11_game_text(bin2, lang):
    idx, txt = bin2[f'game_indx_{lang}.bin'], bin2[f'game_text_{lang}.bin']
    prefix, strings = carddb.read_strtab(idx, txt, 1, 0, lang)
    data, offs = carddb.build_strtab(prefix, strings, lang)
    if data != txt or carddb.write_index([offs]) != idx:
        raise SystemExit(f'WC2011 game_text_{lang}: rebuild mismatch')
    return prefix, strings


def w11_label(bin2, text_id):
    if text_id == 1030:
        return dict(W11_POINT_COST)
    label = dict(POINT_LABELS[text_id])
    if text_id != W11_LIMIT_ASK:
        return label
    for lang in W11_LANGS:
        _, stock = w11_game_text(bin2, lang)
        base, ask = stock[W11_LIMIT_TEXT], stock[W11_LIMIT_ASK]
        own = POINT_LABELS[W11_LIMIT_TEXT].get(lang)
        if own and ask.startswith(base):
            label[lang] = own + ask[len(base):]
    return label


def w11_text_fixes(path, bin2):
    western = {lang: w11_game_text(bin2, lang)[1] for lang in 'efgis'}
    out = {}
    for lang, table in (modspec.load_json(path) if path else {}).items():
        if lang not in western or not isinstance(table, dict):
            raise SystemExit(f'{path}: "{lang}" is not one of {"".join(western)}')
        stock, fix = western[lang], {}
        for old, new in table.items():
            at = [i for i, s in enumerate(stock) if s == old]
            if not at:
                buildwarn.warn(f'{path} ({lang}): no stock game_text string reads {old!r}; fix left out')
                continue
            rows = new.split('\n')
            if len(rows) > len(old.split('\n')):
                buildwarn.warn(f'{path} ({lang}): {new!r} has more rows than the stock {old!r}')
            for i in at:
                if '\n' in old:
                    limit = max(len(r) for r in old.split('\n'))
                else:
                    limit = max(len(r) for strings in western.values() for r in strings[i].split('\n'))
                if any(len(r) > limit for r in rows):
                    buildwarn.warn(f'{path} ({lang}): a row of {new!r} is wider than {limit}, the widest stock row')
                fix[i] = new
        out[lang] = fix
    return out


def w11_add_texts(texts, bin2, out2, fixes=None):
    os.makedirs(out2, exist_ok=True)
    jp = w11_game_text(bin2, 'j')[1]
    text_id = len(jp)
    for lang in W11_LANGS:
        prefix, strings = w11_game_text(bin2, lang)
        fix = (fixes or {}).get(lang, {})
        strings = [fix.get(i, s) for i, s in enumerate(strings)]
        if lang == 'r' and len(strings) < text_id:
            strings = strings + jp[len(strings):]
        if text_id != len(strings):
            raise SystemExit(f'WC2011 game_text_{lang}: {len(strings)} strings, expected {text_id}')
        added = [t.get(lang) or t.get('j' if lang == 'r' else 'e') or t['e'] for t in texts]
        data, offs = carddb.build_strtab(prefix, strings + added, lang)
        open(os.path.join(out2, f'game_text_{lang}.bin'), 'wb').write(data)
        open(os.path.join(out2, f'game_indx_{lang}.bin'), 'wb').write(carddb.write_index([offs]))
    return [text_id + k for k in range(len(texts))]


def print_fingerprint(path):
    data = modspec.load_json(path)
    points, cap = data.get('points'), data.get('point_cap')
    if not isinstance(points, dict) or not isinstance(cap, int):
        sys.exit(f'{path}: needs "points" ({{card name: points}}) and "point_cap"')
    print(fingerprint_line(points, cap))


def import_points(argv):
    import argparse
    import json
    import wc2011opponents
    ap = argparse.ArgumentParser(prog='banlist.py import',
                                 description='Copy the points page export (its "points.json" button) into the repo '
                                             'and list the changes, the cards the game does not have yet (the build '
                                             'ignores them until a card spec adds them) and the fingerprint.')
    ap.add_argument('export', help='points.json downloaded from the points page')
    ap.add_argument('rom11', help='WC2011 ROM (game code BYYP)')
    ap.add_argument('--cards', nargs='*', default=[], help='mod card specs (cards WC2011 lacks)')
    ap.add_argument('--spec', default='variants/retro-genesys/banlists/retro-genesys.json',
                    help='banlist spec whose "point_names" maps page names to game names (default: %(default)s)')
    ap.add_argument('--out', default='mod/test/points/points.json', help='points file of the repo (default: %(default)s)')
    a = ap.parse_args(argv)
    data = modspec.load_json(a.export)
    pts, cap = data.get('points'), data.get('point_cap')
    if not isinstance(pts, dict) or not isinstance(cap, int) or isinstance(cap, bool):
        sys.exit(f'{a.export}: not a points page export (needs "points" and "point_cap")')
    bad = [k for k, n in pts.items() if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= POINT_MAX]
    if bad:
        sys.exit(f'{a.export}: points of {bad[0]!r}: {pts[bad[0]]!r}, use 0 to {POINT_MAX}')
    old = modspec.load_json(a.out).get('points', {}) if os.path.exists(a.out) else {}
    for name in sorted(set(old) | set(pts)):
        if old.get(name) != pts.get(name):
            print(f'{name}: {old.get(name, "-")} -> {pts.get(name, "-")}')
    w11 = wc2011opponents.Wc2011(a.rom11)
    index = w11_index(w11.db.cards[1:], a.cards, None)
    names = modspec.load_json(a.spec).get('point_names', {}) if os.path.exists(a.spec) else {}
    missing = not_in_game(pts, names, index)
    if missing:
        print(f'{len(missing)} cards not in the game, ignored by the build: {", ".join(missing)}')
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
    print(f'{a.out}: {fingerprint_line(pts, cap)}')


if __name__ == '__main__':
    import argparse
    if len(sys.argv) > 1 and sys.argv[1] == 'import':
        import_points(sys.argv[2:])
        sys.exit()
    if len(sys.argv) == 3 and sys.argv[1] == '--fingerprint':
        print_fingerprint(sys.argv[2])
        sys.exit()
    if len(sys.argv) > 1 and sys.argv[1] == 'wc2011':
        main11(sys.argv[2:])
        sys.exit()
    ap = argparse.ArgumentParser(description='Build Forbidden/Limited lists (up to two) from a stock list plus the '
                                             'changes in a banlist spec (name, base, file, cards, optional points or '
                                             'points_file, point_cap and deck_banlist) and add their names to '
                                             'game_text in every language. Cards are '
                                             'named by English name, passcode (digits) or internal id ("id:4844"); '
                                             'status forbidden, limited, semi_limited or unlimited (removes a card '
                                             'of the base list). Every new card the player can obtain (in a pack, '
                                             'a CPU deck of --decks, a story gift of --story) is forbidden in each '
                                             'stock list; hidden new cards are left out.',
                                 epilog='Reads the new cards from ../bin2 next to <out> (run after add_cards.py). '
                                        'Writes <out>/<file>, <out>/limit*.bin for the stock lists, '
                                        '../bin2/game_{indx,text}_<l>.bin next to <out>, and the header with the '
                                        'RAM sizes taken from the largest list. A list with points prints '
                                        '"points: <n> cards, cap <cap>, fingerprint <8 hex>" and one line per '
                                        '--decks spec whose "banlist" matches its "deck_banlist" (total and cards '
                                        'over 3 copies; never stops the build). '
                                        '"banlist.py --fingerprint <points.json>" prints only the fingerprint line. '
                                        'With a point list, the game texts that name the current list (POINT_LABELS) '
                                        'get "Point List" versions, shown while that list is selected.')
    ap.add_argument('spec', nargs='*', help='banlist specs in menu order, e.g. variants/retro-genesys/banlists/'
                                            'eternal.json; none: the stock lists only, with the extra lists off')
    ap.add_argument('extracted_bin', help='extracted bin folder, e.g. extracted/Data_arc_pac/bin')
    ap.add_argument('out', help='output folder, e.g. variants/retro-genesys/pac/Data_arc_pac/bin')
    ap.add_argument('--header', help='C header to write, e.g. variants/retro-genesys/src/banlist_ext.h (BL_EXT the '
                                     'number of specs: mod/src/banlist_ext.asm adds them to the menu; list buffer, '
                                     'viewer and point table sizes for mod/src/banlist.c)')
    ap.add_argument('--decks', nargs='*', default=[], help='CPU deck specs the player can receive cards from')
    ap.add_argument('--story', action='append', default=[], help='story folder whose characters.json offer.gift '
                                                                 'lists give cards (repeatable; a missing folder is '
                                                                 'skipped)')
    ap.add_argument('--cards', nargs='*', default=[], help='card specs: a card with "verified": false (WC2011 pool, '
                                                          'not cleared yet) stops the build if it is obtainable')
    ap.add_argument('--rom11', help='WC2011 ROM, read when a spec has "base": "wc2011:<file>" (e.g. limit201009.bin)')
    a = ap.parse_args()
    if not os.path.isdir(a.extracted_bin):
        sys.exit(f'not found: {a.extracted_bin}')
    main(a.spec, a.extracted_bin, a.out, a.header, a.decks, a.story, a.cards, a.rom11)
