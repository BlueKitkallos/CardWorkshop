#!/usr/bin/env python3
"""Native proof of Card Workshop Tag Duel teams in the CPU Tag Duel and CPU Tag Turbo Duel lists, with no input.
A boot rig makes a fresh profile, sets the Free Duel mode and the team bits, and enters the opponent list scene.
GDB catches the record reads of the drawn rows, then calls the list builder and the team loader on the live list.
Usage: python3 tools/community_editor/tag_smoke/run.py --rom <clean WC2011 EU.nds> [--out build/community-editor-tag-smoke]
"""
import argparse
import copy
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

EDITOR = Path(__file__).resolve().parents[1]
ROOT = EDITOR.parents[1]
sys.path[:0] = [str(EDITOR), str(ROOT / 'tools'), str(ROOT / 'tools' / 'wc2011')]
from adapter import Adapter
import inject
import mlstate
import patch
import view_deal
from w11showcase import Gdb, FRAME_FN

ALL_PATCHES = ['cpu-speed', 'view-mode', 'flash-fixes', 'card-fixes', 'text-fixes', 'wfc-shop']
LIST = 0x021610a0
LIST_COUNT = LIST + 0xeeae
LIST_INDEX = LIST + 0xf320
LIST_PAGE = LIST + 0xefa2
LIST_ROW = LIST + 0xefb8
SCENE = 0x020b9970
LIST_BUILD = 0x02159180
TEAM_LOAD = 0x0215ad70
RECORD_READ = 0x0215bdec
RECORDS = 0x021247c8
SIDE_DECK = 0x020b8874
SIDE_NAME = 0x020b8888
SIDE_PORTRAIT = 0x020b8b18
SIDE_MAIN = 0x020b8c18
TEAM_TEXT = 0x020b8aa2
TEAM_PAIR = 0x02017778
DUELIST_CHARA = 0x02019ca4
SENTINEL = 0x63636363
SUB_DISPCNT = 0x04001000
MODES = {'tag': (0x2003, (1 << 0) | (1 << 1) | (1 << 2) | (1 << 5), list(range(20)), 49),
         'turbo': (0x2004, (1 << 20) | (1 << 21) | (1 << 23), list(range(20, 30)), 50)}


def project(a):
    p = a.fresh()
    d = copy.deepcopy(next(d for d in p['decks'] if len(d['main']) == 40))
    d.update(file='user_tagrig.ydc', name='Tag rig deck')
    p['decks'].append(d)
    base = {b['chara']: b for b in a.cpu_metadata()['base']}
    assert (base[301]['list'], base[401]['list']) == ('duel', 'turbo')
    p['opponents'] = [
        {'chara': 466, 'name': 'Rig Tag', 'deck': d['file'], 'portrait': 300, 'template_deck': 113,
         'key_card': 'id:4007', 'tag': True, 'partner': 301, 'team_name': 'Rig Team'},
        {'chara': 467, 'name': 'Rig Turbo', 'deck': d['file'], 'portrait': 300, 'template_deck': 113,
         'key_card': 'id:4007', 'tag': True, 'turbo': True, 'partner': 401, 'team_name': 'Rig Turbo Team'}]
    return p, d, base


def text(g, addr, n=58):
    return g.read(addr, n).split(b'\0')[0].decode('cp1252')


def session(image, syms, mode_name, out):
    mode, bits, base_teams, added = MODES[mode_name]
    inst = out / mode_name
    inst.mkdir(parents=True, exist_ok=True)
    cfg = mlstate.melon_config(str(inst), True)
    port = view_deal.free_port()
    gcfg = inst / 'cfg_gdb'
    view_deal.gdb_config(cfg, str(gcfg), port)
    toml = gcfg / 'melonDS' / 'melonDS.toml'
    toml.write_text(re.sub(r'(\[Instance0\.Gdb\.ARM9\]\n(?:[^\[\n].*\n)*?)BreakOnStartup = \w+',
                           lambda m: m.group(1) + 'BreakOnStartup = true', toml.read_text()))
    small = mlstate.xvfb
    mlstate.xvfb = lambda: small('800x1024x24')
    try:
        m = mlstate.Melon(str(image), str(gcfg))
    finally:
        mlstate.xvfb = small
    m.xdo('windowsize', m.win, '512', '790')
    result = {'mode': f'{mode:#x}', 'unlocked_bits': f'{bits:#x}'}
    try:
        g = Gdb(port)
        g.bp(syms['tag_rig_start'])
        g.go()
        g.reply()
        if g.reg(15) & ~1 != syms['tag_rig_start'] & ~1:
            raise AssertionError(f'first stop at {g.reg(15):#x}, not the boot rig')
        g.unbp(syms['tag_rig_start'])
        g.write(syms['tag_rig'] + 4, struct.pack('<3I', mode, bits, SENTINEL))
        g.ok(f'Z0,{RECORD_READ:x},4')
        g.go()
        want_rows = [t for t in base_teams if bits >> t & 1] + [added]
        hits = {}
        t0 = time.time()
        while set(hits) != set(want_rows) and time.time() - t0 < 90:
            g.reply()
            r = {n: g.reg(n) for n in (2, 3, 6, 9, 10)}
            team = g.u16(r[10] + 0xf320 + 2 * (r[9] + r[6]))
            hits.setdefault(team, {'row': r[9] + r[6], 'index_r3': r[3], 'record_addr': r[2],
                                   'record_bytes': list(g.read(r[2], 3))})
            g.go()
        g.halt()
        g.cmd(f'z0,{RECORD_READ:x},4')
        g.go()
        time.sleep(3)
        g.halt()
        n = g.u16(LIST_COUNT)
        screen_rows = list(struct.unpack(f'<{n}H', g.read(LIST_INDEX, 2 * n)))
        scene = struct.unpack('<2I', g.read(SCENE, 8))
        g.w32(SUB_DISPCNT, g.u32(SUB_DISPCNT) | 0x10000)
        g.go()
        time.sleep(1)
        subprocess.run(['import', '-window', m.win, str(out / f'{mode_name}_list.png')], env=m.env, check=True)
        g.halt()
        g.at_frame()
        regs = g.regs()
        g.w32(0x021268b4, (1 << 30) - 1)
        g.call(g.u32(syms['tag_rig'] + 16), LIST_BUILD, LIST)
        n = g.u16(LIST_COUNT)
        full_rows = list(struct.unpack(f'<{n}H', g.read(LIST_INDEX, 2 * n)))
        idx = full_rows.index(added) if added in full_rows else None
        setup = None
        if idx is not None:
            pair = g.call(TEAM_PAIR, added)
            g.write(LIST_PAGE, struct.pack('<H', idx // 5))
            g.write(LIST_ROW, struct.pack('<H', idx % 5))
            g.call(g.u32(syms['tag_rig'] + 16), TEAM_LOAD, LIST, 1)
            sides = []
            for side in (1, 3):
                main = SIDE_MAIN + 0xc0 * side
                sides.append({'side': side, 'deck': g.u32(SIDE_DECK + 4 * side),
                              'chara': g.u32(SIDE_PORTRAIT + 4 * side) & 0x7fffffff,
                              'name': text(g, SIDE_NAME + 0x3a * side),
                              'main_count': g.u32(main), 'main_first4': list(struct.unpack('<4H', g.read(main + 0xc, 8)))})
            setup = {'list_index': idx, 'pair': f'{pair:#x}',
                     'member_charas': [g.call(DUELIST_CHARA, pair & 0xffff), g.call(DUELIST_CHARA, pair >> 16)],
                     'team_text_side1': text(g, TEAM_TEXT + 0x3a), 'sides': sides}
        g.resume(regs)
        time.sleep(0.5)
        g.halt()
        g.detach()
    finally:
        m.stop()
    result.update({'scene': list(scene), 'screen_rows': screen_rows, 'want_screen_rows': want_rows,
                   'records': {str(k): {**v, 'record_addr': f'{v["record_addr"]:#x}'} for k, v in sorted(hits.items())},
                   'full_rows': full_rows, 'team_setup': setup})
    return result


def check(res, mode_name):
    mode, bits, base_teams, added = MODES[mode_name]
    errors = []
    if res['screen_rows'] != res['want_screen_rows']:
        errors.append(f'screen rows {res["screen_rows"]} != {res["want_screen_rows"]}')
    if res['full_rows'] != base_teams + [added]:
        errors.append(f'full rows {res["full_rows"]} != {base_teams + [added]}')
    for team in res['want_screen_rows']:
        h = res['records'].get(str(team))
        if h is None:
            errors.append(f'team {team}: no record read seen')
            continue
        addr = int(h['record_addr'], 16)
        if team < 49:
            want = {0: [3, 2, 1], 20: [6, 5, 4]}.get(team, [0, 0, 0])
            if addr != RECORDS + 4 * team or h['record_bytes'] != want:
                errors.append(f'team {team}: record {h}')
        elif RECORDS <= addr < RECORDS + 4 * 51 or h['record_bytes'] != [0, 0, 0]:
            errors.append(f'team {team}: record {h}')
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--out', default=str(ROOT / 'build' / 'community-editor-tag-smoke'))
    ap.add_argument('--variants', default='plain,full')
    args = ap.parse_args()
    out = Path(args.out).resolve()
    a = Adapter(args.rom)
    report = {}
    failed = False
    for variant in args.variants.split(','):
        p, d, base = project(a)
        p['patches'] = [] if variant == 'plain' else list(ALL_PATCHES)
        vout = out / variant
        vout.mkdir(parents=True, exist_ok=True)
        print(f'[{variant}] exporting with patches {p["patches"]}', flush=True)
        bps, built = a.build(p)
        (vout / 'export.bps').write_bytes(bps)
        import ndspy.rom
        rom = ndspy.rom.NintendoDSRom(patch.apply(a.path.read_bytes(), bps))
        inject.apply(rom, str(EDITOR / 'tag_smoke'), str(vout / 'work'), windows=False)
        syms = mlstate.symbols(str(vout / 'work'))
        image = vout / 'tag_rig.nds'
        rom.saveToFile(str(image))
        image.with_suffix('.sav').write_bytes(b'\xff' * 0x10000)
        teams = {o['chara']: o for o in p['opponents']}
        report[variant] = {'build': {k: built[k] for k in ('target_sha1', 'patches', 'added_opponents')}}
        for mode_name in MODES:
            print(f'[{variant}] {mode_name}: running', flush=True)
            res = session(image, syms, mode_name, vout)
            errors = check(res, mode_name)
            s = res['team_setup']
            o = teams[466 if mode_name == 'tag' else 467]
            partner = base[o['partner']]
            if s is None:
                errors.append('added team not in the full list')
            else:
                names = [x['name'] for x in s['sides']]
                if s['team_text_side1'] != o['team_name']:
                    errors.append(f'team text {s["team_text_side1"]!r}')
                if names != [o['name'], partner['name']]:
                    errors.append(f'member names {names}')
                if s['member_charas'] != [o['chara'], o['partner']] or [x['chara'] for x in s['sides']] != s['member_charas']:
                    errors.append(f'member charas {s["member_charas"]} / {[x["chara"] for x in s["sides"]]}')
                want_main = [a.resolve(n) for n in d['main'][:4]]
                if s['sides'][0]['main_count'] != len(d['main']) or s['sides'][0]['main_first4'] != want_main:
                    errors.append(f'first member deck {s["sides"][0]} != {len(d["main"])} {want_main}')
                if s['sides'][1]['deck'] != partner['slot'] or s['sides'][1]['main_count'] < 40:
                    errors.append(f'partner deck {s["sides"][1]} (slot {partner["slot"]})')
            res['errors'] = errors
            failed |= bool(errors)
            report[variant][mode_name] = res
            print(json.dumps(res, indent=1), flush=True)
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('FAILED' if failed else 'passed', flush=True)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
