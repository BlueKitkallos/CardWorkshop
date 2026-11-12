import concurrent.futures
import glob
import re
import os
import pathlib
import shutil
import struct
import subprocess
import sys

import ndspy._lzCommon
import ndspy.code

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buildwarn
import cardword
import pac
import stepcache

LZ = ndspy.code.codeCompression
LZ.compress = stepcache.Items('code-lz', code=(LZ.__file__, ndspy._lzCommon.__file__)).cached(LZ.compress)

CARDWORD_SITES = os.path.join(HERE, 'engine', 'cardword_sites.txt')
CARDWORD_ALLOW = os.path.join(HERE, 'engine', 'cardword_allow.txt')

TOOLCHAIN = os.path.expanduser(os.environ.get('ARM_TOOLCHAIN', '~/tools/arm-gnu-toolchain/bin'))
ARMIPS = os.path.expanduser(os.environ.get('ARMIPS', '~/tools/bin/armips'))
CODE_BASE = 0x022d10c0
ARENA_LO_LITERAL = 0x020a6538
CFLAGS = ['-mcpu=arm946e-s', '-mthumb', '-mthumb-interwork', '-Os', '-ffreestanding', '-nostdlib',
          '-fno-builtin', '-Wall', '-Werror']
MENU_LIST = 'menu_overlay.txt'
SOUND_INDEX = 'SOUND_INDEX'
DUEL_ARCHIVE, DUEL_FILE = 'Data_arc_pac/bin2.pac', 'fx11.bin'


def run(cmd, **kw):
    if os.name == 'nt' and not os.path.exists(cmd[0]) and os.path.exists(cmd[0] + '.exe'):
        cmd = [cmd[0] + '.exe', *cmd[1:]]
    if not os.path.exists(cmd[0]):
        raise SystemExit(f'{cmd[0]} not found: install the ARM toolchain / armips and set ARM_TOOLCHAIN or ARMIPS '
                         '(see tools/README.md)')
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f'{" ".join(cmd)}\n{r.stdout}{r.stderr}')
    return r.stdout


def write_engine_ld(work, labels=os.path.join(HERE, 'engine', 'labels.txt')):
    lines = []
    funcs = ['    .syntax unified\n']
    with open(labels) as f:
        for line in f:
            p = line.split()
            if not p or p[0].startswith('#'):
                continue
            addr = int(p[0], 16)
            if p[2] == 't':
                funcs.append(f'    .global {p[1]}\n    .thumb_set {p[1]}, {addr:#010x}\n')
            elif p[2] == 'a':
                funcs.append(f'    .global {p[1]}\n    .type {p[1]}, %function\n    .set {p[1]}, {addr:#010x}\n')
            else:
                lines.append(f'{p[1]} = {addr:#010x};\n')
    with open(os.path.join(work, 'engine.ld'), 'w') as f:
        f.writelines(lines)
    with open(os.path.join(work, 'engine_syms.S'), 'w') as f:
        f.writelines(funcs)


class Options:
    def __init__(self, lto=False, menu_base=None, menu_size=0, bss_windows=(), code_spans=()):
        self.lto, self.menu_base, self.menu_size, self.menu_overlay = lto, menu_base, menu_size, None
        self.bss_windows, self.bss_layout, self.defines = list(bss_windows), None, []
        self.bank_layout = None
        self.code_spans, self.span_layout = list(code_spans), None
        self.defsyms = {}


def menu_sources(src):
    path = os.path.join(src, MENU_LIST)
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        names = {line.strip() for line in f if line.strip()}
    return {n for n in names if os.path.exists(os.path.join(src, n))}


def hook_names(src):
    names = set()
    for path in glob.glob(os.path.join(src, '*.asm')):
        with open(path) as f:
            names.update(re.findall(r'[A-Za-z_]\w*', f.read()))
    return names | {n[:-4] for n in names if n.endswith('_ptr')}


def compile_objects(src, work, opts):
    sources = sorted(glob.glob(os.path.join(src, '*.c')) + glob.glob(os.path.join(src, '*.S')))
    if not sources:
        return None
    objdir = os.path.join(work, 'obj')
    shutil.rmtree(objdir, ignore_errors=True)
    os.makedirs(objdir)
    gcc = os.path.join(TOOLCHAIN, 'arm-none-eabi-gcc')
    menu = menu_sources(src)
    jobs = []
    for s in sources + [os.path.join(work, 'engine_syms.S')]:
        name = os.path.basename(s)
        lto = ['-flto'] if opts.lto and s.endswith('.c') and name not in menu else []
        if opts.bss_windows and name not in menu:
            lto += ['-fdata-sections', '-ffunction-sections']
        obj = os.path.join(objdir, name + '.o')
        jobs.append((obj, [gcc, *CFLAGS, *opts.defines, *lto, '-I', os.path.join(HERE, 'engine'), '-I', src, '-c', s, '-o', obj]))
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        list(pool.map(lambda job: run(job[1]), jobs))
    objs = [obj for obj, _ in jobs]
    defined, data = set(), set()
    if opts.lto:
        nm = os.path.join(TOOLCHAIN, 'arm-none-eabi-gcc-nm')
        for line in run([nm, '--defined-only', '-g', *objs[:-1]]).splitlines():
            f = line.split()
            if len(f) == 3:
                defined.add(f[2])
                if f[1] in 'BCDGRSV':
                    data.add(f[2])
    roots = sorted(hook_names(src) & defined | data)
    menu_objs = [os.path.basename(o) for o in objs if os.path.basename(o)[:-2] in menu]
    return objs, roots, menu_objs


def write_menu_ld(work, menu_objs):
    with open(os.path.join(work, 'menu.ld'), 'w') as f:
        if not menu_objs:
            return
        code = ' '.join(f'*{name}(.text* .rodata* .data*)' for name in menu_objs)
        bss = ' '.join(f'*{name}(.bss* COMMON)' for name in menu_objs)
        f.write(f'  .menu MENU_BASE : {{ __menu_start = .; {code} . = ALIGN(4); }}\n'
                f'  .menu_bss (NOLOAD) : {{ __menu_bss_start = .; {bss} . = ALIGN(32); __menu_end = .; }}\n')


def write_bss_ld(work, windows, layout):
    with open(os.path.join(work, 'bss_mem.ld'), 'w') as f:
        if windows and layout is not None:
            f.write('MEMORY\n{\n' + ''.join(f'  bss_w{i} : ORIGIN = {lo:#x}, LENGTH = {hi - lo:#x}\n'
                                             for i, (lo, hi) in enumerate(windows)) + '}\n')
    with open(os.path.join(work, 'bss.ld'), 'w') as f:
        if not windows:
            f.write('  __bss_start = .;\n  .bss : { *(.bss*) *(COMMON) }\n  . = ALIGN(4);\n  __bss_end = .;\n')
            return
        f.write('  __bss_start = .;\n  __bss_end = .;\n')
        if layout is None:
            return
        for i, names in enumerate(layout):
            pats = ' '.join(f'*({n})' for n in names)
            f.write(f'  .bss_w{i} {windows[i][0]:#x} (NOLOAD) : {{ __bss_w{i}_start = .; {pats} . = ALIGN(4); __bss_w{i}_end = .; }} > bss_w{i}\n')
        f.write('  .bss_left (NOLOAD) : { *(.bss .bss.*) *(COMMON) }\n'
                '  ASSERT(SIZEOF(.bss_left) == 0, "bss left outside the Wi-Fi windows (inject.py pack_bss)")\n')


def probe_sections(elf):
    out = []
    for m in re.finditer(r'\]\s+(\.bss\S*|COMMON)\s+NOBITS\s+\S+\s+\S+\s+([0-9a-f]+)\s+\S+\s+\S*\s+\d+\s+\d+\s+(\d+)$',
                         run([os.path.join(TOOLCHAIN, 'arm-none-eabi-readelf'), '-SW', elf]), re.M):
        if int(m.group(2), 16):
            out.append((m.group(1), int(m.group(2), 16), int(m.group(3))))
    if any(name == 'COMMON' for name, _, _ in out):
        raise SystemExit('COMMON symbols cannot be placed in the bss windows: compile with -fno-common')
    return out


def pack_bss(sections, windows):
    free = [lo for lo, _ in windows]
    layout = [[] for _ in windows]
    for name, size, align in sorted(sections, key=lambda s: (-s[1], s[0])):
        for i, (lo, hi) in enumerate(windows):
            at = (free[i] + align - 1) & -align
            if at + size <= hi:
                layout[i].append(name)
                free[i] = at + size
                break
        else:
            total = sum(s for _, s, _ in sections)
            raise SystemExit(f'bss {total} B does not fit the idle Wi-Fi windows ({sum(hi - lo for lo, hi in windows)} B, '
                             f'"bss_windows" in the game profile): {name} ({size} B) has no room left')
    return layout


def readonly_sections(map_path, code_base, taken=()):
    """Collect resident const data and explicitly bankable function sections."""
    with open(map_path) as f:
        content = f.read()
    totals = {}
    for name, address, size in re.findall(r'^ (\.rodata\S*|\.text\.bank\S*|\.text\.tear_step_call|\.text\.tear_pick_best|\.text\.tear_reset_clear)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)', content, re.M):
        if int(address, 16) >= code_base and f'*({name})' not in taken:
            totals[name] = totals.get(name, 0) + int(size, 16)
    return [(name, size, 4) for name, size in totals.items() if size]


def resident_sections(map_path, code_base):
    """Input sections of the resident region as (linker pattern, size): LTO sections by name, others by file."""
    with open(map_path) as f:
        content = f.read()
    totals = {}
    for name, address, size, path, before in re.findall(
            r'^ (\.(?:text|rodata|data)\S*)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*?)[ \t]*\n'
            r'(?:[ \t]+0x([0-9a-f]+) \(size before relaxing\)\n)?', content, re.M):
        size = max(int(size, 16), int(before or '0', 16))
        if int(address, 16) < code_base or not size or '.resident' in name:
            continue
        lib = re.fullmatch(r'.*/(lib\w+\.a)\((\S+\.o)\)', path)
        if lib:
            pat = f'*{lib.group(1)}:{lib.group(2)}({name})'
        elif path.endswith('.lto.o') or '.ltrans' in path:
            if name in ('.text', '.rodata', '.data'):
                continue
            pat = f'*({name})'
        elif path.endswith('.o'):
            pat = f'*/{os.path.basename(path)}({name})'
        else:
            continue
        totals[pat] = totals.get(pat, 0) + size
    return [(pat, (size + 3) & ~3) for pat, size in totals.items()]


def pack_spans(sections, spans, reserve=128):
    free = [lo for lo, _ in spans]
    layout = [[] for _ in spans]
    for pat, size in sorted(sections, key=lambda s: (-s[1], s[0])):
        for i, (_, hi) in enumerate(spans):
            if free[i] + size <= hi - reserve:
                layout[i].append(pat)
                free[i] += size
                break
    return layout


def write_spans_ld(work, spans, layout):
    with open(os.path.join(work, 'spans_mem.ld'), 'w') as f:
        if spans and layout:
            f.write('MEMORY\n{\n' + ''.join(f'  span{i} : ORIGIN = {lo:#x}, LENGTH = {hi - lo:#x}\n'
                                             for i, (lo, hi) in enumerate(spans)) + '}\n')
    with open(os.path.join(work, 'spans.ld'), 'w') as f:
        for i, pats in enumerate(layout or []):
            if pats:
                f.write(f'  .span{i} {spans[i][0]:#x} : {{ __span{i}_start = .; {" ".join(pats)} . = ALIGN(4); '
                        f'__span{i}_end = .; }} > span{i}\n')


def pack_readonly(sections, windows, bss_sections, bss_layout, reserve=64):
    """Use only the free suffixes of proven idle windows, after their BSS."""
    sizes = {name: (size, align) for name, size, align in bss_sections}
    free = [lo for lo, _ in windows]
    for i, names in enumerate(bss_layout):
        for name in names:
            size, align = sizes[name]
            free[i] = ((free[i] + align - 1) & -align) + size
        free[i] = (free[i] + 3) & ~3
    starts = free[:]
    layout = [[] for _ in windows]
    for name, size, align in sorted(sections, key=lambda s: (-s[1], s[0])):
        for i, (_, hi) in enumerate(windows):
            at = (free[i] + align - 1) & -align
            if at + size <= hi - reserve:
                layout[i].append(name)
                free[i] = at + size
                break
    return [(starts[i], names) for i, names in enumerate(layout)]


def write_banks_ld(work, layout, windows=()):
    with open(os.path.join(work, 'banks.ld'), 'w') as f:
        for i, (start, names) in enumerate(layout or []):
            if not names:
                continue
            pats = ' '.join(f'*({name})' for name in names)
            f.write(f'  .bank{i} {start:#x} : {{ __bank{i}_start = .; {pats} . = ALIGN(4); __bank{i}_end = .; }}\n')
            f.write(f'  ASSERT(__bss_w{i}_end <= __bank{i}_start, "initialized bank overlaps BSS")\n')
            if windows:
                f.write(f'  ASSERT(__bank{i}_end <= {windows[i][1]:#x}, "initialized bank exceeds idle window")\n')


def code_section(blob, address, bss):
    pad = -len(blob) % 4
    return ndspy.code.MainCodeFile.Section(bytes(blob) + bytes(pad), address, max(bss - pad, 0))


def add_initialized_banks(arm9, banks):
    """Native crt0 copies autoloads before clearing static BSS: exclude banks.

    Replace static BSS clearing with zero-length autoloads for the exact same
    intervals minus initialized banks. ndspy writes zero autoloads after copies.
    """
    if not banks:
        return
    if arm9.codeSettingsOffs is None:
        raise SystemExit('initialized banks require ARM9 module parameters')
    main = arm9.sections[0]
    offset = arm9.codeSettingsOffs
    lo, hi = struct.unpack_from('<II', main.data, offset + 12)
    cursor = lo
    zero_ranges = []
    for address, data in sorted(banks):
        end = address + len(data)
        if address < cursor or end > hi:
            raise SystemExit(f'initialized bank {address:#x}-{end:#x} is outside static BSS or overlaps a bank')
        if address > cursor:
            zero_ranges.append((cursor, address - cursor))
        arm9.sections.append(ndspy.code.MainCodeFile.Section(data, address, 0))
        cursor = end
    if cursor < hi:
        zero_ranges.append((cursor, hi - cursor))
    for address, size in reversed(zero_ranges):
        arm9.sections.append(ndspy.code.MainCodeFile.Section(b'', address, size))
    # The last zero autoload may erase the table only after its final entry
    # has been read. Keep all autoload data/table below the first bank.
    file_bytes = sum((len(section.data) + 3) & ~3 for section in arm9.sections)
    entries = sum(not section.implicit for section in arm9.sections)
    if arm9.ramAddress + file_bytes + entries * 12 > min(address for address, _ in banks):
        raise SystemExit('initialized-bank copy table must precede the first bank')
    struct.pack_into('<I', main.data, offset + 12, hi)


def link_blob(work, built, code_base, opts):
    objs, roots, menu_objs = built
    gcc = os.path.join(TOOLCHAIN, 'arm-none-eabi-gcc')
    elf = os.path.join(work, 'code.elf')
    write_menu_ld(work, menu_objs)
    write_spans_ld(work, opts.code_spans, opts.span_layout)
    write_banks_ld(work, opts.bank_layout, opts.bss_windows)
    flags = [*CFLAGS, f'-Wl,--defsym=CODE_BASE={code_base:#x}', *(f'-Wl,--defsym={k}={v:#x}' for k, v in opts.defsyms.items())]
    if opts.bss_windows:
        flags += ['-fdata-sections', '-ffunction-sections']
    if menu_objs:
        flags += [f'-Wl,--defsym=MENU_BASE={opts.menu_base:#x}', f'-Wl,--defsym=MENU_OVERLAY={opts.menu_overlay}']
    if opts.lto:
        flags += ['-flto', '-flto-partition=none', *(f'-Wl,--undefined={r}' for r in roots)]
    cmd = [gcc, *flags, '-Wl,-L,' + work, '-Wl,-T', os.path.join(HERE, 'engine', 'link.ld'),
           '-Wl,-Map=' + os.path.join(work, 'code.map'), '-o', elf, *objs, '-lgcc']
    if opts.bss_windows and opts.bss_layout is None:
        write_bss_ld(work, opts.bss_windows, None)
        run(cmd)
        bss_sections = probe_sections(elf)
        opts.bss_layout = pack_bss(bss_sections, opts.bss_windows)
        taken = set()
        if opts.code_spans:
            opts.span_layout = pack_spans(resident_sections(os.path.join(work, 'code.map'), code_base), opts.code_spans)
            taken = {pat for pats in opts.span_layout for pat in pats}
            write_spans_ld(work, opts.code_spans, opts.span_layout)
        rodata = readonly_sections(os.path.join(work, 'code.map'), code_base, taken)
        opts.bank_layout = pack_readonly(rodata, opts.bss_windows, bss_sections, opts.bss_layout)
        write_banks_ld(work, opts.bank_layout, opts.bss_windows)
    write_bss_ld(work, opts.bss_windows, opts.bss_layout)
    run(cmd)
    with open(os.path.join(work, 'code.map')) as f:
        empty = re.findall(r'^ \.text\.unlikely(?:\.\S+)?\n\s+0x[0-9a-f]+\s+0x0 \S+\n\s+0x[0-9a-f]+\s+(\w+)$', f.read(), re.M)
    if empty:
        raise SystemExit(f'{", ".join(empty)}: compiled to an empty function (GCC proved its body unreachable, '
                         'usually a call through a constant address cast to a function pointer); call the address directly')
    objcopy = os.path.join(TOOLCHAIN, 'arm-none-eabi-objcopy')
    binf = os.path.join(work, 'code.bin')
    run([objcopy, '-O', 'binary', '-j', '.text', '-j', '.data', elf, binf])
    run([objcopy, '-O', 'binary', '-j', '.fxfile', elf, os.path.join(work, 'fx.bin')])
    menu_blob = None
    if menu_objs:
        menu_bin = os.path.join(work, 'menu.bin')
        run([objcopy, '-O', 'binary', '-j', '.menu', elf, menu_bin])
        with open(menu_bin, 'rb') as f:
            menu_blob = f.read()
    banks = []
    for i, (start, names) in enumerate(opts.bank_layout or []):
        if not names:
            continue
        bank_bin = os.path.join(work, f'bank{i}.bin')
        run([objcopy, '-O', 'binary', '-j', f'.bank{i}', elf, bank_bin])
        with open(bank_bin, 'rb') as f:
            data = f.read()
            lo, hi = opts.bss_windows[i]
            if start < lo or start + len(data) > hi:
                raise SystemExit(f'initialized bank {i} exceeds reserved idle window after linker padding/veneers')
            banks.append((start, data))
    spans = []
    for stale in glob.glob(os.path.join(work, 'span*.bin')):
        os.remove(stale)
    for i, pats in enumerate(opts.span_layout or []):
        if not pats:
            continue
        span_bin = os.path.join(work, f'span{i}.bin')
        run([objcopy, '-O', 'binary', '-j', f'.span{i}', elf, span_bin])
        with open(span_bin, 'rb') as f:
            data = f.read()
        lo, hi = opts.code_spans[i]
        if len(data) > hi - lo:
            raise SystemExit(f'code span {i} {lo:#x}-{hi:#x}: {len(data)} B linked, {hi - lo} B of room')
        spans.append((lo, data))
    return elf, binf, menu_blob, banks, spans


def compile_blob(src, work, code_base=CODE_BASE, opts=None, built=None):
    os.makedirs(work, exist_ok=True)
    opts = opts or Options()
    built = built or compile_objects(src, work, opts)
    if built is None:
        return None
    elf, binf, menu_blob, banks, spans = link_blob(work, built, code_base, opts)
    syms = {}
    funcs = set()
    for line in run([os.path.join(TOOLCHAIN, 'arm-none-eabi-readelf'), '-sW', elf]).splitlines():
        f = line.split()
        if len(f) == 8 and f[0].endswith(':') and f[4] in ('GLOBAL', 'LOCAL') and f[3] in ('FUNC', 'OBJECT', 'NOTYPE'):
            if not f[7].startswith('$'):
                syms[f[7]] = int(f[1], 16)
                if f[3] == 'FUNC':
                    funcs.add(f[7])
    lost = [r for r in built[1] if r not in syms]
    if lost:
        raise SystemExit(f'{", ".join(lost)}: named in the hooks but dropped by the link')
    with open(binf, 'rb') as f:
        blob = f.read()
    bss = syms['__bss_end'] - syms['__bss_start']
    return Blob(blob, bss, syms, funcs, built, menu_blob, banks, spans)


class Blob:
    def __init__(self, code, bss, syms, funcs, built, menu, banks=(), spans=()):
        self.code, self.bss, self.syms, self.funcs, self.built, self.menu = code, bss, syms, funcs, built, menu
        self.banks, self.spans = list(banks), list(spans)

    def span_report(self, spans):
        if not spans:
            return ''
        used = sum(len(data) for _, data in self.spans)
        return (f'; code spans {used} B in the arm9 Wi-Fi code ('
                + ', '.join(f'{sum(len(d) for a, d in self.spans if a == lo)} / {hi - lo} at {lo:#x}' for lo, hi in spans)
                + f', {sum(hi - lo for lo, hi in spans) - used} B free)')

    def window_use(self):
        s, out, i = self.syms, [], 0
        while f'__bss_w{i}_start' in s:
            out.append((s[f'__bss_w{i}_start'], s[f'__bss_w{i}_end'] - s[f'__bss_w{i}_start']))
            i += 1
        return out

    def window_report(self, windows):
        use = self.window_use()
        if not use:
            return ''
        used = sum(n for _, n in use) + sum(len(data) for _, data in self.banks)
        return (f'; bss and initialized banks {used} B in the idle Wi-Fi windows ('
                + ', '.join(f'{n} zero + {sum(len(data) for address, data in self.banks if lo <= address < hi)} initialized / {hi - lo} at {lo:#x}' for (_, n), (lo, hi) in zip(use, windows))
                + f', {sum(hi - lo for lo, hi in windows) - used} B free)')

    def menu_layout(self):
        s = self.syms
        return s['__menu_start'], s['__menu_bss_start'] - s['__menu_start'], s['__menu_end'] - s['__menu_bss_start']


def grow_overlays(ovs, work):
    grown = []
    with open(os.path.join(work, 'hooks.sym')) as f:
        for line in f:
            m = re.fullmatch(r'([0-9a-f]{8}) ov(\d+)_bss_end', line.strip().lower())
            if not m:
                continue
            i, end = int(m.group(2)), int(m.group(1), 16)
            ov = ovs[i]
            bss = end - ov.ramAddress - ov.ramSize
            if bss < ov.bssSize:
                raise SystemExit(f'ov{i:02d}_bss_end {end:#x} is below the end of ov{i:02d} '
                                 f'({ov.ramAddress + ov.ramSize + ov.bssSize:#x})')
            if bss != ov.bssSize:
                ov.bssSize = bss
                grown.append(i)
    return grown


def armips_patch(rom, arm9, src, work, syms, funcs, widen=True):
    hooks = os.path.join(src, 'hooks.asm')
    if not os.path.exists(hooks):
        return set()
    ovs = rom.loadArm9Overlays()
    files = {'arm9.bin': arm9.sections[0].data}
    for i, ov in ovs.items():
        files[f'ov{i:02d}.bin'] = ov.data
    orig = dict(files)
    if widen:
        widened = {name: bytearray(files[name]) for name in cardword.BASES if name in files}
        cardword.apply(widened, cardword.load_sites(CARDWORD_SITES))
        files.update(widened)
    for name, data in files.items():
        with open(os.path.join(work, name), 'wb') as f:
            f.write(data)
    for inc in glob.glob(os.path.join(src, '*.asm')):
        shutil.copy(inc, work)
    with open(os.path.join(work, 'symbols.asm'), 'w') as f:
        for name, addr in sorted(syms.items()):
            if name.replace('_', '').isalnum():
                f.write(f'.definelabel {name}, {addr & ~1 if name in funcs else addr:#x}\n.definelabel {name}_ptr, {addr:#x}\n')
    run([ARMIPS, os.path.abspath(hooks), '-root', work, '-sym', 'hooks.sym'])
    changed = set()
    scanned = {}
    for name, data in orig.items():
        with open(os.path.join(work, name), 'rb') as f:
            new = f.read()
        if widen and name in cardword.BASES:
            scanned[name] = bytearray(new)
        if new == bytes(data):
            continue
        changed.add(name)
        if name == 'arm9.bin':
            arm9.sections[0].data = bytearray(new)
        else:
            ov = ovs[int(name[2:4])]
            ov.data = bytearray(new)
            rom.files[ov.fileID] = ov.save(compress=False)
    grown = grow_overlays(ovs, work)
    if grown or any(n != 'arm9.bin' for n in changed):
        rom.arm9OverlayTable = ndspy.code.saveOverlayTable(ovs)
    if widen:
        for sec in arm9.sections[1:]:
            if sec.ramAddress == cardword.BASES['itcm.bin']:
                scanned['itcm.bin'] = bytearray(sec.data)
        cardword.check(scanned, cardword.load_allow(CARDWORD_ALLOW))
    return changed


def arena_hi(code):
    """(address, start value) of the word a game with "arena_hi_patch" reads its arena top from."""
    import game
    inj = game.load(code)['injection']
    return int(inj['arena_hi_literal'], 16), int(inj['arena_hi_patch']['top'], 16)


def move_arena_hi(data, ram, code):
    """Apply the profile's "arena_hi_patch" to the arm9 image: the game reads its arena top from "arena_hi_literal",
    and the stock literal keeps its value for the loaders that look it up and lower it."""
    import game
    inj = game.load(code)['injection']
    if 'arena_hi_patch' not in inj:
        return
    lit, top = arena_hi(code)
    rows = [tuple(int(x, 16) for x in row) for row in inj['arena_hi_patch']['words']]
    have = {at: struct.unpack_from('<I', data, at - ram)[0] for at, _, _ in rows}
    if all(have[at] == old for at, old, _ in rows):
        for at, _, new in rows:
            struct.pack_into('<I', data, at - ram, new)
        return
    wrong = [at for at, _, new in rows if at != lit and have[at] != new]
    if wrong or have[lit] > top:
        raise SystemExit(f'{code}: the arena top code is neither stock nor patched '
                         f'({", ".join(f"{at:#x} holds {have[at]:#x}" for at in wrong or [lit])}); '
                         f'a ROM built before the arena top moved cannot be patched again, start from the clean ROM')


EXTRA_DEFINES = []


def injection(code, use_windows=True):
    import game
    prof = game.load(code)
    inj = prof.get('injection')
    if not inj:
        raise SystemExit(f'{code}: code injection is not mapped for this game (no "injection" in its profile)')
    lit = {k: int(inj[k], 16) for k in ('arena_lo_literal', 'arena_hi_literal') if k in inj}
    if len(lit) != 1:
        raise SystemExit(f'{code}: the injection profile names one of arena_lo_literal, arena_hi_literal')
    menu = inj.get('menu_overlay', {})
    flag = inj.get('bss_windows_flag')
    on = use_windows and (flag is None or os.environ.get(flag, '1') != '0')
    windows = [tuple(int(x, 16) for x in w.split('-')) for w in inj.get('bss_windows', [])] if on else []
    spans = [tuple(int(x, 16) for x in w.split('-')) for w in inj.get('code_spans', [])] if on else []
    opts = Options(inj.get('lto', False), int(menu['base'], 16) if menu else None, int(menu['size'], 16) if menu else 0,
                   windows, spans)
    if flag:
        opts.defines.append(f'-D{flag}={int(on)}')
    opts.defines += EXTRA_DEFINES
    return (int(inj['code_base'], 16), lit, os.path.join(HERE, '..', inj['engine_labels']),
            inj.get('widen_card_words', False), opts)


def add_menu_overlay(rom, blob, opts):
    start, size, bss = blob.menu_layout()
    if start != opts.menu_base or size != len(blob.menu):
        raise SystemExit(f'menu overlay linked at {start:#x} ({size} B), expected {opts.menu_base:#x} ({len(blob.menu)} B)')
    if size + bss > opts.menu_size:
        raise SystemExit(f'menu overlay {size} B + bss {bss} B = {size + bss} B does not fit the {opts.menu_size}-byte '
                         f'region at {start:#x} ("menu_overlay" in the game profile)')
    ovs = rom.loadArm9Overlays()
    rom.files.append(bytes(blob.menu))
    end = start + size
    ovs[opts.menu_overlay] = ndspy.code.Overlay(bytes(blob.menu), start, size, bss, end, end, len(rom.files) - 1, 0, 0)
    rom.arm9OverlayTable = ndspy.code.saveOverlayTable(ovs)
    return f'; menu overlay {opts.menu_overlay}: {size} bytes + {bss} bss at {start:#x}'


def sound_index_bytes(rom, src):
    if not any(SOUND_INDEX in pathlib.Path(p).read_text() for p in glob.glob(os.path.join(src, '*.S')) + glob.glob(os.path.join(src, '*.asm'))):
        return 0
    sys.path.insert(0, os.path.join(HERE, 'wc2011'))
    import w11sound
    return (w11sound.index_size(rom.getFileByName(w11sound.SDAT_PATH), rom.getFileByName(w11sound.HED_PATH)) + 0xff) & ~0xff


def add_duel_file(rom, work, code_base, inj_heap):
    with open(os.path.join(work, 'fx.bin'), 'rb') as f:
        data = f.read()
    if not data:
        return ''
    fid = rom.filenames.idOf(DUEL_ARCHIVE)
    entries = pac.files(rom.files[fid])
    entries[DUEL_FILE] = data
    rom.files[fid] = pac.build(entries)
    worst = struct.unpack_from('<I', data)[0]
    if inj_heap:
        heap = code_base - int(inj_heap['lo'], 16)
        if heap < inj_heap['need'] + worst + inj_heap['margin']:
            raise SystemExit(f'duel heap {heap} B at {code_base:#x} is under the measured need {inj_heap["need"]} B + the largest '
                             f'layer block {worst} B + the margin {inj_heap["margin"]} B: {inj_heap["need"] + worst + inj_heap["margin"] - heap} B '
                             f'over ("duel_heap" in the game profile; docs/findings/effect-layer-design.md section 23)')
    return f'; bin2/{DUEL_FILE} {len(data)} B, largest layer block {worst} B'


def apply(rom, src, work, code_floor=None, windows=True):
    os.makedirs(work, exist_ok=True)
    import game
    code_base, arena, labels, widen, opts = injection(game.for_rom(rom)['game_code'], windows)
    inj = game.load(game.for_rom(rom)['game_code'])['injection']
    duel_heap = inj.get('duel_heap') if code_floor is None else None
    if code_floor is not None:
        if code_floor > code_base:
            raise SystemExit(f'--code-floor {code_floor:#x} is above the profile\'s code_base {code_base:#x}')
        code_base = code_floor
    if menu_sources(src) and opts.menu_base is None:
        raise SystemExit(f'{MENU_LIST}: this game profile has no "menu_overlay" region')
    opts.menu_overlay = len(rom.arm9OverlayTable) // 32
    write_engine_ld(work, labels)
    arm9 = rom.loadArm9()
    main = arm9.sections[0]
    move_arena_hi(main.data, main.ramAddress, game.for_rom(rom)['game_code'])
    index = sound_index_bytes(rom, src)
    under, index_note = 0, ''
    if index:
        room = tuple(int(x, 16) for x in inj['sound_index_room'].split('-')) if 'sound_index_room' in inj else None
        if room and index <= room[1] - room[0]:
            at = room[0]
            index_note = f'; sound index {index} B at {at:#x} ({room[1] - room[0] - index} B left in the room up to {room[1]:#x})'
        else:
            if 'arena_hi_literal' not in arena:
                raise SystemExit(f'{SOUND_INDEX}: {index} B does not fit "sound_index_room" and this game profile has no '
                                 f'arena_hi_literal to put it under the arena top')
            under = index
            at = struct.unpack_from('<I', main.data, arena['arena_hi_literal'] - main.ramAddress)[0] - index
            index_note = f'; sound index {index} B at {at:#x} under the arena top'
            if room:
                buildwarn.warn(f'{SOUND_INDEX}: {index - room[1] + room[0]} B over the {room[1] - room[0]}-byte '
                               f'"sound_index_room" {room[0]:#x}-{room[1]:#x}, placed under the arena top; the duel '
                               'heap pays for it')
        opts.defsyms.update({SOUND_INDEX: at, f'{SOUND_INDEX}_SIZE': index})
    floor = code_base
    hints = stepcache.Items('inject-base', code=(__file__,))
    hint_key = hints.key(os.path.abspath(work), floor, under, sorted(opts.defsyms.items()))
    hint = hints.get(hint_key) if 'arena_hi_literal' in arena else None
    if hint and int(hint) >= floor:
        code_base = int(hint)
    built = compile_blob(src, work, code_base, opts)
    if built is None:
        if os.path.exists(os.path.join(src, 'hooks.asm')):
            arm9 = rom.loadArm9()
            changed = armips_patch(rom, arm9, src, work, {}, set(), widen)
            rom.arm9 = arm9.save(compress=True)
            print(f'no code; patched {sorted(changed)}')
        return
    if 'arena_hi_literal' in arena:
        top = struct.unpack_from('<I', main.data, arena['arena_hi_literal'] - main.ramAddress)[0] - under
        while True:
            base = (top - len(built.code) - built.bss) & ~0xff
            if base < floor:
                raise SystemExit(f'code {len(built.code)} B + bss {built.bss} B = {len(built.code) + built.bss} B does not fit the '
                                 f'{top - floor}-byte region {floor:#x}-{top:#x} below the arena top'
                                 f'{f" and the {under}-byte sound index" if under else ""} '
                                 f'({floor - base} B over; the region is "code_base" in the game profile)')
            if base == code_base:
                break
            code_base = base
            built = compile_blob(src, work, code_base, opts, built.built)
        hints.put(hint_key, str(code_base).encode())
    blob, bss = built.code, built.bss
    end = (code_base + len(blob) + bss + 0xff) & ~0xff
    if 'arena_lo_literal' in arena:
        lit = arena['arena_lo_literal'] - main.ramAddress
        old_lo = struct.unpack_from('<I', main.data, lit)[0]
        if old_lo != code_base:
            raise SystemExit(f'arena literal is {old_lo:#x}, expected {code_base:#x}')
        struct.pack_into('<I', main.data, lit, end)
        moved = f'arena lo -> {end:#x}{index_note}'
    else:
        lit = arena['arena_hi_literal'] - main.ramAddress
        old_hi = struct.unpack_from('<I', main.data, lit)[0]
        if end > old_hi - under:
            raise SystemExit(f'code + bss end at {end:#x}, past {old_hi - under:#x}: '
                             f'{end - old_hi + under} bytes over the {old_hi - under - code_base}-byte reserve')
        struct.pack_into('<I', main.data, lit, code_base)
        moved = (f'arena hi {old_hi:#x} -> {code_base:#x} (reserve sized from the code, {code_base - floor} B '
                 f'left in the region down to {floor:#x}){index_note}')
    if built.menu is not None:
        moved += add_menu_overlay(rom, built, opts)
    moved += add_duel_file(rom, work, code_base, duel_heap)
    arm9.sections.append(code_section(blob, code_base, bss))
    for address, data in built.spans:
        at = address - main.ramAddress
        if at < 0 or at + len(data) > len(main.data):
            raise SystemExit(f'code span {address:#x} (+{len(data)} B) is outside the arm9 static image')
        main.data[at:at + len(data)] = data
    add_initialized_banks(arm9, built.banks)
    changed = armips_patch(rom, arm9, src, work, built.syms, built.funcs, widen)
    rom.arm9 = arm9.save(compress=True)
    print(f'code: {len(blob)} bytes + {bss} bss at {code_base:#x}, {moved}{built.span_report(opts.code_spans)}'
          f'{built.window_report(opts.bss_windows)}; '
          f'initialized banks {sum(len(data) for _, data in built.banks)} B; patched {sorted(changed)}')


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description='Compile the C/asm sources of a mod (mod/src) into the code blob, without building a ROM. '
                    'build_rom.py calls this module to inject the blob and apply hooks.asm; run it alone to '
                    'check that the code compiles and to see its size.',
        epilog='Toolchain: ARM_TOOLCHAIN (folder with arm-none-eabi-gcc, default ~/tools/arm-gnu-toolchain/bin), '
               'ARMIPS (armips binary, default ~/tools/bin/armips).')
    ap.add_argument('src', nargs='?', default='mod/src', help='source folder (default: %(default)s)')
    ap.add_argument('--work', default='build/work', help='intermediate files (default: %(default)s)')
    ap.add_argument('--game', default='YG8P', help='game code of the profile to use (default: %(default)s)')
    a = ap.parse_args()
    if not os.path.isdir(a.src):
        raise SystemExit(f'source folder not found: {a.src}')
    code_base, _, labels, _, opts = injection(a.game)
    opts.menu_overlay = 0
    os.makedirs(a.work, exist_ok=True)
    write_engine_ld(a.work, labels)
    built = compile_blob(a.src, a.work, code_base, opts)
    if built is None:
        print(f'{a.src}: no .c or .S files')
        return
    menu = ''
    if built.menu is not None:
        start, size, bss = built.menu_layout()
        menu = f'; menu overlay {size} bytes + {bss} bss at {start:#x}'
    print(f'code: {len(built.code)} bytes + {built.bss} bss at {code_base:#x}{menu}{built.span_report(opts.code_spans)}'
          f'{built.window_report(opts.bss_windows)} '
          f'; initialized banks {sum(len(data) for _, data in built.banks)} B ({a.work}/code.elf, code.map)')


if __name__ == '__main__':
    main()
