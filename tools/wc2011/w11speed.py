"""WC2011 CPU speed: test rig ROM (CPU-vs-CPU duels with a trace), runs in melonDS, decision-identity diff."""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

import ndspy.code
import ndspy.rom

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import game
import inject
import mlstate
import ydc

ROM11_NAME = "Yu-Gi-Oh! 5D's - World Championship 2011 - Over the Nexus (Europe) (En,Ja,Fr,De,Es,It).nds"


def find_rom11():
    if os.environ.get('ROM11'):
        return os.environ['ROM11']
    d = ROOT
    while True:
        p = os.path.join(d, 'rom', ROM11_NAME)
        if os.path.exists(p) or os.path.dirname(d) == d:
            return p
        d = os.path.dirname(d)


ROM11 = find_rom11()


def find_up(rel):
    d = ROOT
    while True:
        p = os.path.join(d, rel)
        if os.path.exists(p) or os.path.dirname(d) == d:
            return p
        d = os.path.dirname(d)
RIG_SRC = os.path.join(ROOT, 'mod', 'test', 'w11speed')
DUELS = os.path.join(RIG_SRC, 'duels.json')
WORK = os.path.join(ROOT, 'build', 'w11speed')
TOOLCHAIN = os.path.expanduser(os.environ.get('ARM_TOOLCHAIN', '~/tools/arm-gnu-toolchain/bin'))
CFLAGS = ['-mcpu=arm946e-s', '-mthumb', '-mthumb-interwork', '-O2', '-ffreestanding', '-nostdlib', '-fno-builtin',
          '-Wall', '-Werror']

ARENA_HI_LIT, ARENA_HI = inject.arena_hi('BYYP')
RIG_END = ARENA_HI - 0x2000
RIG_BASE = RIG_END - 0xe000
BOOT_CB_LIT, BOOT_CB = 0x02015fc8, 0x021522f4
SAVE_ID_BL, SAVE_ID = 0x02015f0e, 0x0202d3e0
SAVE_CHECK = 0x02015f50
EXIT_CB_LIT, EXIT_CB = 0x02146518, 0x02019359
RESULT_STEP_LIT, RESULT_STEP = 0x0226d2b4, 0x0219d231
LOOP_MODE_BNE, LOOP_ITER_MOV = 0x02145fe8, 0x02146000
CMD_PUSH = 0x021c3bc8
CMD_PUSH_HEAD = bytes.fromhex('70b50e4ca468032c17d00d4d')
SE_GIVE_UP, SE_GIVE_UP_HEAD = 0x020349a0, bytes.fromhex('0000a0e3')
HOOKS = [
    ('h_main', 1, 0x02256a6a, 0x0226a444),
    ('h_main_b', 2, 0x0226b634, 0x0226a444),
    ('h_chain', 3, 0x0224e3e4, 0x0226a8c8),
    ('h_chain_b', 4, 0x0226b662, 0x0226a8c8),
    ('h_trig', 5, 0x0223a028, 0x0226a75c),
    ('h_prompt', 6, 0x0219af10, 0x0226ad8c),
    ('h_zone', 7, 0x0219daca, 0x0226aa04),
    ('h_step', 8, 0x021460cc, 0x0219d470),
    ('h_pad', 9, 0x020162e6, 0x02014efc),
    ('h_pad', 9, 0x0201634c, 0x02014efc),
]
KINDS = {1: 'main', 2: 'main_b', 3: 'chain', 4: 'chain_b', 5: 'trigger', 6: 'prompt', 7: 'zone'}
EV_CMD, EV_START, EV_END, EV_OK, EV_EPISODE = 0x100, 0x200, 0x201, 0x202, 0x300
EV_N, SEQ_N, SEQ_EVERY, HIST = 2200, 512, 32, 64
BUS_HZ = 33513982
TICK_HZ = BUS_HZ / 64
FRAME_HZ = 59.8261
RIG_MAGIC = 0x32314752


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def put32(b, o, v):
    struct.pack_into('<I', b, o, v)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f'{" ".join(cmd)}\n{r.stdout}{r.stderr}')
    return r.stdout


def thumb_bl(at, target):
    off = target - (at + 4)
    if not -0x400000 <= off < 0x400000:
        raise SystemExit(f'BL {at:#x} -> {target:#x}: out of range')
    off &= 0x7fffff
    return struct.pack('<HH', 0xf000 | (off >> 12) & 0x7ff, 0xf800 | (off >> 1) & 0x7ff)


def arm_blx(at, thumb_target):
    off = thumb_target - (at + 8)
    if not -0x2000000 <= off < 0x2000000 or off & 1:
        raise SystemExit(f'BLX {at:#x} -> {thumb_target:#x}: out of range')
    return struct.pack('<I', 0xfa000000 | (off & 2) << 23 | (off >> 2) & 0xffffff)


def is_arm_call(w):
    return (w >> 25) == 0x7d or ((w & 0x0f000000) == 0x0b000000 and w >> 28 == 0xe)


def call_target(b, o, at, arm=False):
    """Target of a Thumb BL/BLX (or ARM BL/BLX when arm) at `at`, with bit 0 set for a Thumb target."""
    if arm:
        w = u32(b, o)
        if not is_arm_call(w):
            return None
        off = (w & 0xffffff) << 2
        if off & 0x2000000:
            off -= 0x4000000
        if w >> 28 == 0xf:
            return (at + 8 + off + ((w >> 23) & 2)) | 1
        return at + 8 + off
    t = bl_target(b, o, at)
    if t is None:
        return None
    h2 = struct.unpack_from('<H', b, o + 2)[0]
    return t if (h2 & 0xf800) == 0xe800 else t | 1


def bl_target(b, o, at):
    h1, h2 = struct.unpack_from('<HH', b, o)
    if (h1 & 0xf800) != 0xf000 or (h2 & 0xf800) not in (0xf800, 0xe800):
        return None
    off = ((h1 & 0x7ff) << 12) | ((h2 & 0x7ff) << 1)
    if off & 0x400000:
        off -= 0x800000
    t = at + 4 + off
    return t & ~3 if (h2 & 0xf800) == 0xe800 else t


class Image:
    def __init__(self, data, base, name):
        self.d, self.base, self.name = bytearray(data), base, name

    def has(self, a):
        return self.base <= a < self.base + len(self.d)

    def o(self, a):
        if not self.has(a):
            raise SystemExit(f'{self.name}: {a:#x} outside')
        return a - self.base

    def word(self, a):
        return u32(self.d, self.o(a))

    def set_word(self, a, v, old=None):
        if old is not None and self.word(a) != old:
            raise SystemExit(f'{self.name} {a:#x}: {self.word(a):#x}, expected {old:#x}')
        put32(self.d, self.o(a), v)

    def bl(self, at, target, old=None):
        if old is not None and bl_target(self.d, self.o(at), at) != old:
            raise SystemExit(f'{self.name} {at:#x}: not a BL to {old:#x}')
        self.d[self.o(at):self.o(at) + 4] = thumb_bl(at, target)

    def target(self, at, arm=False):
        return call_target(self.d, self.o(at), at, arm)

    def hook(self, at, thumb_fn, old, arm_site=False):
        """Point the call at `at` (Thumb BL, or ARM BLX when arm_site) to Thumb function `thumb_fn`.
        Returns the target it had (bit 0 set for Thumb)."""
        cur = self.target(at, arm_site)
        if cur is None:
            raise SystemExit(f'{self.name} {at:#x}: not a call')
        if old is not None and cur & ~1 != old:
            print(f'{self.name} {at:#x}: call goes to {cur:#x} (another patch), wrapping it')
        code = arm_blx(at, thumb_fn & ~1) if arm_site else thumb_bl(at, thumb_fn & ~1)
        self.d[self.o(at):self.o(at) + 4] = code
        return cur

    def write(self, a, data, old=None):
        o = self.o(a)
        if old is not None and bytes(self.d[o:o + len(old)]) != old:
            raise SystemExit(f'{self.name} {a:#x}: bytes {self.d[o:o + len(old)].hex()}, expected {old.hex()}')
        self.d[o:o + len(data)] = data


class Rom11:
    def __init__(self, path):
        self.rom = ndspy.rom.NintendoDSRom.fromFile(path)
        with open(path, 'rb') as f:
            self.header = f.read(0x200)
        if bytes(self.rom.idCode) not in (b'BYYP', b'YG8P'):
            raise SystemExit(f'{path}: game code {bytes(self.rom.idCode)!r}, expected BYYP/YG8P (WC2011 EU/Dimension Break)')
        self.code = ndspy.code.MainCodeFile(self.rom.arm9, self.rom.arm9RamAddress, self.rom.arm9PostData)
        self.arm9 = Image(self.code.sections[0].data, self.code.sections[0].ramAddress, 'arm9')
        self.ovs = self.rom.loadArm9Overlays()
        self.ov = {i: Image(o.data, o.ramAddress, f'ov{i:02d}') for i, o in self.ovs.items() if i in (3, 5, 7, 13, 18, 23, 31)}
        self.extra = []

    def image(self, a):
        for img in (self.arm9, *self.ov.values()):
            if img.has(a):
                return img
        raise SystemExit(f'{a:#x}: in no patched module')

    def save(self, path, compress=False):
        self.code.sections[0].data = bytes(self.arm9.d)
        for data, ram in self.extra:
            if len(data) % 4:
                raise SystemExit(f'arm9 section at {ram:#x}: {len(data)} B, not a multiple of 4 (the next autoload section would be misaligned)')
            self.code.sections.append(ndspy.code.MainCodeFile.Section(data, ram, 0, implicit=False))
        self.rom.arm9 = self.code.save(compress=compress)
        for i, img in self.ov.items():
            o = self.ovs[i]
            if bytes(img.d) == bytes(o.data):
                continue
            o.data = bytes(img.d)
            o.compressed = compress
            self.rom.files[o.fileID] = o.save(compress=compress)
        self.rom.arm9OverlayTable = ndspy.code.saveOverlayTable(self.ovs)
        out = bytearray(self.rom.save())
        out[0x1000:0x1004] = bytes(4)
        game.keep_header_crc32(out, self.header)
        with open(path, 'wb') as f:
            f.write(out)


def compile_rig(work, base=RIG_BASE, defs=()):
    os.makedirs(work, exist_ok=True)
    elf = os.path.join(work, 'rig.elf')
    srcs = [os.path.join(RIG_SRC, f) for f in ('rig.c', 'rig_stubs.S')]
    run([os.path.join(TOOLCHAIN, 'arm-none-eabi-gcc'), *CFLAGS, *defs, f'-Wl,--defsym=RIG_BASE={base:#x}',
         '-Wl,-T', os.path.join(RIG_SRC, 'rig.ld'), '-Wl,-Map=' + os.path.join(work, 'rig.map'), '-o', elf, *srcs,
         '-lgcc'])
    binf = os.path.join(work, 'rig.bin')
    run([os.path.join(TOOLCHAIN, 'arm-none-eabi-objcopy'), '-O', 'binary', '-R', '.rigbss', elf, binf])
    syms = {}
    for line in run([os.path.join(TOOLCHAIN, 'arm-none-eabi-readelf'), '-sW', elf]).splitlines():
        p = line.split()
        if len(p) == 8 and p[0].endswith(':') and p[3] in ('FUNC', 'OBJECT') and not p[7].startswith('$'):
            syms[p[7]] = int(p[1], 16)
    with open(binf, 'rb') as f:
        return bytearray(f.read()), syms


def deck_words(deck, where):
    if len(deck.main) > 60 or len(deck.side) > 15 or len(deck.extra) > 15:
        raise SystemExit(f'{where}: deck over 60/15/15')
    rec = bytearray(0xc0)
    struct.pack_into('<III', rec, 0, len(deck.main), len(deck.side), len(deck.extra))
    struct.pack_into(f'<{len(deck.main)}H', rec, 0xc, *deck.main)
    struct.pack_into(f'<{len(deck.side)}H', rec, 0x84, *deck.side)
    struct.pack_into(f'<{len(deck.extra)}H', rec, 0xa2, *deck.extra)
    return bytes(rec)


def load_duels(path):
    with open(path) as f:
        spec = json.load(f)
    return spec['duels']


def duel_table(rom, duels):
    import w11duel
    files = ydc.rom_decks(rom)
    out = bytearray()
    for i, d in enumerate(duels):
        recs = []
        for side in ('a', 'b'):
            key = f'deck/{d[side]}.ydc'
            if key not in files:
                raise SystemExit(f'duel {i}: no {key} in the WC2011 ROM')
            recs.append(deck_words(ydc.Deck.parse(files[key]), key))
        chara = d.get('chars') or [int(m.group(2)) + (300 if m.group(1) == 'wcs' else 0)
                                    if (m := re.match(r'(wcs|mod)(\d+)(?:_|$)', d[side], re.I)) else 309
                                    for side in ('a', 'b')]
        spec = d.get('setup') or w11duel.setup(d['seed'])
        for side in range(2):
            deck = ydc.Deck.parse(files[f'deck/{d[("a", "b")[side]]}.ydc'])
            try:
                w11duel.arrange(w11duel.take_field(deck.main, spec, side), spec['slots'][side])
            except ValueError as e:
                raise SystemExit(f'duel {i}, side {side}: {e}')
        out += struct.pack('<IIII', d['seed'], d['first'], *chara) + b''.join(recs) + w11duel.encode(spec)
    return out


def thumb_calls(img):
    """(site, target) of every Thumb BL/BLX in an image; target has bit 0 set for a Thumb function."""
    d, out, o = img.d, [], 0
    while o + 4 <= len(d):
        h1, h2 = struct.unpack_from('<HH', d, o)
        if (h1 & 0xf800) == 0xf000 and (h2 & 0xf800) in (0xf800, 0xe800):
            at = img.base + o
            t = bl_target(d, o, at)
            out.append((at, t if (h2 & 0xf800) == 0xe800 else t | 1))
            o += 4
        else:
            o += 2
    return out


def thumb_blx(at, arm_target):
    off = arm_target - ((at + 4) & ~3)
    if not -0x400000 <= off < 0x400000 or arm_target & 3:
        raise SystemExit(f'BLX {at:#x} -> {arm_target:#x}: out of range')
    off &= 0x7fffff
    return struct.pack('<HH', 0xf000 | (off >> 12) & 0x7ff, 0xe800 | (off >> 1) & 0x7ff)


def function_starts(path=None):
    starts = set()
    with open(path or find_up('build/ghidra/decomp_wc2011/index.tsv')) as f:
        for line in f:
            p = line.split('\t')
            if re.match(r'^[0-9a-f]{8}$', p[0]):
                starts.add(int(p[0], 16))
    return starts


def code_sites(img, path=None):
    """Instruction addresses of the Thumb BL/BLX pairs inside the Ghidra functions of an image, decoded from each
    function's start, so a data word that happens to look like a BL is never taken for a call."""
    import capstone
    cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    cs.skipdata = False
    ok = set()
    with open(path or find_up('build/ghidra/decomp_wc2011/index.tsv')) as f:
        for line in f:
            p = line.split('\t')
            if not re.match(r'^[0-9a-f]{8}$', p[0]):
                continue
            a, n = int(p[0], 16), int(p[2])
            if not img.has(a) or a & 1:
                continue
            code = bytes(img.d[img.o(a):img.o(a) + n])
            for i in cs.disasm(code, a):
                if i.mnemonic in ('bl', 'blx') and i.size == 4:
                    ok.add(i.address)
    return ok


def prof_sites(r, wanted, images=(3, 5)):
    """Thumb call sites in ov03 and ov05 (the duel and CPU overlays) to the functions in `wanted` (addresses without
    the Thumb bit), only at instructions of known functions."""
    sites, targets = [], {}
    for img in (r.ov[i] for i in images):
        real = code_sites(img)
        for at, t in thumb_calls(img):
            if t & ~1 in wanted and at in real:
                sites.append((img, at, t))
                targets.setdefault(t & ~1, t)
    return sites, [targets[a] for a in sorted(targets)]


def build_rig(out, duels, speed=False, work=None, base=None, no_anim=0, hold_result=False, prof=None, red=None,
              view=False, bgm=0, no_se=False, idle=False, stream_log=False, shared_decks=False):
    work = work or os.path.join(WORK, 'rig_work')
    r = Rom11(base or ROM11)
    inject.move_arena_hi(r.arm9.d, r.arm9.base, 'BYYP')
    base_hi = r.arm9.word(ARENA_HI_LIT)
    runtime = next((sec for sec in r.code.sections if len(sec.data) >= 16 and u32(sec.data, 4) == 0x31314453), None)
    rig_base, defs, n_prof = RIG_BASE, (), 0
    if stream_log:
        if prof:
            raise SystemExit('streamed trace and profiling are separate rig modes')
        defs = ('-DSTREAM_LOG',)
    if shared_decks:
        defs += ('-DSHARED_DUEL',)
        def shared_fields(d):
            spec = dict(d.get('setup', {}))
            spec.pop('seed', None)
            return d['a'], d['b'], d.get('chars'), spec
        if not duels or any(shared_fields(d) != shared_fields(duels[0]) for d in duels):
            raise SystemExit('shared deck rigs need identical decks, characters and setup for every seed')
    if prof:
        with open(prof) as f:
            wanted = {int(x.split()[0], 16) & ~1 for x in f if x.strip() and not x.startswith('#')}
        wanted &= function_starts()
        n_prof = len(wanted) + 1
        defs = ('-DPROF', f'-DPROF_N={n_prof}') + (('-DRED',) if red else ())
        blob, syms = compile_rig(work, RIG_BASE, defs)
        top = max(syms['rig_seq'] + 4 * SEQ_N, syms.get('red_tab', 0) + 4 * 4096, syms['prof_excl'] + 4 * n_prof)
        rig_base = (RIG_END - (top - RIG_BASE)) & ~0xfff
        if rig_base < RIG_BASE:
            raise SystemExit(f'--prof: {n_prof - 1} functions need the rig at {rig_base:#x}, below {RIG_BASE:#x}; '
                             f'the duel heap would not fit (the CPU allocates its work memory at its first call). '
                             f'Profile fewer functions per run.')
    blob, syms = compile_rig(work, rig_base, (*defs, f'-DMAX_DUELS={max(1, len(duels))}'))
    # Production ROMs already reserve resident mod code below View Mode. Place
    # the complete rig, including NOLOAD logs, below that reservation.
    rig_limit = min(RIG_END, base_hi)
    def rig_top():
        return max(rig_base + len(blob), syms['rig_ev'] + (128 if prof else 256 if stream_log else EV_N) * 16,
                   syms['rig_seq'] + 4 * SEQ_N, syms.get('red_tab', 0) + 4 * 4096,
                   syms.get('prof_excl', 0) + 4 * n_prof)
    if rig_top() > rig_limit:
        rig_base = (rig_limit - (rig_top() - rig_base)) & ~0xfff
        if rig_base < 0x0239a120:
            raise SystemExit('duel trace rig does not fit above the CPU overlay')
        blob, syms = compile_rig(work, rig_base, (*defs, f'-DMAX_DUELS={max(1, len(duels))}'))
    if rig_top() > rig_limit:
        raise SystemExit('duel trace rig overlaps the resident ROM code')
    if len(duels) > 24:
        raise SystemExit('at most 24 duels per rig')
    table = duel_table(r.rom, duels[:1] if shared_decks else duels)
    o = syms['duels'] - rig_base
    blob[o:o + len(table)] = table
    if shared_decks:
        for i, duel in enumerate(duels):
            struct.pack_into('<II', blob, syms['seed_table'] - rig_base + i * 8, duel['seed'], duel['first'])
    put32(blob, syms['n_duels'] - rig_base, len(duels))
    put32(blob, syms['no_anim'] - rig_base, no_anim)
    put32(blob, syms['hold_result'] - rig_base, int(hold_result))
    put32(blob, syms['bgm'] - rig_base, bgm)
    put32(blob, syms['no_se'] - rig_base, int(no_se))
    put32(blob, syms['idle'] - rig_base, int(idle))
    put32(blob, syms['orig'] - rig_base + 4 * 10, RESULT_STEP)
    if max(syms['rig_seq'] + 4 * SEQ_N, syms.get('red_tab', 0) + 4 * 4096, syms.get('prof_excl', 0) + 4 * n_prof) > RIG_END:
        raise SystemExit('rig log past the arena top')
    a9 = r.arm9
    a9.set_word(ARENA_HI_LIT, rig_base)
    a9.set_word(BOOT_CB_LIT, syms['rig_start'], BOOT_CB)
    a9.write(SE_GIVE_UP, arm_blx(SE_GIVE_UP, syms['h_se_lost'] & ~1), SE_GIVE_UP_HEAD)
    ov3 = r.ov[3]
    ov3.set_word(EXIT_CB_LIT, syms['rig_end'], EXIT_CB)
    ov3.set_word(RESULT_STEP_LIT, syms['rig_result_step'], RESULT_STEP)
    if no_anim:
        if not 2 <= no_anim <= 64:
            raise SystemExit('--no-anim: 2 to 64 duel loop updates per frame')
        ov3.set_word(LOOP_MODE_BNE, 0xea000004, 0x1a000004)
        ov3.set_word(LOOP_ITER_MOV, 0xe3a07000 | (no_anim - 1), 0xe1a07005)
    view_syms = {}
    if speed:
        import w11fast
        view_syms = w11fast.apply(r, os.path.join(WORK, 'w11fast'))
        vm_state = view_syms.get('vm_state')
    elif runtime is not None:
        vm_state = runtime.ramAddress
    elif base_hi != ARENA_HI and any(sec.ramAddress == base_hi and u32(sec.data, 0) == 0 for sec in r.code.sections if len(sec.data) >= 4):
        vm_state = base_hi  # Older standalone View Mode header.
    else:
        vm_state = None
    if view:
        if vm_state is None:
            raise SystemExit('--view: the base ROM has no View Mode code (build it with tools/wc2011/w11fast.py)')
        put32(blob, syms['view_state'] - rig_base, vm_state)
    if view_syms:
        put32(blob, syms['story_config_fn'] - rig_base, view_syms['story_config'])
        syms['story_initial_decks'] = view_syms['story_initial_decks']
    for section in r.code.sections if not view_syms else []:
        if len(section.data) >= 12 and u32(section.data, 4) == 0x31314453:
            put32(blob, syms['story_config_fn'] - rig_base, u32(section.data, 8))
            if len(section.data) >= 16:
                syms['story_initial_decks'] = u32(section.data, 12)
            break
    else:
        if not view_syms and any('setup' in d for d in duels):
            raise SystemExit('duel setup requires a ROM built with the story-duel runtime')
    origs = {}
    for name, slot, site, target in HOOKS:
        cur = r.image(site).hook(site, syms[name], target, arm_site=(name == 'h_step'))
        if origs.setdefault(slot, cur) != cur:
            raise SystemExit(f'hook slot {slot}: two different targets')
    for slot, cur in origs.items():
        put32(blob, syms['orig'] - rig_base + 4 * slot, cur)
    ov3.write(CMD_PUSH, struct.pack('<HHII', 0x4778, 0x46c0, 0xe51ff004, syms['cmd_stub']), CMD_PUSH_HEAD)
    targets = []
    if prof:
        sites, targets = prof_sites(r, wanted, (5,) if os.environ.get('W11PROF_OV05') else (3, 5))
        slot = {t: i for i, t in enumerate(targets)}
        for i, t in enumerate(targets):
            th = syms['prof_thunk'] + 8 * i
            put32(blob, syms['prof_target'] - rig_base + 4 * i, t)
            put32(blob, th - rig_base, 0xe24fc008)
            put32(blob, th + 4 - rig_base, 0xea000000 | ((syms['prof_common'] - (th + 12)) >> 2) & 0xffffff)
        for img, at, t in sites:
            img.write(at, thumb_blx(at, syms['prof_thunk'] + 8 * slot[t]))
        if red:
            with open(red) as f:
                want = {int(x.split()[0], 16) & ~1 for x in f if x.strip() and not x.startswith('#')}
            for i, t in enumerate(targets):
                if t & ~1 in want:
                    blob[syms['prof_red'] - rig_base + i] = 1
        print(f'profiler: {len(targets)} functions, {len(sites)} call sites')
    r.extra.append((bytes(blob), rig_base))
    r.save(out)
    keep = ('rig', 'rig_ev', 'rig_seq', 'rig_in_ai', 'duels', 'n_duels', 'rig_f_duel', 'rig_turns', 'story_initial_decks', 'prof_calls', 'prof_incl',
            'prof_excl', 'red_calls', 'red_rep', 'red_rep_time', 'red_full')
    with open(out + '.json', 'w') as f:
        json.dump({'syms': {k: syms[k] for k in keep if k in syms}, 'duels': duels, 'prof_targets': targets,
                   'speed': speed, 'no_anim': no_anim, 'hold_result': hold_result, 'view': view, 'bgm': bgm,
                   'stream_log': stream_log, 'ev_n': 256 if stream_log else 128 if prof else EV_N}, f,
                  indent=1)
    print(f'{out}: {len(duels)} duels, rig {len(blob)} B at {rig_base:#x}, speed patches {"on" if speed else "off"}'
          + (f', {no_anim} duel updates per frame' if no_anim else ''))


def instance_cfg(d, user):
    cfg = mlstate.melon_config(d, True)
    p = os.path.join(cfg, 'melonDS', 'melonDS.toml')
    with open(p) as f:
        t = f.read()
    t = re.sub(r'(?m)^Username = .*$', f'Username = "{user}"', t)
    with open(p, 'w') as f:
        f.write(t)
    return cfg


RIG_FIELDS = ('magic state duel n_ev lost_ev n_seq hash t_start t_end f_start f_end result reason lp0 lp1 frames steps '
              'ai_steps').split()


EXTRA_FIELDS = (('cat_steps', 4), ('cat_ticks', 4), ('ov_n', 8), ('ov_anim', 8), ('ov_gap', 8), ('ov_hide', 8),
                ('b_calls', 8), ('b_ticks', 8), ('prof_bad', 1), ('prof_deep', 1), ('timers_busy', 1), ('se_lost', 1))


def read_rig(ram, syms, n_prof=0, ev_n=EV_N, stream_log=False):
    b = syms['rig']
    n_extra = sum(n for _, n in EXTRA_FIELDS)
    w = [ram.u32(b + 4 * i) for i in range(len(RIG_FIELDS) + 16 + 2 * HIST + n_extra)]
    if w[0] != RIG_MAGIC:
        return None
    res = dict(zip(RIG_FIELDS, w))
    o = len(RIG_FIELDS)
    res['calls'], res['ticks'] = w[o:o + 8], w[o + 8:o + 16]
    res['hist'], res['hist_ticks'] = w[o + 16:o + 16 + HIST], w[o + 16 + HIST:o + 16 + 2 * HIST]
    o += 16 + 2 * HIST
    for name, n in EXTRA_FIELDS:
        res[name] = w[o] if n == 1 else w[o:o + n]
        o += n
    if n_prof:
        res['prof_calls'] = list(struct.unpack(f'<{n_prof}I', ram.block(syms['prof_calls'], 4 * n_prof)))
        res['prof_incl'] = list(struct.unpack(f'<{n_prof}I', ram.block(syms['prof_incl'], 4 * n_prof)))
        res['prof_excl'] = list(struct.unpack(f'<{n_prof}I', ram.block(syms['prof_excl'], 4 * n_prof)))
        if 'red_calls' in syms:
            res['red_calls'] = list(struct.unpack(f'<{n_prof}I', ram.block(syms['red_calls'], 4 * n_prof)))
            res['red_rep'] = list(struct.unpack(f'<{n_prof}I', ram.block(syms['red_rep'], 4 * n_prof)))
            res['red_rep_time'] = list(struct.unpack(f'<{n_prof}I', ram.block(syms['red_rep_time'], 4 * n_prof)))
            res['red_full'] = ram.u32(syms['red_full'])
    raw = ram.block(syms['rig_ev'], 16 * min(res['n_ev'], ev_n))
    res['events'] = [struct.unpack_from('<HHIII', raw, 16 * i) for i in range(len(raw) // 16)]
    if stream_log and res['n_ev'] > ev_n:
        start = res['n_ev'] % ev_n
        res['events'] = res['events'][start:] + res['events'][:start]
    raw = ram.block(syms['rig_seq'], 4 * min(res['n_seq'] // SEQ_EVERY, SEQ_N))
    res['seq'] = list(struct.unpack(f'<{len(raw) // 4}I', raw))
    if 'rig_f_duel' in syms:
        res['f_duel'] = ram.u32(syms['rig_f_duel'])
    if 'rig_turns' in syms:
        res['turns'] = ram.u32(syms['rig_turns'])
    res['think_drops'] = ram.think_drops()
    res['think_max_s'] = ram.think_max_s()
    if 'story_initial_decks' in syms:
        base = syms['story_initial_decks']
        counts = [min(60, ram.u32(base + s * 4)) for s in range(2)]
        res['initial_decks'] = [list(struct.unpack(f'<{counts[s]}H', ram.block(base + 8 + 120 * s, counts[s] * 2))) for s in range(2)]
    return res


def run_duel(rom, index, out_dir, timeout, shots=False):
    d = os.path.join(out_dir, f'i{index}')
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    link = os.path.join(d, 'r.nds')
    os.symlink(os.path.abspath(rom), link)
    with open(rom + '.json') as f:
        meta = json.load(f)
    syms, stop = meta['syms'], (2, 3, 9) if meta.get('hold_result') else (3, 9)
    cfg = instance_cfg(d, f'R{index}')
    m = mlstate.Melon(link, cfg)
    t0 = time.time()
    res = None
    events, last_event, lost_events = [], 0, 0
    try:
        while time.time() - t0 < timeout:
            time.sleep(1 if meta.get('stream_log') else 8)
            data = m.snapshot(os.path.join(d, 'r.ml1'), 1)
            if shots:
                subprocess.run(['import', '-display', m.display, '-window', 'root', '-crop', '256x420+0+0',
                                os.path.join(d, f'shot{int(time.time() - t0):05d}.png')])
            if not data:
                continue
            res = read_rig(mlstate.Ram(data), syms, len(meta.get('prof_targets', [])),
                           meta.get('ev_n', EV_N), meta.get('stream_log', False))
            if res and meta.get('stream_log'):
                delta = res['n_ev'] - last_event
                have = min(delta, len(res['events']))
                lost_events += max(0, delta - have)
                if have:
                    events.extend(res['events'][-have:])
                last_event = res['n_ev']
            if res and res['state'] in stop:
                break
    finally:
        m.stop()
    if res is None:
        res = {'state': -1}
    if meta.get('stream_log') and 'n_ev' in res:
        res['events'], res['lost_ev'] = events, lost_events
    res['wall'] = round(time.time() - t0, 1)
    res['index'] = index
    with open(os.path.join(out_dir, f'duel{index}.json'), 'w') as f:
        json.dump(res, f)
    return res


def summary(res):
    if res.get('state') not in (2, 3):
        return f'duel {res["index"]}: state {res.get("state")} (no end) wall {res["wall"]} s'
    secs = (res['t_end'] - res['t_start']) / TICK_HZ
    ai = sum(res['ticks'][1:8]) / TICK_HZ
    return (f'duel {res["index"]}: result {res["result"]} LP {res["lp0"]}/{res["lp1"]} hash {res["hash"]:08x} '
            f'duel {secs:.1f} s, engine steps {res["steps"]} ({res["ai_steps"]} with AI), AI busy {ai:.1f} s, '
            f'AI calls {sum(res["calls"][1:8])}, events {res["n_ev"]} lost {res["lost_ev"]}, SEs lost {res.get("se_lost")}, '
            f'think drops {res.get("think_drops")}, '
            f'wall {res["wall"]} s')


def load_runs(d):
    runs = {}
    for f in sorted(os.listdir(d)):
        m = re.match(r'duel(\d+)\.json$', f)
        if m:
            with open(os.path.join(d, f)) as fh:
                runs[int(m.group(1))] = json.load(fh)
    return runs


def frames(ticks):
    return ticks / TICK_HZ * FRAME_HZ


def episodes(res):
    for k, x, t0, span, busy in res.get('events', []):
        if k & 0xff00 == EV_EPISODE:
            yield KINDS[k & 0xff], x & 0xff, x >> 8, t0, span, busy


def cmd_report(a):
    runs = load_runs(a.dir)
    tot, hist = {}, [0] * HIST
    duel_s = ai_s = 0
    for i, res in runs.items():
        print(summary(res))
        if res.get('state') not in (2, 3):
            continue
        duel_s += (res['t_end'] - res['t_start']) / TICK_HZ
        ai_s += sum(res['ticks'][1:8]) / TICK_HZ
        hist = [x + y for x, y in zip(hist, res['hist'])]
        for kind, phase, n, t0, span, busy in episodes(res):
            t = tot.setdefault(kind, [0, 0, 0, 0])
            t[0] += 1
            t[1] += n
            t[2] += span
            t[3] += busy
    print(f'\n{len(runs)} duels: {duel_s:.1f} s, AI busy {ai_s:.1f} s ({100 * ai_s / max(1, duel_s):.0f} %)')
    print('\n| kind | decisions | calls | frames per decision | AI busy frames per decision |')
    print('|---|---|---|---|---|')
    for k, (n, c, span, busy) in sorted(tot.items()):
        print(f'| {k} | {n} | {c} | {frames(span) / n:.1f} | {frames(busy) / n:.2f} |')
    print('\nengine steps with an AI call, by AI time in the step (1/8 frame buckets):')
    print(' '.join(f'{i / 8:g}:{c}' for i, c in enumerate(hist) if c))


def decisions(res):
    """CPU decisions and duel commands in order, with their timing removed."""
    seq = [('hash after call', SEQ_EVERY * (i + 1), w) for i, w in enumerate(res.get('seq', []))]
    cmds = [('cmd', x, a, b, c) for k, x, a, b, c in res.get('events', []) if k == EV_CMD]
    return seq, cmds


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i, x, y
    if len(a) != len(b):
        return min(len(a), len(b)), None, None
    return None


def cmd_diff(a):
    ra, rb = load_runs(a.a), load_runs(a.b)
    same = 0
    rows = []
    for i in sorted(set(ra) & set(rb)):
        x, y = ra[i], rb[i]
        if x.get('state') not in (2, 3) or y.get('state') not in (2, 3):
            rows.append(f'| {i} | no end ({x.get("state")}/{y.get("state")}) | | | |')
            continue
        sa, sb = (x['t_end'] - x['t_start']) / TICK_HZ, (y['t_end'] - y['t_start']) / TICK_HZ
        ai_a, ai_b = sum(x['ticks'][1:8]) / TICK_HZ, sum(y['ticks'][1:8]) / TICK_HZ
        ok = (x['hash'] == y['hash'] and x['n_seq'] == y['n_seq'] and x['result'] == y['result']
              and (x['lp0'], x['lp1']) == (y['lp0'], y['lp1']))
        where = ''
        if not ok:
            (qa, ca), (qb, cb) = decisions(x), decisions(y)
            d = first_diff(qa, qb)
            e = first_diff(ca, cb)
            where = f' first call diff {d}, first command diff {e}'
        same += ok
        rows.append(f'| {i} | {"same" if ok else "DIFFERENT" + where} | {x["n_seq"]} | {sa:.1f} -> {sb:.1f} s '
                    f'(x{sa / max(sb, 1e-9):.2f}) | {ai_a:.1f} -> {ai_b:.1f} s |')
    print('| duel | decisions and outcome | AI calls | duel time | AI busy |')
    print('|---|---|---|---|---|')
    print('\n'.join(rows))
    print(f'\n{same} of {len(rows)} duels identical')
    if same != len(rows):
        raise SystemExit(1)


def func_index(path):
    import bisect
    starts = []
    with open(path) as f:
        for line in f:
            p = line.split('\t')
            if p and re.match(r'^[0-9a-f]{8}$', p[0]):
                starts.append(int(p[0], 16))
    starts.sort()
    return lambda pc: starts[bisect.bisect_right(starts, pc) - 1] if starts and pc >= starts[0] else pc


def cmd_profile(a):
    import collections
    import view_deal
    d = os.path.join(a.out, f'prof{a.index}')
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    link = os.path.join(d, 'r.nds')
    os.symlink(os.path.abspath(a.rom), link)
    with open(a.rom + '.json') as f:
        syms = json.load(f)['syms']
    cfg = os.path.join(d, 'cfg_gdb')
    port = view_deal.free_port()
    view_deal.gdb_config(instance_cfg(d, f'R{a.index}'), cfg, port)
    fn = func_index(a.functions)
    m = mlstate.Melon(link, cfg)
    pcs, fns, depth, incl = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    try:
        g = view_deal.Rsp(port, timeout=60)
        g.cmd('c', reply=False)
        time.sleep(a.skip)
        t0 = time.time()
        n = 0
        while time.time() - t0 < a.seconds:
            time.sleep(a.interval)
            g.s.sendall(b'\x03')
            g.reply()
            pc = g.reg(15)
            st = g.u32(syms['rig'] + 4)
            in_ai = g.u32(syms['rig_in_ai'])
            ai = (g.u32(0x0229e6cc) >> 8) & 0x3f
            snap = (g.u32(0x022c351c) >> 12) & 0xf
            keep = st == 1 and (in_ai or not a.ai_only)
            seen = set()
            if keep and a.stacks:
                sp, lr = g.reg(13), g.reg(14)
                top = 0x027e4000 if sp >= 0x027e0000 else sp + 256
                nb = max(0, min(256, top - sp)) & ~3
                words = struct.unpack(f'<{nb // 4}I', g.read(sp, nb)) if nb and 0x02000000 <= sp < 0x02800000 else ()
                seen = {fn(pc), fn(lr & ~1)}
                seen.update(fn(w & ~1) for w in words if 0x02000000 <= w < 0x023a0000 and w & 1)
            g.cmd('c', reply=False)
            if st != 1:
                if st > 1:
                    break
                continue
            n += 1
            if not keep:
                continue
            for f_ in seen:
                incl[f_] += 1
            pcs[pc] += 1
            fns[fn(pc)] += 1
            depth[(ai, snap)] += 1
        g.s.sendall(b'\x03')
        g.reply()
        g.detach()
    finally:
        m.stop()
    out = {'samples': n, 'functions': fns.most_common(60), 'pcs': pcs.most_common(60),
           'inclusive': incl.most_common(200),
           'depth': [[list(k), v] for k, v in depth.most_common()]}
    with open(os.path.join(a.out, f'profile{a.index}.json'), 'w') as f:
        json.dump(out, f)
    print(f'{n} samples in the duel, {sum(fns.values())} kept')
    for f_, c in fns.most_common(a.top):
        print(f'{c:6d} {100 * c / max(1, n):5.1f}% {f_:#010x}')
    print('AI depth, snapshot depth:', out['depth'][:8])
    if a.stacks:
        kept = sum(fns.values())
        print('inclusive (function on the sampled stack, upper bound):')
        for f_, c in incl.most_common(a.top):
            print(f'{c:6d} {100 * c / max(1, kept):5.1f}% {f_:#010x}')


def cmd_rig(a):
    duels = load_duels(a.duels)
    build_rig(a.out, duels, a.speed, base=a.base, no_anim=a.no_anim, hold_result=a.hold_result, prof=a.prof, view=a.view,
              red=a.red, bgm=a.bgm, no_se=a.no_se, idle=a.idle)


def cmd_frames(a):
    """Where a duel's time goes: frames with a CPU call, frames animating a duel command, other frames; and how much
    CPU time follows straight after an animation."""
    runs = load_runs(a.dir)
    cat = [0] * 3
    steps = [0] * 3
    ov = {k: [0, 0, 0, 0, 0] for k in KINDS}
    total = 0
    for i, res in runs.items():
        if res.get('state') not in (2, 3) or 'cat_ticks' not in res:
            continue
        total += (res['t_end'] - res['t_start']) / TICK_HZ
        for c in range(3):
            cat[c] += res['cat_ticks'][c] / TICK_HZ
            steps[c] += res['cat_steps'][c]
        busy = {}
        for kind, phase, n, t0, span, b in episodes(res):
            busy[kind] = busy.get(kind, 0) + b
        for k, name in KINDS.items():
            o = ov[k]
            o[0] += res['ov_n'][k]
            o[1] += res['ov_anim'][k] / TICK_HZ
            o[2] += res['ov_gap'][k] / TICK_HZ
            o[3] += res['ov_hide'][k] / TICK_HZ
            o[4] += busy.get(name, 0) / TICK_HZ
    print(f'{len(runs)} duels, {total:.1f} s')
    for c, name in enumerate(('frames with a CPU call', 'frames with a duel command queued or running',
                              'other frames')):
        print(f'{name}: {steps[c]} updates, {cat[c]:.1f} s ({100 * cat[c] / max(total, 1e-9):.0f} %)')
    bc = [sum(r.get('b_calls', [0] * 8)[k] for r in runs.values()) for k in range(8)]
    bt = [sum(r.get('b_ticks', [0] * 8)[k] for r in runs.values()) / TICK_HZ for k in range(8)]
    print('CPU calls in command frames: ' + ', '.join(f'{KINDS[k]} {bc[k]} ({bt[k]:.1f} s)' for k in KINDS if bc[k]))
    print('\n| kind | decisions | CPU busy s | after an animation: animation s | gap s | CPU s that fits in it |')
    print('|---|---|---|---|---|---|')
    for k, (n, anim, gap, hide, busy) in ov.items():
        if n:
            print(f'| {KINDS[k]} | {n} | {busy:.1f} | {anim:.1f} | {gap:.1f} | {hide:.1f} |')


def cmd_profrep(a):
    """Emulated ARM9 time per function from a --prof rig run: inclusive, exclusive, calls (inside CPU entries)."""
    with open(a.rom + '.json') as f:
        targets = json.load(f)['prof_targets']
    names = {}
    with open(a.functions) as f:
        for line in f:
            p = line.split('\t')
            if re.match(r'^[0-9a-f]{8}$', p[0]):
                names[int(p[0], 16)] = p[1]
    rows, ai, red = {}, 0, {}
    for i, res in load_runs(a.dir).items():
        if 'prof_calls' not in res:
            continue
        ai += sum(res['ticks'][1:8]) / TICK_HZ
        for j, t in enumerate(targets):
            r = rows.setdefault(t, [0, 0, 0])
            r[0] += res['prof_calls'][j]
            r[1] += res['prof_incl'][j] / BUS_HZ
            r[2] += res['prof_excl'][j] / BUS_HZ
            if res.get('red_calls') and res['red_calls'][j]:
                q = red.setdefault(t, [0, 0, 0.0])
                q[0] += res['red_calls'][j]
                q[1] += res['red_rep'][j]
                q[2] += res['red_rep_time'][j] / BUS_HZ
        print(f'duel {i}: shadow stack mismatches {res["prof_bad"]}, past depth {res["prof_deep"]}, '
              f'timers in use before the rig {res["timers_busy"]:#x}')
    print(f'CPU entry time {ai:.2f} s')
    for key, col in (('exclusive', 2), ('inclusive', 1)):
        print(f'\nby {key} time:\n| function | calls | inclusive s | exclusive s | excl. us per call |')
        print('|---|---|---|---|---|')
        for t, (n, inc, exc) in sorted(rows.items(), key=lambda kv: -kv[1][col])[:a.top]:
            print(f'| {t & ~1:#010x} {names.get(t & ~1, "")} | {n} | {inc:.2f} | {exc:.2f} | '
                  f'{1e6 * exc / max(n, 1):.2f} |')
    if red:
        print('\nrepeats inside one decision, key (function, r0-r3, duel state hash):')
        print('| function | calls | repeated calls | share | inclusive s of repeated calls | of the function\'s |')
        print('|---|---|---|---|---|---|')
        for t, (n, rp, rt) in sorted(red.items(), key=lambda kv: -kv[1][2]):
            inc = rows[t][1]
            print(f'| {t & ~1:#010x} {names.get(t & ~1, "")} | {n} | {rp} | {100 * rp / max(n, 1):.0f} % | {rt:.2f} | '
                  f'{inc:.2f} |')
    if a.json:
        with open(a.json, 'w') as f:
            json.dump({f'{t & ~1:#010x}': v + red.get(t, []) for t, v in rows.items()}, f)


def cmd_run(a):
    with open(a.rom + '.json') as f:
        n = len(json.load(f)['duels'])
    idx = list(range(n)) if not a.only else [int(x) for x in a.only.split(',')]
    os.makedirs(a.out, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        for res in ex.map(lambda i: run_duel(a.rom, i, a.out, a.timeout, a.shots), idx):
            print(summary(res), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('rig', help='build a rig ROM from the WC2011 ROM')
    p.add_argument('out')
    p.add_argument('--duels', default=DUELS)
    p.add_argument('--speed', action='store_true', help='apply the speed patches (tools/wc2011/w11fast.py)')
    p.add_argument('--base', help='WC2011 ROM to build on (default: the stock EU ROM); e.g. the standalone patched ROM')
    p.add_argument('--no-anim', type=int, nargs='?', const=8, default=0, metavar='N',
                   help='tests only: run the duel update N times per drawn frame (default 8), so animations, '
                        'cut-ins and waits pass N times faster')
    p.add_argument('--view', action='store_true',
                   help='spectator view of View Mode (hands hidden, no card-check prompt); the base ROM or --speed '
                        'must carry the View Mode code')
    p.add_argument('--hold-result', action='store_true',
                   help='stay on the result screen instead of leaving the duel (for recordings)')
    p.add_argument('--bgm', type=lambda x: int(x, 0), default=0,
                   help='duel BGM sound id written to 0x020b8858 before each duel (e.g. 448 for a story-only theme); '
                        'without it the rig duel has no music')
    p.add_argument('--no-se', action='store_true',
                   help='tests only: silence the sound effects that use the SE base 0x021273e8 (318 of 367), so a '
                        'recording holds the duel music alone')
    p.add_argument('--idle', action='store_true',
                   help='tests only: side 0 is a human who goes first and never presses anything, so the duel '
                        'waits on its first turn (music recordings with no duel sounds)')
    p.add_argument('--prof', metavar='LIST',
                   help='tests only: time every Thumb call to the functions in LIST (one hex address per line) with '
                        'the hardware timers, inclusive and exclusive, inside CPU entries; read with profrep')
    p.add_argument('--red', metavar='LIST',
                   help='with --prof: for these functions also count calls whose (function, r0-r3, hash of the duel '
                        'state 0x02298ad8-0x0229e000) was already seen in the same CPU decision')
    p.set_defaults(fn=cmd_rig)
    p = sub.add_parser('profrep', help='emulated time per function from a run of a --prof rig')
    p.add_argument('rom')
    p.add_argument('dir')
    p.add_argument('--top', type=int, default=40)
    p.add_argument('--json', help='also write {function: [calls, inclusive s, exclusive s]}')
    p.add_argument('--functions', default=find_up('build/ghidra/decomp_wc2011/index.tsv'))
    p.set_defaults(fn=cmd_profrep)
    p = sub.add_parser('frames', help='duel time by frame kind and CPU time right after an animation')
    p.add_argument('dir')
    p.set_defaults(fn=cmd_frames)
    p = sub.add_parser('run', help='run the rig duels headless, one melonDS per duel')
    p.add_argument('rom')
    p.add_argument('out')
    p.add_argument('--only')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--timeout', type=float, default=1800)
    p.add_argument('--shots', action='store_true', help='screenshot at every poll (debugging the rig)')
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser('diff', help='decision identity and speed between two run folders (stock, patched)')
    p.add_argument('a')
    p.add_argument('b')
    p.set_defaults(fn=cmd_diff)
    p = sub.add_parser('profile', help='PC samples through the melonDS GDB stub (JIT off), binned by function')
    p.add_argument('rom')
    p.add_argument('out')
    p.add_argument('--index', type=int, default=0)
    p.add_argument('--skip', type=float, default=20, help='seconds before sampling starts')
    p.add_argument('--seconds', type=float, default=600)
    p.add_argument('--interval', type=float, default=0.02)
    p.add_argument('--top', type=int, default=40)
    p.add_argument('--ai-only', action='store_true', help='keep only samples taken inside a CPU AI entry')
    p.add_argument('--stacks', action='store_true', help='also count every function whose return address is on the stack')
    p.add_argument('--functions', default=find_up('build/ghidra/decomp_wc2011/index.tsv'))
    p.set_defaults(fn=cmd_profile)
    p = sub.add_parser('report', help='timing per decision kind from a run folder')
    p.add_argument('dir')
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
