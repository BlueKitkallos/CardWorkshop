#!/usr/bin/env python3
"""No-input native main-menu probe for the "Shop instead of WFC" export option.
Usage: python3 tools/community_editor/menu_smoke/run.py --rom <clean WC2011 EU.nds>
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import struct
import sys
import time

EDITOR = Path(__file__).resolve().parents[1]
ROOT = EDITOR.parents[1]
sys.path.insert(0, str(EDITOR))
from adapter import Adapter
import inject
import mlstate
import ndspy.rom
import patch

CTX = 0x02236450
MODES = ['main', 'shop', 'duelist', 'settings', 'legacy', 'wireless_return']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--out', default='build/community-editor-menu-smoke')
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    a = Adapter(args.rom)
    p = a.fresh()
    d = copy.deepcopy(next(d for d in p['decks'] if len(d['main']) == 40))
    d.update(file='user_menu.ydc', name='Menu deck')
    p['decks'].append(d)
    p['opponents'] = [{'chara': 465, 'name': 'Community CPU', 'deck': d['file'], 'portrait': 300,
                       'template_deck': 113, 'key_card': 'id:4007'}]
    p['banlists'] = [{'id': 'points', 'name': 'Community points', 'cap': 100, 'cards': {'id:4007': 99}}]
    p['patches'] = ['cpu-speed', 'view-mode', 'flash-fixes', 'wfc-shop']
    bps, _ = a.build(p)
    rom = ndspy.rom.NintendoDSRom(patch.apply(a.path.read_bytes(), bps))
    src = out / 'src'
    shutil.rmtree(src, ignore_errors=True)
    src.mkdir()
    shutil.copy(ROOT / 'mod/test/w11_menu/src/menu_rig.c', src)
    shutil.copy(ROOT / 'mod/test/w11_menu/src/menu_rig_stubs.S', src)
    for name in ('hooks.asm', 'stubs.S'):
        shutil.copy(Path(__file__).parent / name, src)
    inject.apply(rom, str(src), str(out / 'work'), windows=False)
    syms = mlstate.symbols(str(out / 'work'))
    image = out / 'menu.nds'
    rom.saveToFile(str(image))
    image.with_suffix('.sav').write_bytes(b'\xff' * 0x40000)
    state = image.with_suffix('.ml3')
    m = mlstate.Melon(str(image), mlstate.melon_config(str(out), False))
    results = {}
    try:
        time.sleep(4)
        seed = m.snapshot(str(state), 3)
        for mode, name in enumerate(MODES, 1):
            data = bytearray(seed)
            struct.pack_into('<I', data, mlstate.ram_of(data) - 0x02000000 + syms['menu_rig_mode'], mode)
            state.write_bytes(data)
            m.key('F3')
            time.sleep(4)
            r = mlstate.Ram(m.snapshot(str(state), 3))
            count = r.u16(CTX + 24)
            rows = [r.u32(r.u32(CTX + 56 + i * 4)) for i in range(min(count, 16))]
            results[name] = dict(phase=r.u32(syms['menu_rig_phase']), count=count, rows=rows)
            print(name, {k: [hex(x) for x in v] if k == 'rows' else v for k, v in results[name].items()}, flush=True)
    finally:
        m.stop()
    (out / 'result.json').write_text(json.dumps(results, indent=2) + '\n')
    assert all(results[k]['phase'] == 2 for k in MODES[:5]), results
    assert results['shop']['rows'] == [0x5003, 0x5005], results['shop']
    assert results['duelist']['rows'] == [0x5001, 0x5002, 0x5004, 0x5006, 0x5008], results['duelist']
    assert results['settings']['rows'][-1] == 0x6000 and 0x2008 in results['settings']['rows'], results['settings']
    assert results['wireless_return']['rows'][0] == 0x3001, results['wireless_return']
    assert not {0x3002, 0x3003} & set(results['wireless_return']['rows']), results['wireless_return']
    print('passed', flush=True)


if __name__ == '__main__':
    main()
