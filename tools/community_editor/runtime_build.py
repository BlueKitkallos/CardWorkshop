"""Assemble only the community runtime features selected by the project."""
import shutil
import struct
from pathlib import Path

import w11packs
from model import merged_talk
import w11npc
from ydc import Deck

ROOT = Path(__file__).resolve().parent
SHARED = ROOT.parents[1] / 'variants/dimension-break'
SHARED_OPENING = SHARED / 'src/opening11.c'


def prepare(folder, adapter, p, extra):
    folder = Path(folder)
    src = folder / 'src'
    src.mkdir()
    added = [(f'pack {s["id"]}', s) for s in p['packs'] if s['id'] >= 97]
    hooks = ['.nds', '.include "symbols.asm"', '.thumb']
    names = []
    opening = 'pack-opening' in p['patches']
    if extra or added or opening:
        names += ['members.c', 'members_stubs.S']
        hooks += [(ROOT / 'runtime/hooks.asm').read_text().split('.include "symbols.asm"', 1)[1]]
        w11packs.write_header(str(src), added, extra)
    if added:
        names += ['shop.c', 'shop_stubs.S', 'save.c', 'shop.asm']
        hooks += ['.include "shop.asm"']
    if 'flash-fixes' in p['patches']:
        names += ['boot_flash.c', 'boot_flash.asm']
        hooks += ['.include "boot_flash.asm"']
    report, changes, loose = [], {}, {}
    if opening:
        from opening_assets import load
        changes, loose = load(adapter.rom, adapter.opening_assets)
        (src / 'w11packsfx.h').write_text(adapter.opening_assets['header'])
        names += ['opening.c', 'opening_stubs.S', 'opening.asm']
        hooks += ['.include "opening.asm"']
        shutil.copy(SHARED_OPENING, src / 'opening11.c')
    if p['opponents'] or p['base_cpus']:
        # The project holds explicit IDs and repeated references, unlike the
        # existing JSON spec CLI. Reuse its binary writers with an in-memory
        # deck provider, so no paths in a shared project are opened.
        decks = {d['file']: d for d in p['decks']}

        class ProjectBuilder(w11npc.Builder):
            def deck(self, path, where):
                d = decks[Path(path).name]
                ids = {sec: [adapter.resolve(n) for n in d[sec]] for sec in ('main', 'extra', 'side')}
                return Deck(**ids, header=w11npc.YDC_HEADER), d

        builder = ProjectBuilder(str(adapter.path), str(folder / 'opponents'))
        portraits = builder.files[w11npc.DUEL_BU_PAC]
        for filename, data in list(portraits.items()):
            if '_r_e.' in filename:
                portraits.setdefault(filename.replace('_r_e.', '_r.'), data)
        card_map = builder.cards()
        card_map.update({f'id:{cid}': cid for cid in adapter.by_id})
        for i, o in enumerate(p['opponents']):
            spec = {'chara': o['chara'], 'name': o['name'],
                    'card': f'id:{adapter.resolve(o.get("key_card", "id:4007"))}',
                    'deck': o['deck'], 'deck_name': o.get('deck_name') or o['name'],
                    'portrait': {'wc2011': o.get('portrait', 300)},
                    'status': {'template_deck': o.get('template_deck', 113)},
                    'turbo': o.get('turbo', False)}
            if 'rating' in o:
                spec['rating'] = o['rating']
            else:
                spec['rating'] = struct.unpack_from('<H', builder.files[w11npc.BIN_PAC]['enemystatus.bin'],
                                                   o.get('template_deck', 113) * 12 + 2)[0]
            if 'talk' in o:
                spec['talk'] = {'e':o['talk']}
            report.append(builder.opponent(spec, str(folder)))
            if o.get('tag'):
                builder.tables['free'].pop()
        report += base_overrides(builder, adapter, p, decks)
        teams = tag_teams(builder, adapter, p)
        # Do not apply Dimension Break's art swaps or story modifications.
        builder.write(report)
        for (arc, name), data in builder.changed.items():
            changes.setdefault(arc + '.pac', {})[name] = data
        for f in (folder / 'opponents/src').iterdir():
            shutil.copy(f, src / f.name)
        names += ['opponents.S', 'opponents.asm', 'free_duel.c', 'free_duel.asm']
        hooks += ['.include "opponents.asm"']
        if teams:
            (src / 'w11tag_gen.S').write_text(
                '    .section .rodata\n    .balign 4\n    .global w11tag_teams\nw11tag_teams:\n'
                + ''.join(f'    .hword {", ".join(f"{v:#x}" for v in row)}, 0\n' for row in teams)
                + f'    .global w11tag_teams_n\nw11tag_teams_n:\n    .word {len(teams)}\n')
            names += ['tag.c', 'tag_stubs.S', 'tag.asm']
            hooks += ['.include "tag.asm"']
    if p.get('banlists'):
        from banlist_build import prepare as prepare_banlists
        prepare_banlists(folder, src, adapter, p, changes)
        names += ['points11.c', 'points11.asm']
        hooks += ['.include "points11.asm"']
    if 'wfc-shop' in p['patches']:
        import banlist
        import game
        import w11menu
        bin2 = dict(adapter.dbfiles)
        bin2.update(changes.get('Data_arc_pac/bin2.pac', {}))
        texts = w11menu.label_texts()
        text_dir = folder / 'menu11'
        ids = banlist.w11_add_texts(list(texts.values()), bin2, str(text_dir))
        changes.setdefault('Data_arc_pac/bin2.pac', {}).update({f.name: f.read_bytes() for f in text_dir.iterdir()})
        changes.setdefault(w11menu.PAC, {}).update(w11menu.assets(game.container_files(adapter.rom, w11menu.PAC)))
        (src / 'menu11.h').write_text(''.join(f'#define W11MENU_{k} {i}\n' for k, i in zip(texts, ids)))
        for name in ('menu11.c', 'menu11_stubs.S'):
            shutil.copy(SHARED / 'src' / name, src / name)
        names += ['menu11_gate.S', 'menu11.asm']
        hooks += ['.include "menu11.asm"']
    for name in names:
        shutil.copy(ROOT / 'runtime' / name, src / name)
    (src / 'hooks.asm').write_text('\n'.join(hooks) + '\n')
    return src, changes, report, loose


def base_overrides(builder, adapter, p, decks):
    base = adapter.base_cpus()
    source = adapter.cpu_source()
    portraits = builder.files[w11npc.DUEL_BU_PAC]
    report = []
    for key, o in p['base_cpus'].items():
        b = base[key]
        chara, slot, where = b['chara'], b['slot'], o.get('name') or b['name']
        if 'deck' in o:
            deck = Deck.parse(adapter.deckfiles[b['deck']])
            for sec in ('main', 'extra', 'side'):
                setattr(deck, sec, [adapter.resolve(n) for n in decks[o['deck']][sec]])
            builder.put(w11npc.DECK_PAC, b['deck'], deck.build())
        if {'rating', 'key_card', 'talk'} & set(o):
            status = bytearray(builder.get(w11npc.BIN_PAC, 'enemystatus.bin'))
            row = list(struct.unpack_from('<HHB5BH', status, slot * 12))
            row[1] = o.get('rating', row[1])
            if 'key_card' in o:
                row[8] = adapter.resolve(o['key_card'])
            if 'talk' in o:
                row[2] = builder.talk_set({'e': merged_talk(b['talk'], o['talk'])}, where) + 1
            struct.pack_into('<HHB5BH', status, slot * 12, *row)
            builder.put(w11npc.BIN_PAC, 'enemystatus.bin', bytes(status))
        texts = [o[k] for k in ('name', 'deck_name') if k in o]
        if texts:
            first = builder.game_text(texts, {'at': where})
            if 'name' in o:
                builder.tables['charname'].append((slot, first))
            if 'deck_name' in o:
                builder.tables['deckname'].append((slot + 1, first + len(texts) - 1))
        if 'portrait' in o:
            for ext in ('ncgr', 'ncer', 'nanr', 'nclr'):
                builder.put(w11npc.DUEL_BU_PAC, f'bu{chara:03d}_r.lz{ext}', portraits[f'bu{o["portrait"]:03d}_r.lz{ext}'])
            if o['portrait'] in source.char_deck:
                offsets = bytearray(builder.get(w11npc.BIN_PAC, 'character.bin'))
                offsets[slot] = builder.files[w11npc.BIN_PAC]['character.bin'][source.char_deck[o['portrait']]]
                builder.put(w11npc.BIN_PAC, 'character.bin', bytes(offsets))
        report.append({'base_chara': chara, 'deck_slot': slot, 'changed': sorted(o)})
    return report


TAG_TEAM_FIRST = 49


def tag_teams(builder, adapter, p):
    tags = [o for o in p['opponents'] if o.get('tag')]
    if not tags:
        return []
    duelists = adapter.duelists(p)
    for chara, duelist in sorted(duelists.items()):
        if duelist >= w11npc.STORY_CHARS:
            builder.tables['story'].append((duelist, chara))
    rows = []
    for i, o in enumerate(tags):
        text = builder.game_text([o['team_name']], {'at': o['name']})
        rows.append((TAG_TEAM_FIRST + i, 0x8000 if o.get('turbo') else 0, duelists[o['chara']],
                     duelists[o['partner']], text))
    return rows
