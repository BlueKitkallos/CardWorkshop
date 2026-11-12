"""WC2011 CPU speed patch: the same CPU decisions in less time. Applies to the stock WC2011 EU ROM or inside a build."""
import argparse
import hashlib
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import inject

SRC = os.path.join(ROOT, 'mod', 'w11fast')
TOOLCHAIN = os.path.expanduser(os.environ.get('ARM_TOOLCHAIN', '~/tools/arm-gnu-toolchain/bin'))
CFLAGS = [*os.environ.get('W11FAST_DEFS', '').split(), '-mcpu=arm946e-s', '-mthumb', '-mthumb-interwork', '-O2', '-ffreestanding', '-nostdlib', '-fno-builtin',
          '-Wall', '-Werror']
EU_SHA1 = '7617788d197ffd45d2ab2bb6deadbf0f9874e2fa'

ITCM = 0x01ff8000
CODE_BASE = 0x01fff520
CODE_END = 0x02000000
ITCM_ARENA_LO_LIT = 0x02051ee4


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'{" ".join(cmd)}\n{r.stdout}{r.stderr}')
    return r.stdout


def compile_code(work, src=SRC, name='w11fast', base=CODE_BASE, limit=CODE_END, skip=(), srcs=None):
    os.makedirs(work, exist_ok=True)
    elf = os.path.join(work, f'{name}.elf')
    if srcs is None:
        srcs = sorted(os.path.join(src, f) for f in os.listdir(src) if f.endswith(('.c', '.S')) and f not in skip)
    run([os.path.join(TOOLCHAIN, 'arm-none-eabi-gcc'), *CFLAGS, f'-Wl,--defsym=CODE_BASE={base:#x}',
         '-Wl,-T', os.path.join(src, f'{name}.ld'), '-Wl,-Map=' + os.path.join(work, f'{name}.map'), '-o', elf,
         *srcs, '-lgcc'])
    binf = os.path.join(work, f'{name}.bin')
    run([os.path.join(TOOLCHAIN, 'arm-none-eabi-objcopy'), '-O', 'binary', elf, binf])
    syms = {}
    for line in run([os.path.join(TOOLCHAIN, 'arm-none-eabi-readelf'), '-sW', elf]).splitlines():
        p = line.split()
        if len(p) == 8 and p[0].endswith(':') and p[3] in ('FUNC', 'OBJECT', 'NOTYPE') and not p[7].startswith('$'):
            syms[p[7]] = int(p[1], 16)
    with open(binf, 'rb') as f:
        blob = f.read()
    if base + len(blob) > limit:
        raise SystemExit(f'{name} code {len(blob)} B does not fit {base:#x}-{limit:#x}')
    return blob, syms


PROP_LOOKUP = 0x02029c0c
PROP_LOOKUP_HEAD = bytes.fromhex('f8b5334f051c0420385e00ae')
FRAME_GET = 0x0202abf8
FRAME_GET_HEAD = bytes.fromhex('08b5fff743fa40688006c00e')
GENRE_READ = 0x0202a124
GENRE_READ_HEAD = bytes.fromhex('10b50c1c09490840fff776fe')
COPY = 0x02089774
COPY_HEAD = bytes.fromhex('000052e31eff2f01')
STEP_CALL, ENGINE_STEP = 0x021460cc, 0x0219d470
MAIN_CALL, CPU_MAIN = 0x02256a6a, 0x0226a444
CHAIN_CALL, CPU_CHAIN = 0x0224e3e4, 0x0226a8c8
TRIG_CALL, CPU_TRIG = 0x0223a028, 0x0226a75c
ZONE_ID = 0x021a36f8
ZONE_ID_HEAD = bytes.fromhex('feb50d1c009214222e1c5643')
DUEL_STEPS = 0x0228faa8
HEAP_CREATE_CALL, HEAP_CREATE = 0x02016698, 0x0207c3fc
DUEL_SETUP, DUEL_LOOP, DUEL_EXIT = 0x02144d40, 0x02145fc0, 0x021462a0
START_CMD_CALL, CMD_PUSH = 0x0219b0e8, 0x021c3bc8
REPLAY_PROMPT_CALL, SET_CALLBACK = 0x0201950e, 0x02014ff0

AP_STUBS = 0x02000500
AP_STUBS_OLD = bytes.fromhex('1ae8ad575da5bad81081ace525b616511bb4b098bac1b499db4e18e641dc309b4953c3c44fbea6f8f0e8f00e'
                             '922d9c718fd3383f002204df70475d1728c707220123a86f8978cdb757c91c06')
AP_STUBS_NEW = bytes.fromhex('00009fe51eff2fe1cfb3000000009fe51eff2fe177b1000007402de91c009fe51c109fe5002091e5020050e1'
                             '14009f05000081050c0080023c0081050780bde830fc2d02e4e42d0200260002')
AP_HOOK, AP_HOOK_OLD, AP_HOOK_NEW = 0x020009f8, bytes.fromhex('1eff2fe1'), bytes.fromhex('c6feffea')

VIEW_SRC = os.path.join(ROOT, 'mod', 'w11view')
FIX_SRC = os.path.join(ROOT, 'mod', 'w11fix')
ARENA_HI_LIT, ARENA_HI = inject.arena_hi('BYYP')
MENU_DEFAULT, MENU_DEFAULT_OLD = 0x0214da8c, 0xea000169
FREE_DUEL_ENTRY, FREE_DUEL_ITEMS, FREE_DUEL_N = 0x0215c5c4, 0x0215c3a8, 6
VIEW_ID, VIEW_LABEL = 0x2007, 0x1c35 - 3000
LIST_EXIT_CALL, SCENE_SWITCH = 0x02156f70, 0x02016cf4
ARM_NOP, MOV_R0_R1 = 0xe1a00000, 0xe1a00001
VIEWER_SITES = ((0x02150790, 0xe5922004, 0x02150794, 0xe2022001, ARM_NOP, 'vm_viewer_r2'),
                (0x02150198, 0xe5911004, 0x0215019c, 0xe2011001, ARM_NOP, 'vm_viewer_r1'),
                (0x02150b98, 0xe5901004, 0x02150bb0, 0xe2010001, MOV_R0_R1, 'vm_viewer_r1'))
TILE_CHECK, TILE_CHECK_HEAD = 0x021506f8, 0xe92d0008
CARD_VIEW, CARD_VIEW_HEAD = 0x0215ebac, 0xe92d000f
BUSTUP_CALL, BUSTUP_LOAD = 0x0214d5c4, 0x0214d5e8
RESULT_PANEL_CALL, RESULT_PANEL = 0x0219d2de, 0x0219ae94
OPTIONS_ENTRY, OPTIONS_ITEMS, OPTIONS_N = 0x0215c5ec, 0x0215c420, 6
PROFILE_ID, PROFILE_LABEL = 0x2008, 1743 - 3000
CM_STEPS, CM_INIT, CM_SETUP, CM_CONFIRM = 0x02153680, 0x0214cadc, 0x0214cc30, 0x0214cd20
CM_SETUP_STEPS, CM_CONFIRM_STEP, CM_END_STEP = (5, 12, 15, 18), 6, 8
CM_LOOK_STEPS, CM_GENDER_EXIT = 0x021539a4, 0x0214ea58
CM_HAIR_COLOR, CM_HAIR_COLOR_HEAD = 0x02151740, bytes.fromhex('0c1090e520c09fe5')
CM_WEAR_COLOR, CM_WEAR_COLOR_HEAD = 0x02151774, bytes.fromhex('b210d0e110009fe5')
JANKEN_PICK_CALL, JANKEN_PICK = 0x0215074c, 0x021511c8
THINK_OFF_CALL, THINK_OFF = 0x02148c6c, 0x02146944
THINK_DELAY_CMP, THINK_DELAY = 0x0201601c, 30
GAME_TEXT, GAME_TEXT_HEAD = 0x0202b64c, bytes.fromhex('10b50d4909690a6a002a0fd1')
TEXT_FIRST, TEXT_LANGS = 0x7f00, {1: 'e', 2: 'g', 3: 'f', 4: 'i', 5: 's'}
VIEW_HELP, PROFILE_HELP = TEXT_FIRST, TEXT_FIRST + 1
HELP_TEXTS = (
    (VIEW_LABEL + 3000, {'e': 'Watch two CPUs duel.', 'f': "Regardez deux CPU s'affronter.",
                         'g': 'Sieh zwei CPUs beim Duell zu.', 's': 'Mira un duelo entre dos CPU.',
                         'i': 'Guarda un duello tra due CPU.'}),
    (PROFILE_LABEL + 3000, {'e': 'Change your name, look and region.', 'f': 'Modifiez votre nom, apparence et région.',
                            'g': 'Ändere Name, Aussehen und Region.', 's': 'Cambia tu nombre, aspecto y región.',
                            'i': 'Cambia nome, aspetto e regione.'}),
)
MENU_DECIDE_WAITS, MENU_DECIDE_FRAMES = (0x02154a18, 0x02154b68, 0x021563f0, 0x02156058), 8
SET_BRIGHT, SET_BRIGHT_HEAD = 0x0208278c, bytes.fromhex('002902d100210180704704dd')
CUTIN_REQUEST_CALL, CUTIN_SETUP = 0x021906a8, 0x0218bf0c
CUTIN_RESTORED, CUTIN_RESTORED_HEAD = 0x02188dc0, struct.pack('<5I', 0xe59f1030, 0xe5910000, 0xe3c00a0e, 0xe3800a06, 0xe5810000)
FRAME_CALL, FRAME_UPDATE = 0x020161aa, 0x020176f0
SUMMON_BG_CLEARS, SUMMON_BG_CLEAR_OLD, SUMMON_BG_CLEAR = (0x02164868, 0x02164954), 0xe3c20001, 0xe3c20005
MATERIAL_DRAW_CALLS = ((0x021698c0, 0xebfffb06), (0x021698f8, 0xebfffaf8))
PANEL_FRAME_LOAD, GFX_LOAD = 0x02020f20, 0x0201c03c
PANEL_FRAME_FREE, HEAP_FREE = 0x02020f48, 0x02016aa8
PANEL_JOB_DONE, PANEL_JOB_FREE = 0x02021020, 0x020202a5
JOB_UPLOAD_CALL = 0x02025c84


def record_count(rom, name):
    import game
    prof = game.for_rom(rom)
    files = {k.lower(): v for k, v in game.container_files(rom, f"{prof['archive_root']}/bin2.pac").items()}
    data = files.get(name.lower())
    if not data or len(data) % 8:
        raise SystemExit(f'bin2.pac: no {name} of 8-byte records')
    return len(data) // 8


def trampoline(target):
    return struct.pack('<HHII', 0x4778, 0x46c0, 0xe51ff004, target)


def arm_branch(at, target, link=False):
    off = target - (at + 8)
    if not -0x2000000 <= off < 0x2000000 or off & 3:
        raise SystemExit(f'B {at:#x} -> {target:#x}: out of range')
    return (0xeb000000 if link else 0xea000000) | (off >> 2) & 0xffffff


def pack_help_texts(blob, syms, base):
    import carddb
    data = bytearray()
    offs = []
    for fallback, texts in HELP_TEXTS:
        row = []
        for lang in range(7):
            code = TEXT_LANGS.get(lang)
            if code is None:
                row.append(0xffff)
                continue
            row.append(len(data))
            data += carddb.encode_text(texts[code], code) + b'\0'
        offs.append(row)
    room = syms['pe_text_data_end'] - syms['pe_text_data'] if 'pe_text_data_end' in syms else 384
    if len(data) > room:
        raise SystemExit(f'help texts: {len(data)} B, room for {room}')
    struct.pack_into(f'<{len(HELP_TEXTS)}H', blob, syms['pe_text_fallback'] - base, *(f for f, _ in HELP_TEXTS))
    struct.pack_into(f'<{7 * len(HELP_TEXTS)}H', blob, syms['pe_text_offs'] - base, *(v for row in offs for v in row))
    blob[syms['pe_text_data'] - base:syms['pe_text_data'] - base + len(data)] = data


def apply_view(r, work, think=True, cutin=True, menus=True, fades=True, display=True):
    """View Mode: a CPU-vs-CPU duel picked from Free Duel, shown as a spectator. Code in main RAM below the arena top."""
    skip = (() if cutin else ('cutin.c',)) + (() if display else ('display.c',))
    blob, _ = compile_code(work, VIEW_SRC, 'w11view', ARENA_HI - 0x4000, ARENA_HI, skip)
    base = (ARENA_HI - len(blob)) & ~0xff
    blob, syms = compile_code(work, VIEW_SRC, 'w11view', base, ARENA_HI, skip)
    if syms['vm_state'] != base:
        raise SystemExit(f'w11view: vm_state at {syms["vm_state"]:#x}, not at the base {base:#x}')
    blob = bytearray(blob)
    ov3, ov7, ov18 = r.ov[3], r.ov[7], r.ov[18]
    r.ov[31].hook(0x02165010, syms['story_duel'], 0x02016d68, arm_site=True)
    r.arm9.hook(REPLAY_PROMPT_CALL, syms['story_replay_prompt'], SET_CALLBACK)
    # Initial arrangement runs after the native shuffle. Effect shuffles below
    # replant only outstanding explicit draws, using copies still in the deck.
    initial = [(at, target) for at, target in __import__('w11speed').thumb_calls(ov3)
               if 0x0219b020 <= at < 0x0219b1ac and target & ~1 == 0x021a7b7c]
    if len(initial) != 2:
        raise SystemExit('normal duel setup: expected two initial deck shuffles')
    for at, _ in initial:
        ov3.hook(at, syms['story_initial_shuffle'], 0x021a7b7c)
    if ov3.target(START_CMD_CALL) & ~1 != CMD_PUSH or ov3.word(START_CMD_CALL - 8) != 0x21002001:
        raise SystemExit(f'normal duel setup: {START_CMD_CALL:#x} is not the duel-start command push')
    ov3.hook(START_CMD_CALL, syms['story_start_cmd'], CMD_PUSH)
    for start, end, target, wrapper in (
        (0x021c0bb4, 0x021c0c54, 0x021a7b7c, 'story_effect_shuffle'),
        (0x02253a04, 0x02253e36, 0x021d0950, 'story_normal_draw'),
    ):
        sites = [at for at, t in __import__('w11speed').thumb_calls(ov3) if start <= at < end and t & ~1 == target]
        if len(sites) != 1:
            raise SystemExit(f'{wrapper}: expected exactly one engine call, found {len(sites)}')
        ov3.hook(sites[0], syms[wrapper], target)
    struct.pack_into('<I', blob, syms['story_next_main'] - base,
                     ov3.hook(MAIN_CALL, syms['story_main'], None))
    if ov3.word(DUEL_STEPS + 8) != DUEL_LOOP:
        raise SystemExit(f'ov03 {DUEL_STEPS + 8:#x}: duel loop step {ov3.word(DUEL_STEPS + 8):#x}, expected {DUEL_LOOP:#x}')
    struct.pack_into('<I', blob, syms['vm_next_loop'] - base, DUEL_LOOP)
    struct.pack_into('<I', blob, syms['vm_next_exit'] - base, ov3.word(DUEL_STEPS + 12))
    hi = r.arm9.word(ARENA_HI_LIT)
    if hi == ARENA_HI:
        r.arm9.set_word(ARENA_HI_LIT, base)
    elif hi > base:
        raise SystemExit(f'arm9 arena top {hi:#x}: above the View Mode code at {base:#x}, not the stock {ARENA_HI:#x}')
    if menus:
        items = [struct.unpack_from('<5I', ov18.d, ov18.o(FREE_DUEL_ITEMS) + 20 * i) for i in range(FREE_DUEL_N)]
        if [it[0] for it in items] != list(range(0x2001, 0x2007)):
            raise SystemExit('ov18: Free Duel menu items are not 0x2001-0x2006')
        items = items[:-1] + [(VIEW_ID, VIEW_LABEL, VIEW_HELP - 3000, 0, 0)] + items[-1:]
        struct.pack_into(f'<{5 * len(items)}I', blob, syms['vm_items'] - base, *(v for it in items for v in it))
        opts = [struct.unpack_from('<5I', ov18.d, ov18.o(OPTIONS_ITEMS) + 20 * i) for i in range(OPTIONS_N)]
        if [it[0] for it in opts] != list(range(0x4001, 0x4007)):
            raise SystemExit('ov18: User Settings items are not 0x4001-0x4006')
        label = PROFILE_LABEL & 0xffffffff
        opts = opts[:1] + [(PROFILE_ID, label, PROFILE_HELP - 3000, 0, 0)] + opts[1:]
        struct.pack_into(f'<{5 * len(opts)}I', blob, syms['pe_items'] - base, *(v for it in opts for v in it))
        ov18.set_word(MENU_DEFAULT, arm_branch(MENU_DEFAULT, syms['vm_menu_default']), MENU_DEFAULT_OLD)
        ov18.set_word(FREE_DUEL_ENTRY, 0x2000, 0x2000)
        ov18.set_word(FREE_DUEL_ENTRY + 0xc, len(items), FREE_DUEL_N)
        ov18.set_word(FREE_DUEL_ENTRY + 0x10, syms['vm_items'], FREE_DUEL_ITEMS)
        ov7.hook(LIST_EXIT_CALL, syms['vm_list_exit'], SCENE_SWITCH, arm_site=True)
        ov7.hook(JANKEN_PICK_CALL, syms['vm_janken_pick'], JANKEN_PICK, arm_site=True)
        ov18.set_word(OPTIONS_ENTRY, 0x4000, 0x4000)
        ov18.set_word(OPTIONS_ENTRY + 0xc, len(opts), OPTIONS_N)
        ov18.set_word(OPTIONS_ENTRY + 0x10, syms['pe_items'], OPTIONS_ITEMS)
        ov13 = r.ov[13]
        ov13.set_word(CM_STEPS, syms['pe_init'], CM_INIT)
        for i in CM_SETUP_STEPS:
            ov13.set_word(CM_STEPS + 4 * i, syms['pe_setup'], CM_SETUP)
        ov13.set_word(CM_STEPS + 4 * CM_CONFIRM_STEP, syms['pe_confirm'], CM_CONFIRM)
        ov13.set_word(CM_STEPS + 4 * CM_END_STEP, syms['pe_done'], 0)
        ov13.set_word(CM_LOOK_STEPS + 8, syms['pe_gender_exit'], CM_GENDER_EXIT)
        ov13.write(CM_HAIR_COLOR, struct.pack('<II', 0xe51ff004, syms['pe_hair_color']), CM_HAIR_COLOR_HEAD)
        ov13.write(CM_WEAR_COLOR, struct.pack('<II', 0xe51ff004, syms['pe_wear_color']), CM_WEAR_COLOR_HEAD)
        for at, old, at2, old2, new2, fn in VIEWER_SITES:
            ov3.set_word(at, arm_branch(at, syms[fn], link=True), old)
            ov3.set_word(at2, new2, old2)
        ov3.set_word(TILE_CHECK, arm_branch(TILE_CHECK, syms['vm_tile_check']), TILE_CHECK_HEAD)
        ov3.set_word(CARD_VIEW, arm_branch(CARD_VIEW, syms['vm_card_view']), CARD_VIEW_HEAD)
        ov3.hook(BUSTUP_CALL, syms['vm_bustup'], BUSTUP_LOAD, arm_site=True)
        ov3.hook(RESULT_PANEL_CALL, syms['vm_result_panel'], RESULT_PANEL)
        pack_help_texts(blob, syms, base)
        for at in MENU_DECIDE_WAITS:
            old = ov18.word(at)
            if old & 0xfff00fff != 0xe3a00020:
                raise SystemExit(f'ov18 {at:#x}: {old:#010x} is not mov rN, #0x20')
            ov18.set_word(at, old & ~0xff | MENU_DECIDE_FRAMES)
        r.arm9.write(GAME_TEXT, trampoline(syms['pe_text_hook']), GAME_TEXT_HEAD)
    if fades:
        r.arm9.write(SET_BRIGHT, trampoline(syms['vm_bright']), SET_BRIGHT_HEAD)
    if think:
        struct.pack_into('<I', blob, syms['think_next_step'] - base,
                         ov3.hook(STEP_CALL, syms['think_step'], None, arm_site=True))
        ov3.hook(THINK_OFF_CALL, syms['think_stop'], THINK_OFF, arm_site=True)
        r.arm9.write(THINK_DELAY_CMP, bytes([THINK_DELAY, 0x2c]), bytes([0x3c, 0x2c]))
    if menus:
        struct.pack_into('<I', blob, syms['inspect_next_step'] - base,
                         ov3.hook(STEP_CALL, syms['inspect_step'], None, arm_site=True))
        ov3.hook(0x0214604c, syms['inspect_field'], 0x0216d624, arm_site=True)
    if cutin:
        ov3.hook(CUTIN_REQUEST_CALL, syms['cutin_request'], CUTIN_SETUP, arm_site=True)
        from w11speed import arm_blx
        ov3.write(CUTIN_RESTORED, arm_blx(CUTIN_RESTORED, syms['cutin_restored'] & ~1) + struct.pack('<4I', *[ARM_NOP] * 4),
                  CUTIN_RESTORED_HEAD)
        r.arm9.hook(FRAME_CALL, syms['cutin_frame_start'], FRAME_UPDATE)
    if display:
        from w11speed import arm_blx
        for at in SUMMON_BG_CLEARS:
            ov3.set_word(at, SUMMON_BG_CLEAR, SUMMON_BG_CLEAR_OLD)
        for at, old in MATERIAL_DRAW_CALLS:
            ov3.write(at, arm_blx(at, syms['material_draw'] & ~1), struct.pack('<I', old))
        r.arm9.bl(PANEL_FRAME_LOAD, syms['panel_frame_hold'] & ~1, GFX_LOAD)
        r.arm9.bl(PANEL_FRAME_FREE, syms['panel_frame_free'] & ~1, HEAP_FREE)
        r.arm9.set_word(PANEL_JOB_DONE, syms['panel_job_done'], PANEL_JOB_FREE)
        r.arm9.bl(JOB_UPLOAD_CALL, syms['panel_job_upload'] & ~1, GFX_LOAD)
    ov3.set_word(DUEL_STEPS + 8, syms['vm_loop'])
    ov3.set_word(DUEL_STEPS + 12, syms['vm_exit'])
    r.extra.append((bytes(blob), base))
    return syms


def apply_fixes(r, work, cards=True, duel=True):
    """Base-game bug fixes shared with Dimension Break (mod/w11fix): code in main RAM below the arena top."""
    work = os.path.join(work, 'w11fix')
    srcs, asms = [], []
    if cards:
        srcs += ['fix_cards.c', 'fix_cpu.c', 'qol/fix_qol.c']
        asms += ['w11fix_cards.asm', 'qol/fix_qol.asm']
    if duel:
        srcs.append('fix_duel.c')
        asms.append('w11fix_duel.asm')
    srcs = [os.path.join(FIX_SRC, f) for f in srcs]
    hi = r.arm9.word(ARENA_HI_LIT)
    if hi > ARENA_HI or hi & 0xff:
        raise SystemExit(f'arm9 arena top {hi:#x}: not the stock {ARENA_HI:#x} or a block base below it')
    blob, _ = compile_code(work, FIX_SRC, 'w11fix', hi - 0x4000, hi, srcs=srcs)
    base = (hi - len(blob)) & ~0xff
    blob, syms = compile_code(work, FIX_SRC, 'w11fix', base, hi, srcs=srcs)
    blob += bytes(-len(blob) % 4)
    r.arm9.set_word(ARENA_HI_LIT, base, hi)
    mods = {f'ov{i:02d}.bin': img for i, img in r.ov.items()}
    for name, img in mods.items():
        with open(os.path.join(work, name), 'wb') as f:
            f.write(img.d)
    with open(os.path.join(work, 'symbols.asm'), 'w') as f:
        for name, addr in sorted(syms.items()):
            f.write(f'.definelabel {name}, {addr & ~1:#x}\n.definelabel {name}_ptr, {addr:#x}\n')
    top = os.path.join(work, 'w11fix_top.asm')
    with open(top, 'w') as f:
        f.write('.nds\n.thumb\n.include "symbols.asm"\n' +
                ''.join(f'.include "{os.path.join(FIX_SRC, a)}"\n' for a in asms))
    run([inject.ARMIPS, top, '-root', work])
    for name, img in mods.items():
        with open(os.path.join(work, name), 'rb') as f:
            new = f.read()
        if len(new) != len(img.d):
            raise SystemExit(f'w11fix: {name} changed size')
        img.d[:] = new
    r.extra.append((bytes(blob), base))
    return syms


def apply(r, work, speed=True, view=True, genre_cache=True, cutin=True, fades=True, sound=True,
          card_fixes=True, text_fixes=True, duel_fixes=True, display=True):
    """Patch a w11speed.Rom11 (arm9 and overlay images plus extra arm9 autoload sections) in place.
    duel_fixes go with view (the QoL option); card_fixes also fix card text, text_fixes the other text errors."""
    apply_apfix(r)
    inject.move_arena_hi(r.arm9.d, r.arm9.base, 'BYYP')
    syms = apply_speed(r, work, genre_cache=genre_cache) if speed else {}
    if view or fades or cutin or display:
        syms.update(apply_view(r, work, think=speed, cutin=cutin, menus=view, fades=fades, display=display))
    if card_fixes or (view and duel_fixes):
        syms.update(apply_fixes(r, work, cards=card_fixes, duel=view and duel_fixes))
    if card_fixes or text_fixes:
        import w11textfix
        w11textfix.apply(r.rom, card=card_fixes, text=text_fixes)
    if sound:
        import w11sound
        w11sound.fix_se_room(r.rom)
    return syms


def apply_apfix(r):
    for at, old, new in ((AP_STUBS, AP_STUBS_OLD, AP_STUBS_NEW), (AP_HOOK, AP_HOOK_OLD, AP_HOOK_NEW)):
        o = r.arm9.o(at)
        if bytes(r.arm9.d[o:o + len(new)]) != new:
            r.arm9.write(at, new, old)


def apply_speed(r, work, genre_cache=True):
    blob, syms = compile_code(work)
    blob = bytearray(blob)
    struct.pack_into('<I', blob, syms['genre_count'] - CODE_BASE, record_count(r.rom, 'CARD_Genre.bin') if genre_cache else 0)
    itcm = next((sec for sec in r.code.sections if sec.ramAddress == ITCM), None)
    if itcm is None or ITCM + len(itcm.data) + itcm.bssSize != CODE_BASE:
        raise SystemExit(f'arm9: ITCM autoload does not end at {CODE_BASE:#x}; already patched?')
    end = (CODE_BASE + len(blob) + 31) & ~31
    r.arm9.set_word(ITCM_ARENA_LO_LIT, end, CODE_BASE)
    itcm.data = bytes(itcm.data) + bytes(blob)
    r.arm9.write(PROP_LOOKUP, trampoline(syms['prop_hook']), PROP_LOOKUP_HEAD)
    r.arm9.write(FRAME_GET, trampoline(syms['frame_hook']), FRAME_GET_HEAD)
    r.arm9.write(GENRE_READ, trampoline(syms['genre_hook']), GENRE_READ_HEAD)
    r.arm9.write(COPY, struct.pack('<II', 0xe51ff004, syms['copy_hook']), COPY_HEAD)
    r.arm9.bl(HEAP_CREATE_CALL, syms['fast_heap_create'] & ~1, HEAP_CREATE)
    ov3 = r.ov[3]
    ov3.set_word(DUEL_STEPS + 4, syms['fast_setup'], DUEL_SETUP)
    ov3.set_word(DUEL_STEPS + 12, syms['fast_exit'], DUEL_EXIT)
    for site, name, old, arm in ((STEP_CALL, 'fast_step', ENGINE_STEP, True),
                                 (MAIN_CALL, 'fast_main_phase', CPU_MAIN, False),
                                 (CHAIN_CALL, 'fast_chain', CPU_CHAIN, False),
                                 (TRIG_CALL, 'fast_trigger', CPU_TRIG, False)):
        cur = ov3.target(site, arm)
        if cur is None or cur & ~1 != old:
            raise SystemExit(f'ov03 {site:#x}: expected a call to {old:#x}, found {cur and hex(cur)}')
        ov3.hook(site, syms[name], old, arm_site=arm)
    ov3.write(ZONE_ID, trampoline(syms['zone_card_id']), ZONE_ID_HEAD)
    ov3.set_word(ZONE_ID - 4, syms['zone_card_id'], ZONE_ID | 1)
    return syms


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def work_dir(out):
    return os.path.join(ROOT, 'build', 'w11fast', os.path.splitext(os.path.basename(out))[0])


def cmd_build(a):
    import w11speed
    import patch
    got = sha1(a.rom)
    if got != EU_SHA1:
        raise SystemExit(f'{a.rom}: sha1 {got}, not the WC2011 EU dump this patch is made for '
                         f'(Yu-Gi-Oh! 5D\'s World Championship 2011: Over the Nexus, Europe, BYYP, sha1 {EU_SHA1})')
    r = w11speed.Rom11(a.rom)
    apply(r, work_dir(a.out), speed=not a.view_only, genre_cache=not a.no_genre_cache, cutin=not a.no_cutin_fix,
          display=not a.no_display_fixes,
          card_fixes=not (a.no_card_fixes or a.view_only), text_fixes=not (a.no_text_fixes or a.view_only),
          duel_fixes=not (a.no_duel_fixes or a.view_only))
    r.save(a.out, compress=True)
    print(f'{a.out}: patched')
    if a.bps:
        with open(a.rom, 'rb') as f:
            src = f.read()
        with open(a.out, 'rb') as f:
            tgt = f.read()
        bps, _ = patch.create(src, tgt)
        if patch.apply(src, bps) != tgt:
            raise SystemExit('internal error: the BPS patch does not rebuild the patched ROM; nothing written')
        with open(a.bps, 'wb') as f:
            f.write(bps)
        print(f'{a.bps}: {len(bps)} B, source sha1 {EU_SHA1}, target sha1 {hashlib.sha1(tgt).hexdigest()}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rom', help='stock WC2011 EU ROM (.nds)')
    ap.add_argument('out', help='patched ROM')
    ap.add_argument('--bps', help='also write a BPS patch from the stock ROM to the patched one')
    ap.add_argument('--no-genre-cache', action='store_true',
                    help='use stock genre reads, preserving duel heap for animation in large mods')
    ap.add_argument('--no-cutin-fix', action='store_true',
                    help='leave out the battle cut-in green band fix (Dimension Break carries its own)')
    ap.add_argument('--no-display-fixes', action='store_true',
                    help='leave out the Fusion/Synchro animation and card panel display fixes (Dimension Break carries its own)')
    ap.add_argument('--no-card-fixes', action='store_true',
                    help='leave out the card effect fixes and their card text (Dimension Break builds its own from mod/w11fix)')
    ap.add_argument('--no-text-fixes', action='store_true',
                    help='leave out the text error fixes (Dimension Break applies them in its own text build)')
    ap.add_argument('--no-duel-fixes', action='store_true',
                    help='leave out Final Attack, Rental Deck Key Card and skin colour fixes (Dimension Break builds its own)')
    ap.add_argument('--view-only', action='store_true',
                    help='tests only: View Mode without the speed patches or the thinking-bubble change (stock CPU timing, '
                         'same spectator view)')
    a = ap.parse_args()
    cmd_build(a)


if __name__ == '__main__':
    main()
