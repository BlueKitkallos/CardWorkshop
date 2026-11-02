#!/usr/bin/env python3
"""Copy the parts of an Arm GNU Toolchain and armips the Workshop runs into one folder."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

VERSION = '15.2.rel1'
DOWNLOADS = f'https://developer.arm.com/-/media/Files/downloads/gnu/{VERSION}'
SOURCE = {'name': f'arm-gnu-toolchain-src-snapshot-{VERSION}.tar.xz',
          'url': f'{DOWNLOADS}/srcrel/arm-gnu-toolchain-src-snapshot-{VERSION}.tar.xz',
          'sha256': '06f4e5792b566a771c300ac6f46c3422e23e34f4e3a5d44a8cb5594ead6fb82e',
          'covers': f'Arm GNU Toolchain {VERSION}: GCC, libgcc, Binutils, GMP, MPFR, MPC, ISL, expat, libiconv'}
HOSTS = {('Linux', 'x86_64'): 'x86_64-arm-none-eabi.tar.xz',
         ('Windows', 'AMD64'): 'mingw-w64-x86_64-arm-none-eabi.zip',
         ('Darwin', 'arm64'): 'darwin-arm64-arm-none-eabi.tar.xz'}
EXE = '.exe' if os.name == 'nt' else ''
TOOLS = ['gcc', 'as', 'ld', 'ld.bfd', 'objcopy', 'readelf', 'nm', 'gcc-nm']
LIBEXEC = ['cc1', 'collect2', 'lto1', 'lto-wrapper']
CFLAGS = ['-mcpu=arm946e-s', '-mthumb']
UA = {'User-Agent': 'card-workshop-build'}


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def boost_notice(header):
    lines = []
    for line in Path(header).read_text(encoding='utf-8').splitlines():
        if not line.startswith('//'):
            break
        lines.append(line[2:].removeprefix(' '))
        if 'DEALINGS IN THE SOFTWARE' in line:
            return '\n'.join(lines) + '\n'
    raise SystemExit(f'{header}: no licence block')


def armips_licences(src, out):
    src = Path(src)
    files = {'LICENSE.txt': src / 'LICENSE.txt', 'filesystem-LICENSE.txt': src / 'ext' / 'filesystem' / 'LICENSE'}
    for name, path in files.items():
        if not path.is_file():
            raise SystemExit(f'{path}: missing')
        copy(path, out / name)
    (out / 'tinyformat-LICENSE.txt').write_text(boost_notice(src / 'ext' / 'tinyformat' / 'tinyformat.h'),
                                                 encoding='utf-8')


def armips_version(exe):
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    m = re.search(r'armips assembler (v[\w.]+)', r.stdout + r.stderr)
    if not m:
        raise SystemExit(f'{exe}: no version in its output')
    return m.group(1)


def bundle(root, out, armips, armips_src):
    root, out = Path(root), Path(out)
    gcc = root / 'bin' / f'arm-none-eabi-gcc{EXE}'
    ver = subprocess.run([str(gcc), '-dumpversion'], capture_output=True, text=True, check=True).stdout.strip()
    for t in TOOLS:
        p = root / 'bin' / f'arm-none-eabi-{t}{EXE}'
        if p.exists():
            copy(p, out / 'bin' / p.name)
    for p in (root / 'bin').glob('*.dll'):
        copy(p, out / 'bin' / p.name)
    for p in (root / 'arm-none-eabi' / 'bin').iterdir():
        if p.stem in ('as', 'ld', 'ld.bfd', 'objcopy', 'nm', 'readelf') or p.suffix == '.dll':
            copy(p, out / 'arm-none-eabi' / 'bin' / p.name)
    libexec = root / 'libexec' / 'gcc' / 'arm-none-eabi' / ver
    for p in libexec.iterdir():
        if p.stem in LIBEXEC or p.name.startswith('liblto_plugin') or p.suffix == '.dll':
            copy(p, out / 'libexec' / 'gcc' / 'arm-none-eabi' / ver / p.name)
    lib = root / 'lib' / 'gcc' / 'arm-none-eabi' / ver
    for name in ('include', 'include-fixed'):
        if (lib / name).is_dir():
            shutil.copytree(lib / name, out / 'lib' / 'gcc' / 'arm-none-eabi' / ver / name)
    libgcc = Path(subprocess.run([str(gcc), *CFLAGS, '-print-libgcc-file-name'], capture_output=True, text=True,
                                 check=True).stdout.strip()).resolve()
    copy(libgcc, out / 'lib' / 'gcc' / 'arm-none-eabi' / ver / libgcc.relative_to(lib.resolve()))
    licences = out / 'licenses'
    for p in sorted(root.glob('*.txt')):
        copy(p, licences / 'arm-gnu-toolchain' / p.name)
    if not (licences / 'arm-gnu-toolchain' / 'license.txt').is_file():
        linux_licence(licences / 'arm-gnu-toolchain' / 'license.txt')
    armips_licences(armips_src, licences / 'armips')
    copy(Path(armips), out / 'bin' / f'armips{EXE}')
    credits = {
        'components': [
            {'name': 'Arm GNU Toolchain (GCC, Binutils, libgcc)', 'version': f'{VERSION} (GCC {ver})',
             'use': 'Builds the mod code in an export.',
             'licence': 'GPL-3.0-or-later; libgcc and GCC headers GPL-3.0 with GCC Runtime Library Exception 3.1; '
                        'GMP, MPFR, MPC LGPL-3.0-or-later; ISL MIT',
             'url': 'https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads',
             'licences': 'licenses/arm-gnu-toolchain/'},
            {'name': 'armips', 'version': armips_version(armips), 'use': 'Assembles the game hooks in an export.',
             'licence': 'MIT; includes tinyformat (BSL-1.0) and ghc::filesystem (MIT)',
             'url': 'https://github.com/Kingcom/armips', 'licences': 'licenses/armips/'}],
        'sources': [SOURCE]}
    (out / 'credits.json').write_text(json.dumps(credits, indent=1) + '\n', encoding='utf-8')
    print(f'{out}: GCC {ver}, {sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) // 2**20} MB')


def linux_licence(dst):
    url = f'{DOWNLOADS}/binrel/arm-gnu-toolchain-{VERSION}-{HOSTS[("Linux", "x86_64")]}'
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r, tarfile.open(fileobj=r, mode='r|xz') as t:
        for m in t:
            if m.isfile() and m.name.count('/') == 1 and m.name.endswith('/license.txt'):
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(t.extractfile(m).read())
                return
    raise SystemExit(f'{url}: no license.txt')


def fetch(dest):
    key = (platform.system(), platform.machine())
    if key not in HOSTS:
        raise SystemExit(f'no Arm GNU Toolchain build listed for {key}')
    name = f'arm-gnu-toolchain-{VERSION}-{HOSTS[key]}'
    archive = Path(dest) / name
    with urllib.request.urlopen(urllib.request.Request(f'{DOWNLOADS}/binrel/{name}', headers=UA)) as r, \
            open(archive, 'wb') as f:
        shutil.copyfileobj(r, f)
    if name.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter='tar')
    archive.unlink()
    return next(p.parent.parent for p in Path(dest).rglob(f'arm-none-eabi-gcc{EXE}') if p.parent.name == 'bin')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('out', type=Path, help='output folder, e.g. toolchain')
    ap.add_argument('--armips', required=True, help='armips binary')
    ap.add_argument('--armips-src', required=True, help='armips source checkout, for its licence files')
    ap.add_argument('--from', dest='src', help='installed toolchain folder (default: download the Arm build)')
    a = ap.parse_args()
    if a.out.exists():
        raise SystemExit(f'{a.out} exists')
    if a.src:
        bundle(a.src, a.out, a.armips, a.armips_src)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            bundle(fetch(tmp), a.out, a.armips, a.armips_src)


if __name__ == '__main__':
    sys.exit(main())
