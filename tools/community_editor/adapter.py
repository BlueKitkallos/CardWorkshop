"""WC2011 EU reader/writer. The UI and project model do not import this module."""
import base64
import hashlib
import io
import json
import sys
import tempfile
import re
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / 'wc2011'))
import carddb
import game
import modspec
import nttx
import pac
import patch
import wc2011cards
import w11packs
from ydc import Deck
from model import BASE_CPU_FIELDS, diagnostics, project, prune_base_cpus, read_project



FREE_DUEL_LISTS = (('duel', 0x71, 60), ('turbo', 0xd5, 20))
TAG_LISTS = (('tag', 0, 20), ('tag-turbo', 20, 10))
TAG_TEAMS = 0x0209b760
TAG_TEAM_NAMES = 0x129b
DUELIST_CHARA = 0x02019ca4
TAG_DUELIST_FIRST = 0x12d
FRAME_GROUPS = {0: 'normal', 15: 'normal', 2: 'fusion', 3: 'fusion', 4: 'ritual', 5: 'ritual', 10: 'token',
                12: 'synchro', 17: 'synchro', 18: 'synchro', 19: 'synchro', 13: 'spell', 14: 'trap'}

class Adapter:
    id = 'wc2011-eu'

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.profile = game.load('BYYP')
        self.sha1 = game.sha1(self.path)
        if self.sha1 != self.profile['clean_sha1']:
            raise ValueError('This is not a clean WC2011 Europe ROM, and modified ROMs cannot be used. '
                             f'Its SHA-1 is {self.sha1}; a clean one is {self.profile["clean_sha1"]}.')
        self.rom = game.open_rom(str(self.path))
        self.dbfiles = game.container_files(self.rom, self.profile['card_db']['container'])
        self.db = carddb.CardDB.load(self.dbfiles, self.profile)
        self.index = modspec.CardIndex(self.db)
        self.by_id = {c.id: c for c in self.db.cards[1:]}
        self.row_for_id = {c.id: i for i, c in enumerate(self.db.cards) if i}
        self.textfiles = game.container_files(self.rom, w11packs.TEXT_PAC)
        text = carddb.PackText.load(self.textfiles, self.profile)
        self.packs = []
        for pid in range(1, 82):
            p = {'id': pid, 'name': {l: text.names[pl][pid] for l, pl in w11packs.LANGS.items()},
                 'desc': {l: text.descs[pl][pid] for l, pl in w11packs.LANGS.items()}}
            if pid != 60:
                members = w11packs.pack_cards(self.db, pid)
                p['cards'] = {r: [f'id:{c.id}' for c in self.db.cards[1:] if c.id in members[r]]
                              for r in w11packs.RARITY}
            self.packs.append(p)
        self.deckfiles = game.container_files(self.rom, 'Data_arc_pac/deck.pac')
        self.decks = []
        for name, raw in sorted(self.deckfiles.items()):
            if name.endswith('.ydc'):
                d = Deck.parse(raw)
                self.decks.append({'file': name, 'name': name,
                                   **{s: [f'id:{cid}' for cid in getattr(d, s)] for s in ('main', 'extra', 'side')}})
        self.original_decks = {d['file']: d for d in self.decks}
        self.original_packs = {p['id']: p for p in self.packs}
        self._art = None
        self._pack_art = None
        self._png = {}
        self.opening_assets = None
        self._cpu_source = None
        self._cpu_metadata = None

    def fresh(self):
        return project(self.sha1, self.packs, self.decks)

    def resolve(self, ref):
        try:
            return self.index.deck_id(self.index.resolve(ref, 'project'))
        except (SystemExit, ValueError, KeyError):
            return None

    def catalog(self):
        preferred = {c.names['e']: self.resolve(c.names['e']) for c in self.db.cards[1:]}
        return [{'id': c.id, 'ref': f'id:{c.id}', 'name': c.names['e'],
                 'canonical_id': preferred[c.names['e']],
                 'placement': self.placement(c.id), 'frame': FRAME_GROUPS.get(c.frame, 'effect'),
                 'password': c.password, 'description': c.descs['e'],
                 'atk': c.atk, 'def': c.def_, 'level': c.level}
                for c in self.db.cards[1:]]

    def placement(self, cid):
        c = self.by_id[cid]
        if c.frame == 10:
            return 'none'
        return 'extra' if c.frame in (2, 3, 17, 18, 19) else 'main'

    def cpu_source(self):
        if self._cpu_source is None:
            import wc2011opponents
            self._cpu_source = wc2011opponents.Wc2011(str(self.path))
        return self._cpu_source

    def cpu_metadata(self):
        if self._cpu_metadata is not None:
            return self._cpu_metadata
        source = self.cpu_source()
        templates, names = {}, {}
        for chara, slot in sorted(source.char_deck.items()):
            if not 0 <= slot <= 300 or slot >= len(source.status):
                continue
            _, _, translated = source.display_name(slot)
            name = translated.get('e') or f'CPU {chara}'
            names[chara] = name
            filename = source.deck_file(slot)
            filename = filename.lower() + '.ydc' if filename else None
            if filename not in self.original_decks:
                continue
            _, rating, talk, *stats, key = source.status[slot]
            deck_name = (source.deck_name(slot) or {}).get('e') or filename
            portrait = chara if any(f'bu{chara:03d}_r{suffix}.lzncgr' in source.bustups for suffix in ('', '_e')) and chara <= 464 else 300
            templates.setdefault(slot, {'slot':slot, 'name':name, 'deck_name':deck_name,
                                        'file':filename, 'portrait':portrait, 'rating':rating,
                                        'key_card':f'id:{key}', 'stats':stats,
                                        'talk':source.talk_lines(talk - 1)['e'] if talk > 0 else []})
        portrait_ids = {int(m[1]) for key in source.bustups
                        if (m := re.fullmatch(r'bu(\d{3})_r(?:_e)?\.lzncgr', key)) and int(m[1]) <= 464}
        portraits = [{'id':i, 'name':names.get(i, f'Portrait {i}')} for i in portrait_ids]
        import ndspy.codeCompression
        import w11npc
        a9 = ndspy.codeCompression.decompress(bytes(self.rom.arm9))
        base = []

        def add(roster, duelist, **extra):
            chara = w11npc.char_deck(a9, duelist, DUELIST_CHARA)
            t = templates[source.char_deck[chara]]
            base.append({'chara':chara, 'list':roster, 'duelist':duelist, 'slot':t['slot'], 'name':t['name'],
                         'deck':t['file'], 'deck_name':t['deck_name'], 'portrait':t['portrait'],
                         'key_card':t['key_card'], 'rating':t['rating'], 'talk':t['talk'], **extra})
        for roster, first, count in FREE_DUEL_LISTS:
            for duelist in range(first, first + count):
                add(roster, duelist)
        import struct
        for roster, first, count in TAG_LISTS:
            for team in range(first, first + count):
                pair = struct.unpack_from('<2H', a9, TAG_TEAMS + 4 * team - 0x02000000)
                for i, duelist in enumerate(pair):
                    add(roster, duelist, team=source.text['e'][TAG_TEAM_NAMES + team],
                        partner=w11npc.char_deck(a9, pair[1 - i], DUELIST_CHARA))
        self._cpu_metadata = {'templates':sorted(templates.values(), key=lambda x:(x['name'], x['deck_name'])),
                              'portraits':sorted(portraits, key=lambda x:x['name']), 'base':base}
        return self._cpu_metadata

    def base_cpus(self):
        return {str(b['chara']): b for b in self.cpu_metadata()['base']}

    def tidy(self, p):
        if not p['base_cpus']:
            return p
        base = {k: {f: b[f] for f in BASE_CPU_FIELDS} for k, b in self.base_cpus().items()}
        return prune_base_cpus(p, base)

    def duelists(self, p):
        base = {b['chara']: b['duelist'] for b in self.cpu_metadata()['base']}
        added = sorted({o['chara'] for o in p['opponents'] if o.get('tag')} |
                       {o['partner'] for o in p['opponents'] if o.get('tag') and o.get('partner') not in base})
        return {**base, **{chara: TAG_DUELIST_FIRST + i for i, chara in enumerate(added)}}

    def validate(self, p):
        p = self.tidy(read_project(p, self.sha1))
        if {x['id'] for x in p['packs'] if x['id'] < 97} != set(self.original_packs):
            raise ValueError('Keep all 81 base game packs.')
        if not set(self.original_decks) <= {x['file'] for x in p['decks']}:
            raise ValueError('The project must keep every base game deck.')
        for d in p['decks']:
            if d['file'] not in self.original_decks and not re.fullmatch(r'user_[A-Za-z0-9_-]+\.ydc', d['file']):
                raise ValueError('Added deck files must be named user_<name>.ydc.')
        # Original CPU and rental decks sometimes follow rules unlike player decks.
        # Check only edits, leaving the clean game playable without alterations.
        base = self.base_cpus() if p['base_cpus'] else {}
        referenced = {o['deck'] for o in [*p['opponents'], *p['base_cpus'].values()] if 'deck' in o}
        changed = {d['file'] for d in p['decks'] if d['file'] not in self.original_decks or
                   any(d[s] != self.original_decks[d['file']][s] for s in ('main', 'extra', 'side'))}
        issues = diagnostics(p, self.resolve, check_decks=changed | referenced, placement=self.placement,
                             copy_key=lambda cid: self.resolve(self.by_id[cid].names['e']) or cid,
                             base_names={k: b['name'] for k, b in base.items()})
        if any(o.get('tag') for o in p['opponents']):
            charas = {b['chara'] for b in self.cpu_metadata()['base']} | {o['chara'] for o in p['opponents']}
            for o in p['opponents']:
                if o.get('tag') and (o.get('partner') not in charas or o.get('partner') == o['chara']):
                    issues.append(f'CPU {o["name"]}: pick a partner for the team.')
        for key, o in p['base_cpus'].items():
            if key not in base:
                issues.append(f'Character {key} is not a base game Free Duel CPU.')
                continue
            name = o.get('name') or base[key]['name']
            if 'deck' in o and base[key]['deck'] in changed:
                issues.append(f'CPU {name}: you edited its base game deck, but it now uses a different deck.')
            if 'portrait' in o and o['portrait'] not in {x['id'] for x in self.cpu_metadata()['portraits']}:
                issues.append(f'CPU {name}: portrait {o["portrait"]} is not in the game.')
        if 'pack-opening' in p['patches'] and self.opening_assets is None:
            issues.append('Import a WC2010 ROM for Better pack opening.')
        if p.get('banlists') and not any('unresolved card' in s for s in issues):
            from banlist_build import card_values
            for bl in p['banlists']:
                try:
                    values = card_values(self, bl)
                    if bl['id'] == 'classic' and sum(v != 3 for v in values.values()) > 248:
                        issues.append(f'{bl["name"]}: too many limited cards. The game allows 248, and each artwork counts.')
                except ValueError as e:
                    issues.append(str(e))
        return issues

    def points_preset(self):
        source = json.loads((Path(__file__).resolve().parent / 'data/retro-genesys.json').read_text(encoding='utf-8'))
        cards, skipped = {}, []
        for name, value in source['points'].items():
            cid = self.resolve(name)
            if cid is None or cid not in self.by_id:
                skipped.append(name)
                continue
            cards[f'id:{cid}'] = value
        return {'id': 'points', 'name': source['name'], 'cap': source['point_cap'], 'cards': cards,
                'skipped': skipped}

    def base_banlists(self):
        import banlist
        _, text = carddb.read_strtab(self.dbfiles['game_indx_e.bin'], self.dbfiles['game_text_e.bin'], 1, 0, 'e')
        result = []
        for filename, raw in sorted(self.textfiles.items()):
            if not re.fullmatch(r'limit\d{6}\.bin', filename):
                continue
            rows, header = banlist.parse(raw)
            name = text[int.from_bytes(header[:2], 'little') + banlist.NAME_BASE]
            cards = {f'id:{self.resolve(self.by_id[cid].names["e"])}':n for cid, n in rows if cid in self.by_id}
            result.append({'file':filename, 'name':name, 'cards':cards})
        return result

    def image(self, kind, ident):
        key = kind, ident
        if key in self._png:
            return self._png[key]
        from PIL import Image
        if kind == 'card':
            if ident not in self.row_for_id:
                raise ValueError('Unknown card.')
            if self._art is None:
                self._art = game.container_files(self.rom, 'Data_arc_pac/card.pac')['card_5bg64x64.bin']
            i, size = self.row_for_id[ident], wc2011cards.ART_ENTRY
            im = wc2011cards.bgdt_image(self._art[i * size:(i + 1) * size])
        elif kind == 'pack' and 1 <= ident <= 81:
            if self._pack_art is None:
                self._pack_art = game.container_files(self.rom, w11packs.ART_PAC)
            im = Image.fromarray(w11packs.decode_bgdt(nttx.lz_decompress(
                self._pack_art[f'l_pack{ident:02d}.lz5bg'])))
        elif kind == 'portrait':
            import bustup
            im = bustup.wc2011_portrait(self.cpu_source().bustups, ident)
        else:
            raise ValueError('Unknown image.')
        out = io.BytesIO()
        im.save(out, 'PNG')
        self._png[key] = out.getvalue()
        return self._png[key]

    def build(self, p):
        p = self.tidy(read_project(p, self.sha1))
        issues = self.validate(p)
        if issues:
            raise ValueError('Fix these before exporting:\n' + '\n'.join(issues[:30]))
        # Always reload a clean source. Repeated exports never accumulate edits.
        if game.sha1(self.path) != self.sha1:
            raise ValueError('The ROM changed after it was opened. Open it again.')
        rom = game.open_rom(str(self.path))
        db = carddb.CardDB.load(self.dbfiles, self.profile)
        text = carddb.PackText.load(self.textfiles, self.profile)
        changed = [s for s in p['packs'] if s != self.original_packs.get(s['id'])]
        specs = [(f'pack {s["id"]}', s) for s in p['packs']]
        w11packs.assign(db, specs)
        extra = w11packs.extra_rows(db, specs)
        if changed:
            w11packs.set_text(text, db, [(f'pack {s["id"]}', s) for s in changed])
        replacements = {}
        dbout = dict(self.dbfiles)
        # The editor changes only memberships and card rarity, not names, effects or sorting.
        for table in ('prop', 'pack'):
            name = db.name(table)
            dbout[name] = db.files()[name]
        if dbout != self.dbfiles:
            replacements[self.profile['card_db']['container']] = dbout
        if extra:
            import struct
            dbout[w11packs.EXTRA_FILE] = struct.pack(f'<{len(extra) + 2}I', w11packs.EXTRA_MAGIC, len(extra), *extra)
            replacements[self.profile['card_db']['container']] = dbout
        tout = dict(self.textfiles)
        tout.update(text.files())
        if tout != self.textfiles:
            replacements[w11packs.TEXT_PAC] = tout
        added = [s for s in p['packs'] if s['id'] >= 97]
        art_changes = [s for s in changed if s.get('image') or s['id'] >= 97]
        if art_changes:
            from PIL import Image
            art = game.container_files(rom, w11packs.ART_PAC)
            for s in art_changes:
                if s.get('image'):
                    im = Image.open(io.BytesIO(base64.b64decode(s['image'].split(',', 1)[1]))).convert('RGB')
                else:
                    # A new pack can reuse stock artwork until the author
                    # supplies a replacement; assets still come from the ROM.
                    im = Image.fromarray(w11packs.decode_bgdt(nttx.lz_decompress(art['l_pack01.lz5bg']))).convert('RGB')
                pid = s['id']
                art[f'l_pack{pid:02d}.lz5bg'] = w11packs.big_file(im, nttx.lz_decompress(art['l_pack01.lz5bg']))
                art[f'pack{pid:02d}.lz5bg'] = w11packs.icon_file(im, nttx.lz_decompress(art['pack01.lz5bg']), (32, 64))
                art[f's_pack{pid:02d}.lz5bg'] = w11packs.icon_file(im, nttx.lz_decompress(art['s_pack01.lz5bg']), (20, 40))
            replacements[w11packs.ART_PAC] = art
        dout = dict(self.deckfiles)
        for d in p['decks']:
            original = self.original_decks.get(d['file'])
            if original is None or any(d[s] != original[s] for s in ('main', 'extra', 'side')):
                stock = Deck.parse(self.deckfiles[d['file']]) if original else Deck()
                for sec in ('main', 'extra', 'side'):
                    setattr(stock, sec, [self.resolve(n) for n in d[sec]])
                dout[d['file']] = stock.build()
        if dout != self.deckfiles:
            replacements['Data_arc_pac/deck.pac'] = dout
        needs_runtime = bool(extra or added or p['opponents'] or p['base_cpus'] or p.get('banlists') or
                             {'flash-fixes', 'pack-opening', 'wfc-shop'} & set(p['patches']))
        runtime_report = []
        loose = {}
        if not replacements and not needs_runtime and not p['patches']:
            target = self.path.read_bytes()
        else:
            with tempfile.TemporaryDirectory(prefix='wc-project-build-') as folder:
                qol = {'cpu-speed', 'view-mode', 'flash-fixes', 'card-fixes', 'text-fixes'} & set(p['patches'])
                import w11speed
                import w11fast
                base = w11speed.Rom11(str(self.path))
                ui = 'flash-fixes' in qol
                w11fast.apply(base, str(Path(folder) / 'qol'), speed='cpu-speed' in qol,
                              view='view-mode' in qol, cutin=ui, fades=ui, sound=ui, display=ui,
                              card_fixes='card-fixes' in qol, text_fixes='text-fixes' in qol)
                base.save(str(Path(folder) / 'qol.nds'), compress=True)
                rom = game.open_rom(str(Path(folder) / 'qol.nds'))
                if needs_runtime:
                    import inject
                    from runtime_build import prepare
                    src, runtime_changes, runtime_report, loose = prepare(folder, self, p, extra)
                    for path, files in runtime_changes.items():
                        if path not in replacements:
                            replacements[path] = game.container_files(rom, path)
                        replacements[path].update(files)
                    for path, data in loose.items():
                        rom.setFileByName(path, data)
                    if 'flash-fixes' in qol and 'sound/ds_data_hed.sdat' in loose:
                        import w11sound
                        w11sound.fix_se_room(rom)
                for path, files in replacements.items():
                    rom.files[rom.filenames.idOf(path)] = pac.build(files)
                if replacements and {'card-fixes', 'text-fixes'} & qol:
                    import w11textfix
                    w11textfix.apply(rom, card='card-fixes' in qol, text='text-fixes' in qol, strict=False)
                if needs_runtime:
                    inject.apply(rom, str(src), str(Path(folder) / 'work'), windows='wfc-shop' in p['patches'])
                if added:
                    # Known loader save type: the new shop records need the
                    # expanded FLASH backup configured by shop.asm.
                    rom.idCode = b'YG8P'
            original = self.path.read_bytes()
            target = bytearray(rom.save(updateDeviceCapacity=True))
            target[0x1000:0x1004] = original[0x1000:0x1004]
            game.keep_header_crc32(target, original)
            capacity = 0x20000 << target[0x14]
            target.extend(b'\xff' * (capacity - len(target)))
            target = bytes(target)
        source = self.path.read_bytes()
        bps, _ = patch.create(source, target)
        if patch.apply(source, bps) != target:
            raise ValueError('The patch failed its self-check.')
        return bps, {'source_sha1': self.sha1, 'target_sha1': hashlib.sha1(target).hexdigest(),
                     'changed_archives': sorted(replacements), 'extra_memberships': len(extra),
                     'changed_files': sorted(loose),
                     'membership_runtime': bool(extra or added), 'added_packs': len(added),
                     'added_opponents': [r for r in runtime_report if 'base_chara' not in r],
                     'base_cpus': [r for r in runtime_report if 'base_chara' in r], 'patches': p['patches'],
                     'banlists': [bl['name'] for bl in p.get('banlists', [])],
                     'save_type': 'FLASH 2 Mbit' if added else 'EEPROM 512 Kbit',
                     'verified_bps': True}
