"""Run: python3 -m unittest discover -s tools/community_editor -p 'test_*.py'.
Set WC_EDITOR_TEST_ROM for clean-ROM integration tests (no emulator inputs).
"""
import copy
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from adapter import Adapter
import carddb
import game
import modspec
import patch
import w11packs
from model import NEWER, diagnostics, encode, project, prune_base_cpus, read_project, to_file


def spec(pid, names):
    return {'id': pid, 'name': {l: f'Pack {pid}' for l in 'efgisjk'},
            'desc': {l: '' for l in 'efgisjk'}, 'cards': names}


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.card = carddb.Card(id=4007, packs=[3, 0, 0], pack_rarity=[2, 0, 0], rarity=2)
        self.db = type('DB', (), {'cards': [carddb.Card(), self.card]})()

    def test_shared_stock_preserves_old_primary_even_if_later(self):
        specs = [(str(pid), spec(pid, {}), [('Card', r, 4007)])
                 for pid, r in [(1, 'common'), (2, 'rare'), (3, 'ultra')]]
        self.assertEqual(w11packs.apply_stock(self.db, specs), [])
        self.assertEqual(self.card.packs[0], 3)
        self.assertEqual(self.card.rarity, 2)

    def test_removing_primary_chooses_remaining_membership(self):
        specs = [('one', spec(1, {}), [('Card', 'common', 4007)]), ('three', spec(3, {}), [])]
        w11packs.apply_stock(self.db, specs)
        self.assertEqual(self.card.packs[0], 1)
        self.assertEqual(self.card.rarity, 0)

    def test_membership_in_unedited_pack_is_retained(self):
        w11packs.apply_stock(self.db, [('one', spec(1, {}), [('Card', 'rare', 4007)])])
        self.assertEqual(self.card.packs[0], 3)

    def test_unresolved_references_are_saveable_and_block_export(self):
        p = project('test', [spec(61, {'common': ['Future card']})], [])
        self.assertEqual(read_project(p, 'test'), p)
        self.assertTrue(any('unresolved card' in s for s in diagnostics(p, lambda _: None)))

    def test_project_cannot_read_local_art_paths(self):
        p = project('test', [spec(61, {})], [])
        p['packs'][0]['art'] = {'background': '/etc/passwd'}
        with self.assertRaises(ValueError):
            read_project(p, 'test')

    def test_opponent_ids_and_references(self):
        p = project('test', [], [])
        p['opponents'] = [{'chara': 465, 'name': 'CPU', 'deck': 'missing.ydc'}]
        self.assertTrue(any('missing' in s for s in diagnostics(p, lambda _: 4007)))
        p['opponents'].append(dict(p['opponents'][0]))
        with self.assertRaises(ValueError):
            read_project(p, 'test')

    def test_extra_deck_placement_and_capacity(self):
        deck = {'file':'user_test.ydc', 'main':['Monster'] * 40, 'extra':['Spell'], 'side':[]}
        p = project('test', [], [deck])
        resolve = lambda ref: {'Monster':1, 'Spell':2, 'Fusion':3}.get(ref)
        placement = lambda cid: 'extra' if cid == 3 else 'main'
        issues = diagnostics(p, resolve, placement=placement)
        self.assertTrue(any('cannot go in extra' in s for s in issues))
        p['decks'][0]['extra'] = ['Fusion'] * 16
        issues = diagnostics(p, resolve, placement=placement)
        self.assertTrue(any('extra must contain 0–15' in s for s in issues))
        p['decks'][0]['extra'] = []
        p['decks'][0]['main'] = ['Fusion']
        self.assertTrue(any('cannot go in main' in s for s in diagnostics(p, resolve, placement=placement)))

    def test_point_values_and_budget_bounds(self):
        p = project('test', [], [])
        p['banlists'] = [{'id':'points', 'name':'Points', 'cap':100, 'cards':{'Future card':99}}]
        self.assertEqual(read_project(p, 'test')['banlists'][0]['cards']['Future card'], 99)
        p['banlists'][0]['cards']['Future card'] = 100
        with self.assertRaises(ValueError):
            read_project(p, 'test')
        p['banlists'][0]['cards']['Future card'] = 5
        p['banlists'][0]['cap'] = 0
        with self.assertRaises(ValueError):
            read_project(p, 'test')

    def test_custom_cpu_dialogue_shape(self):
        p = project('test', [], [])
        p['opponents'] = [{'name':'CPU', 'deck':'user_test.ydc', 'talk':['Ready.'] * 27}]
        with self.assertRaises(ValueError):
            read_project(p, 'test')

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_purchased_box_compaction_preserves_remaining_odds(self):
        # Compile the exact compactor used by the injected shop runtime.
        source = (Path(__file__).parent / 'runtime/shop.c').read_text()
        function = source.split('void community_box_compact_words', 1)[1].split('void community_box_compact(void)', 1)[0]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp)
            (path / 'compact.c').write_text('typedef unsigned int u32;\nvoid community_box_compact_words' + function)
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Werror', '-o', str(path / 'compact.so'),
                            str(path / 'compact.c')], check=True, capture_output=True)
            lib = ctypes.CDLL(str(path / 'compact.so'))
            slots = [0, 1, 0, 2, 3, 0, 1] + [0] * 9 + [2, 0, 3] + [0] * 45
            words = (ctypes.c_uint32 * 4)(*[sum(slots[i * 16 + j] << (j * 2) for j in range(16)) for i in range(4)])
            lib.community_box_compact_words(words)
            decoded = [(words[i // 16] >> (2 * (i % 16))) & 3 for i in range(64)]
            self.assertEqual(decoded, [1, 2, 3, 1, 2, 3] + [0] * 58)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_runtime_lookup_and_primary_fallback(self):
        # Exercise the exact shipped C runtime, including zero-valued Common
        # rarity, missing keys and lookups either side of a binary-search split.
        rows = [4007 | (2 << 16), 4007 | (3 << 16) | (4 << 24), 4500 | (42 << 16) | (3 << 24)]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp)
            shutil.copy(Path(__file__).parent / 'runtime/members.c', src)
            w11packs.write_header(tmp, [], rows)
            (src / 'fallback.c').write_text('unsigned original_pack_member(unsigned id,unsigned slot){return 7+slot;}\n'
                                           'unsigned original_pack_rarity(unsigned id,unsigned slot){return 2+slot;}\n')
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Werror', '-o', str(src / 'runtime.so'),
                            str(src / 'members.c'), str(src / 'fallback.c')], check=True, capture_output=True)
            lib = ctypes.CDLL(str(src / 'runtime.so'))
            self.assertEqual(lib.community_pack_rarity(4007, 2), 0)
            self.assertEqual(lib.community_pack_rarity(4007, 3), 4)
            self.assertEqual(lib.community_pack_rarity(4500, 42), 3)
            self.assertEqual(lib.community_pack_rarity(4007, 1), 2)
            self.assertEqual(lib.community_pack_rarity(4007, 32), 3)
            self.assertEqual(lib.community_pack_member(4007, 0, 2), 2)
            self.assertEqual(lib.community_pack_member(4007, 0, 3), 3)
            self.assertEqual(lib.community_pack_member(4008, 0, 2), 7)


class ProjectFormatTests(unittest.TestCase):
    def v1(self):
        decks = [{'file': f'user_{n}.ydc', 'name': n, 'main': [], 'extra': [], 'side': []} for n in 'ab']
        p = project('test', [spec(1, {'common': ['Card']})], decks)
        p['opponents'] = [{'name': 'A', 'deck': 'user_a.ydc'}, {'name': 'B', 'deck': 'user_b.ydc'}]
        return p

    def test_v1_migrates_with_fixed_cpu_ids(self):
        old = self.v1()
        p = read_project(old, 'test')
        self.assertEqual([o.pop('chara') for o in copy.deepcopy(p)['opponents']], [465, 466])
        self.assertEqual({k: v for k, v in p.items() if k != 'opponents'}, {k: v for k, v in old.items() if k != 'opponents'})
        f = to_file(p)
        self.assertEqual(f['sections']['cpus']['items'][1]['chara'], 466)
        del f['sections']['cpus']['items'][0]
        f['sections']['decks']['items'].reverse()
        q = read_project(f, 'test')
        self.assertEqual([(o['chara'], o['deck']) for o in q['opponents']], [(466, 'user_b.ydc')])
        self.assertFalse(any('missing' in s for s in diagnostics(q, lambda _: 1)))

    def test_unknown_sections_round_trip_and_rom_sections_block_export(self):
        f = to_file(read_project(self.v1(), 'test'))
        f['sections']['scenario'] = {'version': 3, 'rom': True, 'cues': {'465': [1.5, 'cpu:465'], '10': None}}
        f['sections']['notes'] = {'version': 1, 'rom': False, 'text': 'Été'}
        raw = encode(f)
        p = read_project(json.loads(raw), 'test')
        self.assertEqual(encode(to_file(json.loads(json.dumps(p)))), raw)
        issues = diagnostics(p, lambda _: 1)
        self.assertEqual([s for s in issues if 'newer tool' in s], ['Section “scenario” was made with a newer tool. Update the Workshop to export.'])
        f['sections']['decks']['version'] = 2
        with self.assertRaisesRegex(ValueError, NEWER):
            read_project(f, 'test')

    def test_base_cpu_changes_round_trip_reset_and_migrate(self):
        f = to_file(read_project(self.v1(), 'test'))
        self.assertEqual(f['sections']['cpus']['version'], 3)
        f['sections']['cpus']['base'] = {'301': {'name': 'Moja', 'rating': 900, 'talk': {'0': 'Hi', '25': 'Won'}},
                                         '401': {'rating': 1220}}
        raw = encode(f)
        p = read_project(json.loads(raw), 'test')
        self.assertEqual(encode(to_file(json.loads(json.dumps(p)))), raw)
        lines = ['Hi'] + ['...'] * 27
        base = {'301': {'name': 'Moja', 'rating': 680, 'talk': lines}, '401': {'rating': 1220}}
        self.assertEqual(prune_base_cpus(p, base)['base_cpus'], {'301': {'rating': 900, 'talk': {'25': 'Won'}}})
        p['base_cpus']['301'] = {'rating': 680, 'talk': {'25': '...'}}
        self.assertEqual(prune_base_cpus(p, base)['base_cpus'], {})
        v2 = copy.deepcopy(f)
        v2['sections']['cpus']['version'] = 2
        v2['sections']['cpus']['base'] = {'301': {'talk': lines[:25] + ['Won'] + lines[26:]}}
        p = prune_base_cpus(read_project(v2, 'test'), base)
        self.assertEqual(p['base_cpus'], {'301': {'talk': {'25': 'Won'}}})
        old = copy.deepcopy(f)
        old['sections']['cpus'] = {'version': 1, 'items': f['sections']['cpus']['items']}
        p = read_project(old, 'test')
        self.assertEqual(p['base_cpus'], {})
        self.assertEqual(to_file(p)['sections']['cpus']['base'], {})
        for bad in ({'301': {'turbo': True}}, {'465': {'rating': 1}}, {'301': {'talk': {'28': 'Hi'}}}):
            f['sections']['cpus']['base'] = bad
            with self.assertRaises(ValueError):
                read_project(f, 'test')
        f['sections']['cpus']['version'] = 4
        with self.assertRaisesRegex(ValueError, NEWER):
            read_project(f, 'test')

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / 'variants/retro-genesys').exists(), 'repository only')
    def test_points_preset_matches_repository_list(self):
        import export_public
        self.assertEqual((Path(__file__).parent / 'data/retro-genesys.json').read_text(encoding='utf-8'),
                         export_public.points_list(), 'run tools/community_editor/export_public.py')

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / 'variants/dimension-break/lang').exists(), 'repository only')
    def test_menu_labels_match_dimension_break_lang(self):
        import w11menu
        lang = Path(__file__).resolve().parents[2] / 'variants/dimension-break/lang'
        tables = {code: json.loads((lang / f'{code}.json').read_text(encoding='utf-8')) for code in 'fgis'}
        for key, english in w11menu.LABELS.items():
            for code, table in tables.items():
                self.assertEqual(w11menu.TRANSLATIONS[key][code], table.get(english), f'{key} {code}')


@unittest.skipUnless(os.environ.get('WC_EDITOR_TEST_ROM'), 'Set WC_EDITOR_TEST_ROM for ROM integration')
class RomIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = Adapter(os.environ['WC_EDITOR_TEST_ROM'])
        if os.environ.get('WC_EDITOR_TEST_ROM10'):
            from opening_assets import prepare
            cls.a.opening_assets = prepare(os.environ['WC_EDITOR_TEST_ROM10'], cls.a.rom)

    def test_clean_round_trip_and_images(self):
        a = self.a
        self.assertEqual(a.validate(a.fresh()), [])
        self.assertTrue(a.image('card', 4007).startswith(b'\x89PNG'))
        self.assertTrue(a.image('pack', 1).startswith(b'\x89PNG'))
        self.assertIn('cpu-speed', a.fresh()['patches'])
        self.assertNotIn('pack-opening', a.fresh()['patches'])
        rating = a.base_cpus()['301']['rating']
        bps, report = a.build({**a.fresh(), 'patches': [], 'base_cpus': {'301': {'rating': rating}}})
        self.assertEqual(report['source_sha1'], report['target_sha1'])
        self.assertEqual(patch.apply(a.path.read_bytes(), bps), a.path.read_bytes())

    def test_base_cpu_overrides_export(self):
        import struct
        import ndspy.rom
        from ydc import Deck
        import w11npc
        a, p = self.a, self.a.fresh()
        base = a.base_cpus()
        from collections import Counter
        self.assertEqual(Counter(b['list'] for b in base.values()), {'duel': 60, 'turbo': 20, 'tag': 40, 'tag-turbo': 20})
        regular, turbo = base['301'], base['401']
        self.assertEqual((regular['name'], turbo['list'], base['361']['team'], base['361']['partner']),
                         ('Moja', 'turbo', 'Harmonic Resonators', 362))
        d = copy.deepcopy(next(d for d in p['decks'] if len(d['main']) == 40))
        d.update(file='user_base.ydc', name='Base CPU deck')
        p['decks'].append(d)
        talk = list(regular['talk'])
        talk[0], talk[25] = 'Workshop line 0', 'Workshop tag win'
        p['base_cpus'] = {'301': {'name': 'Workshop Moja', 'deck_name': 'Workshop Deck', 'deck': d['file'],
                                  'portrait': 129, 'key_card': 'id:4007', 'rating': 2345,
                                  'talk': {'0': talk[0], '25': talk[25]}},
                          '401': {'name': 'Workshop Rider', 'portrait': 301, 'rating': 1999,
                                  'deck_name': turbo['deck_name']}}
        p['opponents'] = [{'chara': 465, 'name': 'Tag A', 'deck': d['file'], 'tag': True, 'partner': 301,
                           'team_name': 'Workshop Team'},
                          {'chara': 466, 'name': 'Tag B', 'deck': d['file'], 'tag': True, 'turbo': True,
                           'partner': 465, 'team_name': 'Workshop Turbo Team'}]
        p['patches'] = []
        self.assertEqual(a.validate(p), [])
        bps, report = a.build(p)
        self.assertEqual([(r['base_chara'], r['changed']) for r in report['base_cpus']],
                         [(301, ['deck', 'deck_name', 'key_card', 'name', 'portrait', 'rating', 'talk']),
                          (401, ['name', 'portrait', 'rating'])])
        rom = ndspy.rom.NintendoDSRom(patch.apply(a.path.read_bytes(), bps))
        clean_bin, built_bin = (game.container_files(r, 'Data_arc_pac/bin.pac') for r in (a.rom, rom))
        row = lambda files, slot: struct.unpack_from('<HHB5BH', files['enemystatus.bin'], slot * 12)
        for slot in range(301):
            if slot not in (regular['slot'], turbo['slot']):
                self.assertEqual(row(built_bin, slot), row(clean_bin, slot))
        got, old = row(built_bin, regular['slot']), row(clean_bin, regular['slot'])
        self.assertEqual((got[0], got[1], got[3:8], got[8]), (old[0], 2345, old[3:8], 4007))
        lines = built_bin['talkmsg_e.bin'].split(b'\0')
        self.assertEqual([s.decode() for s in lines[56 + (got[2] - 1) * 28:][:28]], talk)
        got, old = row(built_bin, turbo['slot']), row(clean_bin, turbo['slot'])
        self.assertEqual(got, (old[0], 1999, *old[2:]))
        decks = game.container_files(rom, 'Data_arc_pac/deck.pac')
        built = Deck.parse(decks[regular['deck']])
        self.assertEqual(built.main, [a.resolve(n) for n in d['main']])
        self.assertEqual(decks[regular['deck']][:8], a.deckfiles[regular['deck']][:8])
        self.assertEqual(decks[turbo['deck']], a.deckfiles[turbo['deck']])
        clean_bu, built_bu = (game.container_files(r, w11npc.DUEL_BU_PAC + '.pac') for r in (a.rom, rom))
        for ext in ('ncgr', 'ncer', 'nanr', 'nclr'):
            self.assertEqual(built_bu[f'bu301_r.lz{ext}'], clean_bu[f'bu129_r_e.lz{ext}'])
            self.assertEqual(built_bu[f'bu401_r.lz{ext}'], clean_bu[f'bu301_r.lz{ext}'])
        self.assertEqual(built_bin['character.bin'][turbo['slot']], clean_bin['character.bin'][regular['slot']])
        bin2 = game.container_files(rom, a.profile['card_db']['container'])
        text = carddb.read_strtab(bin2['game_indx_e.bin'], bin2['game_text_e.bin'], 1, 0, 'e')[1]
        moja, rider = text.index('Workshop Moja'), text.index('Workshop Rider')
        self.assertEqual(text[moja + 1], 'Workshop Deck')
        code = b''.join(bytes(s.data) for s in rom.loadArm9().sections)
        self.assertIn(struct.pack('<4H', regular['slot'], moja, turbo['slot'], rider), code)
        self.assertIn(struct.pack('<2H', regular['slot'] + 1, moja + 1), code)
        team, turbo_team = text.index('Workshop Team'), text.index('Workshop Turbo Team')
        self.assertIn(struct.pack('<12H', 49, 0, 0x12d, 0x71, team, 0, 50, 0x8000, 0x12e, 0x12d, turbo_team, 0), code)
        self.assertIn(struct.pack('<4H', 0x12d, 465, 0x12e, 466), code)
        self.assertEqual(rom.loadArm9().sections[0].data[0x17778:0x1777c], bytes.fromhex('7847c046'))
        ov07 = rom.loadArm9Overlays([7])[7].data
        self.assertEqual([ov07[at - 0x0214c840 + 3] for at in (0x21592f0, 0x215bdc4)], [0xeb, 0xeb])

    def test_shared_stock_rarities_are_in_patch_and_linked_runtime(self):
        import struct
        import ndspy.rom
        a, p = self.a, self.a.fresh()
        ref = p['packs'][0]['cards']['ultra'][0]
        for pid, rarity in [(2, 'common'), (3, 'rare')]:
            s = p['packs'][pid - 1]
            for values in s['cards'].values():
                if ref in values:
                    values.remove(ref)
            s['cards'][rarity].append(ref)
        self.assertEqual(a.validate(p), [])
        bps, report = a.build(p)
        self.assertEqual(report['extra_memberships'], 2)
        target = patch.apply(a.path.read_bytes(), bps)
        rom = ndspy.rom.NintendoDSRom(target)
        files = game.container_files(rom, a.profile['card_db']['container'])
        db = carddb.CardDB.load(files, a.profile)
        blob = files[w11packs.EXTRA_FILE]
        extra = struct.unpack(f'<{len(blob) // 4}I', blob)[2:]
        cid = int(ref.split(':')[1])
        for pid, rarity in [(1, 'ultra'), (2, 'common'), (3, 'rare')]:
            self.assertIn(cid, w11packs.pack_cards(db, pid, extra)[rarity])
        self.assertTrue(any(blob in bytes(s.data) for s in rom.loadArm9().sections))
        self.assertNotEqual(rom.arm9, a.rom.arm9)
        self.assertNotEqual(rom.loadArm9Overlays([10])[10].data, a.rom.loadArm9Overlays([10])[10].data)
        self.assertEqual(game.sha1(a.path), a.sha1)

    def test_edited_deck_and_pack_art_export(self):
        import base64
        import io
        import ndspy.rom
        from PIL import Image
        from ydc import Deck
        a, p = self.a, self.a.fresh()
        image = io.BytesIO()
        Image.new('RGB', (64, 128), '#5a9bde').save(image, 'PNG')
        p['packs'][0]['image'] = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        p['packs'][0]['name']['e'] = 'WORKSHOP TEST'
        d = next(d for d in p['decks'] if len(d['main']) == 40 and len(d['extra']) <= 15 and len(d['side']) <= 15)
        d['main'] = list(reversed(d['main']))
        bps, report = a.build(p)
        rom = ndspy.rom.NintendoDSRom(patch.apply(a.path.read_bytes(), bps))
        text = carddb.PackText.load(game.container_files(rom, w11packs.TEXT_PAC), a.profile)
        self.assertEqual(text.names['eng'][1], 'WORKSHOP TEST')
        got = Deck.parse(game.container_files(rom, 'Data_arc_pac/deck.pac')[d['file']])
        self.assertEqual(got.main, [a.resolve(n) for n in d['main']])
        self.assertIn(w11packs.ART_PAC, report['changed_archives'])

    def test_added_pack_cpu_custom_deck_and_qol_together(self):
        import ndspy.rom
        import struct
        a, p = self.a, self.a.fresh()
        s = copy.deepcopy(p['packs'][0])
        s.update(id=97, price=175)
        p['packs'].append(s)
        d = copy.deepcopy(next(d for d in p['decks'] if len(d['main']) == 40))
        d.update(file='user_test.ydc', name='Community CPU deck')
        p['decks'].append(d)
        p['opponents'] = [{'name': 'Community CPU', 'chara':465, 'deck':d['file'],
                           'portrait':300, 'template_deck':113, 'key_card':'id:4007'}]
        p['patches'] = ['cpu-speed', 'view-mode', 'flash-fixes', 'card-fixes', 'text-fixes', 'wfc-shop']
        p['banlists'] = [{'id':'classic', 'name':'Community classic', 'cards':{'id:4007':1}},
                        {'id':'points', 'name':'Community points', 'cap':100, 'cards':{'id:4007':99}}]
        p['default_banlist'] = 'points'
        if a.opening_assets:
            p['patches'].append('pack-opening')
        self.assertEqual(a.validate(p), [])
        bps, report = a.build(p)
        target = patch.apply(a.path.read_bytes(), bps)
        rom = ndspy.rom.NintendoDSRom(target)
        self.assertEqual(bytes(rom.idCode), b'YG8P')
        dbfiles = game.container_files(rom, a.profile['card_db']['container'])
        db = carddb.CardDB.load(dbfiles, a.profile)
        for rarity, refs in s['cards'].items():
            self.assertEqual(w11packs.pack_cards(db, 97)[rarity], {a.resolve(n) for n in refs})
        decks = game.container_files(rom, 'Data_arc_pac/deck.pac')
        self.assertIn('mod465.ydc', decks)
        self.assertIn('user_test.ydc', decks)
        status = game.container_files(rom, 'Data_arc_pac/bin.pac')['enemystatus.bin']
        self.assertEqual(struct.unpack_from('<H', status, 301 * 12)[0], 301)
        self.assertEqual(report['added_opponents'][0]['deck_slot'], 301)
        self.assertNotEqual(rom.loadArm9Overlays([2])[2].data, a.rom.loadArm9Overlays([2])[2].data)
        self.assertNotEqual(rom.loadArm9Overlays([7])[7].data, a.rom.loadArm9Overlays([7])[7].data)
        import banlist
        files = game.container_files(rom, 'Data_arc_pac/bin.pac')
        self.assertIn((4007, 1), banlist.parse(files['limit_community_classic.bin'])[0])
        raw = files['limit_community_points.bin']
        offset = 8 + 2 * struct.unpack_from('<H', raw)[0]
        self.assertEqual(raw[offset:offset + 4], b'PNT1')
        cap, n = struct.unpack_from('<HH', raw, offset + 4)
        self.assertEqual(cap, 100)
        ids = struct.unpack_from(f'<{n}H', raw, offset + 8)
        values = raw[offset + 8 + n * 2:offset + 8 + n * 3]
        self.assertEqual(dict(zip(ids, values))[4007], 99)
        if a.opening_assets:
            self.assertIn('opening10_scene.bin', dbfiles)
            self.assertEqual(report['changed_files'], ['sound/ds_data_hed.sdat', 'sound/sound_data.sdat'])
        import w11sound
        hed = rom.getFileByName(w11sound.HED_PATH)
        self.assertTrue(struct.unpack_from('<I', hed, 4)[0] & w11sound.NO_STREAM_BUFFER)
        w11sound.fix_se_room(rom)
        self.assertEqual(rom.getFileByName(w11sound.HED_PATH), hed)
        import w11textfix
        self.assertEqual(w11textfix.verify(rom), [])
        import w11fast
        import w11speed
        with tempfile.TemporaryDirectory() as tmp:
            qol = w11speed.Rom11(str(a.path))
            w11fast.apply(qol, tmp)
            qol.save(str(Path(tmp) / 'qol.nds'), compress=True)
            ref = ndspy.rom.NintendoDSRom.fromFile(str(Path(tmp) / 'qol.nds'))
        arm9 = rom.loadArm9()
        images = lambda r: {'arm9': r.loadArm9().sections[0].data,
                            **{i: ov.data for i, ov in r.loadArm9Overlays().items()}}
        clean, want, got = images(a.rom), images(ref), images(rom)
        params, lit = arm9.codeSettingsOffs, w11fast.ARENA_HI_LIT - 0x02000000
        allowed = {*range(params, params + 0x20), *range(lit, lit + 4)}
        lost = [(k, i) for k, data in want.items() for i in range(len(clean[k]))
                if data[i] != clean[k][i] and got[k][i] != data[i] and not (k == 'arm9' and i in allowed)]
        self.assertEqual(lost, [])
        top = struct.unpack_from('<I', arm9.sections[0].data, w11fast.ARENA_HI_LIT - 0x02000000)[0]
        blocks = sorted((s.ramAddress, s.ramAddress + len(s.data) + s.bssSize) for s in arm9.sections[1:]
                        if top <= s.ramAddress < w11fast.ARENA_HI)
        self.assertEqual(blocks[0][0], top)
        self.assertTrue(all(e <= b for (_, e), (b, _) in zip(blocks, blocks[1:])), blocks)
        self.assertLessEqual(blocks[-1][1], w11fast.ARENA_HI)
        self.assertEqual(struct.unpack_from('<I', next(s.data for s in arm9.sections[1:]
                                                        if s.ramAddress == blocks[-1][0]), 4)[0], 0x31314453)
        fixture = Path(__file__).resolve().parents[2] / 'build/community-editor-combined'
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / 'combined.nds').write_bytes(target)
        (fixture / 'combined.bps').write_bytes(bps)
        self.assertEqual(game.sha1(a.path), a.sha1)


if __name__ == '__main__':
    unittest.main()
