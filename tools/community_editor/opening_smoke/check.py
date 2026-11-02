#!/usr/bin/env python3
"""No-input shop reveal check. Build the fixture as documented in README.md."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import mlstate


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rom', default='build/community-editor-opening/rig/opening.nds')
    ap.add_argument('--rarity', choices=['common', 'rare', 'super', 'ultra'], default='ultra')
    ap.add_argument('--skip', action='store_true')
    ap.add_argument('--record', action='store_true', help='muted MP4 preview')
    args = ap.parse_args()
    rom = (ROOT / args.rom).resolve()
    out = rom.parent.parent / (args.rarity + ('-skip' if args.skip else ''))
    out.mkdir(parents=True, exist_ok=True)
    cfg = mlstate.melon_config(str(out), False)
    config = Path(cfg) / 'melonDS' / 'melonDS.toml'
    config.write_text(config.read_text().replace('ShowOSD = true', 'ShowOSD = false'))
    elf = rom.parent / 'work/code.elf'
    nm = str(Path.home() / 'tools/arm-gnu-toolchain/bin/arm-none-eabi-nm')
    symbols = {name: int(addr, 16) for addr, _, name in
               (line.split() for line in subprocess.check_output([nm, str(elf)], text=True).splitlines()
                if len(line.split()) == 3)}
    m = mlstate.Melon(str(rom), cfg)
    rec = None
    try:
        if args.skip or args.rarity != 'ultra':
            # Set the fixture flag directly in RAM before the reveal; no menu
            # inputs. The fixture sends one B edge during the animation.
            time.sleep(1)
            data = bytearray(m.snapshot(str(rom.with_suffix('.ml3')), 3))
            struct.pack_into('<I', data, mlstate.ram_of(data) + symbols['opening_skip'] - 0x02000000, int(args.skip))
            struct.pack_into('<I', data, mlstate.ram_of(data) + symbols['opening_kind'] - 0x02000000, ['common', 'rare', 'super', 'ultra'].index(args.rarity))
            rom.with_suffix('.ml3').write_bytes(data)
            m.key('F3')
        if args.record:
            rec = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'x11grab',
                                    '-framerate', '60', '-video_size', '256x384', '-i', m.display + '+0,24',
                                    '-t', '19', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                                    str(out / 'preview.mp4')], env=m.env)
        time.sleep(18)
        data = m.snapshot(str(rom.with_suffix('.ml3')), 3)
        (out / 'complete.ml3').write_bytes(data)
        ram = mlstate.Ram(data)
        p = data.index(b'GP2A', 16)
        display = struct.unpack_from('<I', data, p + 16)[0]
        result = {'counter': ram.u16(0x02166b60),
                  'selection': ram.u16(0x02166b5c),
                  'scene': ram.u32(0x02159dd0),
                  'display_mode': display & 7,
                  'skip_triggered': ram.u32(symbols['opening_skip']) == 2,
                  'soundmask': ram.u32(symbols['opening_rig'] + 40),
                  'sound_first_counter': [ram.u32(symbols['opening_rig'] + 44 + i * 4) for i in range(4)]}
        store=0x02158d10
        entry=next(i for i in range(ram.u16(store+0x10a4)) if ram.u16(store+0x30+i*0x34)==1)
        result['opened_mask']=ram.u32(store+0x5c+entry*0x34)
        result['rarity'] = args.rarity
        result['ok'] = (result['counter'] == 0 and result['selection'] == 1 and
                        result['scene'] == 4 and result['display_mode'] == 0 and
                        (not args.skip or result['skip_triggered']) and bool(result['opened_mask'] & 1) and
                        (args.skip or result['soundmask'] == {'common':1,'rare':3,'super':5,'ultra':9}[args.rarity]))
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        subprocess.run(['import', '-window', 'root', '-crop', '256x384+0+24',
                        str(out / 'complete.png')], env=m.env, check=True)
        if rec:
            rec.wait(timeout=25)
        print(json.dumps(result, indent=2))
        if not result['ok']:
            raise SystemExit(1)
    finally:
        if rec and rec.poll() is None:
            rec.terminate()
            rec.wait()
        m.stop()


if __name__ == '__main__':
    main()
