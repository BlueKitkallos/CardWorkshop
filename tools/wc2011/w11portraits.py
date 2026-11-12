"""WC2011 8bpp animated portrait bundles, with one palette and shared OBJ blocks."""
import json
import os
import struct

from PIL import Image, ImageOps

import bustup

TALK_OBJ_BYTES = 0xe000

def labels(count):
    names = [f'CellAnime{i}\0'.encode() for i in range(count)]
    offsets, offset = [], 0
    for name in names:
        offsets.append(offset)
        offset += len(name)
    body = struct.pack(f'<{count}I', *offsets) + b''.join(names)
    return b'LBAL' + struct.pack('<I', 8 + len(body)) + body


def static_nanr(count):
    """One static animation per dialogue pose, using the stock cell-index element type."""
    seq = b''.join(struct.pack('<HHIII', 1, 0, 0x10000, 2, i * 8) for i in range(count))
    frames = b''.join(struct.pack('<IHH', i * 4, 4, 0xbeef) for i in range(count))
    indices = b''.join(struct.pack('<HH', i, 0xbeef) for i in range(count))
    body = struct.pack('<HHIIIII', count, count, 24, 24 + len(seq), 24 + len(seq) + len(frames), 0, 0)
    body += seq + frames + indices
    return bustup.nitro(b'RNAN', 0x0100,
                        [b'KNBA' + struct.pack('<I', len(body) + 8) + body,
                         labels(count), b'TXEU' + struct.pack('<II', 12, 0)])


def face_overlays(frame_indices, w, h, box):
    """Frame 0 as whole 32x64 blocks; every other frame adds 32x16 objects over the pixels that differ.

    Objects earlier in a cell are drawn on top, as stock portraits do for their faces.
    """
    def cut(indices, bx, by, bw, bh):
        return b''.join(indices[(by + y) * w + bx:(by + y) * w + bx + bw] for y in range(bh))

    tiles, blocks = bytearray(), {}

    def name(block, bw, bh):
        if block not in blocks:
            blocks[block] = len(tiles) // bustup.UNIT
            for ty in range(0, bh, 8):
                for tx in range(0, bw, 8):
                    for y in range(8):
                        tiles.extend(block[(ty + y) * bw + tx:(ty + y) * bw + tx + 8])
        return blocks[block]

    base = frame_indices[0]
    under = []
    for by in range(0, h, 64):
        for bx in range(0, w, 32):
            block = cut(base, bx, by, 32, 64)
            if any(block):
                under.append(struct.pack('<HHH', ((by + box[1]) & 0xff) | 0xa000, ((bx + box[0]) & 0x1ff) | 0xc000, name(block, 32, 64)))
    cells = []
    for indices in frame_indices:
        over = []
        if indices != base:
            if any(a and not b for a, b in zip(base, indices)):
                raise ValueError('portrait expressions must keep every opaque pixel of the first frame opaque')
            for by in range(0, h, 16):
                for bx in range(0, w, 32):
                    block = cut(indices, bx, by, 32, 16)
                    if block != cut(base, bx, by, 32, 16):
                        over.append(struct.pack('<HHH', ((by + box[1]) & 0xff) | 0x6000, ((bx + box[0]) & 0x1ff) | 0x8000, name(block, 32, 16)))
        cells.append(b''.join(over + under))
    return tiles, cells


def encode(images, box, template, dialogue=False):
    """Encode full frames; unchanged 32x64 OBJ blocks share character data.

    32-wide objects avoid the third 64-wide-column placement issue in the duel UI.
    Character offsets use the stock 1D/128KB OBJ mapping (128 bytes per name).
    """
    t_ncer, t_nanr, t_nclr = template
    w, h = images[0].size
    if any(im.size != (w, h) for im in images):
        raise ValueError('portrait frames must all have the same native dimensions')
    if w % 32 or h % 64:
        raise ValueError('portrait dimensions must be multiples of 32x64')
    rgba = [im.convert('RGBA') for im in images]
    # Train one palette across every frame, never a different palette per expression.
    strip = Image.new('RGBA', (w * len(rgba), h))
    for i, im in enumerate(rgba):
        strip.paste(im, (i * w, 0))
    indexed, colors = bustup.quantize(strip)
    frame_indices = [b''.join(indexed[y * strip.width + i * w:y * strip.width + (i + 1) * w]
                              for y in range(h)) for i in range(len(rgba))]
    def cut(indices, bx, by, bh):
        return b''.join(indices[(by + y) * w + bx:(by + y) * w + bx + 32] for y in range(bh))

    tall = {(bx, by) for by in range(0, h, 64) for bx in range(0, w, 32)
            if not dialogue or len({cut(f, bx, by, 64) for f in frame_indices}) == 1}
    tiles, blocks, cells = bytearray(), {}, []
    for indices in frame_indices:
        oams = []
        for by in range(0, h, 64):
            for bx in range(0, w, 32):
                parts = [(by, 64)] if (bx, by) in tall else [(by, 32), (by + 32, 32)]
                for py, bh in parts:
                    block = cut(indices, bx, py, bh)
                    if not any(block):
                        continue
                    if block not in blocks:
                        blocks[block] = len(tiles) // bustup.UNIT
                        for ty in range(0, bh, 8):
                            for tx in range(0, 32, 8):
                                for y in range(8):
                                    tiles += block[(ty + y) * 32 + tx:(ty + y) * 32 + tx + 8]
                    x, y = bx + box[0], py + box[1]
                    shape = 0xa000 if bh == 64 else 0x2000
                    size = 0xc000 if bh == 64 else 0x8000
                    oams.append(struct.pack('<HHH', (y & 0xff) | shape, (x & 0x1ff) | size, blocks[block]))
        cells.append(b''.join(oams))
    limit = TALK_OBJ_BYTES if dialogue else 0x20000
    if dialogue and len(tiles) > limit:
        tiles, cells = face_overlays(frame_indices, w, h, box)
    if len(tiles) > limit:
        raise ValueError(f'portrait needs {len(tiles):#x} bytes of OBJ characters, over the {limit:#x} '
                         f'the game gives one {"talk portrait side" if dialogue else "duel portrait"}')
    header = struct.pack('<HHIIIII', 0xffff, 0xffff, 4, 0x00200010, 0, len(tiles), 24)
    ncgr = bustup.nitro(b'RGCN', 0x0101, [b'RAHC' + struct.pack('<I', 8 + len(header) + len(tiles)) + header + tiles])
    nclr = bytearray(t_nclr)
    p = bustup.section(nclr, b'TTLP')
    off = p + 8 + struct.unpack_from('<I', nclr, p + 20)[0]
    struct.pack_into('<256H', nclr, off, *(bustup.to555(*c) for c in colors))
    table, offset = bytearray(), 0
    for cell in cells:
        table += struct.pack('<HHI', len(cell) // 6, 0x1f, offset)
        offset += len(cell)
    body = struct.pack('<HHIIIII', len(cells), 0, 24, 2, 0, 0, 0) + table + b''.join(cells)
    body += b'\0' * (-len(body) % 4)
    ncer = bustup.nitro(b'RECN', 0x0100, [b'KBEC' + struct.pack('<I', len(body) + 8) + body,
                                        labels(len(cells)), b'TXEU' + struct.pack('<II', 12, 0)])
    return {'ncgr': ncgr, 'nclr': bytes(nclr), 'ncer': ncer,
            'nanr': static_nanr(len(cells)) if dialogue else t_nanr}


def bundle(path, talk_template, duel_template):
    with open(path, encoding='utf-8') as f:
        spec = json.load(f)
    root = os.path.dirname(path)
    outputs = []
    for outfit in spec['outfits']:
        files = {}
        talk_w = Image.open(os.path.join(root, outfit['talk'][0])).width
        if talk_w < 128 or talk_w % 32:
            raise ValueError(f'{path}: talk frames must be 128 wide, or wider in steps of 32 for side bleed')
        for kind, size, box, template in [('talk', (talk_w, 192), (-talk_w // 2, -96), talk_template),
                                          ('duel', (160, 192), (-96, -96), duel_template)]:
            if kind == 'duel' and 'duel' not in outfit:
                continue
            images = [Image.open(os.path.join(root, p)).convert('RGBA') for p in outfit[kind]]
            if not images or any(im.size != size for im in images):
                raise ValueError(f'{path}: {kind} requires native {size[0]}x{size[1]} frames')
            if kind == 'duel' and len(images) != 5:
                raise ValueError(f'{path}: duel requires exactly five cells (0-4)')
            if kind == 'talk':
                files['right'] = encode(images, box, template, dialogue=True)
                files['left'] = encode([ImageOps.mirror(im) for im in images], box, template, dialogue=True)
            else:
                files['duel'] = encode(images, box, template)
        outputs.append((outfit, files))
    return outputs
