"""Build project banlists with the existing generic WC2011 list runtime."""
from pathlib import Path
import struct

import banlist


def card_values(adapter, bl):
    out = {}
    for ref, value in bl['cards'].items():
        cid = adapter.resolve(ref)
        if cid is None:
            raise ValueError(f'{bl["name"]}: unresolved card “{ref}”.')
        # Alternate artworks share the same logical limit and point value.
        for member in adapter.index.resolve(adapter.by_id[cid].names['e'], bl['name']):
            if member in out and out[member] != value:
                raise ValueError(f'{bl["name"]}: {adapter.by_id[cid].names["e"]} is listed twice with different values.')
            out[member] = value
    return out


def prepare(folder, src, adapter, project, changes):
    lists = project.get('banlists', [])
    if not lists:
        return
    bin2 = dict(adapter.dbfiles)
    bin2.update(changes.get('Data_arc_pac/bin2.pac', {}))
    point_at = next((i for i, bl in enumerate(lists) if bl['id'] == 'points'), None)
    labels = sorted(banlist.POINT_LABELS) if point_at is not None else []
    texts = [{'e':bl['name']} for bl in lists]
    texts += ([banlist.POINT_MSG] if point_at is not None else [])
    texts += [banlist.w11_label(bin2, i) for i in labels]
    work = Path(folder) / 'banlists'
    text_dir = work / 'bin2'
    ids = banlist.w11_add_texts(texts, bin2, str(text_dir))
    changes.setdefault('Data_arc_pac/bin2.pac', {}).update({f.name:f.read_bytes() for f in text_dir.iterdir()})
    _, base_header = banlist.parse(adapter.textfiles['limit201009.bin'])
    files, point_max = [], 1
    for i, bl in enumerate(lists):
        filename = f'limit_community_{bl["id"]}.bin'
        files.append(filename)
        values = card_values(adapter, bl)
        entries = [(cid, value) for cid, value in values.items() if value != 3] if bl['id'] == 'classic' else []
        if len(entries) > banlist.W11_STOCK_LIST_ENTRIES:
            raise ValueError(f'{bl["name"]}: too many limited cards. The game allows {banlist.W11_STOCK_LIST_ENTRIES}, and each artwork counts.')
        header = struct.pack('<H', ids[i] - banlist.NAME_BASE) + base_header[2:]
        raw = banlist.build(entries, header)
        if bl['id'] == 'points':
            values = {cid:n for cid, n in values.items() if n}
            raw += banlist.point_table(bl['cap'], values)
            point_max = max(len(values), 1)
        changes.setdefault('Data_arc_pac/bin.pac', {})[filename] = raw
    point_index = 3 + point_at if point_at is not None else 0xff
    text_map = list(zip(labels, ids[len(lists) + 1:]))
    paths = ''.join(f'Bin/{f}\\000' for f in files)
    header = [f'#define BL11_EXT {len(lists)}', f'#define BL11_PATHS "{paths}"',
              f'#define BL11_POINT_MAX {point_max}', f'#define BL11_POINT_INDEX {point_index}',
              f'#define BL11_POINT_TEXT {ids[len(lists)] if point_at is not None else 0}',
              '#define BL11_TEXT_MAP ' + ' '.join(f'X({x}, {y})' for x, y in text_map)]
    header += banlist.w11_starter_lines(None)
    (src / 'points11.h').write_text('\n'.join(header)+'\n')
    default = project.get('default_banlist', 'base')
    original = adapter.rom.loadArm9().sections[0]
    start = struct.unpack_from('<H', original.data, 0x0202e156 - original.ramAddress)[0] & 0xff
    if default != 'base':
        start = 3 + next(i for i, bl in enumerate(lists) if bl['id'] == default)
    (src / 'points11_def.asm').write_text(f'.definelabel BL11_EXT, {len(lists)}\n.definelabel BL11_START, {start}\n')
