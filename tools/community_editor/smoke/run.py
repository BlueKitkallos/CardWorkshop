#!/usr/bin/env python3
"""Native integration smoke, using a direct boot rig and no gameplay/menu inputs.
Usage: python3 tools/community_editor/smoke/run.py --rom <clean WC2011 EU.nds>
Requires the existing local melonDS + Xvfb setup used by the project's rigs.
"""
import argparse
import copy
import json
from pathlib import Path
import struct
import sys
import time

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
from adapter import Adapter
import game
import inject
import mlstate
import patch


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--out', default='build/community-editor-smoke')
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    a = Adapter(args.rom)
    p = a.fresh()
    for pid, rarity in [(2, 'common'), (3, 'rare')]:
        s = p['packs'][pid - 1]
        for names in s['cards'].values():
            if 'id:4007' in names:
                names.remove('id:4007')
        s['cards'][rarity].append('id:4007')
    added = copy.deepcopy(p['packs'][0])
    added.update(id=97, price=150)
    for lang in added['name']:
        added['name'][lang] = 'COMMUNITY TEST'
    p['packs'].append(added)
    d = copy.deepcopy(next(d for d in p['decks'] if len(d['main']) == 40))
    d.update(file='user_smoke.ydc', name='Smoke deck')
    p['decks'].append(d)
    p['opponents'] = [{'chara':465, 'name':'Community CPU', 'deck':d['file'],
                       'portrait':300, 'template_deck':113, 'key_card':'id:4007'}]
    base = {b['chara']: b for b in a.cpu_metadata()['base']}
    regular, turbo = base[301], base[401]
    assert (regular['list'], turbo['list']) == ('duel', 'turbo')
    p['opponents'] += [{'chara':466, 'name':'Smoke Tag', 'deck':d['file'], 'portrait':300, 'template_deck':113,
                        'key_card':'id:4007', 'tag':True, 'partner':301, 'team_name':'Smoke Team'},
                       {'chara':467, 'name':'Smoke Turbo Tag', 'deck':d['file'], 'portrait':300, 'template_deck':113,
                        'key_card':'id:4007', 'tag':True, 'turbo':True, 'partner':466, 'team_name':'Smoke Turbo Team'}]
    p['base_cpus'] = {'301': {'name': 'Smoke Moja', 'deck_name': 'Smoke Deck', 'deck': d['file'], 'portrait': 129,
                              'key_card': 'id:4007', 'rating': 2345, 'talk': {str(i): f'Smoke line {i}' for i in range(28)}},
                      '401': {'name': 'Smoke Rider', 'deck': d['file'], 'portrait': 301, 'rating': 1999}}
    p['patches'] = ['cpu-speed', 'view-mode', 'flash-fixes']
    bps, report = a.build(p)
    (out / 'export.bps').write_bytes(bps)
    import ndspy.rom
    rom = ndspy.rom.NintendoDSRom(patch.apply(a.path.read_bytes(), bps))
    inject.apply(rom, str(EDITOR / 'smoke'), str(out / 'work'), windows=False)
    syms = mlstate.symbols(str(out / 'work'))
    image = out / 'smoke.nds'
    rom.saveToFile(str(image))
    image.with_suffix('.sav').write_bytes(b'\xff' * 0x40000)
    cfg = mlstate.melon_config(str(out), True)
    m = mlstate.Melon(str(image), cfg)
    try:
        # Let the directly constructed shop settle and the one-shot probe run.
        time.sleep(12)
        state = image.with_suffix('.ml1')
        if not m.snapshot(str(state), 1):
            raise RuntimeError('Could not capture the native probe state.')
    finally:
        m.stop()
    ram = mlstate.main_ram(str(state))
    address = syms['community_smoke']
    head = struct.unpack_from('<5I', ram, address - mlstate.MAIN)
    if head[0] != 0x434d534b or head[1] != 3:
        raise AssertionError(f'Probe did not finish: {head}')
    rows = []
    for i, (pid, mask) in enumerate([(1,8),(2,1),(3,2),(97,8)]):
        row = struct.unpack_from('<7I6H', ram, address - mlstate.MAIN + 20 + i * 40)
        assert row[0] == pid and row[1] > 0, row
        assert row[6] == mask, (pid, row[6], mask)
        draw = list(row[7:12])
        assert len(set(draw)) == 5 and all(a.resolve(f'id:{cid}') is not None for cid in draw), draw
        wanted = {a.resolve(n) for values in next(s for s in p['packs'] if s['id'] == pid)['cards'].values() for n in values}
        assert set(draw) <= wanted, (pid, draw)
        rows.append({'pack':pid, 'count':row[1], 'common_rare_super_ultra':list(row[2:6]),
                     'shared_card_mask':row[6], 'draw':draw})
    assert head[4] == 301, head
    status = game.container_files(rom, 'Data_arc_pac/bin.pac')['enemystatus.bin']
    want_main = [a.resolve(n) for n in d['main'][:4]]
    cpus = []
    for k, (b, o) in enumerate([(regular, p['base_cpus']['301']), (turbo, p['base_cpus']['401'])]):
        row = struct.unpack_from('<7I4H60s60s', ram, address - mlstate.MAIN + 180 + k * 156)
        chara, deck, portrait, rating, key, talk, count = row[:7]
        name, deck_name = (t.split(b'\0')[0].decode('cp1252') for t in row[11:13])
        built = struct.unpack_from('<HHB5BH', status, b['slot'] * 12)
        got = {'chara': chara, 'deck': deck, 'portrait': portrait & 0x7fffffff, 'rating': rating, 'key': key,
               'talk': talk, 'main_count': count, 'main': list(row[7:11]), 'name': name, 'deck_name': deck_name}
        want = {'chara': b['chara'], 'deck': b['slot'], 'portrait': b['chara'], 'rating': o['rating'],
                'key': a.resolve(o['key_card']) if 'key_card' in o else int(b['key_card'][3:]), 'talk': built[2] - 1, 'main_count': len(d['main']),
                'main': want_main, 'name': o['name'], 'deck_name': o.get('deck_name', b['deck_name'])}
        assert got == want, (got, want)
        cpus.append(got)
    assert cpus[0]['talk'] >= 177, cpus[0]
    tags = []
    for k, (members, team_name, pair) in enumerate([((466, 301), 'Smoke Team', 0x12d | 0x71 << 16),
                                                     ((467, 466), 'Smoke Turbo Team', 0x12e | 0x12d << 16)]):
        row = struct.unpack_from('<4I40s60s', ram, address - mlstate.MAIN + 492 + k * 116)
        got = {'stock_team_0': row[0], 'pair': row[1], 'members': list(row[2:4]),
               'name': row[4].split(b'\0')[0].decode('cp1252'), 'first_member_name': row[5].split(b'\0')[0].decode('cp1252')}
        want = {'stock_team_0': 0xae00ad, 'pair': pair, 'members': list(members), 'name': team_name,
                'first_member_name': 'Smoke Tag' if k == 0 else 'Smoke Turbo Tag'}
        assert got == want, (got, want)
        tags.append(got)
    result = {'state':'passed', 'cpu_character_465_deck':head[4], 'packs':rows, 'base_cpus':cpus, 'tag_teams':tags, 'build':report}
    (out / 'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
