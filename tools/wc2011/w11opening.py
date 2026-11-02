#!/usr/bin/env python3
"""Import the WC2010 pack reveal graphics; keep ROM data out of source control."""
import argparse
from pathlib import Path
import sys
import struct
import ndspy.lz10
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import game
import nttx


def build(rom10, out):
    rom = game.open_rom(rom10)
    if bytes(rom.idCode) not in (b'BYXE', b'BYXP'):
        raise ValueError('opening donor must be WC2010 USA (BYXE) or Europe (BYXP)')
    files = game.container_files(rom, 'Data_arc_pac/Getpack.pac')
    dst = Path(out) / 'Data_arc_pac' / 'Getpack'
    dst.mkdir(parents=True, exist_ok=True)
    names = ['rare.lz' + e for e in ('ncer', 'nanr', 'ncgr', 'nclr')]
    # The shop interface stays WC2011. Only the top-screen reveal background
    # and rarity animation come from the donor.

    # Keep the small list icons at their original playback speed. The reveal
    # uses the donor's 3D pack effects, not these NCER badges.
    for name in names:
        (dst / name).unlink(missing_ok=True)
    effect = game.container_files(rom, 'Data_arc_pac/effect.pac')
    edst = Path(out) / 'Data_arc_pac' / 'effect'
    edst.mkdir(parents=True, exist_ok=True)
    for name in effect:
        if name.startswith('pack_'):
            (edst / name).write_bytes(effect[name])
    overlay = bytes(rom.loadArm9Overlays()[10].data)
    lo, hi = 0x02164850, 0x02165060
    scene = bytearray(overlay[lo - 0x02159cc0:hi - 0x02159cc0])
    # Start the authored effect on the final flip, removing only the old
    # pre-effect hold. The model/material animation curves stay untouched.
    for address in (0x02165008, 0x02165018):
        assert struct.unpack_from('<I', scene, address-lo)[0] == 0xf532012c
        struct.pack_into('<I', scene, address-lo, 0xf532010e)
    relocs = []
    for at in range(0, len(scene), 4):
        value = struct.unpack_from('<I', scene, at)[0]
        if lo <= value < hi:
            relocs.append(at)
            struct.pack_into('<I', scene, at, value - lo)
    bdst = Path(out) / 'Data_arc_pac' / 'bin2'
    bdst.mkdir(parents=True, exist_ok=True)
    header = struct.pack('<4I', 0x3031504f, len(relocs), 0x02164c10-lo, 0x02164df8-lo)
    (bdst / 'opening10_scene.bin').write_bytes(header + struct.pack('<%dI' % len(relocs), *relocs) + scene)
    # The original back texture is required by the donor's model material.
    card = game.container_files(rom, 'Data_arc_pac/card.pac')
    indexes = card['card_5tx128_idx.bin']
    start, end = struct.unpack_from('<2I', indexes)
    (bdst / 'opening10_back.bin').write_bytes(nttx.lz_decompress(card['card_5tx128.bin'][start:end]))
    # WC2011 fixes BG0 to 8bpp. Expand WC2010's 4bpp grid into that format.
    blocks = nttx.blocks(nttx.lz_decompress(files['bg_ue.lz5bg']))
    bg = bytearray(blocks['BGDT'])
    msize = struct.unpack_from('<I', bg, 4)[0]
    pixels = bytes(v for x in bg[20 + msize:] for v in (x & 15, x >> 4))
    struct.pack_into('<H', bg, 0, 0xff01)
    struct.pack_into('<I', bg, 16, len(pixels))
    bg = bg[:20 + msize] + pixels
    palette = struct.pack('<I', 256) + blocks['PALT'][4:].ljust(512, b'\0')
    body = b''.join(tag + struct.pack('<I', len(data) + 8) + data
                    for tag, data in [(b'PALT', palette), (b'BGDT', bg)])
    grid = ndspy.lz10.compress(b'NTBG\xff\xfe\x00\x01' +
                             struct.pack('<IHH', len(body) + 16, 16, 2) + body)
    for name in ('bg_ue.lz5bg', 'bg_ue2.lz5bg'):
        (dst / name).write_bytes(grid)
    print(f'WC2010 opening: native scene + pack models/effects -> {dst.parent}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rom10')
    ap.add_argument('out', help='variant pac directory')
    args = ap.parse_args()
    build(args.rom10, args.out)
