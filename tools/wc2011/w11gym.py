#!/usr/bin/env python3
"""WC2011 scenario rig: a duel started from a written board (WC2011's own duel-puzzle loader), run in melonDS,
result read from RAM."""
import argparse
import concurrent.futures
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import carddb
import game
import gym

VARIANT = os.path.join(ROOT, 'variants', 'dimension-break')
GYM_SRC = os.path.join(ROOT, 'mod', 'test', 'w11gym', 'src')
SCENARIOS = os.path.join(ROOT, 'mod', 'test', 'w11scenarios')
FAST11 = os.path.join(ROOT, 'build', 'w11fast', 'base.nds')
NPC11 = os.path.join(ROOT, 'build', 'w11npc')
WORK = os.environ.get('W11GYM_WORK') or os.path.join(ROOT, 'build', 'w11gym')
MAGIC = 0x31475747
PZ_MAX = 0xeb0
PLAYER_SIZE = 0xb3c
LOG_N = 128
STATES = {0: 'waiting', 1: 'launched', 2: 'running', 3: 'done', 4: 'exited'}
DONE = {1: 'turns', 2: 'duel over', 3: 'frames', 4: 'phase'}
ATTRS = ('none', 'light', 'dark', 'water', 'fire', 'earth', 'wind', 'divine')
PHASES = {'draw': 0, 'standby': 1, 'main1': 2, 'battle': 3, 'main2': 4, 'end': 5}
PILES = (('hand', 11), ('extra', 12), ('deck', 13), ('gy', 14), ('banished', 15))
OFF = {'lp': 0, 'hand_count': 0xc, 'deck_count': 0x10, 'gy_count': 0x14, 'extra_count': 0x18,
       'banished_count': 0x1c, 'slots': 0x34, 'hand': 0x124, 'deck': 0x304, 'extra': 0x4e4, 'gy': 0x55c,
       'banished': 0x7b4}
COUNT_OF = {'hand': 'hand_count', 'deck': 'deck_count', 'extra': 'extra_count', 'gy': 'gy_count',
            'banished': 'banished_count'}
DEFAULT_CHARS = [309, 310]
ACT_N = 4
SHOT_CROP = '256x420+0+0'
GYM_CODE_FLOOR = 0x023b9400
ACT_KINDS = {'special_summon': 1, 'activate': 2, 'inspect': 3, 'summon_group': 4, 'summon': 5, 'summon_procedure': 6}
ACT_ZONES = {'any': 0, 'hand': 11, 'gy': 14, 'banished': 15}
ACT_RESULTS = {1: 'queued', 3: 'card not found'}


class Cards:
    def __init__(self, rom_path):
        import ydc
        rom = game.open_rom(rom_path)
        prof = game.for_rom(rom)
        self.db = carddb.CardDB.load(game.container_files(rom, prof['card_db']['container']), prof)
        self.decks = ydc.rom_decks(rom)
        self.by_name = {}
        in_pack, priced = set(), set()
        for c in self.db.cards[1:]:
            # Match the shipped CPU deck compiler: prefer an obtainable
            # artwork over hidden duplicate IDs. Stock effects such as White
            # Stone's search do not recognise every hidden Blue-Eyes copy.
            if any(c.packs) and self.by_name.get(c.names['e']) not in in_pack:
                self.by_name[c.names['e']] = c.id
                in_pack.add(c.id)
            if c.pwcost and self.by_name.get(c.names['e']) not in in_pack | priced:
                self.by_name[c.names['e']] = c.id
                priced.add(c.id)
            self.by_name.setdefault(c.names['e'], c.id)
        self.by_fold = {}
        for name, cid in self.by_name.items():
            self.by_fold.setdefault(name.casefold(), cid)
        self.by_pw = {c.password: c.id for c in self.db.cards[1:] if c.password}
        self.names = {c.id: c.names['e'] for c in self.db.cards[1:]}
        self.frames = {c.id: c.frame for c in self.db.cards[1:]}

    def frame(self, cid):
        return self.frames.get(cid, 0)

    def id(self, ref, where):
        if isinstance(ref, int):
            if ref in self.by_pw:
                return self.by_pw[ref]
            raise SystemExit(f'{where}: no card has passcode {ref}')
        if ref.startswith('id:'):
            cid = int(ref[3:])
            if cid not in self.names:
                raise SystemExit(f'{where}: no card has id {cid}')
            return cid
        if ref in self.by_name:
            return self.by_name[ref]
        if ref.casefold() in self.by_fold:
            return self.by_fold[ref.casefold()]
        raise SystemExit(f'{where}: unknown card {ref!r}')

    def name(self, cid):
        return self.names.get(cid, f'id:{cid}')


def entry(e):
    return e if isinstance(e, dict) else {'card': e}


def side_blob(side, cards, where):
    slots = {}
    for k, m in enumerate(side.get('monsters', [])):
        m = entry(m)
        slot = m.get('slot', k)
        if not 0 <= slot <= 4 or slot in slots:
            raise SystemExit(f'{where}: monster slot {slot}')
        pos = m.get('position', 'attack')
        face = m.get('face_up', pos != 'set')
        flags = int(face) | (2 if pos in ('defense', 'set') else 0) | (0x10 if m.get('special') else 0)
        slots[slot] = (cards.id(m['card'], where), flags)
    spell_slot = 5
    for s in side.get('spells', []):
        s = entry(s)
        if s.get('field'):
            slot = 10
        else:
            slot = s.get('slot', spell_slot)
            spell_slot = slot + 1
        if not 5 <= slot <= 10 or slot in slots:
            raise SystemExit(f'{where}: spell slot {slot}')
        slots[slot] = (cards.id(s['card'], where), int(s.get('face_up', True)))
    piles = {}
    for name, bit in PILES:
        ids = [cards.id(c, where) for c in side.get(name, [])]
        for c, n in side.get(f'{name}_fill', []) if name == 'deck' else []:
            ids += [cards.id(c, where)] * n
        if len(ids) > 255:
            raise SystemExit(f'{where}: {name} holds at most 255 cards')
        if ids:
            piles[bit] = ids
    mask = sum(1 << s for s in slots) | sum(1 << b for b in piles)
    out = bytearray(struct.pack('<H', mask))
    for s in sorted(slots):
        cid, flags = slots[s]
        out += struct.pack('<HB', cid, flags)
    for b in sorted(piles):
        out += bytes([len(piles[b])]) + b''.join(struct.pack('<H', c) for c in piles[b])
    return bytes(out)


def expand_side(side, cards, seed, where):
    import random
    if 'deck_file' in side:
        from deck_paths import resolve_deck
        with open(resolve_deck(os.path.join(ROOT, side['deck_file']))) as f:
            d = json.load(f)
        main = [n for n, k in d['main'].items() for _ in range(k)]
        random.Random(seed).shuffle(main)
        out = dict(side)
        out.setdefault('hand', main[:5])
        out.setdefault('deck', main[5:] if 'hand' not in side else main)
        out.setdefault('extra', [n for n, k in d.get('extra', {}).items() for _ in range(k)])
        return out
    if 'ydc' not in side:
        return side
    import ydc
    key = f'deck/{side["ydc"]}.ydc'
    if key not in cards.decks:
        raise SystemExit(f'{where}: no {key} in the ROM')
    d = ydc.Deck.parse(cards.decks[key])
    main = [f'id:{c & 0x3fff}' for c in d.main]
    random.Random(seed).shuffle(main)
    out = dict(side)
    out.setdefault('hand', main[:5])
    out.setdefault('deck', main[5:] if 'hand' not in side else main)
    out.setdefault('extra', [f'id:{c & 0x3fff}' for c in d.extra])
    return out


def expand(scn, cards):
    sides = scn['sides']
    if len(sides) != 2:
        raise SystemExit(f'{scn["name"]}: "sides" lists 2 players, the first takes the first turn')
    seed = scn.get('seed', 1)
    scn['sides'] = [expand_side(s, cards, seed * 2 + k, f'{scn["name"]} side {k}') for k, s in enumerate(sides)]


def scenario_blob(scn, cards):
    sides = scn['sides']
    if len(sides) != 2:
        raise SystemExit(f'{scn["name"]}: "sides" lists 2 players, the first takes the first turn')
    out = bytearray(b'YQ' + struct.pack('<HH', sides[0].get('lp', 8000), sides[1].get('lp', 8000)))
    for k, s in enumerate(sides):
        out += side_blob(s, cards, f'{scn["name"]} side {k}')
    out += b'\0'
    if len(out) > PZ_MAX:
        raise SystemExit(f'{scn["name"]}: board is {len(out)} B, the rig holds {PZ_MAX}')
    return bytes(out)


def box_bytes(scn, cards):
    expand(scn, cards)
    if scn.get('turbo'):
        for side in scn['sides']:
            side['spells'] = list(side.get('spells', [])) + [{'card': 'Speed World 2', 'field': True}]
    blob = scenario_blob(scn, cards)
    stop = scn.get('stop', {})
    chars = scn.get('chars', DEFAULT_CHARS)
    phase = PHASES[stop['phase']] + 1 if 'phase' in stop else 0
    head = struct.pack('<IIIIIIIIII', 1, MAGIC, int(scn.get('cpu_both', True)), scn.get('seed', 1), chars[0], chars[1],
                       0 if stop.get('duel_end') else stop.get('turns', 0 if phase or stop.get('frames') else 1), phase,
                       stop.get('frames', 0),
                       len(blob))
    acts = scn.get('actions', [scn['action']] if 'action' in scn else [])
    if len(acts) > ACT_N:
        raise SystemExit(f'{scn["name"]}: at most {ACT_N} actions')
    tail = struct.pack('<4I', scn.get('turn', 1) - 1, int(scn.get('turbo', False)),
                       *(s.get('speed_counters', 0) for s in scn['sides']))
    for act in acts + [None] * (ACT_N - len(acts)):
        if act is None:
            tail += bytes(24)
            continue
        zone = act.get('from', 'any')
        tail += struct.pack('<IIIIII', ACT_KINDS[act['kind']], act.get('side', 0), cards.id(act['card'], scn['name']),
                            ACT_ZONES[zone] if zone in ACT_ZONES else int(zone) + 1, act.get('turn', 0), act.get('wait', 0))
    return head + b''.join(deck_record(s, cards, scn['name']) for s in scn['sides']) + blob.ljust(PZ_MAX, b'\0') + tail


def deck_record(side, cards, where):
    extra_frames = {2, 3, 17, 18, 19}
    main, extra = [], [cards.id(c, where) for c in side.get('extra', [])]
    refs = side.get('hand', []) + side.get('deck', []) + side.get('gy', []) + side.get('banished', [])
    refs += [c for c, n in side.get('deck_fill', []) for _ in range(n)]
    refs += [entry(m)['card'] for m in side.get('monsters', []) + side.get('spells', [])]
    for r in refs:
        cid = cards.id(r, where)
        (extra if cards.frame(cid) in extra_frames else main).append(cid)
    main, extra = main[:60], extra[:15]
    rec = bytearray(0xc0)
    struct.pack_into('<III', rec, 0, len(main), 0, len(extra))
    struct.pack_into(f'<{len(main)}H', rec, 0xc, *main)
    struct.pack_into(f'<{len(extra)}H', rec, 0xa2, *extra)
    return bytes(rec)


def symbols(work):
    syms = gym.symbols(work)
    with open(os.path.join(work, 'code.map')) as map_file:
        for address, name in re.findall(r'0x([0-9a-f]+)\s+(__bank\d+_(?:start|end))\s+=', map_file.read()):
            syms[name] = int(address, 16)
    syms['gym_box'] = syms['gym_storage']
    syms['gym_end'] = syms['gym_storage'] + 4
    return syms


def load_scenarios(paths, only=None):
    files = []
    for p in paths:
        files += [(f, True) for f in sorted(glob.glob(os.path.join(p, '*.json')))] if os.path.isdir(p) else [(p, False)]
    out = []
    for f, scanned in files:
        with open(f) as fh:
            scn = json.load(fh)
        scn['name'] = os.path.splitext(os.path.basename(f))[0]
        if scn['name'] in only if only else not (scanned and scn.get('open_bug')):
            out.append(scn)
    return out


def duel_variant():
    variant = os.path.join(WORK, 'variant')
    shutil.rmtree(variant, ignore_errors=True)
    os.makedirs(os.path.join(variant, 'src'))
    for folder in ('pac', 'files'):
        source = os.path.join(VARIANT, folder)
        if os.path.isdir(source):
            os.symlink(source, os.path.join(variant, folder))
    with open(os.path.join(VARIANT, 'src', 'menu_overlay.txt')) as f:
        omit = {line.strip() for line in f if line.strip()}
    omit |= {'menu_overlay.txt', 'w11menu.c', 'w11menu_stubs.S', 'menu11.h', 'debug11.c', 'debug11.h',
             'debug11_font.h', 'points11.c', 'packs11.c', 'packs11_stubs.S'}
    for name in os.listdir(os.path.join(VARIANT, 'src')):
        if name not in omit:
            os.symlink(os.path.join(VARIANT, 'src', name), os.path.join(variant, 'src', name))
    with open(os.path.join(variant, 'src', 'gym_shop.c'), 'w') as f:
        f.write('void w11pk_save(void) {}\nvoid w11pk_load(void) {}\nvoid w11pk_clear(void) {}\n')
    return variant


def base_variant():
    variant = os.path.join(WORK, 'base_variant')
    shutil.rmtree(variant, ignore_errors=True)
    os.makedirs(os.path.join(variant, 'src'))
    with open(os.path.join(VARIANT, 'src', 'hooks.asm')) as f:
        m = re.search(r'^\.if defined\(gym_start\)\n(.*?)^\.endif\n', f.read(), re.S | re.M)
    if not m:
        raise SystemExit(f'{VARIANT}/src/hooks.asm: no gym_start block')
    with open(os.path.join(variant, 'src', 'hooks.asm'), 'w') as f:
        f.write('.nds\n.thumb\n.include "symbols.asm"\n.macro jump_to, target\n    bx pc\n    nop\n.arm\n'
                '    ldr pc, [pc, -4]\n    .word target\n.thumb\n.endmacro\n' + m[1])
    with open(os.path.join(variant, 'src', 'gym_base.c'), 'w') as f:
        f.write('unsigned w11_visual_frame(unsigned id) { return ((unsigned (*)(unsigned))0x02022d71)(id); }\n'
                'int dm_proc_ok(unsigned p, unsigned uid) { return 1; }\n')
    return variant


def cmd_build(a):
    os.makedirs(WORK, exist_ok=True)
    if a.base:
        rom = os.path.join(WORK, 'gym.nds')
        r = subprocess.run([sys.executable, os.path.join(HERE, '..', 'build_rom.py'), a.base, rom, '--mod', base_variant(),
                            '--src', GYM_SRC, '--code-floor', hex(a.code_floor if a.code_floor is not None else GYM_CODE_FLOOR)],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(r.stdout + r.stderr)
        return finish_build(rom)
    if not os.path.isfile(FAST11):
        raise SystemExit(f'{FAST11}: run `make rom VARIANT=dimension-break` first (it makes the sped-up base)')
    rom = os.path.join(WORK, 'gym.nds')
    extra = []
    if a.pad_kb:
        pad = os.path.join(WORK, 'pad')
        os.makedirs(pad, exist_ok=True)
        with open(os.path.join(pad, 'w11pad.c'), 'w') as f:
            f.write(f'const unsigned char w11_pad[{a.pad_kb * 1024}] __attribute__((used)) = {{1}};\n')
        extra = ['--src', pad]
    if not os.path.isdir(os.path.join(NPC11, 'src')):
        raise SystemExit(f'{NPC11}: run `make rom VARIANT=dimension-break` first (it builds the story NPC files)')
    r = subprocess.run([sys.executable, os.path.join(HERE, '..', 'build_rom.py'), FAST11, rom, '--mod', VARIANT if a.production_ui else duel_variant(),
                        '--pac', os.path.join(NPC11, 'pac'), '--src', os.path.join(NPC11, 'src'),
                        '--src', GYM_SRC, *extra, '--game-code', 'YG8P',
                        '--code-floor', hex(a.code_floor if a.code_floor is not None else GYM_CODE_FLOOR)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    print(r.stdout.strip().splitlines()[-2])
    finish_build(rom)


def finish_build(rom):
    syms = symbols(os.path.join(WORK, 'work'))
    with open(os.path.join(WORK, 'syms.json'), 'w') as f:
        json.dump(syms, f)
    d = os.path.join(WORK, 'base')
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    link = os.path.join(d, 'g.nds')
    os.symlink(rom, link)
    m = gym.Melon(link, gym.melon_config(d, True))
    try:
        state = None
        for _ in range(60):
            time.sleep(1)
            data = m.snapshot(os.path.join(d, 'g.ml1'), 1)
            if data and gym.Ram(data).u32(syms['gym_state']) == 0 and gym.Ram(data).u32(0x020b7cc4) > 60:
                state = data
                break
    finally:
        m.stop()
    if not state:
        raise SystemExit(f'no savestate at the rig wait point; see {d}')
    # Verify the native SDK copied every initialized bank and did not clear it.
    ram = gym.Ram(state)
    bank_bytes = 0
    for path in sorted(glob.glob(os.path.join(WORK, 'work', 'bank*.bin'))):
        number = os.path.basename(path)[4:-4]
        key = f'__bank{number}_start'
        if key not in syms:
            continue
        with open(path, 'rb') as bank_file:
            want = bank_file.read()
        if ram.block(syms[key], len(want)) != want:
            raise SystemExit(f'initialized bank {number} differs from linked image after native boot')
        bank_bytes += len(want)
    if bank_bytes:
        print(f'native boot: {bank_bytes} initialized bank bytes verified')
    with open(os.path.join(WORK, 'base.ml1'), 'wb') as f:
        f.write(state)
    shutil.rmtree(d)
    print(f'{rom}, {WORK}/base.ml1: rig waiting for a scenario')


def read_side(ram, base, p):
    b = base + p * PLAYER_SIZE
    out = {'lp': ram.u32(b)}
    for name in ('hand', 'deck', 'extra', 'gy', 'banished'):
        n = ram.u32(b + OFF[COUNT_OF[name]])
        out[name] = [ram.u32(b + OFF[name] + 4 * i) & 0x3fff for i in range(min(n, 150))]
    out['field'] = {}
    for s in range(11):
        sl = ram.block(b + OFF['slots'] + 20 * s, 20)
        w, = struct.unpack_from('<I', sl, 0)
        if w & 0x3fff:
            out['field'][s] = {'id': w & 0x3fff, 'face_up': struct.unpack_from('<H', sl, 8)[0],
                               'defense': struct.unpack_from('<H', sl, 6)[0], 'flags': struct.unpack_from('<I', sl, 16)[0]}
    return out


def read_result(ram, syms):
    res = {k: ram.u32(syms[k]) for k in ('gym_state', 'gym_done', 'gym_frames', 'gym_turns', 'gym_oks', 'gym_log_n')}
    res['speed_counters'] = [ram.u32(syms['gym_speed'] + 4 * i) for i in range(2)]
    res['actions'] = [ram.u32(syms['gym_act_result'] + 4 * i) for i in range(ACT_N)]
    res['heap'] = dict(zip(('start', 'end', 'peak_used', 'peak_blocks', 'min_free', 'min_largest'),
                           (ram.u32(syms['gym_heap'] + 4 * i) for i in range(6))))
    if 'gym_se_lost_n' in syms:
        res['se_lost'] = ram.u32(syms['gym_se_lost_n'])
    info = [ram.u32(syms['gym_end_info'] + 4 * i) for i in range(6)]
    res.update(why=info[0], turn_player=info[1], phase=info[2], decided=info[3], winner=info[4])
    base = syms['gym_end'] if res['gym_state'] >= 3 else 0x0229ac94
    res['sides'] = [read_side(ram, base, p) for p in range(2)]
    if 'gym_stats' in syms and res['gym_state'] >= 3:
        for p in range(2):
            for slot, f in res['sides'][p]['field'].items():
                if slot < 5:
                    a = syms['gym_stats'] + 12 * (5 * p + slot)
                    f['atk'], f['def'], f['attr'] = (struct.unpack('<i', struct.pack('<I', ram.u32(a + 4 * k)))[0]
                                                     for k in range(3))
    n = res['gym_log_n']
    log = []
    for k in range(max(0, n - LOG_N), n):
        i = k % LOG_N
        w = [ram.u32(syms['gym_log'] + 16 * i + 4 * j) for j in range(4)]
        log.append({'op': w[0] & 0xffff, 'frame': w[0] >> 16, 'a': w[1] & 0xffff, 'b': w[1] >> 16, 'c': w[2],
                    'turn_player': w[3] & 0xff, 'phase': (w[3] >> 8) & 0xff, 'turns': w[3] >> 16})
    res['log'] = log
    res['acts'] = [ram.u32(syms['gym_acts'] + 4 * i) for i in range(ram.u32(syms['gym_acts_n']))]
    return res


def activations(res):
    """(turn number from the start, side, card id) of every effect activation (duel command 0x2d)."""
    return [(w >> 16, w >> 15 & 1, w & 0x3fff) for w in res.get('acts', [])]


def screenshots(m, d, stop, every):
    k = 0
    while not stop.wait(every):
        subprocess.run(['import', '-display', m.display, '-window', 'root', '-crop', SHOT_CROP,
                        os.path.join(d, f'shot{k:04d}.png')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        k += 1


def run_one(scn, cards, syms, timeout, keep, shots=0.0):
    d = os.path.join(WORK, 'run', scn['name'])
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    rom = os.path.join(d, 'g.nds')
    os.symlink(os.path.join(WORK, 'gym.nds'), rom)
    with open(os.path.join(WORK, 'base.ml1'), 'rb') as f:
        state = bytearray(f.read())
    box = box_bytes(scn, cards)
    r = gym.ram_of(state)
    o = syms['gym_box'] - gym.MAIN + r
    state[o:o + len(box)] = box
    for addr, value in scn.get('ram', {}).items():
        a = int(addr, 16) - gym.MAIN + r
        state[a:a + 4] = struct.pack('<I', value)
    with open(os.path.join(d, 'g.ml1'), 'wb') as f:
        f.write(state)
    t0 = time.time()
    m = gym.Melon(rom, gym.melon_config(d, not shots))
    res = None
    stop_shots = threading.Event()
    try:
        m.key('F1')
        if shots:
            threading.Thread(target=screenshots, args=(m, d, stop_shots, shots), daemon=True).start()
        limit = scn.get('stop', {}).get('timeout', timeout)
        while time.time() - t0 < limit:
            time.sleep(2)
            data = m.snapshot(os.path.join(d, 'g.ml2'), 2)
            if not data:
                continue
            ram = gym.Ram(data)
            if ram.u32(syms['gym_box']) != 1:
                m.key('F1')
                continue
            if ram.u32(syms['gym_state']) >= 3:
                res = read_result(ram, syms)
                break
        else:
            if data:
                res = read_result(gym.Ram(data), syms)
                res['timeout'] = True
    finally:
        stop_shots.set()
        m.stop()
    if res is None:
        res = {'gym_state': -1}
    res['wall'] = round(time.time() - t0, 1)
    res['name'] = scn['name']
    with open(os.path.join(d, 'result.json'), 'w') as f:
        json.dump(res, f)
    if not keep:
        for fn in ('g.ml1', 'g.ml2'):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                os.remove(p)
    return res


def check(scn, res, cards):
    out = []
    exp = scn.get('expect', {})
    if res.get('timeout') and exp.get('stop') != 'timeout':
        out.append(('completed', False, 'duel rig timed out'))
    sides = res.get('sides')
    if not sides:
        return [('result', False, 'no result read')]
    if 'stop' in exp:
        got = DONE.get(res.get('why'), 'timeout' if res.get('timeout') else str(res.get('why')))
        out.append(('stop', got == exp['stop'], got))
    for key, zone in (('gy_has', 'gy'), ('hand_has', 'hand'), ('banished_has', 'banished'), ('deck_has', 'deck')):
        for s, names in exp.get(key, {}).items():
            have = [cards.name(c) for c in sides[int(s)][zone]]
            miss = [n for n in names if n not in have]
            out.append((f'{key} {s}', not miss, f'missing {miss}' if miss else 'ok'))
    for s, names in exp.get('deck_shuffled', {}).items():
        deck = [cards.name(c) for c in sides[int(s)]['deck']]
        pos = sorted(i for i, n in enumerate(deck) if n in names)
        k, n = len(names), len(deck)
        ok = len(pos) == k and pos != list(range(k)) and pos != list(range(n - k, n))
        out.append((f'deck_shuffled {s}', ok, f'positions {pos} of {n}'))
    for key in ('hand', 'deck', 'gy', 'banished', 'extra'):
        for s, want in exp.get(f'{key}_count', {}).items():
            got = len(sides[int(s)][key])
            lo, hi = want if isinstance(want, list) else (want, want)
            out.append((f'{key}_count {s}', lo <= got <= hi, str(got)))
    for s, want in exp.get('speed_counters', {}).items():
        got = res['speed_counters'][int(s)]
        out.append((f'speed_counters {s}', got == want, str(got)))
    for s, want in exp.get('lp', {}).items():
        got = sides[int(s)]['lp']
        lo, hi = want if isinstance(want, list) else (want, want)
        out.append((f'lp {s}', lo <= got <= hi, str(got)))
    for s, names in exp.get('field_has', {}).items():
        have = [cards.name(f['id']) for f in sides[int(s)]['field'].values()]
        miss = [n for n in names if n not in have]
        out.append((f'field_has {s}', not miss, f'missing {miss}' if miss else 'ok'))
    for s, entries in exp.get('field_position', {}).items():
        for name, position in entries.items():
            cid = cards.id(name, scn['name'])
            matches = [f for f in sides[int(s)]['field'].values()
                       if f['id'] == cid or (isinstance(name, str) and not name.startswith('id:')
                                             and cards.name(f['id']) == cards.name(cid))]
            ok = any(('set' if not f['face_up'] else 'defense' if f['defense'] else 'attack') == position for f in matches)
            out.append((f'field_position {s} {name}', ok, position))
    for key, k in (('field_atk', 'atk'), ('field_def', 'def'), ('field_attr', 'attr')):
        for s, entries in exp.get(key, {}).items():
            for name, want in entries.items():
                cid = cards.id(name, scn['name'])
                got = [f.get(k) for f in sides[int(s)]['field'].values()
                       if f['id'] == cid or (isinstance(name, str) and not name.startswith('id:')
                                             and cards.name(f['id']) == cards.name(cid))]
                if k == 'attr':
                    got = [ATTRS[g] if g is not None and g < len(ATTRS) else g for g in got]
                    ok = want in got
                else:
                    lo, hi = want if isinstance(want, list) else (want, want)
                    ok = any(g is not None and lo <= g <= hi for g in got)
                out.append((f'{key} {s} {name}', ok, str(got)))
    if 'se_lost' in exp:
        got = res.get('se_lost')
        out.append(('se_lost', got is not None and got <= exp['se_lost'], str(got)))
    acts = [cid for _, _, cid in activations(res)]
    for name in exp.get('activated', []):
        n = acts.count(cards.id(name, scn['name']))
        out.append((f'activated {name}', n > 0, f'{n} activation(s)'))
    for name in exp.get('not_activated', []):
        n = acts.count(cards.id(name, scn['name']))
        out.append((f'not_activated {name}', n == 0, f'{n} activation(s)'))
    return out


def describe(res, cards):
    lines = [f'stop: {DONE.get(res.get("why"), res.get("why"))}{" (timeout)" if res.get("timeout") else ""}, '
             f'frames {res.get("gym_frames")}, turn changes {res.get("gym_turns")}, phase {res.get("phase")}, '
             f'commands {res.get("gym_log_n")}, wall {res.get("wall")} s']
    for p, s in enumerate(res.get('sides', [])):
        field = ', '.join(f'{k}:{cards.name(v["id"])}{"" if v["face_up"] else "(set)"}{"(def)" if v["defense"] else ""}'
                          f'{" " + str(v["atk"]) + "/" + str(v["def"]) + " " + ATTRS[v["attr"]] if "atk" in v and 0 <= v["attr"] < len(ATTRS) else ""}'
                          for k, v in sorted(s['field'].items()))
        lines.append(f'  side {p}: LP {s["lp"]}, hand {[cards.name(c) for c in s["hand"]]}, deck {len(s["deck"])}, '
                     f'GY {[cards.name(c) for c in s["gy"]]}, banished {len(s["banished"])}, field [{field}]')
    h = res.get('heap')
    if h and h['start']:
        lines.append(f'  duel heap {h["start"]:#x}-{h["end"]:#x} ({h["end"] - h["start"]} B): peak use {h["peak_used"]} B '
                     f'in {h["peak_blocks"]} blocks, lowest free {h["min_free"]} B, smallest largest free block '
                     f'{h["min_largest"]} B')
    if res.get('se_lost'):
        lines.append(f'  sound effects not played (bank load failed after eviction): {res["se_lost"]}')
    for i, r in enumerate(res.get('actions', [])):
        if r:
            lines.append(f'  action {i}: ' + ACT_RESULTS.get(r, f'refused, allowed actions mask {r & 0xff:#x}, failed checks {r >> 16:#x}'))
    acts = activations(res)
    lines.append('  activations: ' + (', '.join(f'turn {t + 1} side {s} {cards.name(c)}' for t, s, c in acts) or 'none'))
    return lines


def cmd_run(a):
    syms_path = os.path.join(WORK, 'syms.json')
    if not os.path.isfile(syms_path) or not os.path.isfile(os.path.join(WORK, 'base.ml1')):
        raise SystemExit('run `tools/wc2011/w11gym.py build` first')
    with open(syms_path) as f:
        syms = json.load(f)
    cards = Cards(os.path.join(WORK, 'gym.nds'))
    only = a.only.split(',') if a.only else None
    if a.smoke:
        seen, picks = set(), set(only or [])
        for s in load_scenarios(a.scenarios, None):
            family = '_'.join(s['name'].split('_')[:2])
            if '_full' not in s['name'] and not s['name'].startswith('full_') and family not in seen:
                seen.add(family)
                picks.add(s['name'])
        only = sorted(picks)
    scns = load_scenarios(a.scenarios, only)
    if not scns:
        raise SystemExit('no scenario')
    fails = 0
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        for scn, res in zip(scns, ex.map(lambda s: run_one(s, cards, syms, a.timeout, a.keep, a.shots), scns)):
            print(f'== {scn["name"]}')
            for line in describe(res, cards):
                print(line)
            if 'commands' in scn.get('measure', []) or a.commands:
                for e in res.get('log', []):
                    ids = [cards.name(v & 0x3fff) for v in (e['a'], e['b'], e['c'] & 0xffff) if (v & 0x3fff) in cards.names]
                    print(f'    t{e["turns"]} p{e["phase"]} op {e["op"]:#06x} a {e["a"]:#06x} b {e["b"]:#06x} '
                          f'c {e["c"]:#010x} {" ".join(ids)}')
            for name, ok, msg in check(scn, res, cards):
                print(f'  {"pass" if ok else "FAIL"} {name}: {msg}')
                fails += not ok
    if fails:
        raise SystemExit(f'{fails} check(s) failed')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('build', help=f'gym ROM from the variant build + {os.path.relpath(GYM_SRC, ROOT)}, then the '
                                     'savestate of the rig waiting for a scenario')
    p.add_argument('--code-floor', type=lambda value: int(value, 0), help='test-only resident code floor (hex or decimal)')
    p.add_argument('--production-ui', action='store_true',
                   help='retain all production UI code to test animation memory pressure')
    p.add_argument('--pad-kb', type=int, default=0,
                   help='tests only: add N KB of dummy code, to measure the duel heap with a larger code reserve')
    p.add_argument('--base', help='build the rig on this ROM instead of the variant, e.g. the QoL patch on the base game '
                                   '(set W11GYM_WORK to keep the Dimension Break rig)')
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser('run', help='run scenarios (files or folders), one muted melonDS each')
    p.add_argument('scenarios', nargs='*', default=[SCENARIOS])
    p.add_argument('--only', help='comma-separated scenario names')
    p.add_argument('--smoke', action='store_true',
                   help='add the first scenario of each family (first two name words), full duels excluded')
    p.add_argument('--jobs', '-j', type=int, default=1, help='emulators at once (default 1)')
    p.add_argument('--timeout', type=float, default=180)
    p.add_argument('--keep', action='store_true', help='keep the savestates of each run')
    p.add_argument('--commands', action='store_true', help='print every duel command the rig logged')
    p.add_argument('--shots', type=float, default=0.0, metavar='S',
                   help='run at normal speed and screenshot the screens every S seconds into build/w11gym/run/<name>/')
    p.set_defaults(fn=cmd_run)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
