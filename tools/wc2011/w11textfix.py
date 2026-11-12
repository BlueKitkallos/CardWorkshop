#!/usr/bin/env python3
"""Stock WC2011 text fixes shared by Dimension Break and the QoL patch: card names and texts, story messages and
pack descriptions, from mod/w11fix. Groups: "card" (card effect errors) and "text" (other text errors)."""
import argparse
import copy
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import buildwarn
import carddb
import game
import pac
import w11lang

FIX_DIR = os.path.join(HERE, '..', '..', 'mod', 'w11fix')
CARD_TEXT = 'card_text.json'
STORY_TEXT = 'story_text.json'
PACK_TEXT = 'pack_text.json'
GROUPS = ('card', 'text')
STORY_GROUP = 'text'
MES_IDX_PAC = 'Data_arc_pac/RPG_SCRIPT_MES_IDX'
MES_TXT_PAC = 'Data_arc_pac/RPG_SCRIPT_MES_TXT'
PACK_PAC = 'Data_arc_pac/bin.pac'
STORY_LANGS = 'egfis'
LINE_MAX = 38


class TextFixError(ValueError):
    pass


def load(name, fix_dir=FIX_DIR):
    with open(os.path.join(fix_dir, name), encoding='utf-8') as f:
        return json.load(f)


def selected(fixes, groups):
    for key, fix in fixes.items():
        if fix.get('group') not in GROUPS:
            raise TextFixError(f'{key}: "group" is one of {", ".join(GROUPS)}')
    return {k: v for k, v in fixes.items() if v['group'] in groups}


def groups_of(card, text):
    return tuple(g for g, on in zip(GROUPS, (card, text)) if on)


def replace_pairs(text, pairs, where, strict=True):
    for old, new in pairs:
        n = text.count(old)
        if n == 1:
            text = text.replace(old, new)
        elif strict:
            raise TextFixError(f'{where}: {old!r} found {n} times')
    return text


def fix_cards(db, limits, groups=GROUPS, strict=True, fixes=None):
    fixes = selected(load(CARD_TEXT) if fixes is None else fixes, groups)
    by_reading = db.spec.get('sort_by_reading', False)
    changed = set()
    for cid, fix in fixes.items():
        _, c = db.by_id(int(cid))
        if strict and c.names['e'] != fix['card']:
            raise TextFixError(f'{CARD_TEXT}: {cid} is {c.names["e"]!r}, not {fix["card"]!r}')
        for kind in ('names', 'descs'):
            for lang, pairs in fix.get(kind, {}).items():
                where = f'{CARD_TEXT}: {fix["card"]} {kind} [{lang}]'
                old = getattr(c, kind)[lang]
                text = replace_pairs(old, pairs, where, strict)
                if text == old:
                    continue
                problem = None
                if len(carddb.encode_text(text, lang)) > limits[kind][lang]:
                    problem = f'over {limits[kind][lang]} bytes'
                elif kind == 'names':
                    after = copy.copy(c)
                    after.names = {**c.names, lang: text}
                    if (carddb._sort_key(c, lang, by_reading), carddb.kana_pair(c, lang)) != \
                            (carddb._sort_key(after, lang, by_reading), carddb.kana_pair(after, lang)):
                        problem = 'the name would move in the sort order or the kana search'
                if problem:
                    if strict:
                        raise TextFixError(f'{where}: {problem}')
                    continue
                getattr(c, kind)[lang] = text
                changed.add(int(cid))
    return changed


def check_story(data, where):
    for lang, table in data.items():
        if lang not in STORY_LANGS or not isinstance(table, dict):
            raise TextFixError(f'{where}: "{lang}" is not one of {STORY_LANGS}')
        for old, new in table.items():
            try:
                new.encode('latin-1')
            except UnicodeEncodeError:
                raise TextFixError(f'{where} ({lang}): only Latin-1 characters: {new!r}')
            limit = max([LINE_MAX] + [w11lang.width(r) for r in old.split('\n')])
            for r in new.split('\n'):
                if w11lang.width(r) > limit:
                    buildwarn.warn(f'{where} ({lang}): row "{r}" has {w11lang.width(r)} characters, '
                                   f'the message window holds about {limit}')
    return data


def story_fixes(groups=GROUPS):
    if STORY_GROUP not in groups:
        return {}
    return check_story(load(STORY_TEXT), STORY_TEXT)


def merge_story(shared, own, where):
    out = {l: dict(t) for l, t in shared.items()}
    for lang, table in own.items():
        dup = sorted(set(table) & set(out.get(lang, {})))
        if dup:
            raise TextFixError(f'{where} ({lang}): {dup[0]!r} is already fixed by {STORY_TEXT}')
        out.setdefault(lang, {}).update(table)
    return out


def mes_fix(idx, txt, table, enc):
    offs = struct.unpack(f'<{len(idx) // 4}I', idx)
    out, body, hits = [], bytearray(), set()
    for a, b in zip(offs, offs[1:]):
        raw = txt[a:b]
        s = raw.split(b'\0')[0].decode(enc, 'replace')
        out.append(len(body))
        if s in table:
            r = table[s].encode(enc)
            body += r + b'\0' * (4 - len(r) % 4)
            hits.add(s)
        else:
            body += raw
    out.append(len(body))
    return struct.pack(f'<{len(out)}I', *out), bytes(body), hits


def fix_messages(get, names, lang, table):
    out, used = {}, set()
    for tk in sorted(k for k in names if k.endswith(f'_txt_{lang}.bin')):
        ik = tk[:-len(f'_txt_{lang}.bin')] + f'_idx_{lang}.bin'
        idx, txt, hits = mes_fix(get(MES_IDX_PAC, ik), get(MES_TXT_PAC, tk), table, 'latin-1')
        if hits:
            out[(MES_IDX_PAC, ik)] = idx
            out[(MES_TXT_PAC, tk)] = txt
            used |= hits
    return out, used


def messages(idx, txt):
    offs = struct.unpack(f'<{len(idx) // 4}I', idx)
    return [txt[a:b].split(b'\0')[0].decode('latin-1', 'replace') for a, b in zip(offs, offs[1:])]


def pack_fixes(groups=GROUPS):
    return selected(load(PACK_TEXT), groups)


def fix_pack_spec(spec, where):
    fix = load(PACK_TEXT).get(str(spec['id']))
    if fix:
        for lang, pairs in fix['descs'].items():
            spec['desc'][lang] = replace_pairs(spec['desc'][lang], pairs, f'{where}: desc [{lang}] ({PACK_TEXT})')
    return spec


def fix_pack_text(pt, groups=GROUPS, strict=True):
    lang_of = {l: pl for pl, l in pt.langs.items()}
    changed = set()
    for pid, fix in pack_fixes(groups).items():
        for lang, pairs in fix['descs'].items():
            store = pt.descs[lang_of[lang]]
            old = store[int(pid)]
            text = replace_pairs(old, pairs, f'{PACK_TEXT}: pack {pid} desc [{lang}]', strict)
            carddb.encode_text(text, lang)
            if text != old:
                store[int(pid)] = text
                changed.add(int(pid))
    return changed


def put_files(rom, arc, files, stock):
    entries = dict(stock)
    diff = {n: d for n, d in files.items() if d != stock[n]}
    if diff:
        entries.update(diff)
        rom.setFileByName(arc, pac.build(entries))
    return diff


def apply(rom, card=True, text=True, strict=True):
    groups = groups_of(card, text)
    prof = game.for_rom(rom)
    if prof['game_code'] != 'BYYP':
        raise TextFixError(f'not the WC2011 EU ROM (game code {prof["game_code"]})')
    changed = set()
    arc = prof['card_db']['container']
    bin2 = game.container_files(rom, arc)
    db = carddb.CardDB.load(bin2, prof)
    fix_cards(db, carddb.text_limits(db), groups, strict)
    if put_files(rom, arc, db.files(), bin2):
        changed.add(arc)
    table = story_fixes(groups)
    if table:
        files = {a: game.container_files(rom, a + '.pac') for a in (MES_IDX_PAC, MES_TXT_PAC)}
        out = {}
        for lang, fixes in sorted(table.items()):
            got, used = fix_messages(lambda a, n: out.get((a, n), files[a][n]), files[MES_TXT_PAC], lang, fixes)
            out.update(got)
            if strict:
                for s in fixes:
                    if s not in used:
                        raise TextFixError(f'{STORY_TEXT} ({lang}): no stock message reads {s!r}')
        for a in (MES_IDX_PAC, MES_TXT_PAC):
            if put_files(rom, a + '.pac', {n: d for (x, n), d in out.items() if x == a}, files[a]):
                changed.add(a + '.pac')
    text_files = game.container_files(rom, PACK_PAC)
    pt = carddb.PackText.load(text_files, prof)
    if fix_pack_text(pt, groups, strict) and put_files(rom, PACK_PAC, pt.files(), text_files):
        changed.add(PACK_PAC)
    return changed


def check_pairs(text, pairs, where):
    out = []
    for old, new in pairs:
        if new not in text:
            out.append(f'{where}: {new!r} missing')
        if old in text.replace(new, ''):
            out.append(f'{where}: {old!r} still present')
    return out


def verify(rom, card=True, text=True):
    groups = groups_of(card, text)
    prof = game.for_rom(rom)
    problems = []
    db = carddb.CardDB.load(game.container_files(rom, prof['card_db']['container']), prof)
    for cid, fix in selected(load(CARD_TEXT), groups).items():
        _, c = db.by_id(int(cid))
        for kind in ('names', 'descs'):
            for lang, pairs in fix.get(kind, {}).items():
                problems += check_pairs(getattr(c, kind)[lang], pairs, f'card {cid} {fix["card"]} {kind} [{lang}]')
    table = story_fixes(groups)
    if table:
        idx = game.container_files(rom, MES_IDX_PAC + '.pac')
        txt = game.container_files(rom, MES_TXT_PAC + '.pac')
        for lang, fixes in sorted(table.items()):
            seen = set()
            for tk in (k for k in txt if k.endswith(f'_txt_{lang}.bin')):
                seen.update(messages(idx[tk[:-len(f'_txt_{lang}.bin')] + f'_idx_{lang}.bin'], txt[tk]))
            for old, new in fixes.items():
                if new not in seen:
                    problems.append(f'story [{lang}]: {new!r} missing')
                if old in seen:
                    problems.append(f'story [{lang}]: {old!r} still present')
    pt = carddb.PackText.load(game.container_files(rom, PACK_PAC), prof)
    for pid, fix in pack_fixes(groups).items():
        for lang, pairs in fix['descs'].items():
            pl = next(p for p, l in pt.langs.items() if l == lang)
            problems += check_pairs(pt.descs[pl][int(pid)], pairs, f'pack {pid} desc [{lang}]')
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rom', help='WC2011 EU ROM')
    ap.add_argument('--out', help='write the fixed ROM here (without it, only verify the ROM)')
    ap.add_argument('--groups', nargs='*', choices=GROUPS, default=list(GROUPS))
    a = ap.parse_args()
    rom = game.open_rom(a.rom)
    card, text = 'card' in a.groups, 'text' in a.groups
    if a.out:
        for arc in sorted(apply(rom, card, text)):
            print(f'changed {arc}')
        rom.saveToFile(a.out)
        rom = game.open_rom(a.out)
    problems = verify(rom, card, text)
    print('\n'.join(problems) or f'text fixes ({", ".join(a.groups)}): all present')
    raise SystemExit(1 if problems else 0)


if __name__ == '__main__':
    main()
