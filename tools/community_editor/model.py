"""Portable project data. No Dimension Break paths or ROM payloads belong here."""
import copy
import json
import re

FORMAT = 'wc-mod-project'
VERSION = 1
FORMAT_VERSION = 2
SECTIONS = {'packs': 1, 'decks': 1, 'cpus': 3, 'banlists': 1, 'patches': 1}
BASE_CPU_FIELDS = ('name', 'deck', 'deck_name', 'portrait', 'key_card', 'rating', 'talk')
NEWER = 'This project was made with a newer tool. Update the Workshop to open it.'
ADAPTER = 'wc2011-eu'
RARITIES = ('ultra', 'super', 'rare', 'common')
LANGS = 'efgisjk'
QOL = (
    {'id': 'cpu-speed', 'name': 'CPU speed', 'available': True,
     'reason': 'Makes the CPU think faster.'},
    {'id': 'view-mode', 'name': 'QoL', 'available': True,
     'reason': 'Adds View Mode and Duelist Info, speeds up menus and fixes small duel bugs.'},
    {'id': 'pack-opening', 'name': 'Better pack opening', 'available': True,
     'reason': 'Opens packs in 3D.'},
    {'id': 'flash-fixes', 'name': 'UI fixes', 'available': True,
     'reason': 'Fixes the white menu flash and other glitches.'},
    {'id': 'card-fixes', 'name': 'Fix card effects', 'available': True,
     'reason': "Fixes cards that don't work as written."},
    {'id': 'text-fixes', 'name': 'Fix text errors', 'available': True,
     'reason': 'Fixes typos and wrong card text.'},
    {'id': 'wfc-shop', 'name': 'Shop instead of WFC', 'available': True,
     'reason': 'Puts a Shop on the main menu in place of Nintendo WFC.'},
)


def project(base_sha1, packs, decks):
    return {'format': FORMAT, 'version': VERSION, 'name': 'Untitled mod',
            'game': ADAPTER, 'base_sha1': base_sha1, 'packs': copy.deepcopy(packs),
            'decks': copy.deepcopy(decks), 'opponents': [], 'base_cpus': {}, 'patches': [q['id'] for q in QOL if q['id'] != 'pack-opening'],
            'banlists': [], 'default_banlist': 'base'}


def working(data):
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError('The Workshop cannot read this project format.')
    if 'sections' not in data:
        if data.get('version') != VERSION:
            raise ValueError('The Workshop cannot read this project format.')
        p = copy.deepcopy(data)
        p.setdefault('base_cpus', {})
    else:
        fv = data.get('format_version')
        if type(fv) is not int or fv < 2:
            raise ValueError('The Workshop cannot read this project format.')
        if fv > FORMAT_VERSION:
            raise ValueError(NEWER)
        sections = data['sections']
        if not isinstance(sections, dict) or any(not isinstance(v, dict) or type(v.get('version')) is not int
                                                 or v['version'] < 1 for v in sections.values()):
            raise ValueError('Each project section needs a version.')
        for name, version in SECTIONS.items():
            if name in sections and sections[name]['version'] > version:
                raise ValueError(NEWER)
        for name in ('packs', 'decks'):
            if name not in sections:
                raise ValueError(f'The project has no {name} section.')
        get = lambda name, key, default: copy.deepcopy(sections.get(name, {}).get(key, default))
        p = {'format': FORMAT, 'version': VERSION, 'name': data.get('name'), 'game': data.get('game'),
             'base_sha1': data.get('base_sha1'), 'packs': get('packs', 'items', None),
             'decks': get('decks', 'items', None), 'opponents': get('cpus', 'items', []),
             'base_cpus': get('cpus', 'base', {}),
             'patches': get('patches', 'enabled', []), 'banlists': get('banlists', 'items', []),
             'default_banlist': get('banlists', 'default', 'base')}
        if sections.get('cpus', {}).get('version', 3) < 3 and isinstance(p['base_cpus'], dict):
            for o in p['base_cpus'].values():
                if isinstance(o, dict) and isinstance(o.get('talk'), list):
                    o['talk'] = {str(i): line for i, line in enumerate(o['talk'])}
        unknown = {k: v for k, v in sections.items() if k not in SECTIONS}
        if unknown:
            p['preserved'] = json.dumps(unknown, ensure_ascii=False)
    if isinstance(p.get('opponents'), list):
        for i, o in enumerate(p['opponents']):
            if isinstance(o, dict):
                o.setdefault('chara', 465 + i)
    return p


def preserved(p):
    raw = p.get('preserved')
    if raw is None:
        return {}
    try:
        sections = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        sections = None
    if not isinstance(sections, dict) or any(k in SECTIONS or not isinstance(v, dict) or type(v.get('version')) is not int
                                             for k, v in sections.items()):
        raise ValueError('Sections from other tools in this project cannot be read.')
    return sections


def to_file(p):
    sections = {'packs': {'version': 1, 'items': p['packs']},
                'decks': {'version': 1, 'items': p['decks']},
                'cpus': {'version': 3, 'items': p['opponents'], 'base': p.get('base_cpus', {})},
                'banlists': {'version': 1, 'items': p.get('banlists', []),
                             'default': p.get('default_banlist', 'base')},
                'patches': {'version': 1, 'enabled': p['patches']}}
    sections.update(preserved(p))
    return copy.deepcopy({'format': FORMAT, 'format_version': FORMAT_VERSION, 'game': p['game'],
                          'base_sha1': p['base_sha1'], 'name': p['name'], 'sections': sections})


def read_project(data, expected_sha1):
    data = working(data)
    if data.get('game') != ADAPTER or data.get('base_sha1') != expected_sha1:
        raise ValueError('This project was made for a different ROM.')
    if not isinstance(data.get('name'), str) or not data['name'].strip():
        raise ValueError('The project needs a name.')
    for key in ('packs', 'decks', 'opponents', 'patches'):
        if not isinstance(data.get(key), list):
            raise ValueError(f'{key} must be a list.')
    ids = set()
    for p in data['packs']:
        if not isinstance(p, dict):
            raise ValueError('Each pack must be an object.')
        pid = p.get('id')
        if type(pid) is not int or not (1 <= pid <= 81 or 97 <= pid <= 116) or pid in ids:
            raise ValueError(f'Pack ID {pid} is not valid or is used twice.')
        ids.add(pid)
        for key in ('name', 'desc'):
            if not isinstance(p.get(key), dict) or any(not isinstance(p[key].get(l), str) for l in LANGS):
                raise ValueError(f'Pack {pid}: {key} needs text in all seven languages.')
        cards = p.get('cards', {})
        if not isinstance(cards, dict) or set(cards) - set(RARITIES):
            raise ValueError(f'Pack {pid} has an unknown rarity.')
        for r, names in cards.items():
            if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
                raise ValueError(f'Pack {pid}: the {r} list has an empty or invalid card.')
        # Images travel with the project; never trust local paths from a shared project.
        if 'art' in p:
            raise ValueError('Pack images must be stored in the project, not linked from a file.')
        image = p.get('image')
        if image is not None:
            import base64
            import io
            from PIL import Image
            if not isinstance(image, str) or not image.startswith('data:image/png;base64,') or len(image) > 2000000:
                raise ValueError(f'Pack {pid}: the pack image is not a valid PNG.')
            try:
                raw = base64.b64decode(image.split(',', 1)[1], validate=True)
                with Image.open(io.BytesIO(raw)) as im:
                    if im.format != 'PNG' or im.size != (64, 128):
                        raise ValueError('Use a 64 × 128 PNG.')
                    im.verify()
            except Exception as e:
                raise ValueError(f'Pack {pid}: the pack image is not valid. {e}') from e
    files = set()
    for d in data['decks']:
        if not isinstance(d, dict) or not isinstance(d.get('file'), str) or d['file'] in files:
            raise ValueError('Each deck needs its own file name.')
        files.add(d['file'])
        for sec in ('main', 'extra', 'side'):
            if not isinstance(d.get(sec), list) or any(not isinstance(n, str) or not n.strip() for n in d[sec]):
                raise ValueError(f'Deck {d["file"]}: the {sec} list has an empty or invalid card.')
    charas = set()
    for i, o in enumerate(data['opponents']):
        if not isinstance(o, dict) or not isinstance(o.get('name'), str) or not isinstance(o.get('deck'), str):
            raise ValueError('Each CPU needs a name and a deck.')
        chara = o['chara']
        if type(chara) is not int or not 465 <= chara < 0x10000 or chara in charas:
            raise ValueError('Each added CPU needs a unique character ID from 465 upward.')
        charas.add(chara)
        if type(o.get('template_deck', 113)) is not int or not 0 <= o.get('template_deck', 113) <= 300:
            raise ValueError('CPU template deck must be a base game slot from 0 to 300.')
        if type(o.get('turbo', False)) is not bool or type(o.get('tag', False)) is not bool:
            raise ValueError('CPU turbo and tag options must be true or false.')
        if type(o.get('partner', 0)) is not int or not isinstance(o.get('team_name', ''), str):
            raise ValueError('A tag CPU needs a partner character ID and a team name.')
        check_cpu_fields(o)
        check_talk(o.get('talk'), list)
    base = data.get('base_cpus')
    if not isinstance(base, dict):
        raise ValueError('Changes to base game CPUs must be an object.')
    for key, o in base.items():
        if not re.fullmatch(r'\d{1,3}', key) or int(key) > 464:
            raise ValueError(f'“{key}” is not a base game character ID.')
        if not isinstance(o, dict) or set(o) - set(BASE_CPU_FIELDS):
            raise ValueError(f'The changes to base game CPU {key} have a field the Workshop does not know.')
        if any(k in o and not isinstance(o[k], str) for k in ('name', 'deck')):
            raise ValueError(f'The name and deck of base game CPU {key} must be text.')
        check_cpu_fields(o)
        check_talk(o.get('talk'), dict)
    if any(not isinstance(p, str) or p not in {q['id'] for q in QOL} for p in data['patches']):
        raise ValueError('The project turns on a patch the Workshop does not know.')
    lists = data.get('banlists', [])
    if not isinstance(lists, list) or len(lists) > 2:
        raise ValueError('A project can have one classic list and one points list.')
    seen = set()
    for bl in lists:
        if not isinstance(bl, dict) or bl.get('id') not in ('classic', 'points') or bl['id'] in seen:
            raise ValueError('A project can have one classic list and one points list.')
        seen.add(bl['id'])
        if not isinstance(bl.get('name'), str) or not bl['name'].strip():
            raise ValueError('Each banlist needs a name.')
        if not isinstance(bl.get('cards'), dict):
            raise ValueError('A banlist must pair each card with a number.')
        maximum = 3 if bl['id'] == 'classic' else 99
        if any(not isinstance(ref, str) or not ref.strip() or type(n) is not int or not 0 <= n <= maximum
               for ref, n in bl['cards'].items()):
            raise ValueError(f'{bl["name"]}: card values must be whole numbers from 0 to {maximum}.')
        if bl['id'] == 'points' and (type(bl.get('cap')) is not int or not 1 <= bl['cap'] <= 65535):
            raise ValueError('Deck point budget must be from 1 to 65535.')
    if data.get('default_banlist', 'base') not in seen | {'base'}:
        raise ValueError('The starting list is missing from the project.')
    preserved(data)
    return copy.deepcopy(data)


def check_cpu_fields(o):
    if type(o.get('portrait', 300)) is not int or not 0 <= o.get('portrait', 300) <= 464:
        raise ValueError('CPU portrait must be a base game portrait number from 0 to 464.')
    if not isinstance(o.get('key_card', 'id:4007'), str):
        raise ValueError('CPU key card must be a card reference.')
    if 'deck_name' in o and not isinstance(o['deck_name'], str):
        raise ValueError('CPU deck name must be text.')
    if 'rating' in o and (type(o['rating']) is not int or not 0 <= o['rating'] <= 65535):
        raise ValueError('CPU rating must be a whole number from 0 to 65535.')


def check_talk(talk, shape):
    if talk is None:
        return
    if shape is list and (not isinstance(talk, list) or len(talk) != 28):
        raise ValueError('CPU dialogue needs 28 lines.')
    if shape is dict and (not isinstance(talk, dict) or
                          any(not re.fullmatch(r'\d{1,2}', k) or int(k) > 27 for k in talk)):
        raise ValueError('Changed dialogue lines must be numbered from 0 to 27.')
    if any(not isinstance(line, str) for line in (talk if shape is list else talk.values())):
        raise ValueError('Each dialogue line must be text.')


def merged_talk(base, changes):
    return [changes.get(str(i), line) for i, line in enumerate(base)]


def prune_base_cpus(p, base):
    kept = {}
    for key, o in p.get('base_cpus', {}).items():
        changes = {k: v for k, v in o.items() if key not in base or v != base[key].get(k)}
        if key in base and isinstance(changes.get('talk'), dict):
            lines = base[key]['talk']
            changes['talk'] = {i: line for i, line in changes['talk'].items()
                               if int(i) >= len(lines) or line != lines[int(i)]}
            if not changes['talk']:
                del changes['talk']
        if changes:
            kept[key] = changes
    p['base_cpus'] = kept
    return p


def diagnostics(p, resolve, check_decks=None, placement=None, copy_key=None, base_names=None):
    """All draft errors remain visible and saveable; exporting must reject them."""
    issues = []
    def issue(message):
        issues.append(message)
    def card_id(n, context):
        cid = resolve(n)
        if cid is None:
            issue(f'{context}: unresolved card “{n}”.')
        return cid
    for pack in p['packs']:
        pid, cards = pack['id'], pack.get('cards', {})
        label = f'Pack {pid} ({pack["name"]["e"]})'
        if pid == 60:
            if cards:
                issue(f'{label}: All at Random cannot have its own card list.')
            continue
        if pid < 60 or pid >= 97:
            for r in RARITIES:
                if len(cards.get(r, [])) < (4 if r == 'common' else 1):
                    issue(f'{label}: needs at least {"4 Commons" if r == "common" else "1 " + r.capitalize()}.')
        if pid < 97 and 'price' in pack:
            issue(f'{label}: base game pack prices cannot be changed.')
        if pid >= 97 and (type(pack.get('price', 150)) is not int or not 1 <= pack.get('price', 150) <= 65535):
            issue(f'{label}: price must be a whole number from 1 to 65535 DP.')
        seen = set()
        for r, names in cards.items():
            for n in names:
                cid = card_id(n, label)
                key = cid if cid is not None else n.casefold()
                if key in seen:
                    issue(f'{label}: “{n}” is in the pack twice.')
                seen.add(key)
    for d in p['decks']:
        if check_decks is not None and d['file'] not in check_decks:
            continue
        label = f'Deck {d["file"]}'
        all_ids = []
        for sec, lo, hi in (('main', 40, 60), ('extra', 0, 15), ('side', 0, 15)):
            if not lo <= len(d[sec]) <= hi:
                issue(f'{label}: {sec} must contain {lo}–{hi} cards.')
            ids = [card_id(n, label) for n in d[sec]]
            all_ids += ids
            if placement:
                for n, cid in zip(d[sec], ids):
                    if cid is None:
                        continue
                    allowed = placement(cid)
                    if allowed == 'none' or sec != 'side' and allowed != sec:
                        issue(f'{label}: “{n}” cannot go in {sec}.')
        from collections import Counter
        logical = [copy_key(cid) if copy_key and cid is not None else cid for cid in all_ids]
        if any(n > 3 for cid, n in Counter(logical).items() if cid is not None):
            issue(f'{label}: a card has more than three copies across Main, Extra and Side.')
    if len(p['opponents']) > 196:
        issue('You can add up to 196 Free Duel CPUs.')
    deck_files = {d['file'] for d in p['decks']}
    base = p.get('base_cpus', {})
    cpus = [(o['name'], {'key_card': 'id:4007', **o}) for o in p['opponents']]
    cpus += [(o.get('name') or (base_names or {}).get(key) or f'CPU {key}', o) for key, o in base.items()]
    for label, o in cpus:
        if 'name' in o and not o['name'].strip():
            issue('Every CPU needs a name.')
        if 'deck' in o and o['deck'] not in deck_files:
            issue(f'CPU {label}: deck {o["deck"]} is missing.')
        if o.get('tag') and not o.get('team_name', '').strip():
            issue(f'CPU {label}: the team needs a name.')
        if 'key_card' in o:
            card_id(o['key_card'], f'CPU {label} key card')
        talk = o.get('talk', [])
        for i, line in (((int(k), v) for k, v in talk.items()) if isinstance(talk, dict) else enumerate(talk)):
            if not line.strip() or '\0' in line:
                issue(f'CPU {label}: dialogue line {i + 1} is empty or invalid.')
            for encoding in ('cp1252', 'cp932', 'euc-kr'):
                try:
                    line.encode(encoding)
                except UnicodeEncodeError:
                    issue(f'CPU {label}: dialogue line {i + 1} has a character the game cannot show.')
                    break
    if sum('talk' in o for _, o in cpus) > 78:
        issue('Only 78 CPUs can have their own dialogue.')
    for pid in p['patches']:
        q = next(q for q in QOL if q['id'] == pid)
        if not q['available']:
            issue(f'{q["name"]}: {q["reason"]}')
    for bl in p.get('banlists', []):
        for ref in bl['cards']:
            card_id(ref, bl['name'])
    for name, section in preserved(p).items():
        if section.get('rom', True) is not False:
            issue(f'Section “{name}” was made with a newer tool. Update the Workshop to export.')
    return issues


def encode(p):
    return (json.dumps(p, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
