"""CPU AI test bench: CPU-vs-CPU duels started from a scenario, run headless in melonDS."""
import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import random
import re
import shutil
import struct
import zlib
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import modspec
from ydc import Deck
from mlstate import MAIN, MELON, MELON_CFG, MIN_STATE, Melon, Ram, melon_config, ram_of, symbols, xvfb

GYM_SRC = os.path.join(ROOT, 'mod', 'test', 'gym', 'src')
CLEAN_ROM = os.path.join(ROOT, 'rom', 'Yu-Gi-Oh! - World Championship 2008 (Europe) (En,Ja,Fr,De,Es,It).nds')
SAVE = os.environ.get('GYM_SAVE', os.path.join(ROOT, 'build', 'gym', 'bench.sav'))
VARIANT = os.path.join(ROOT, 'variants', 'retro-genesys')
LOCK = '/tmp/claude-1000/ygo_build.lock' if os.path.isdir('/tmp/claude-1000') else '/tmp/ygo_build.lock'

MAGIC = 0x314d5947
KIT_DECK = 'wcs08_tear_01.ydc'
SAVE_EXTRA = [7261, 7257, 7260, 7303, 7302] * 3
SAVE_DECK = 0xc8
ZONES = ('hand', 'deck', 'gy', 'banished', 'extra', 'monsters', 'spells', 'opt_used')
MAX_CARDS = 320
POSITIONS = ('attack', 'defense', 'choose')
LOG_N = 2048
TAGS = {'resolve': 1, 'fusion': 2, 'normal_summon': 4, 'ai_main': 5, 'ai_chain': 6, 'pick': 0x34,
        'answer': 0x35, 'target': 0x36, 'fuse_decision': 0x37, 'activate': 0x2c, 'arrive': 0x81, 'attack': 0x85}
DUEL_RNG = 0x022d0f70
DUEL_DONE = {1: 'tag', 2: 'turns', 3: 'duel over', 4: 'phase', 5: 'settled'}
PHASES = {'draw': 0, 'standby': 1, 'main1': 2, 'battle': 3, 'main2': 4, 'end': 5}
PLAYERS = 0x022cdff0
PSIZE = 0xfac
CARD_ID_MASK = 0x3fff


def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        raise SystemExit(f'failed ({r.returncode}): {" ".join(map(str, cmd))}')
    return r


def code_text(work):
    with open(os.path.join(work, 'code.map')) as f:
        m = re.search(r'(?m)^\.text\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)', f.read())
    with open(os.path.join(work, 'code.bin'), 'rb') as f:
        return int(m.group(1), 16), f.read()[:int(m.group(2), 16)]


def code_changes(ram, text):
    start, want = text
    got = ram.block(start, len(want))
    return [start + i for i in range(0, len(want), 4) if got[i:i + 4] != want[i:i + 4]]


def sha1(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


class Cards:
    def __init__(self):
        e2 = os.path.join(ROOT, 'extracted', 'Data_arc_pac', 'bin2')
        m2 = os.path.join(VARIANT, 'pac', 'Data_arc_pac', 'bin2')
        self.index = modspec.CardIndex(modspec.load_db(e2, m2))

    def id(self, name, where):
        return self.index.resolve(name, where)[0]

    def name(self, cid):
        cid &= CARD_ID_MASK
        return self.index.name(cid) if cid in self.index.by_id else f'#{cid}'


def deck_file(path, cards, where, seed):
    path = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if path.endswith('.ydc'):
        d = Deck.load(path)
        main, extra = list(d.main), list(d.extra)
    else:
        spec = modspec.load_json(path)
        main = [cards.id(n, where) for n, k in spec.get('main', {}).items() for _ in range(k)]
        extra = [cards.id(n, where) for n, k in spec.get('extra', {}).items() for _ in range(k)]
    random.Random(seed).shuffle(main)
    return main, extra


def side_cards(spec, cards, where):
    out = {z: [] for z in ZONES}
    if spec.get('deck_file'):
        main, extra = deck_file(spec['deck_file'], cards, f'{where}.deck_file', spec.get('shuffle', 0))
        spec = dict(spec, hand=[cards.name(c) for c in main[:5]] + spec.get('hand', []),
                    deck=[cards.name(c) for c in main[5:]] + spec.get('deck', []), extra=[cards.name(c) for c in extra] + spec.get('extra', []))
    for z in ('hand', 'deck', 'banished', 'extra'):
        out[z] = [cards.id(n, f'{where}.{z}') for n in spec.get(z, [])]
    for g in spec.get('gy', []):
        g = {'card': g} if isinstance(g, str) else g
        out['gy'].append(cards.id(g['card'], f'{where}.gy') | (1 if g.get('fusion') else 0) << 16)
    fill = spec.get('deck_fill')
    if fill:
        out['deck'] += [cards.id(fill[0], f'{where}.deck_fill')] * int(fill[1])
    for m in spec.get('monsters', []):
        m = {'card': m} if isinstance(m, str) else m
        pos = POSITIONS.index(m.get('position', 'attack'))
        out['monsters'].append(cards.id(m['card'], f'{where}.monsters') | (1 if m.get('fusion') else 0) << 16 | pos << 17)
    for i, s in enumerate(spec.get('spells', [])):
        s = {'card': s} if isinstance(s, str) else s
        slot = s.get('slot', 10 if s.get('field') else 5 + i)
        out['spells'].append(cards.id(s['card'], f'{where}.spells') | slot << 16 | (1 if s.get('face_up') else 0) << 20)
    for name, n in spec.get('opt_used', []):
        out['opt_used'].append(cards.id(name, f'{where}.opt_used') | int(n) << 16)
    if len(out['monsters']) > 5:
        raise SystemExit(f'{where}: at most 5 monsters')
    if not out['deck']:
        raise SystemExit(f'{where}: the Deck is empty; give "deck" or "deck_fill"')
    return out


def scenario_blob(scn, cards):
    stop = scn.get('stop', {})
    tag = stop.get('tag', 0)
    tag = TAGS[tag] if isinstance(tag, str) else int(tag)
    card = cards.id(stop['card'], 'stop.card') if stop.get('card') else 0
    force_vs = cards.id(stop['force_vs'], 'stop.force_vs') if stop.get('force_vs') else 0
    sides = [side_cards(scn.get(k, {}), cards, k) for k in ('first', 'second')]
    lp = [int(scn.get(k, {}).get('lp', 0)) for k in ('first', 'second')]
    phase = PHASES[stop['phase']] + 1 if 'phase' in stop else 0
    turns = int(stop.get('turns', 0 if tag or phase else 1))
    head = struct.pack('<IHHHHHHHHHHii', MAGIC, int(scn.get('turn', 2)), turns, tag, card, int(stop.get('count', 1)), phase,
                       1 if stop.get('settle') else 0, int(stop.get('force', 0)), int(stop.get('end_frames', 0)), force_vs, *lp)
    counts = b''.join(struct.pack('<8H', *(len(s[z]) for z in ZONES)) for s in sides)
    flat = [c for s in sides for z in ZONES for c in s[z]]
    if len(flat) > MAX_CARDS:
        raise SystemExit(f'{scn["name"]}: {len(flat)} cards, at most {MAX_CARDS}')
    return head + counts + struct.pack(f'<{len(flat)}I', *flat)


def load_scenarios(paths):
    out = []
    for p in paths:
        files = sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith('.json')) if os.path.isdir(p) else [p]
        for f in files:
            with open(f) as fh:
                s = json.load(fh)
            s.setdefault('name', os.path.splitext(os.path.basename(f))[0])
            out.append(s)
    return out


def gym_dir(name):
    return os.path.join(ROOT, 'build', 'gym', name)


def unverified_ids(names):
    with open(os.path.join(ROOT, 'mod', 'effects', 'auto.json')) as f:
        cards = json.load(f)['cards']
    by = {c['name'].lower(): c['id'] for c in cards} | {str(c['id']): c['id'] for c in cards}
    lack = [n for n in names if n.lower() not in by]
    if lack:
        raise SystemExit(f'--unverified: not in mod/effects/auto.json: {lack}')
    return sorted({by[n.lower()] for n in names})


def unverified_sources(d, src_dir, names):
    gen = os.path.join(d, 'gen')
    os.makedirs(gen, exist_ok=True)
    sel = ','.join(map(str, unverified_ids(names))) if names else '1'
    env = dict(os.environ, YGO_UNVERIFIED=sel)
    auto_c = os.path.join(gen, 'port_auto.c')
    sel_file = os.path.join(gen, 'selection')
    old_sel = open(sel_file).read() if os.path.exists(sel_file) else None
    deps = [os.path.join(ROOT, 'mod', 'effects', 'auto.json'), os.path.join(HERE, 'wc2008', 'decomp2c.py'), os.path.join(HERE, 'wc2008', 'w11expr.py')]
    if old_sel != sel or not os.path.exists(auto_c) or os.path.getmtime(auto_c) < max(os.path.getmtime(p) for p in deps):
        print('translating every card of mod/effects/auto.json for the bench (about 1 s per card)', flush=True)
        run([sys.executable, os.path.join(HERE, 'wc2008', 'decomp2c.py'), 'build', '--out', auto_c], env=env)
        with open(sel_file, 'w') as f:
            f.write(sel)
    run([sys.executable, os.path.join(HERE, 'effectport.py'), 'rows', '--out', os.path.join(gen, 'port_rows.h'),
         '--w11-out', os.path.join(gen, 'port_w11.h')], env=env, stdout=subprocess.DEVNULL)
    for f in ('port_auto.c', 'port_rows.h', 'port_w11.h'):
        link = os.path.join(src_dir, f)
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(os.path.join(gen, f), link)


def build(name, src, unverified=None):
    d = gym_dir(name)
    mod = os.path.join(d, 'mod')
    if os.path.isdir(mod):
        shutil.rmtree(mod)
    os.makedirs(os.path.join(mod, 'src'))
    os.symlink(os.path.join(VARIANT, 'files'), os.path.join(mod, 'files'))
    src_pac = os.path.join(VARIANT, 'pac', 'Data_arc_pac')
    with open(os.path.join(src, 'monplane.h')) as f:
        need = sorted(set(re.findall(r'X\(\d+, \w+, (\d+)\)', f.read())))
    lack = [k for k in need if not os.path.isdir(os.path.join(src_pac, 'monplane_x', k))]
    if lack:
        raise SystemExit(f'{src}/monplane.h loads field sprites from monplane_x/{lack[0]}.pac, missing in {src_pac}: '
                         'run `make cards assets` first')
    pac = os.path.join(mod, 'pac', 'Data_arc_pac')
    os.makedirs(os.path.join(pac, 'deck'))
    for f in os.listdir(src_pac):
        if f != 'deck':
            os.symlink(os.path.join(src_pac, f), os.path.join(pac, f))
    for f in os.listdir(os.path.join(src_pac, 'deck')):
        deck = Deck.load(os.path.join(src_pac, 'deck', f))
        if f == KIT_DECK:
            deck.extra = [deck.extra[i % len(deck.extra)] for i in range(15)]
        deck.save(os.path.join(pac, 'deck', f))
    for sdir in (src, os.path.join(VARIANT, 'src')):
        for f in os.listdir(sdir):
            if f not in ('hooks.asm', 'tear_trace.h'):
                os.symlink(os.path.abspath(os.path.join(sdir, f)), os.path.join(mod, 'src', f))
    for f in os.listdir(GYM_SRC):
        os.symlink(os.path.join(GYM_SRC, f), os.path.join(mod, 'src', f))
    if unverified is not None:
        unverified_sources(d, os.path.join(mod, 'src'), unverified)
    with open(os.path.join(src, 'hooks.asm')) as f:
        hooks = f.read()
    with open(os.path.join(mod, 'src', 'hooks.asm'), 'w') as f:
        f.write(hooks + '\n.include "gym_hooks.asm"\n')
    rom = os.path.join(d, 'gym.nds')
    run(['flock', LOCK, sys.executable, os.path.join(HERE, 'build_rom.py'), '--mod', mod, CLEAN_ROM, rom],
        stdout=subprocess.DEVNULL)
    print(f'{rom}: built from {src}')
    return rom


def save_with_extra(src, dst):
    import save as savefile
    lay, data, recs, best = savefile.load_latest(src)
    if best is None:
        raise SystemExit(f'{src}: no valid save record')
    slot, (counter, _, _, img) = best
    img = bytearray(img)
    struct.pack_into('<I', img, SAVE_DECK + 8, len(SAVE_EXTRA))
    struct.pack_into(f'<{len(SAVE_EXTRA)}H', img, SAVE_DECK + 0xca, *SAVE_EXTRA)
    savefile.write_record(lay, data, slot, (counter + 1) & 0xffffffff, img)
    with open(dst, 'wb') as f:
        f.write(data)


LIST, LIST_PAGE, LIST_CURSOR, LIST_ROW = 0x021d2520, 0x021d21ec, 0x021d21fa, 6
LIST_MAX = 4096
KITKALLOS = 220


def list_ram(m, state):
    for _ in range(5):
        data = m.snapshot(state, 3)
        if data:
            return Ram(data)
        time.sleep(1)
    raise SystemExit('no savestate from the opponent list')


def pick_opponent(m, state, char, confirm=True):
    ram = list_ram(m, state)
    i = next((i for i in range(LIST_MAX) if ram.u16(LIST + 2 * i) == char), None)
    if i is None:
        raise SystemExit(f'char {char} is not in the Free Duel list')
    page, cur = divmod(i, LIST_ROW)
    for _ in range(64):
        now = ram.u16(LIST_PAGE)
        if now == page:
            break
        m.key('w' if page > now else 'q')
        time.sleep(0.8)
        ram = list_ram(m, state)
    else:
        raise SystemExit(f'opponent list: page {page + 1} not reached')
    tap = (64 + 58 * (cur % 3), 290 + 55 * (cur // 3))
    m.tap(*tap)
    time.sleep(1.5)
    if list_ram(m, state).u16(LIST_CURSOR) != cur:
        raise SystemExit(f'opponent list: cursor not on char {char}')
    if confirm:
        m.tap(*tap)
        time.sleep(2.5)
    return tap


def walk_to_duel(rom, walk, d, syms, delay=0.0):
    m = Melon(rom, melon_config(d, False))
    try:
        time.sleep(10)
        m.key('x')
        time.sleep(3)
        m.tap(128, 275)
        time.sleep(4)
        m.tap(128, 340)
        time.sleep(5)
        for _ in range(2):
            m.key('x')
            time.sleep(3)
        time.sleep(1.5)
        pick_opponent(m, os.path.splitext(rom)[0] + '.ml3', KITKALLOS)
        time.sleep(1 + delay)
        for _ in range(3):
            m.tap(49, 372)
            time.sleep(4)
        m.tap(192, 389)
        for _ in range(30):
            time.sleep(2)
            data = m.snapshot(os.path.join(walk, 'g.ml1'), 1)
            if data and Ram(data).u32(syms['gym_waiting']) == 1:
                return data
        return None
    finally:
        m.stop()


def base(name):
    d = gym_dir(name)
    rom = os.path.join(d, 'gym.nds')
    if not os.path.exists(rom):
        raise SystemExit(f'{rom}: build it first (gym.py build {name})')
    syms = symbols(os.path.join(d, 'work'))
    walk = os.path.join(d, 'walk')
    os.makedirs(walk, exist_ok=True)
    wrom = os.path.join(walk, 'g.nds')
    if os.path.lexists(wrom):
        os.remove(wrom)
    os.symlink(rom, wrom)
    save_with_extra(SAVE, os.path.join(walk, 'g.sav'))
    state = None
    for attempt in range(6):
        state = walk_to_duel(wrom, walk, d, syms, 0.7 * attempt)
        if state and Ram(state).u32(0x022d0f7c) == 1:
            break
        print(f'walk {attempt + 1}: {"Kitkallos does not go first" if state else "no duel"}, again')
        state = None
    if not state:
        raise SystemExit('could not reach a duel where Kitkallos (player 1) goes first; see ' + walk)
    with open(os.path.join(d, 'base.ml1'), 'wb') as f:
        f.write(state)
    with open(os.path.join(d, 'base.json'), 'w') as f:
        json.dump({'rom_sha1': sha1(rom)}, f)
    shutil.rmtree(walk)
    print(f'{d}/base.ml1: duel paused at the first deal')


def board(ram, cards, p):
    b = PLAYERS + p * PSIZE
    out = {'lp': ram.u32(b), 'deck': ram.u32(b + 0x10), 'gy_n': ram.u32(b + 0x14), 'extra_n': ram.u32(b + 0x18),
           'hand': [cards.name(ram.u32(b + 0x120 + 4 * i)) for i in range(min(ram.u32(b + 0xc), 20))],
           'gy': [cards.name(ram.u32(b + 0x710 + 4 * i)) for i in range(min(ram.u32(b + 0x14), 60))],
           'banished': [cards.name(ram.u32(b + 0xa80 + 4 * i)) for i in range(min(ram.u32(b + 0x1c), 60))],
           'field': []}
    for s in range(11):
        w = ram.u32(b + 0x30 + 20 * s)
        if w & CARD_ID_MASK:
            neg = '(negated)' if s < 5 and ram.u32(b + 0x30 + 20 * s + 0x10) & 0x100 else ''
            out['field'].append(f'{s}:{cards.name(w)}{"" if ram.u16(b + 0x30 + 20 * s + 8) else "(set)"}{neg}')
    return out


def events(ram, syms):
    n = ram.u32(syms['glog_n'])
    out = []
    for k in range(max(0, n - LOG_N), n):
        w = struct.unpack('<4I', ram.block(syms['glog'] + (k % LOG_N) * 16, 16))
        out.append((w[0] & 0xffff, w[0] >> 16, w[1], w[2], w[3]))
    return out


def describe(ev, cards, side_of):
    tag, turn, a, b, c = ev
    nm = cards.name
    s = lambda p: side_of(p & 1)
    if tag == 1:
        return f'{s(b)} resolve {nm(a)}'
    if tag == 2:
        return f'{s(b)} FUSION {nm(a)} ({c} materials)'
    if tag == 4:
        return f'{s(b)} normal summon {nm(a)}'
    if tag == 5:
        return f'{s(b)} ai main -> {nm(a)}' if a else f'{s(b)} ai main -> normal summon'
    if tag == 6:
        return f'{s(b)} ai chain {nm(a)} vs {nm(c)}'
    if tag == 9:
        return f'{s(b)} ai battle -> {nm(a)}'
    if tag == 3:
        return f'{s(b)} HUMAN PROMPT {nm(a)} {c:#x}'
    if tag == 7:
        return f'to GY {nm(a)}'
    if tag == 0x20:
        return f'talk {("field_spell", "effect_fusion", "mill", "summon")[a] if a < 4 else a} {nm(c) if c else ""}'
    if tag == 0x30:
        return f'{s(b)} pick {nm(a)} -> {nm(c)}'
    if tag == 0x32:
        return f'{s(b)} activate {nm(a)}'
    if tag == 0x34:
        return f'{s(b)} {nm(a)} picks {nm(c & 0xffff)} (mode {c >> 16})'
    if tag == 0x35:
        return f'{s(b)} answer {nm(a)} msg {c & 0xffff:#x} = {c >> 16}'
    if tag == 0x36:
        return f'{s(b)} {nm(a)} targets {nm(c & 0xffff)} of {side_of(c >> 16)}'
    if tag == 0x37:
        return f'{s(b)} fuse? {nm(a)} best {c & 0xff} setup {(c >> 8) & 0xff} -> {c >> 16}'
    if tag in (0x41, 0x42):
        return f'{s(b)} {"register" if tag == 0x41 else "watch"} {nm(a)} uid {c}'
    if tag == 0x44:
        return f'{s(b)} end phase moves {nm(a)} from slot {c}'
    if tag == 0x39:
        return f'{s(b)} lethal plan: {nm(a)} first at {nm(c & 0xffff)} (slot {c >> 16})'
    if tag == 0x3a:
        return f'{s(b)} cryme? {nm(a)} kinds {c & 0xff:#x} threat {c >> 8}'
    if tag == 0x3b:
        return f'{s(b)} {nm(a)} spares GY-trigger cards (mask {c:#x})'
    if tag == 0x3c:
        return f'{s(b)} D.D. Crow answers {nm(a)} uid {c}'
    if tag == 0x38:
        return f'{s(b)} attack plan: {nm(a)} first at {nm(c & 0xffff)} (slot {c >> 16}), the protector'
    if tag in (0x60, 0x61):
        return f'{s(b)} synchro {nm(a)} {"material" if tag == 0x60 else "send"} slots {c:#x}'
    if tag == 0x62:
        return f'{s(b)} synchro? {nm(a)} materials {c & 0xff:#x} -> {c >> 8}'
    if tag == 0x81:
        return f'{s(b)} field +{nm(a)} slot {(b >> 8) & 0xff}{"" if b & 0x10000 else " (set)"}'
    if tag == 0x82:
        return f'{s(b)} field -{nm(a)} slot {(b >> 8) & 0xff}'
    if tag == 0x83:
        return f'LP {side_of(0)} {a}, {side_of(1)} {b}'
    if tag == 0x84:
        return f'phase {a} ({s(b)})'
    if tag == 0x85:
        tgt = 'direct' if b == 0xffffffff else f'{nm(b & 0xffff)} (slot {b >> 16})'
        return f'{s(c)} attack {nm(a & 0xffff)} (slot {a >> 16}) -> {tgt}'
    if tag == 0x86:
        return 'setup done'
    if tag == 0x88:
        return f'WARNING {s(b)} {nm(a)} got a uid outside the loaded decks (more scenario cards than deck + Extra Deck)'
    if tag == 0x89:
        return f'WARNING {s(b)} Extra Deck card {nm(a)} got a Main Deck uid (more Extra Deck cards than the loaded deck has; a Fusion Summon of it can stall the duel screen)'
    if tag == 0x8f:
        return f'stop: {DUEL_DONE.get(a, a)}'
    if tag == 0x8e:
        return f'{s(b)} forced {nm(a)} ({"response" if (b >> 8) & 1 else "main"}) #{c}'
    if tag == 0x8d:
        return f'{s(b)} force refused {nm(a)} phase {(b >> 12) & 0xf} {"response" if (b >> 8) & 1 else "main"}: {force_reason(c)}'
    if tag == 0x8b:
        return (f'{s(b)} {("before", "after", "precost")[(b >> 8) & 3]}: LP {c} hand {a & 0xff} deck {(a >> 8) & 0xff} '
                f'gy {(a >> 16) & 0xff} banished {a >> 24} monsters {b >> 24} spells {(b >> 16) & 0xff}')
    if tag == 0x8c:
        return f'{s(b)} {("before", "after", "precost")[(a >> 24) & 3]}: {nm(a & 0xffff)} slot {(a >> 16) & 0xff} {c & 0xffff}/{c >> 16}'
    return f'tag {tag:#x} {nm(a)} {b:#x} {c:#x}'


def force_reason(r):
    if r & 0x100:
        return 'not in hand or on the field'
    if r & 0x200:
        return f'slot {r >> 16} state blocks activation'
    bits = [('engine check', 1), ('timing', 2), ('can', 4), ('can+targets', 8)]
    out = ' '.join(f'{n}={1 if r & b else 0}' for n, b in bits)
    return f'slot {r >> 16}: {out}' + (' cpu-blocked' if r & 0x10 else '')


def summarize(scn, ram, syms, cards, wall, reason):
    first = ram.u32(syms['gym_side_player']) & 1
    side_of = lambda p: 'first' if (p & 1) == first else 'second'
    evs = [e for e in events(ram, syms) if e[0] not in (0x80,)]
    warnings = [describe(e, cards, side_of) for e in evs if e[0] in (0x88, 0x89)]
    run_from = next((i for i, e in enumerate(evs) if e[0] == 0x86), 0)
    evs = evs[run_from:]
    res = {'name': scn['name'], 'stop': reason, 'wall': wall, 'turns': ram.u32(0x022d0f84) - ram.u32(syms['gym_start_turn']),
           'fusions': [f'{side_of(e[3])}:{cards.name(e[2])}' for e in evs if e[0] == 2],
           'attacks': [describe(e, cards, side_of).split(' attack ')[1] for e in evs if e[0] == 0x85],
           'activations': {}, 'chain': [describe(e, cards, side_of) for e in evs if e[0] == 6],
           'lp': {side_of(p): ram.u32(PLAYERS + p * PSIZE) for p in (0, 1)},
           'board': {side_of(p): board(ram, cards, p) for p in (0, 1)},
           'log': [f't{e[1]} ' + describe(e, cards, side_of) for e in evs], 'warnings': warnings,
           'events': evs, 'card_name': cards.name}
    for e in evs:
        if e[0] == 1:
            k = f'{side_of(e[3])}:{cards.name(e[2])}'
            res['activations'][k] = res['activations'].get(k, 0) + 1
    res['window'] = window(evs, scn.get('stop', {}).get('card'), cards, side_of)
    res['checks'] = check(scn.get('expect', {}), res)
    return res


def snap_state(evs, cards, side_of):
    st = {}
    for e in evs:
        tag, _, a, b, c = e
        if tag == 0x8b:
            st.setdefault(side_of(b), {}).update(lp=c, hand=a & 0xff, deck=(a >> 8) & 0xff, gy=(a >> 16) & 0xff,
                                                 banished=a >> 24, monsters=b >> 24, spells=(b >> 16) & 0xff,
                                                 field=(b >> 24) + ((b >> 16) & 0xff))
        elif tag == 0x8c:
            st.setdefault(side_of(b), {}).setdefault('stats', []).append((cards.name(a & 0xffff), c & 0xffff, c >> 16))
    return st


def window(evs, card, cards, side_of):
    kind = lambda e: (e[3] >> 8 if e[0] == 0x8b else e[2] >> 24) & 0xff if e[0] in (0x8b, 0x8c) else None
    start = next((i for i, e in enumerate(evs) if e[0] == 1 and (not card or cards.name(e[2]) == card)), None)
    end = next((i for i, e in enumerate(evs) if kind(e) == 1), None)
    pre = next((i for i, e in enumerate(evs) if kind(e) == 2), None)
    if start is None or end is None:
        return None

    def snap(i):
        j, n = i, 0
        while j < len(evs) and evs[j][0] in (0x8b, 0x8c) and n < 2:
            n += evs[j][0] == 0x8b
            j += 1
        return snap_state(evs[i:j], cards, side_of)
    return {'side': side_of(evs[start][3]), 'before': snap(start + 1), 'after': snap(end),
            'precost': snap(pre) if pre is not None and pre < start else None}


def in_range(got, want):
    return want[0] <= got <= want[1] if isinstance(want, list) else got == want


def check(expect, res):
    out = []
    win = res.get('window')
    for key, w0, w1 in (('delta', 'before', 'after'), ('cost_delta', 'precost', 'before')):
        if key not in expect:
            continue
        if not win or not win.get(w0):
            out.append((key, False, f'no {w0} snapshot of the stop card (it never resolved, or the chain never settled)'))
            continue
        b0, a0 = win[w0], win[w1]
        for side, zones in expect[key].items():
            if side == 'total':
                for z, want in zones.items():
                    got = sum(a0.get(sd, {}).get(z, 0) - b0.get(sd, {}).get(z, 0) for sd in ('first', 'second'))
                    out.append((key, in_range(got, want), f'both sides {z} {got:+d}, want {want}'))
                continue
            b, a = b0.get(side, {}), a0.get(side, {})
            for z, want in zones.items():
                got = a.get(z, 0) - b.get(z, 0)
                out.append((key, in_range(got, want), f'{side} {z} {b.get(z)} -> {a.get(z)} ({got:+d}), want {want}'))
    for side, want in expect.get('stat_delta', {}).items():
        if not win:
            out.append(('stat_delta', False, 'no settled resolve window'))
            continue
        bs = {n: (atk, df) for n, atk, df in win['before'].get(side, {}).get('stats', [])}
        got = [(n, atk - bs[n][0], df - bs[n][1]) for n, atk, df in win['after'].get(side, {}).get('stats', []) if n in bs]
        hits = [g for g in got if in_range(g[1], want.get('atk', g[1])) and in_range(g[2], want.get('def', g[2]))
                and (not want.get('card') or g[0] == want['card'])]
        n = want.get('count', 1)
        out.append(('stat_delta', in_range(len(hits), n), f'{side} ATK/DEF changes {got}, want {n} with {want}'))
    if 'stop' in expect:
        out.append(('stop', res['stop'] == expect['stop'], f'stopped on "{res["stop"]}", want "{expect["stop"]}"'))
    fus = [f.split(':', 1)[1] for f in res['fusions'] if f.startswith('first:')]
    if 'fusions' in expect:
        want = expect['fusions']
        out.append(('fusions', fus[:len(want)] == want, f'{fus} starts with {want}'))
    for n in expect.get('no_fusion', []):
        out.append(('no_fusion', n not in fus, f'{n} not in {fus}'))
    ns = [e[2] for e in res['events'] if e[0] == 4]
    for n in expect.get('no_normal_summon', []):
        got = [x for x in ns if res['card_name'](x) == n]
        out.append(('no_normal_summon', not got, f'{n} Normal Summoned {len(got)} times by the Tearlaments AI'))
    if 'first_attack_target' in expect:
        got = res['attacks'][0].split(' -> ')[1].split(' (')[0] if res['attacks'] else None
        out.append(('first_attack_target', got == expect['first_attack_target'], f'{got} == {expect["first_attack_target"]}'))
    if 'max_resolves' in expect:
        for card, n in expect['max_resolves'].items():
            got = res['activations'].get(f'first:{card}', 0)
            out.append(('max_resolves', got <= n, f'{card} resolved {got} <= {n}'))
    for card, want in expect.get('picks', {}).items():
        got = [l.split(' -> ', 1)[1] for l in res['log'] if f' first pick {card} -> ' in l]
        out.append(('picks', all(w in got for w in want), f'{card} picks {got} include {want}'))
    if expect.get('no_wasted_trigger'):
        declined, wasted = set(), []
        for e in res['events']:
            if e[0] == 0x37 and not e[4] >> 16:
                declined.add(e[2])
            elif e[0] == 0x34 and e[4] >> 16 == 5 and (e[4] & 0xffff) in declined:
                wasted.append(e[4] & 0xffff)
        out.append(('no_wasted_trigger', not wasted, f'cards Special Summoned after their GY Fusion was declined: {wasted}'))
    if 'lp_first_min' in expect:
        out.append(('lp_first_min', res['lp']['first'] >= expect['lp_first_min'],
                    f'first LP {res["lp"]["first"]} >= {expect["lp_first_min"]}'))
    if 'lp_second_max' in expect:
        out.append(('lp_second_max', res['lp']['second'] <= expect['lp_second_max'],
                    f'second LP {res["lp"]["second"]} <= {expect["lp_second_max"]}'))
    if 'lp_second_min' in expect:
        out.append(('lp_second_min', res['lp']['second'] >= expect['lp_second_min'],
                    f'second LP {res["lp"]["second"]} >= {expect["lp_second_min"]}'))
    if 'second_monsters_max' in expect:
        n = sum(1 for f in res['board']['second']['field'] if int(f.split(':')[0]) < 5)
        out.append(('second_monsters_max', n <= expect['second_monsters_max'], f'second has {n} monsters <= {expect["second_monsters_max"]}'))
    for s in expect.get('log_has', []):
        out.append(('log_has', any(s in l for l in res['log']), f'a log line contains "{s}"'))
    for s in expect.get('log_lacks', []):
        got = [l for l in res['log'] if s in l]
        out.append(('log_lacks', not got, f'no log line contains "{s}"' + (f' (got {got[0]!r})' if got else '')))
    if 'log_order' in expect:
        want, k = expect['log_order'], 0
        for l in res['log']:
            if k < len(want) and want[k] in l:
                k += 1
        out.append(('log_order', k == len(want), f'log lines contain {want} in this order (matched {k})'))
    for side, texts in expect.get('field_has', {}).items():
        f = res['board'][side]['field']
        out.append(('field_has', all(any(t in x for x in f) for t in texts), f'{side} field {f} shows {texts}'))
    for side, texts in expect.get('field_lacks', {}).items():
        f = res['board'][side]['field']
        out.append(('field_lacks', not any(t in x for t in texts for x in f), f'{side} field {f} shows none of {texts}'))
    for side, names in expect.get('gy_has', {}).items():
        gy = res['board'][side]['gy']
        out.append(('gy_has', all(n in gy for n in names), f'{side} GY {gy} has {names}'))
    for side, names in expect.get('banished_has', {}).items():
        ban = res['board'][side]['banished']
        out.append(('banished_has', all(n in ban for n in names), f'{side} banished {ban} has {names}'))
    for side, names in expect.get('gy_lacks', {}).items():
        gy = res['board'][side]['gy']
        out.append(('gy_lacks', not any(n in gy for n in names), f'{side} GY {gy} has none of {names}'))
    return out


def run_one(name, scn, cards, syms, timeout, keep):
    d = gym_dir(name)
    inst = os.path.join(d, 'run', scn['name'])
    if os.path.isdir(inst):
        shutil.rmtree(inst)
    os.makedirs(inst)
    rom = os.path.join(inst, 'g.nds')
    os.symlink(os.path.join(d, 'gym.nds'), rom)
    shutil.copy(SAVE, os.path.join(inst, 'g.sav'))
    with open(os.path.join(d, 'base.ml1'), 'rb') as f:
        state = bytearray(f.read())
    blob = scenario_blob(scn, cards)
    r = ram_of(state)
    box = syms['gym_box'] - MAIN + r
    state[box:box + 4] = struct.pack('<I', 1)
    state[box + 32:box + 32 + len(blob)] = blob
    if scn.get('rng'):
        rng = DUEL_RNG - MAIN + r
        state[rng:rng + 4] = struct.pack('<I', int(scn['rng']) & 0xffffffff)
    with open(os.path.join(inst, 'g.ml1'), 'wb') as f:
        f.write(state)
    t0 = time.time()
    m = Melon(rom, os.path.join(d, 'cfg_fast'))
    reason, ram, last, still = 'timeout', None, None, time.time()
    try:
        m.key('F1')
        limit = scn.get('stop', {}).get('timeout', timeout)
        while time.time() - t0 < limit:
            time.sleep(1)
            data = m.snapshot(os.path.join(inst, 'g.ml2'), 2)
            if not data:
                continue
            ram = Ram(data)
            if ram.u32(syms['gym_box']) != 1:
                m.key('F1')
                continue
            done = ram.u32(syms['gym_done'])
            if done:
                reason = DUEL_DONE.get(done, str(done))
                break
            fp = (ram.u32(syms['gym_frames']), ram.u32(syms['glog_n']), hashlib.md5(ram.block(0x022cb000, 0x6000)).digest())
            if fp != last:
                last, still = fp, time.time()
            elif ram.u16(0x022ccbc4) & 0x3fff == 5:
                reason = DUEL_DONE[3]
                break
            elif time.time() - still > scn.get('stop', {}).get('hang', 12):
                cmd = ram.u32(0x022ccbc4), ram.u32(0x022ccbc8)
                reason = f'hang (command {cmd[0]:#010x} {cmd[1]:#010x}, gym state {ram.u32(syms["gym_state"])})'
                break
    finally:
        m.stop()
    wall = time.time() - t0
    if ram is None:
        return {'name': scn['name'], 'stop': 'no savestate', 'wall': wall}
    res = summarize(scn, ram, syms, cards, wall, reason)
    bad = code_changes(ram, code_text(os.path.join(d, 'work')))
    if bad:
        res['checks'].append(('code', False, f'mod code overwritten at {", ".join(hex(a) for a in bad[:4])}'
                                             f'{" ..." if len(bad) > 4 else ""} ({len(bad)} words)'))
    if not keep:
        shutil.rmtree(inst)
    return res


def print_result(res, measure, out):
    w = out.write
    checks = res.get('checks', [])
    ok = 'pass' if checks and all(c[1] for c in checks) else 'FAIL' if checks else '-'
    w(f'## {res["name"]}: stop={res["stop"]} wall={res["wall"]:.1f}s turns={res.get("turns", "?")} checks={ok}\n')
    for c in checks:
        w(f'  {"ok  " if c[1] else "FAIL"} {c[0]}: {c[2]}\n')
    for line in res.get('warnings', []):
        w(f'  {line}\n')
    if 'board' not in res:
        return
    for k in measure:
        v = res[k]
        if k == 'log':
            w('  log:\n' + ''.join(f'    {line}\n' for line in v))
        elif k == 'board':
            for side, b in v.items():
                w(f'  {side}: LP {b["lp"]} deck {b["deck"]} gy {b["gy_n"]} extra {b["extra_n"]}\n'
                  f'    hand {b["hand"]}\n    field {b["field"]}\n    gy {b["gy"]}\n    banished {b["banished"]}\n')
        else:
            w(f'  {k}: {v}\n')


def cmd_run(a):
    d = gym_dir(a.name)
    meta = os.path.join(d, 'base.json')
    if not os.path.exists(meta) or json.load(open(meta))['rom_sha1'] != sha1(os.path.join(d, 'gym.nds')):
        base(a.name)
    melon_config(d, True)
    cards = Cards()
    syms = symbols(os.path.join(d, 'work'))
    scns = load_scenarios(a.scenarios)
    if a.only:
        scns = [s for s in scns if s['name'] in a.only]
    for s in scns:
        scenario_blob(s, cards)
    jobs = a.jobs or max(1, min(len(scns), (os.cpu_count() or 2) // 2))
    t0 = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        futs = []
        for i, s in enumerate(scns):
            futs.append(ex.submit(run_one, a.name, s, cards, syms, a.timeout, a.keep))
            time.sleep(0.3)
        for f in futs:
            results.append(f.result())
    measure = a.measure.split(',') if a.measure else None
    out = open(a.out, 'w') if a.out else sys.stdout
    out.write(f'| scenario | stop | wall s | turns | fusions | attacks | LP first/second | checks |\n|---|---|---|---|---|---|---|---|\n')
    for r in results:
        ch = r.get('checks', [])
        out.write(f'| {r["name"]} | {r["stop"]} | {r["wall"]:.1f} | {r.get("turns", "")} | {", ".join(r.get("fusions", []))} | '
                  f'{len(r.get("attacks", []))} | {r.get("lp", {}).get("first", "")}/{r.get("lp", {}).get("second", "")} | '
                  f'{"pass" if ch and all(c[1] for c in ch) else "FAIL" if ch else "-"} |\n')
    out.write(f'\n{len(results)} scenarios, {jobs} in parallel, {time.time() - t0:.1f} s\n\n')
    for r, s in zip(results, scns):
        print_result(r, measure or s.get('measure', ['fusions', 'attacks', 'lp']), out)
    if a.out:
        out.close()
        print(open(a.out).read())


def pool_names():
    path = os.path.join(ROOT, 'build', 'wc2011', 'wc2011_status.tsv')
    with open(path, encoding='utf-8') as f:
        rows = [l.rstrip('\n').split('\t') for l in f][1:]
    return {r[1]: r[5] for r in rows if r[3] != 'no' or r[2] not in ('normal', 'token')}


def winner(r):
    if r.get('stop') != 'duel over':
        return None
    lp, b = r['lp'], r['board']
    lost = [sd for sd in ('first', 'second') if lp[sd] == 0] or [sd for sd in ('first', 'second') if b[sd]['deck'] == 0]
    return None if len(lost) != 1 else ('second' if lost[0] == 'first' else 'first')


def write_duel_log(where, s, r, cards, stem):
    os.makedirs(where, exist_ok=True)
    with open(os.path.join(where, s['name'] + '.txt'), 'w') as fh:
        fh.write(f'first {stem(s["decks"][0])}, second {stem(s["decks"][1])}; winner {winner(r) or "none"}\n')
        for side in ('first', 'second'):
            main, _ = deck_file(s[side]['deck_file'], cards, side, s[side]['shuffle'])
            fh.write(f'{side} opening hand: {[cards.name(c) for c in main[:5]]}\n'
                     f'{side} next draws: {[cards.name(c) for c in main[5:15]]}\n')
        print_result(r, ['fusions', 'attacks', 'lp', 'board', 'log'], fh)


def cmd_sweep(a):
    decks = [p for g in a.decks for p in sorted(glob.glob(g))]
    if len(decks) < 2:
        raise SystemExit('sweep: give at least two deck files')
    stem = lambda p: os.path.splitext(os.path.basename(p))[0]
    scns = []
    for i, x in enumerate(decks):
        for y in decks[i + 1:]:
            for s in range(1, a.seeds + 1):
                f, g = (x, y) if s % 2 else (y, x)
                scns.append({'name': f'{stem(f)}_vs_{stem(g)}_s{s}', 'turn': 0,
                             'first': {'deck_file': os.path.relpath(f, ROOT), 'shuffle': s},
                             'second': {'deck_file': os.path.relpath(g, ROOT), 'shuffle': s + 1000},
                             'stop': {'turns': a.turns, 'timeout': a.timeout, 'hang': 25}, 'measure': ['activations'],
                             'rng': zlib.crc32(f'{stem(f)}_vs_{stem(g)}_s{s}'.encode()) | 1,
                             'decks': (f, g)})
    d = gym_dir(a.name)
    meta = os.path.join(d, 'base.json')
    if not os.path.exists(meta) or json.load(open(meta))['rom_sha1'] != sha1(os.path.join(d, 'gym.nds')):
        base(a.name)
    melon_config(d, True)
    cards, syms, pool = Cards(), symbols(os.path.join(d, 'work')), pool_names()
    held = {}
    for p in decks:
        main, extra = deck_file(p, cards, p, 0)
        held[p] = {cards.name(c) for c in main + extra}
    for s in scns:
        scenario_blob(s, cards)
    print(f'sweep: {len(scns)} duels, {len(decks)} decks, {a.turns} turns each, -j {a.jobs}', flush=True)
    t0, results = time.time(), []
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        futs = []
        for s in scns:
            futs.append(ex.submit(run_one, a.name, s, cards, syms, a.timeout, False))
            time.sleep(0.3)
        for k, f in enumerate(futs, 1):
            results.append(f.result())
            r = results[-1]
            if a.logs:
                write_duel_log(a.logs, scns[k - 1], r, cards, stem)
            print(f'sweep: {k}/{len(scns)} duels done, {time.time() - t0:.0f} s; {r["name"]}: {r["stop"]}, '
                  f'turn {r.get("turns")}, winner {winner(r) or "none"}', flush=True)
    stats = {}
    for r, s in zip(results, scns):
        bad = not str(r['stop']).startswith(('turns', 'duel over'))
        names = held[s['decks'][0]] | held[s['decks'][1]]
        t = r.get('turns') or 0
        seen = set()
        for side, draws in (('first', t // 2), ('second', (t + 1) // 2)):
            main, extra = deck_file(s[side]['deck_file'], cards, side, s[side]['shuffle'])
            seen |= {cards.name(c) for c in main[:5 + draws] + extra}
        res, ann = {}, {}
        for e in r.get('events', []):
            if e[0] == 1:
                res[cards.name(e[2])] = res.get(cards.name(e[2]), 0) + 1
            elif e[0] == 0x2c:
                ann[cards.name(e[2])] = ann.get(cards.name(e[2]), 0) + 1
        for n in names:
            if n not in pool:
                continue
            st = stats.setdefault(n, {'duels': 0, 'seen': 0, 'used': 0, 'resolves': 0, 'activates': 0, 'bad': []})
            st['duels'] += 1
            st['seen'] += n in seen
            st['used'] += n in res
            st['resolves'] += res.get(n, 0)
            st['activates'] += ann.get(n, 0)
            if bad:
                st['bad'].append(f'{r["name"]}: {r["stop"]}')
    out = open(a.out, 'w') if a.out else sys.stdout
    out.write('| card | verified | duels | duels seen | duels used | resolves | ACTIVATE | flag |\n|---|---|---|---|---|---|---|---|\n')
    for n, st in sorted(stats.items(), key=lambda kv: (not kv[1]['bad'], kv[1]['used'] > 0, kv[0])):
        flag = []
        if st['bad']:
            flag.append(f'{len(st["bad"])} hang/timeout')
        if not st['used']:
            flag.append('never resolved' if st['seen'] else 'never seen')
        if st['activates'] > st['resolves']:
            flag.append('more ACTIVATE than resolves')
        out.write(f'| {n} | {pool[n]} | {st["duels"]} | {st["seen"]} | {st["used"]} | {st["resolves"]} | {st["activates"]} | {"; ".join(flag)} |\n')
    pairs = {}
    for r, s in zip(results, scns):
        f, g = map(stem, s['decks'])
        p = pairs.setdefault(tuple(sorted((f, g))), {})
        win = winner(r)
        key = 'unfinished' if win is None else f'{(f, g)[win == "second"]} {"first" if win == "first" else "second"}'
        p[key] = p.get(key, 0) + 1
    out.write('\n| pair | wins A (first/second) | wins B (first/second) | unfinished |\n|---|---|---|---|\n')
    for (x, y), p in sorted(pairs.items()):
        cell = lambda d: (f'{d} {p.get(d + " first", 0) + p.get(d + " second", 0)} '
                          f'({p.get(d + " first", 0)}/{p.get(d + " second", 0)})')
        out.write(f'| {x} vs {y} | {cell(x)} | {cell(y)} | {p.get("unfinished", 0)} |\n')
    bad = sorted({b for st in stats.values() for b in st['bad']})
    out.write(f'\n{len(scns)} duels in {time.time() - t0:.0f} s; {len(bad)} ended in a hang or timeout\n')
    for b in bad:
        out.write(f'- {b}\n')
    if a.out:
        out.close()
        print(open(a.out).read())


def main():
    ap = argparse.ArgumentParser(description=__doc__ + ' A scenario (JSON) sets both players\' cards; the duel then runs '
                                 'CPU vs CPU from that state until a stop condition, and a table of trace results is printed.',
                                 epilog='Scenario format and examples: docs/archive-wc2008/MODDING-wc2008.md "Test the CPU AI", mod/test/scenarios/.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='build the gym ROM build/gym/<name>/gym.nds (mod + gym hooks) and its paused base savestate')
    b.add_argument('name', help='bench name, e.g. head or before')
    b.add_argument('--src', default=os.path.join(ROOT, 'mod', 'src'), help='engine C sources to build with variants/retro-genesys/src (default: mod/src)')
    b.add_argument('--no-base', action='store_true', help='skip the base savestate (made by the first run instead)')
    b.add_argument('--unverified', nargs='*', metavar='CARD',
                   help='also build the auto-translated effects of mod/effects/auto.json not yet "verified" (default ROMs '
                        'leave them out): the named cards (names or ids), or every one with no name. Every one is about '
                        '130 KB of code, which leaves too little heap: duels hang in battle damage with WC2011 monsters')
    r = sub.add_parser('run', help='run scenarios on a built bench, several melonDS at once, and print the results')
    r.add_argument('name', help='bench name given to build')
    r.add_argument('scenarios', nargs='+', help='scenario .json files or folders of them')
    r.add_argument('--only', nargs='*', help='scenario names to run from the folders')
    r.add_argument('-j', '--jobs', type=int, help='parallel emulators (default: nproc/2, at most one per scenario)')
    r.add_argument('--timeout', type=float, default=120, help='seconds per scenario unless the scenario sets stop.timeout')
    r.add_argument('--measure', help='comma list overriding each scenario\'s "measure": fusions,attacks,activations,chain,lp,board,log')
    r.add_argument('--out', help='also write the results to this file')
    r.add_argument('--keep', action='store_true', help='keep build/gym/<name>/run/<scenario>/ (ROM link, savestates)')
    w = sub.add_parser('sweep', help='CPU-vs-CPU duels between every pair of decks, then one row per WC2011 pool card: '
                       'duels it was in, duels where it resolved, resolves, ACTIVATE starbursts, hangs')
    w.add_argument('name', help='bench name given to build')
    w.add_argument('decks', nargs='+', help='deck spec .json or .ydc files (globs allowed)')
    w.add_argument('--seeds', type=int, default=4, help='duels per deck pair, seats alternating (default 4)')
    w.add_argument('--turns', type=int, default=12, help='turns per duel (default 12)')
    w.add_argument('--timeout', type=float, default=500, help='seconds per duel (default 500)')
    w.add_argument('-j', '--jobs', type=int, default=2, help='parallel emulators (default 2)')
    w.add_argument('--out', help='also write the table to this file')
    w.add_argument('--logs', help='write each duel\'s opening hands, event log and end board to <logs>/<duel>.txt')
    c = sub.add_parser('clean', help='delete build/gym/<name> (ROM, savestates, work files)')
    c.add_argument('name')
    a = ap.parse_args()
    if a.cmd == 'build':
        build(a.name, a.src, a.unverified)
        if not a.no_base:
            base(a.name)
    elif a.cmd == 'run':
        cmd_run(a)
    elif a.cmd == 'sweep':
        cmd_sweep(a)
    elif a.cmd == 'clean':
        shutil.rmtree(gym_dir(a.name))


if __name__ == '__main__':
    main()
