#!/usr/bin/env python3
"""WC2011 View Mode duel series for showcase clips: unrigged CPU-vs-CPU duels between two Free Duel opponents, started
from a savestate at the second opponent pick (one tap, then A at the janken's music select), a text replay per duel, a
score per duel, and the recording of a chosen duel from the tap until the game is back at the Free Duel menu."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, 'tools'), HERE]
import gym
import melonds_capture as cap
import view_deal

WORK = os.path.join(ROOT, 'build', 'w11showcase')
VIEW_ELF = os.path.join(ROOT, 'build', 'w11fast', 'w11view.elf')
VIEW_BIN = os.path.join(ROOT, 'build', 'w11fast', 'w11view.bin')
NM = os.path.expanduser(os.environ.get('ARM_TOOLCHAIN', '~/tools/arm-gnu-toolchain/bin')) + '/arm-none-eabi-nm'

FRAME = 0x020b7cc4
CALLBACK = 0x020b7c8c
SCENE = 0x020b9970
SCENE_PREV = 0x020b9928
SCENE_CB = 0x020b9994
SCENE_GO = 0x020b9990
FRAME_FN = 0x020162e4
TITLE_SCENE = (31, 28)
LIST_SCENE = 0x02157000
MENU_ID = 0x020b8f3c
VIEW_ID = 0x2007
LIST_CURSOR = 0x020b8f58
LOAD_SIDE = 0x02018bd8
SE_STOP = 0x02033b5c
SE_ALL = 0x8f00001
FATAL_FN = 0x0201dca4
SOUND_HANDLES = 0x021278a0
UNLOCK = 0x02126884
UNLOCK_FIRST, UNLOCK_N = 0x71, 60
LIST = 0x021610a0
LIST_COUNT = LIST + 0xeeae
LIST_PAGE = LIST + 0xefa2
LIST_ROW = LIST + 0xefb8
LIST_CHARS = 0x021701c0
PORTRAIT = 0x020b8b18
LAUNCH = 0x02019358
LAUNCH_STEP = 0x020b8834
SEED = 0x020b8bec
FRAME_BASE = 0x10000
PAD_NEW = 0x020b87e0
KEY_A = 1
JANKEN_FRAMES = 90
PUSH = 0x021c3bc8
DUEL = 0x0229dd44
PLAYERS = 0x0229ac94
PSIZE = 0xb3c
PBLOCK = 0x124
SOFT_BRIGHT = 0x020b9130
ROW_TAP = (90, 256)
ROW_STEP = 24
PILES = ('hand', 'deck', 'gy', 'extra', 'banished')
PILE_OFF = {'hand': 0xc, 'deck': 0x10, 'gy': 0x14, 'extra': 0x18, 'banished': 0x1c}
ZONES = 12
SIDE_NAMES = ('bottom', 'top')
PHASES = {0: 'DP', 1: 'SP', 2: 'M1', 3: 'BP', 4: 'M2', 5: 'EP', 7: 'start'}
GDB_WAIT = 4.0
STUCK_WALL = 120
HANG_FRAMES = 60 * 60 * 6
RECORD_TAIL = 6.0
MUSIC_MASK = 0x02126918
MUSIC_LAST = 0x0212691a
DUEL_BGM = 0x020b8858
CUT_FPS = 60
CUT_DARK = 9
CUT_RUN = 6

ENGINES = {
    'dm': {
        'name': 'Dark Magician',
        'cards': ['Dark Magician', 'Dark Magician Girl', 'Dark Paladin', 'Dark Magician Girl the Dragon Knight',
                  'Dark Magical Circle', 'Eternal Soul', 'The Eye of Timaeus', 'The Gaze of Timaeus',
                  'Magician of Dark Illusion', 'Dark Magic Attack', 'Thousand Knives', 'Illusion Magic',
                  'Dark Magic Inheritance', 'Magician Navigation', 'Amulet Dragon', 'Palladium Oracle Mahad',
                  'Apprentice Illusion Magician', "Magician's Rod", "Magician's Robe", 'Soul Servant',
                  'Palladium Oracle Mana', 'Dark Flare Knight'],
        'signature': ['Dark Magician', 'Dark Paladin', 'Dark Magician Girl the Dragon Knight', 'Dark Magical Circle',
                      'Eternal Soul', 'The Eye of Timaeus', 'The Gaze of Timaeus', 'Amulet Dragon'],
    },
    'gladiator': {
        'name': 'Gladiator Beast',
        'prefix': 'Gladiator Beast',
        'cards': ['Gladiator Proving Ground', 'Test Tiger', 'Gladiator Beast War Chariot'],
        'signature': ['Gladiator Beast Gyzarus', 'Gladiator Beast Heraklinos', 'Gladiator Beast Gaiodiaz'],
        'tag_out': True,
    },
    'blackwing': {
        'name': 'Blackwing',
        'prefix': 'Blackwing',
        'cards': ['Black Whirlwind', 'Black-Winged Dragon', 'Stardust Dragon', 'Black Rose Dragon',
                  'Delta Crow - Anti Reverse'],
        'signature': ['Blackwing Armor Master', 'Black-Winged Dragon', 'Blackwing - Silverwind the Ascendant',
                      'Blackwing Armed Wing', 'Black Whirlwind'],
        'synchro': True,
    },
    'chaos': {
        'name': 'Chaos Lightsworn',
        'suffix': 'Lightsworn',
        'cards': ['Judgment Dragon', 'Black Luster Soldier - Envoy of the Beginning', 'Chaos Sorcerer',
                  'Chaos Emperor Dragon - Envoy of the End', 'Charge of the Light Brigade', 'Necro Gardna',
                  'Armageddon Knight', 'Ryko, Lightsworn Hunter', 'Lyla, Lightsworn Sorceress',
                  'Garoth, Lightsworn Warrior', 'Wulf, Lightsworn Beast', 'Ehren, Lightsworn Monk',
                  'Jain, Lightsworn Paladin', 'Celestia, Lightsworn Angel', 'Gragonith, Lightsworn Dragon',
                  'Solar Recharge', 'Lumina, Lightsworn Summoner'],
        'signature': ['Judgment Dragon', 'Black Luster Soldier - Envoy of the Beginning', 'Chaos Sorcerer',
                      'Chaos Emperor Dragon - Envoy of the End'],
        'mills': True,
    },
}


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def view_symbols():
    out = subprocess.run([NM, VIEW_ELF], capture_output=True, text=True, check=True).stdout
    syms = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3:
            syms[p[2]] = int(p[0], 16)
    return {k: syms[k] for k in ('vm_state', 'vm_list_exit', 'vm_janken_pick')}


def free_port():
    while True:
        port = random.randrange(24000, 32000, 2)
        try:
            for p in (port, port + 1):
                with socket.socket() as s:
                    s.bind(('127.0.0.1', p))
            return port
        except OSError:
            continue


class Gdb(view_deal.Rsp):
    def cmd(self, data, reply=True):
        r = super().cmd(data, reply)
        while reply and data[0] in 'mMpPzZ' and r[:1] in ('S', 'T'):
            r = self.reply()
        return r

    def halt(self):
        self.s.sendall(b'\x03')
        self.reply()

    def go(self):
        self.cmd('c', reply=False)

    def bp(self, addr):
        self.ok(f'Z0,{addr:x},2')

    def unbp(self, addr):
        self.cmd(f'z0,{addr:x},2')

    def read(self, addr, n):
        r = self.cmd(f'm{addr:x},{n:x}')
        out, i = [], 0
        while i < len(r):
            if r[i] == '*':
                out.append(out[-1] * (ord(r[i + 1]) - 29))
                i += 2
            else:
                out.append(r[i])
                i += 1
        try:
            data = bytes.fromhex(''.join(out))
        except ValueError:
            raise SystemExit(f'GDB read {addr:#x}+{n:#x}: {r[:40]!r}')
        if len(data) != n:
            raise SystemExit(f'GDB read {addr:#x}+{n:#x}: got {len(data)} bytes ({r[:16]})')
        return data

    def read_big(self, addr, n):
        return b''.join(self.read(addr + o, min(0x100, n - o)) for o in range(0, n, 0x100))

    def u16(self, addr):
        return struct.unpack('<H', self.read(addr, 2))[0]

    def wait(self, timeout):
        self.s.settimeout(timeout)
        try:
            self.reply()
            return True
        except SystemExit:
            return False
        finally:
            self.s.settimeout(60)

    def regs(self):
        return {n: self.reg(n) for n in range(17)}

    def resume(self, regs):
        for n in list(range(15)) + [16]:
            self.set_reg(n, regs[n])
        self.set_reg(15, regs[15] | (regs[16] >> 5 & 1))
        self.go()

    def at_frame(self):
        self.bp(FRAME_FN)
        self.go()
        self.reply()
        self.unbp(FRAME_FN)

    def call(self, fn, *args):
        self.bp(FRAME_FN)
        for i, v in enumerate(args):
            self.set_reg(i, v)
        self.set_reg(14, FRAME_FN | 1)
        self.set_reg(15, fn | 1)
        self.go()
        self.reply()
        self.unbp(FRAME_FN)
        if self.reg(15) != FRAME_FN:
            raise SystemExit(f'call {fn:#x}: stopped at {self.reg(15):#x}')
        return self.reg(0)


class Headless:
    def __init__(self, rom, cfg):
        self.m = gym.Melon(rom, cfg)
        self.env = self.m.env

    def tap(self, x, y):
        self.m.tap(x, y + 22)

    def key(self, k):
        self.m.key(k)

    def shot(self, path):
        subprocess.run(['import', '-window', 'root', path], env=self.env)

    def stop(self):
        self.m.stop()


class Recorder:
    def __init__(self, rom, cfg, raw):
        w, h = 1024, 1536
        self.xvfb, disp = gym.xvfb(f'{w}x{h}x24')
        self.env = dict(os.environ, DISPLAY=disp, XDG_CONFIG_HOME=cfg, **cap.audio_env())
        self.mods = cap.load_audio(False)
        self.melon = self.rec = None
        self.melon = subprocess.Popen([cap.MELON, '-f', rom], env=self.env, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True)
        self.win = cap.find_window(self.env, self.melon.pid)
        time.sleep(2)
        subprocess.run(['xdotool', 'windowmove', self.win, '0', '0', 'windowsize', self.win, str(w), str(h)], env=self.env)
        time.sleep(1)
        self.x, self.y, cw, ch, self.s = cap.screen_area(*cap.geometry(self.env, self.win))
        self.size, self.raw = (cw, ch), raw
        self.disp = disp

    def start_capture(self):
        if not cap.melon_on_sink():
            raise SystemExit(f'melonDS sound is not on {cap.SINK}')
        cw, ch = self.size
        self.rec = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-thread_queue_size', '1024',
                                     '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '60', '-video_size', f'{cw}x{ch}',
                                     '-i', f'{self.disp}+{self.x},{self.y}', '-thread_queue_size', '1024', '-f', 'pulse',
                                     '-i', f'{cap.SINK}.monitor', '-copyts', '-c:v', 'libx264', '-preset', 'veryfast',
                                     '-crf', '12', '-pix_fmt', 'yuv444p', '-c:a', 'pcm_s16le', self.raw],
                                    stdin=subprocess.PIPE, text=True)

    def xdo(self, *args):
        subprocess.run(['xdotool', *args], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def key(self, k):
        self.xdo('windowfocus', '--sync', self.win, 'keydown', k)
        time.sleep(0.12)
        self.xdo('keyup', k)
        time.sleep(0.2)

    def tap(self, x, y):
        self.xdo('mousemove', str(self.x + x * self.s + self.s // 2), str(self.y + y * self.s + self.s // 2),
                 'mousedown', '1')
        time.sleep(0.15)
        self.xdo('mouseup', '1')

    def stop(self):
        if self.rec and self.rec.poll() is None:
            self.rec.stdin.write('q')
            self.rec.stdin.flush()
            self.rec.wait(60)
        for p in (self.melon, self.xvfb):
            if p and p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        for mod in reversed(self.mods):
            cap.sh('pactl', 'unload-module', mod)


def gdb_cfg(src, dst):
    port = free_port()
    view_deal.gdb_config(src, dst, port)
    return port


def instance(work, name, rom, sav):
    inst = os.path.join(work, 'run', name)
    shutil.rmtree(inst, ignore_errors=True)
    os.makedirs(inst)
    os.symlink(os.path.abspath(rom), os.path.join(inst, 'v.nds'))
    shutil.copy(sav, os.path.join(inst, 'v.sav'))
    return inst


def opponent_char(text):
    if text.isdigit():
        return int(text)
    roster = os.path.join(ROOT, 'build', 'wc2011', 'opponents', 'roster.tsv')
    for line in open(roster, encoding='utf-8').read().splitlines()[1:]:
        f = line.split('\t')
        if text.lower() in (f[0].lower(), f[4].lower()):
            return int(f[2])
    for d in ('variants/dimension-break/opponents',):
        p = os.path.join(ROOT, d, text + '.json')
        if os.path.exists(p):
            spec = json.load(open(p, encoding='utf-8'))
            for k in ('chara', 'stock_chara'):
                if k in spec:
                    return spec[k]
    raise SystemExit(f'opponent {text!r}: give a char id, a roster.tsv opponent or name, or an opponent spec name')


def cmd_start(a):
    rom = os.path.abspath(a.rom)
    bottom, top = opponent_char(a.bottom), opponent_char(a.top)
    work = a.work
    os.makedirs(work, exist_ok=True)
    blob = open(VIEW_BIN, 'rb').read()
    syms = view_symbols()
    sav = os.path.join(work, 'start.sav')
    shutil.copy(a.save, sav)
    inst = instance(work, 'start', rom, sav)
    port = gdb_cfg(gym.melon_config(inst, True), os.path.join(inst, 'cfg'))
    emu = Headless(os.path.join(inst, 'v.nds'), os.path.join(inst, 'cfg'))
    try:
        g = Gdb(port)
        g.go()
        t0 = time.time()
        while True:
            time.sleep(1)
            g.halt()
            if (g.u32(SCENE), g.u32(SCENE + 4)) == TITLE_SCENE and g.u32(FRAME) > 600:
                break
            if time.time() - t0 > 120:
                raise SystemExit('the title screen never came up')
            g.go()
        code = g.read_big(syms['vm_list_exit'], 0x100)
        want = blob[syms['vm_list_exit'] - syms['vm_state']:][:0x100]
        if code != want:
            raise SystemExit(f'{VIEW_BIN} is not the View Mode code in {rom}: rebuild the ROM and w11fast together')
        g.at_frame()
        regs = g.regs()
        for n in range(UNLOCK_FIRST, UNLOCK_FIRST + UNLOCK_N):
            w = UNLOCK + (n >> 5) * 4
            g.w32(w, g.u32(w) | 1 << (n & 31))
        g.w32(MENU_ID, VIEW_ID)
        g.w32(syms['vm_state'], 1)
        g.call(LOAD_SIDE, 1, bottom)
        if g.u32(PORTRAIT + 4) & 0x7fffffff != bottom:
            raise SystemExit(f'char {bottom}: side 1 portrait {g.u32(PORTRAIT + 4):#x} after the load')
        g.call(syms['vm_list_exit'], 0, 0, 0)
        if g.u32(syms['vm_state']) != 2:
            raise SystemExit('vm_list_exit did not take the first pick')
        g.resume(regs)
        time.sleep(4)
        g.halt()
        n = g.u16(LIST_COUNT)
        chars = list(struct.unpack(f'<{n}H', g.read(LIST_CHARS, 2 * n)))
        if top not in chars:
            raise SystemExit(f'char {top} is not in the CPU Duel list ({n} entries: {chars})')
        index = chars.index(top)
        g.at_frame()
        regs = g.regs()
        g.write(LIST_CURSOR, bytes([1, index // 5, index % 5]))
        g.w32(SCENE_PREV, g.u32(SCENE))
        g.w32(SCENE, 7)
        g.w32(SCENE + 4, 5)
        g.w32(SCENE_CB, LIST_SCENE)
        g.w32(SCENE_GO, 1)
        g.resume(regs)
        time.sleep(5)
        g.halt()
        page, row = g.u16(LIST_PAGE), g.u16(LIST_ROW)
        if page * 5 + row != index or g.u32(PORTRAIT + 4) & 0x7fffffff != top:
            raise SystemExit(f'list cursor on page {page} row {row}, portrait {g.u32(PORTRAIT + 4):#x}; wanted index {index}')
        g.at_frame()
        regs = g.regs()
        thunk = struct.pack('<6H2I', 0xb500, 0x4802, 0x2100, 0x4b02, 0x4798, 0xbd00, SE_ALL, SE_STOP)
        saved = g.read(FATAL_FN, len(thunk))
        g.write(FATAL_FN, thunk)
        try:
            g.call(FATAL_FN)
        finally:
            g.write(FATAL_FN, saved)
        g.resume(regs)
        time.sleep(1)
        g.halt()
        playing = [g.u32(SOUND_HANDLES + i * 0x6c + 0x28) & 0xffff for i in range(0x1c)
                   if g.read(SOUND_HANDLES + i * 0x6c + 0x5a, 1)[0] < 0x80 and g.u32(SOUND_HANDLES + i * 0x6c + 0x28) & 0x3000000 == 0x1000000]
        if playing:
            raise SystemExit(f'sound effects still playing after the stop: {playing}')
        frame = g.u32(FRAME)
        g.go()
        time.sleep(1)
        emu.shot(os.path.join(work, 'pre.png'))
        state = os.path.join(inst, 'v.ml1')
        if not emu.m.snapshot(state, 1):
            raise SystemExit('no savestate from the opponent list')
        g.detach()
    finally:
        emu.stop()
    shutil.copy(state, os.path.join(work, 'pre.ml1'))
    meta = {'rom': rom, 'rom_sha1': sha1(rom), 'save': os.path.abspath(a.save), 'save_sha1': sha1(a.save),
            'bottom': bottom, 'top': top, 'names': [a.bottom, a.top], 'list_index': index, 'list_count': n,
            'tap': [ROW_TAP[0], ROW_TAP[1] + ROW_STEP * row], 'state_frame': frame,
            'unlocked_list_bits': [UNLOCK_FIRST, UNLOCK_FIRST + UNLOCK_N - 1], 'view_symbols': syms,
            'engines': [a.bottom_engine, a.top_engine]}
    with open(os.path.join(work, 'start.json'), 'w') as f:
        json.dump(meta, f, indent=2)
    shutil.rmtree(inst)
    print(f'{work}/pre.ml1: View Mode, bottom char {bottom} picked, top char {top} under the cursor '
          f'(list entry {index}, page {index // 5 + 1} row {index % 5 + 1})')


def load_meta(work):
    meta = json.load(open(os.path.join(work, 'start.json')))
    if sha1(meta['rom']) != meta['rom_sha1']:
        raise SystemExit(f'{meta["rom"]} changed since {work}/pre.ml1 was made: run start again')
    return meta


def sample(g, regs):
    st = struct.unpack('<9I', g.read(DUEL, 0x24))
    ev = {'f': g.u32(FRAME), 'op': regs[0] & 0xffff, 'a': regs[1] & 0xffff, 'b': regs[2] & 0xffff, 'c': regs[3] & 0xffff,
          'tp': st[1], 'tc': st[4], 'ph': st[6], 'win': st[8], 'lp': [], 'n': [], 'z': []}
    for p in (0, 1):
        blk = g.read_big(PLAYERS + p * PSIZE, PBLOCK)
        ev['lp'].append(struct.unpack_from('<i', blk, 0)[0])
        ev['n'].append([struct.unpack_from('<I', blk, PILE_OFF[k])[0] for k in PILES])
        ev['z'].append([struct.unpack_from('<I', blk, 0x34 + 20 * z)[0] & 0x3fff for z in range(ZONES)])
        hand = min(ev['n'][p][0], 20)
        raw = g.read(PLAYERS + p * PSIZE + PBLOCK, 4 * hand) if hand else b''
        ev['h'] = ev.get('h', []) + [[w & 0x3fff for w in struct.unpack(f'<{hand}I', raw)]]
    return ev


def play(g, emu, meta, seed, syms, wall_limit, log, recorder=None, on_duel=None, music=None):
    if music is not None:
        g.write(MUSIC_MASK, struct.pack('<H', g.u16(MUSIC_MASK) | 1 << music))
        g.write(MUSIC_LAST, struct.pack('<H', 1 << music))
    g.bp(LAUNCH)
    g.go()
    if recorder:
        recorder.start_capture()
        time.sleep(1.0)
    emu.tap(*meta['tap'])
    if not g.wait(20):
        raise SystemExit('the tap did not start the launcher')
    while g.u32(LAUNCH_STEP) != 0:
        g.go()
        g.reply()
    g.unbp(LAUNCH)
    if g.u32(syms['vm_state']) != 3:
        raise SystemExit(f'View Mode state {g.u32(syms["vm_state"])} at the launch, not 3')
    tap_frame = g.u32(FRAME)
    g.w32(FRAME, FRAME_BASE | seed)
    g.bp(syms['vm_janken_pick'])
    for _ in range(JANKEN_FRAMES):
        g.go()
        if not g.wait(30):
            raise SystemExit('the janken never came up')
    janken_frame = g.u32(FRAME)
    if g.u32(SEED) != seed:
        raise SystemExit(f'duel seed {g.u32(SEED):#x} after the launch, not {seed:#x}')
    g.write(PAD_NEW, struct.pack('<H', g.u16(PAD_NEW) | KEY_A))
    g.unbp(syms['vm_janken_pick'])
    g.bp(PUSH)
    g.go()
    t0 = time.time()
    res = {'seed': seed, 'tap_frame': tap_frame, 'janken_frame': janken_frame}
    last_frame, last_push, n = None, None, 0
    moved = time.time()
    while time.time() - t0 < wall_limit:
        if g.wait(GDB_WAIT):
            if g.reg(15) != PUSH:
                g.go()
                continue
            regs = [g.reg(i) for i in range(4)]
            ev = sample(g, regs)
            g.go()
            n += 1
            log.write(json.dumps(ev, separators=(',', ':')) + '\n')
            if n == 1 and on_duel:
                on_duel()
            last_push = ev['f']
            if ev['op'] & 0x7fff == 5:
                res['end_frame'] = ev['f']
            continue
        g.halt()
        if g.reg(15) == PUSH:
            regs = [g.reg(i) for i in range(4)]
            ev = sample(g, regs)
            g.go()
            n += 1
            log.write(json.dumps(ev, separators=(',', ':')) + '\n')
            last_push = ev['f']
            if ev['op'] & 0x7fff == 5:
                res['end_frame'] = ev['f']
            continue
        frame, vm = g.u32(FRAME), g.u32(syms['vm_state'])
        if n and vm == 0:
            res['menu_frame'] = frame
            break
        if frame != last_frame:
            moved = time.time()
        elif time.time() - moved > STUCK_WALL:
            res['end'] = 'stuck'
            break
        if last_push is not None and frame - last_push > HANG_FRAMES:
            res['end'] = 'hang'
            break
        last_frame = frame
        g.go()
    else:
        res['end'] = 'timeout'
    res['pushes'] = n
    return res


def duel_summary(events):
    if not events:
        return {}
    last = events[-1]
    end = next((e for e in events if e['op'] & 0x7fff == 5), None)
    win = (end or last)['win']
    first = next((e['tp'] for e in events if e['op'] & 0x7fff in (0x2, 0xa, 0xb, 0xc) or e['tc'] == 0), None)
    return {'winner': {1: 0, 2: 1, 3: 'draw'}.get(win), 'lp': last['lp'], 'turns': last['tc'] + 1,
            'first': first, 'frames': last['f'] - events[0]['f'], 'ended': end is not None}


def run_one(work, meta, seed, timeout, keep=False):
    syms = meta['view_symbols']
    name = f's{seed}'
    inst = instance(work, name + f'_{os.getpid()}_{random.randrange(1 << 30)}', meta['rom'],
                    os.path.join(work, 'start.sav'))
    shutil.copy(os.path.join(work, 'pre.ml1'), os.path.join(inst, 'v.ml1'))
    port = gdb_cfg(gym.melon_config(inst, True), os.path.join(inst, 'cfg'))
    runs = os.path.join(work, 'runs')
    os.makedirs(runs, exist_ok=True)
    log_path = os.path.join(runs, name + '.jsonl')
    t0 = time.time()
    emu = Headless(os.path.join(inst, 'v.nds'), os.path.join(inst, 'cfg'))
    duel_state = os.path.join(inst, 'v.ml5')
    try:
        g = Gdb(port)
        g.go()
        time.sleep(0.5)
        emu.key('F1')
        time.sleep(1)
        g.halt()
        if not 0 <= g.u32(FRAME) - meta['state_frame'] < 5000:
            raise SystemExit(f'seed {seed}: pre.ml1 did not load (frame {g.u32(FRAME)})')
        snap = threading.Thread(target=lambda: emu.m.snapshot(duel_state, 5))
        with open(log_path, 'w') as log:
            res = play(g, emu, meta, seed, syms, timeout, log, on_duel=snap.start)
        if snap.is_alive():
            snap.join(10)
        g.detach()
    except SystemExit as e:
        res = {'seed': seed, 'end': f'error: {e}'}
    finally:
        emu.stop()
    events = [json.loads(line) for line in open(log_path)] if os.path.exists(log_path) else []
    res.update(duel_summary(events))
    res.setdefault('end', 'duel over' if res.get('ended') else 'no result')
    res['wall'] = round(time.time() - t0, 1)
    if os.path.exists(duel_state) and os.path.getsize(duel_state) >= gym.MIN_STATE:
        shutil.copy(duel_state, os.path.join(runs, name + '.duel.ml1'))
    with open(os.path.join(runs, name + '.json'), 'w') as f:
        json.dump(res, f, indent=2)
    if not keep:
        shutil.rmtree(inst, ignore_errors=True)
    return res


def seed_list(text):
    out = []
    for part in text.split(','):
        lo, _, hi = part.partition('-')
        out += range(int(lo, 0), int(hi or lo, 0) + 1)
    return out


def cmd_run(a):
    meta = load_meta(a.work)
    seeds = seed_list(a.seeds)
    print(f'{len(seeds)} duels, {a.jobs} at once: {meta["names"][0]} (bottom) vs {meta["names"][1]} (top)', flush=True)
    t0 = time.time()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        futs = {}
        for s in seeds:
            futs[ex.submit(run_one, a.work, meta, s, a.timeout)] = s
            time.sleep(1)
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            done += 1
            el = time.time() - t0
            print(f'[{done}/{len(seeds)}] seed {r["seed"]}: {r["end"]}, winner {r.get("winner")}, turns {r.get("turns")}, '
                  f'LP {r.get("lp")}, wall {r["wall"]} s; elapsed {el:.0f} s, ETA {el / done * (len(seeds) - done):.0f} s',
                  flush=True)


class Names:
    def __init__(self, rom):
        import w11gym
        cache = os.path.join(WORK, 'names_' + sha1(rom)[:12] + '.json')
        if os.path.exists(cache):
            self.names = {int(k): v for k, v in json.load(open(cache)).items()}
        else:
            self.names = w11gym.Cards(rom).names
            os.makedirs(WORK, exist_ok=True)
            with open(cache, 'w') as f:
                json.dump(self.names, f)

    def __call__(self, cid):
        return self.names.get(cid & 0x3fff, f'id:{cid & 0x3fff}') if cid & 0x3fff else '-'


def zone_name(z):
    return f'M{z + 1}' if z < 5 else f'S{z - 4}' if z < 10 else 'Field' if z == 10 else \
        {11: 'hand', 12: 'Extra Deck', 13: 'Deck', 14: 'GY', 15: 'banished'}.get(z, f'zone {z}')


def moves(prev, ev):
    out = []
    for p in (0, 1):
        dn = {k: ev['n'][p][i] - prev['n'][p][i] for i, k in enumerate(PILES)}
        for z in range(11):
            was, now = prev['z'][p][z], ev['z'][p][z]
            if was == now:
                continue
            if was:
                to = next((k for k in ('gy', 'banished', 'hand', 'deck', 'extra') if dn[k] > 0), None)
                if to:
                    dn[to] -= 1
                out.append((p, 'leave', was, z, to))
            if now:
                src = next((k for k in ('hand', 'deck', 'extra', 'gy', 'banished') if dn[k] < 0), None)
                if src:
                    dn[src] += 1
                out.append((p, 'arrive', now, z, src))
    return out


def replay(events, names, meta):
    who = [f'{SIDE_NAMES[p]} ({meta["names"][p]})' for p in (0, 1)]
    lines, facts = [], []
    prev = None
    depth = 0
    turn = None
    for ev in events:
        p = ev['op'] >> 15
        op = ev['op'] & 0x7fff
        t = f't{ev["tc"] + 1:<2} {SIDE_NAMES[ev["tp"]]:<6} {PHASES.get(ev["ph"], ev["ph"]):<5}'
        if ev['tc'] != turn and ev['ph'] in (0, 7):
            turn = ev['tc']
            lines.append(f'== turn {turn + 1}: {who[ev["tp"]]}, LP bottom {ev["lp"][0]} / top {ev["lp"][1]}, '
                         f'hands {ev["n"][0][0]}/{ev["n"][1][0]}, decks {ev["n"][0][1]}/{ev["n"][1][1]}')
            if 'h' in ev:
                lines.append('   hands: ' + '; '.join(f'{SIDE_NAMES[q]} ' + (', '.join(names(c) for c in ev['h'][q]) or '-')
                                                     for q in (0, 1)))
        text = None
        if op == 0x2d:
            text = f'{SIDE_NAMES[p]} activates {names(ev["b"])}'
            facts.append({'t': ev['tc'], 'side': p, 'kind': 'activate', 'card': names(ev['b'])})
        elif op == 0x10:
            depth += 1
            text = f'  chain link {depth}'
        elif op == 0x11:
            text = f'  resolves {names(ev["b"])}'
        elif op == 0x12:
            depth = 0
        elif op == 0x50:
            text = f'{SIDE_NAMES[p]} {"sets" if ev["b"] & 0x8000 else "summons"} {names(ev["a"])}'
        elif op == 0x4e:
            text = f'{SIDE_NAMES[p]} summons {names(ev["a"])} from the Extra Deck'
        elif op == 0x51:
            text = f'{SIDE_NAMES[p]} {"plays" if ev["b"] & 0x4000 else "sets"} {names(ev["a"])}'
        elif op == 0x15:
            mine, theirs = (ev['a'], ev['b']) if p == 0 else (ev['b'], ev['a'])
            text = f'{SIDE_NAMES[p]} attacks with {names(mine)} -> {names(theirs) if theirs else "direct"}'
        elif op in (0x28, 0x30):
            zp = ev['z'][p][ev['a']] if ev['a'] < ZONES else 0
            what = f'{SIDE_NAMES[p]} {zone_name(ev["a"])} {names(zp)}' if zp else f'{SIDE_NAMES[p]} {zone_name(ev["a"])}'
            text = f'  {"targets" if op == 0x28 else "destroys"} {what}'
        elif op == 0x5:
            text = f'duel over: {"draw" if ev["win"] == 3 else "winner " + who[{1: 0, 2: 1}.get(ev["win"], 0)]}'
        if prev:
            for side, kind, card, z, pile in moves(prev, ev):
                facts.append({'t': ev['tc'], 'side': side, 'kind': kind, 'card': names(card), 'zone': z, 'pile': pile})
                if kind == 'arrive':
                    lines.append(f'{t} {SIDE_NAMES[side]} {zone_name(z)} + {names(card)}' + (f' (from {pile})' if pile else ''))
                else:
                    lines.append(f'{t} {SIDE_NAMES[side]} {zone_name(z)} - {names(card)}' + (f' (to {pile})' if pile else ''))
            if ev['lp'] != prev['lp']:
                lines.append(f'{t} LP bottom {ev["lp"][0]} / top {ev["lp"][1]}')
        if text:
            lines.append(f'{t} {text}')
        prev = ev
    return lines, facts


def engine_score(facts, side, key, names_all):
    eng = ENGINES[key]
    cards = set(eng['cards']) | set(eng['signature'])
    is_engine = lambda n: n in cards or ('prefix' in eng and n.startswith(eng['prefix'])) or \
        ('suffix' in eng and n.endswith(eng['suffix']))
    plays, sig, specials = 0, set(), {}
    for f in facts:
        if f['side'] != side:
            continue
        if f['kind'] == 'activate' and is_engine(f['card']):
            plays += 1
        if f['kind'] == 'arrive' and f['zone'] < 5 and is_engine(f['card']):
            plays += 1
        if f['kind'] in ('activate', 'arrive') and f['card'] in eng['signature']:
            sig.add(f['card'])
        if f['kind'] == 'arrive' and f['zone'] < 5:
            if eng.get('tag_out') and f['pile'] == 'deck' and f['card'].startswith('Gladiator Beast'):
                specials['tag-outs'] = specials.get('tag-outs', 0) + 1
            if f['pile'] == 'extra':
                specials['extra'] = specials.get('extra', 0) + 1
        if eng.get('mills') and f['kind'] == 'activate' and f['card'].endswith('Lightsworn') is False and \
                ', Lightsworn' in f['card']:
            specials['lightsworn effects'] = specials.get('lightsworn effects', 0) + 1
    shown = bool(sig) or specials.get('tag-outs', 0) > 0
    return {'plays': plays, 'signature': sorted(sig), **specials, 'main_line': shown and plays >= 3}


def lp_story(events):
    lead, changes, last = None, 0, None
    dealt = [0, 0]
    for ev in events:
        if last:
            for p in (0, 1):
                d = last['lp'][p] - ev['lp'][p]
                if d > 0:
                    dealt[1 - p] += d
        diff = ev['lp'][0] - ev['lp'][1]
        now = (diff > 0) - (diff < 0)
        if now and lead is not None and now != lead:
            changes += 1
        if now:
            lead = now
        last = ev
    return changes, dealt


def card_story(events):
    last = {}
    for ev in events:
        last[ev['tc']] = ev
    diffs = [sum(1 for c in last[t]['z'][0] if c) + last[t]['n'][0][0] - sum(1 for c in last[t]['z'][1] if c) - last[t]['n'][1][0]
             for t in sorted(last)]
    signs = [d > 0 for d in diffs if d]
    return sum(a != b for a, b in zip(signs, signs[1:])), sum(map(abs, diffs)) / max(len(diffs), 1)


def score_duel(events, facts, meta):
    s = duel_summary(events)
    changes, dealt = lp_story(events)
    card_changes, card_gap = card_story(events)
    turns = s.get('turns') or 0
    win = s.get('winner')
    win_lp = s['lp'][win] if isinstance(win, int) else 0
    eng = [engine_score(facts, p, meta['engines'][p], None) for p in (0, 1)] if all(meta.get('engines', [])) else [{}, {}]
    bf = card_changes * 3.0 + max(0.0, 3 - card_gap) * 2 + changes + min(dealt) / 4000 + 1 - min(win_lp, 8000) / 8000 \
        + min(turns, 16) / 4
    if turns < 5:
        bf -= 5
    if not s.get('ended'):
        bf -= 10
    return {'turns': turns, 'winner': win, 'lp': s.get('lp'), 'lead_changes': changes, 'dealt': dealt,
            'card_lead_changes': card_changes, 'card_gap': round(card_gap, 1), 'back_and_forth': round(bf, 2), 'engines': eng,
            'main_line': all(e.get('main_line') for e in eng), 'ended': s.get('ended')}


def cmd_score(a):
    meta = load_meta(a.work) if not a.any_rom else json.load(open(os.path.join(a.work, 'start.json')))
    if a.engines:
        meta['engines'] = a.engines.split(',')
    names = Names(meta['rom'])
    runs = os.path.join(a.work, 'runs')
    rows = []
    for fn in sorted(os.listdir(runs)):
        if not fn.endswith('.jsonl'):
            continue
        seed = int(fn[1:-6])
        events = [json.loads(line) for line in open(os.path.join(runs, fn))]
        lines, facts = replay(events, names, meta)
        with open(os.path.join(runs, f's{seed}.log.txt'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
        sc = score_duel(events, facts, meta)
        sc['seed'] = seed
        rows.append(sc)
    rows.sort(key=lambda r: (r['main_line'], r['back_and_forth']), reverse=True)
    out = [f'{meta["names"][0]} (bottom, {meta["engines"][0]}) vs {meta["names"][1]} (top, {meta["engines"][1]})', '',
           '| seed | winner | turns | card lead changes | mean card gap | final LP b/t | LP lead changes | damage dealt b/t | back-and-forth | main line | bottom engine | top engine |',
           '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        def eng(e):
            extra = ', '.join(f'{k} {v}' for k, v in e.items() if k not in ('plays', 'signature', 'main_line'))
            return f'{e.get("plays", 0)} plays; {", ".join(e.get("signature", [])) or "no signature"}' + (f'; {extra}' if extra else '')
        w = r['winner']
        out.append(f'| {r["seed"]} | {SIDE_NAMES[w] if isinstance(w, int) else w} | {r["turns"]} | {r["card_lead_changes"]} | {r["card_gap"]} | '
                   f'{"/".join(map(str, r["lp"] or []))} | {r["lead_changes"]} | {r["dealt"][0]}/{r["dealt"][1]} | '
                   f'{r["back_and_forth"]} | {"yes" if r["main_line"] else "no"} | {eng(r["engines"][0])} | {eng(r["engines"][1])} |')
    text = '\n'.join(out) + '\n'
    with open(os.path.join(a.work, 'scores.md'), 'w') as f:
        f.write(text)
    print(text)


def sounding_melons():
    out = []
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            name = open(f'/proc/{pid}/comm').read().strip()
            if name not in ('AppRun', 'melonDS'):
                continue
            env = open(f'/proc/{pid}/environ', 'rb').read().split(b'\0')
        except OSError:
            continue
        if b'SDL_AUDIODRIVER=dummy' not in env:
            out.append(int(pid))
    return out


def cmd_record(a):
    meta = load_meta(a.work)
    loud = sounding_melons()
    if loud:
        raise SystemExit(f'melonDS with sound is running (pids {loud}): Mat\'s or another recording; record after it closes')
    seed = a.seed
    syms = meta['view_symbols']
    out_dir = a.out_dir or os.path.join(ROOT, 'youtube', 'takes', a.name)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, a.name)
    ref = os.path.join(a.work, 'runs', f's{seed}.jsonl')
    inst = instance(a.work, f'rec{seed}', meta['rom'], os.path.join(a.work, 'start.sav'))
    shutil.copy(os.path.join(a.work, 'pre.ml1'), os.path.join(inst, 'v.ml1'))
    cap.make_config()
    port = gdb_cfg(cap.CFG, os.path.join(inst, 'cfg'))
    raw = stem + '.raw.mkv'
    rec = Recorder(os.path.join(inst, 'v.nds'), os.path.join(inst, 'cfg'), raw)
    log_path = stem + '.rec.jsonl'
    try:
        g = Gdb(port)
        g.go()
        time.sleep(0.5)
        rec.key('F1')
        time.sleep(1)
        g.halt()
        if not 0 <= g.u32(FRAME) - meta['state_frame'] < 5000:
            raise SystemExit(f'pre.ml1 did not load (frame {g.u32(FRAME)})')
        with open(log_path, 'w') as log:
            res = play(g, rec, meta, seed, syms, a.timeout, log, recorder=rec, music=a.music)
            res['music'] = a.music
            res['duel_bgm'] = g.u16(DUEL_BGM)
        t_menu = time.time()
        g.go()
        while time.time() - t_menu < 30:
            time.sleep(0.5)
            g.halt()
            bright = g.u16(SOFT_BRIGHT)
            g.go()
            if bright == 0:
                break
        time.sleep(a.tail)
        g.detach()
    finally:
        rec.stop()
    cap.finish(raw, stem + '.mp4', 4, a.crf)
    os.remove(raw)
    got = [json.loads(line) for line in open(log_path)]
    want = [json.loads(line) for line in open(ref)] if os.path.exists(ref) else None
    key = lambda e: {k: v for k, v in e.items() if k not in ('f', 'h')}
    same = want is not None and len(got) == len(want) and all(key(x) == key(y) for x, y in zip(got, want))
    res.update(duel_summary(got))
    res['matches_series_run'] = same
    print(f'seed {seed}: recorded {stem}.mp4; {len(got)} duel commands, '
          f'{"identical to" if same else "DIFFERENT from"} the series run ({ref})', flush=True)
    names = Names(meta['rom'])
    lines, facts = replay(got, names, meta)
    with open(stem + '.log.txt', 'w') as f:
        f.write(f'{meta["names"][0]} (bottom) vs {meta["names"][1]} (top), seed {seed}\n')
        f.write('\n'.join(lines) + '\n')
    shutil.copy(os.path.join(a.work, 'pre.ml1'), stem + '.pre.ml1')
    duel_state = os.path.join(a.work, 'runs', f's{seed}.duel.ml1')
    if os.path.exists(duel_state):
        shutil.copy(duel_state, stem + '.ml1')
    with open(stem + '.seed.json', 'w') as f:
        json.dump({'seed': seed, 'seed_address': f'{SEED:#010x}', 'frame_counter': f'{FRAME:#010x} = {FRAME_BASE | seed:#x}', 'how': 'pre.ml1 loaded with the melonDS GDB stub; the '
                   'opponent row tapped once; at the launcher\'s first step the frame counter is set to 0x10000 + seed, so '
                   'the game itself takes the seed as its duel seed (frame & 0xffff) and seeds the system random word from '
                   'it at the janken and duel scene starts; A is set in the pad word on '
                   f'the {JANKEN_FRAMES}th frame of the janken music select. The .ml1 is a savestate of the same duel '
                   'after its setup and plays it with no input.', **{k: meta[k] for k in (
                       'rom', 'rom_sha1', 'save', 'save_sha1', 'bottom', 'top', 'names', 'engines', 'tap',
                       'unlocked_list_bits')}, 'record': res}, f, indent=2)
    shutil.rmtree(inst, ignore_errors=True)


def brightness(video, fps=CUT_FPS):
    w, h = 32, 48
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', video, '-vf', f'fps={fps},scale={w}:{h}', '-f', 'rawvideo',
                          '-pix_fmt', 'gray', '-'], stdout=subprocess.PIPE)
    raw = p.stdout.read()
    if p.wait():
        raise SystemExit(f'{video}: ffmpeg could not read it')
    return [sum(raw[i:i + w * h]) / (w * h) for i in range(0, len(raw) - w * h + 1, w * h)]


def dark_runs(levels):
    runs, start = [], None
    for i, v in enumerate(levels + [CUT_DARK]):
        if v < CUT_DARK and start is None:
            start = i
        elif v >= CUT_DARK and start is not None:
            if i - start >= CUT_RUN:
                runs.append((start, i))
            start = None
    return runs


def cmd_cut(a):
    levels = brightness(a.video)
    runs = dark_runs(levels)
    if len(runs) < 2:
        raise SystemExit(f'{a.video}: {len(runs)} black screens found; need the one before the janken and the one after the duel')
    first, last = runs[0][1], runs[-1][0]
    flat = sorted(levels[runs[0][0]:runs[0][1]])[(runs[0][1] - runs[0][0]) // 2]
    while first > runs[0][0] and abs(levels[first - 1] - flat) > 0.5:
        first -= 1
    flat = sorted(levels[runs[-1][0]:runs[-1][1]])[(runs[-1][1] - runs[-1][0]) // 2]
    while last < runs[-1][1] and abs(levels[last] - flat) > 0.5:
        last += 1
    last += 1
    t0, t1 = first / CUT_FPS, last / CUT_FPS
    print(f'{a.video}: janken fade-in at {t0:.3f} s, fade to black done at {t1:.3f} s, {t1 - t0:.3f} s', flush=True)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-stats', '-y', '-ss', f'{t0:.3f}', '-i', a.video, '-t', f'{t1 - t0:.3f}',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', str(a.crf), '-pix_fmt', 'yuv420p', '-r', str(CUT_FPS),
                    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', a.out], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', default=WORK, help='folder for pre.ml1, start.sav, start.json and runs/ (default build/w11showcase)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('start', help='boot the ROM under the GDB stub to the title, pick the bottom opponent by calling '
                       'the game\'s own side loader and View Mode\'s list exit, open the second pick with the cursor on '
                       'the top opponent, save <work>/pre.ml1 (no menu input)')
    s.add_argument('--rom', default=os.path.join(ROOT, 'build', 'dimension-break.nds'))
    s.add_argument('--save', default=os.path.join(ROOT, 'build', 'dimension-break.sav'))
    s.add_argument('--bottom', required=True, help='char id, roster.tsv opponent/name or opponent spec name')
    s.add_argument('--top', required=True)
    s.add_argument('--bottom-engine', choices=sorted(ENGINES), help='deck engine scored for the bottom side')
    s.add_argument('--top-engine', choices=sorted(ENGINES))
    r = sub.add_parser('run', help='play duels headless from pre.ml1, one per seed, and log every duel command')
    r.add_argument('seeds', help='e.g. 1-20 or 3,7,11: 1 to 0xffff, the low 16 bits of the frame counter at the tap')
    r.add_argument('-j', '--jobs', type=int, default=4)
    r.add_argument('--timeout', type=float, default=1800, help='wall seconds per duel')
    c = sub.add_parser('score', help='text replays (runs/s<seed>.log.txt) and the score table (scores.md)')
    c.add_argument('--engines', help='bottom,top engine keys, overriding start.json')
    c.add_argument('--any-rom', action='store_true', help='score even if the ROM changed since start')
    d = sub.add_parser('record', help='replay one seed in real time from pre.ml1 with sound and record it')
    d.add_argument('seed', type=int)
    d.add_argument('--name', required=True, help='file stem in the output folder')
    d.add_argument('-o', '--out-dir', help='default youtube/takes/<name>')
    d.add_argument('--crf', type=int, default=16)
    d.add_argument('--tail', type=float, default=RECORD_TAIL, help='seconds recorded once the Free Duel menu is lit')
    d.add_argument('--timeout', type=float, default=3600)
    d.add_argument('--music', type=int, choices=range(16), help='duel theme preselected in Music Select: 0-11 DU_R_01..12, '
                   '13-15 the added themes (docs/modding/music-select.md); default the save\'s last pick')
    u = sub.add_parser('cut', help='the upload cut of a recording: from the first frame of the janken fade-in to the end '
                       'of the fade to black after the duel, before the menu comes back')
    u.add_argument('video')
    u.add_argument('out')
    u.add_argument('--crf', type=int, default=16)
    a = ap.parse_args()
    {'start': cmd_start, 'run': cmd_run, 'score': cmd_score, 'record': cmd_record, 'cut': cmd_cut}[a.cmd](a)


if __name__ == '__main__':
    main()
