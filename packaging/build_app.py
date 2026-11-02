#!/usr/bin/env python3
"""Package the Workshop with PyInstaller: dist/CardWorkshop, with the sources, a bundled toolchain and the licences."""
import argparse
import ast
import importlib.util
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import urllib.request

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = {'ndspy', 'numpy', 'PIL'}
DEV = shutil.ignore_patterns('__pycache__', 'test_*.py', 'smoke', 'banlist_smoke', 'opening_smoke', 'browser_check.py')
EXCLUDE = ['readline']
SYSTEM_RUNTIME = ['libstdc++.so.6', 'libgcc_s.so.1', 'ucrtbase.dll', 'api-ms-win-*.dll']
DISTS = {
    'ndspy': ('ndspy', 'Reads and writes the ROM files.', 'GPL-3.0-or-later'),
    'numpy': ('NumPy', 'Handles images and tables.', None),
    'pillow': ('Pillow', 'Reads and converts images.', None),
    'pyinstaller': ('PyInstaller bootloader', 'Starts the app.',
                    'GPL-2.0-or-later with the PyInstaller bootloader exception; runtime hooks Apache-2.0'),
}
DIST_URLS = {'ndspy': 'https://github.com/RoadrunnerWMC/ndspy', 'numpy': 'https://numpy.org',
             'pillow': 'https://python-pillow.org', 'pyinstaller': 'https://pyinstaller.org'}
DEBIAN = {'libssl3': ('OpenSSL', 'Apache-2.0'), 'libffi8': ('libffi', 'MIT'), 'libbz2-1.0': ('bzip2', 'bzip2-1.0.6'),
          'liblzma5': ('XZ Utils (liblzma)', 'public domain'), 'libsqlite3-0': ('SQLite', 'public domain'),
          'zlib1g': ('zlib', 'Zlib')}
GCC_RUNTIME = re.compile(rb'(?:libgfortran|libquadmath|libgcc_s)[\w.]*?-(\d+\.\d+\.\d+)-(\d+\.el(\d+)_(\d+)\.alma[\w.]*?)'
                         rb'\.x86_64\.debug')
FONT = 'mod/art/fonts/cinzel'
UA = {'User-Agent': 'card-workshop-build'}


def hidden_imports():
    names = set()
    for path in (ROOT / 'tools').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
                names.update(f'{node.module}.{a.name}' for a in node.names if importlib.util.find_spec(node.module) and
                             getattr(importlib.util.find_spec(node.module), 'submodule_search_locations', None) and
                             importlib.util.find_spec(f'{node.module}.{a.name}'))
    top = THIRD_PARTY | set(sys.stdlib_module_names)
    return sorted(n for n in names if n.split('.')[0] in top and n.split('.')[0] not in EXCLUDE)


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def dist_licences(name, out):
    dist = metadata.distribution(name)
    files = [f for f in dist.files or [] if '.dist-info' in f.parts[0] and
             re.search(r'licen[cs]e|copying|notice', f.as_posix(), re.I) and f.name != 'RECORD']
    files = [f for f in files if Path(dist.locate_file(f)).is_file()]
    if not files:
        raise SystemExit(f'{name}: no licence file in its dist-info')
    for f in files:
        rel = Path(*f.parts[1:])
        if rel.parts and rel.parts[0] == 'licenses':
            rel = Path(*rel.parts[1:])
        copy(Path(dist.locate_file(f)), out / name / rel)
    return dist


def python_licences(out):
    ver = platform.python_version()
    for p in (Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE.txt'):
        if p.is_file():
            copy(p, out / 'python' / 'LICENSE.txt')
            break
    else:
        raise SystemExit('Python LICENSE.txt not found')
    url = f'https://raw.githubusercontent.com/python/cpython/v{ver}/Doc/license.rst'
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r:
        (out / 'python' / 'license.rst').write_bytes(r.read())
    return {'name': 'Python', 'version': ver, 'use': 'Runs the Workshop.',
            'licence': 'PSF-2.0. The libraries it includes are listed in license.rst.',
            'url': 'https://www.python.org', 'licences': 'licenses/python/'}


def bundled_binaries():
    tocs = sorted((ROOT / 'build' / 'pyinstaller').rglob('Analysis-*.toc'))
    if not tocs:
        raise SystemExit('PyInstaller analysis file not found')
    toc = ast.literal_eval(tocs[-1].read_text(encoding='utf-8'))
    found = {Path(src) for part in toc if isinstance(part, list) for item in part
             if isinstance(item, tuple) and len(item) == 3 and item[2] == 'BINARY' for src in [item[1]] if src}
    if not found:
        raise SystemExit(f'{tocs[-1]}: no binaries listed')
    return found


def debian_package(path):
    for p in {str(path), str(path.resolve()), str(path).replace('/usr/lib/', '/lib/', 1),
              str(path.resolve()).replace('/usr/lib/', '/lib/', 1)}:
        r = subprocess.run(['dpkg', '-S', p], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.split(':')[0].strip()
    return None


def system_licences(out):
    roots = [Path(p).resolve() for p in {*site.getsitepackages(), site.getusersitepackages(), sys.base_prefix}]
    rows, unknown = {}, []
    for src in sorted(bundled_binaries()):
        real = src.resolve()
        if any(src.match(p) for p in SYSTEM_RUNTIME) or any(real.is_relative_to(r) for r in roots):
            continue
        pkg = debian_package(src) if sys.platform.startswith('linux') else None
        if pkg not in DEBIAN:
            unknown.append(f'{src} ({pkg or "no package"})')
            continue
        version = subprocess.run(['dpkg-query', '-W', '-f', '${Version}', pkg], capture_output=True, text=True,
                                 check=True).stdout.strip()
        copy(Path('/usr/share/doc') / pkg / 'copyright', out / 'system' / f'{pkg}.txt')
        name, licence = DEBIAN[pkg]
        rows.setdefault(pkg, {'name': name, 'version': f'{version} (Ubuntu package {pkg})',
                              'use': 'Used by Python.', 'licence': licence, 'url': 'https://packages.ubuntu.com/' + pkg,
                              'licences': f'licenses/system/{pkg}.txt', 'files': []})['files'].append(src.name)
    if unknown:
        raise SystemExit('bundled libraries with no known licence:\n  ' + '\n  '.join(unknown))
    return list(rows.values())


def gcc_runtime_sources(internal):
    sources = {}
    for path in internal.rglob('*'):
        if not path.is_file() or path.is_symlink() or not re.match(r'lib(gfortran|quadmath|gcc_s)', path.name):
            continue
        m = GCC_RUNTIME.search(path.read_bytes())
        if not m:
            raise SystemExit(f'{path}: GCC runtime library of unknown origin')
        ver, rel, major, minor = (g.decode() for g in m.groups())
        name = f'gcc-{ver}-{rel}.src.rpm'
        sources[name] = {'name': name, 'url': f'https://vault.almalinux.org/{major}.{minor}/BaseOS/Source/Packages/{name}',
                         'covers': f'GCC {ver} runtime libraries bundled with NumPy (libgfortran, libquadmath)'}
    return list(sources.values())


def font_version(path):
    data = path.read_bytes()
    tables = {data[12 + 16 * i:16 + 16 * i]: int.from_bytes(data[20 + 16 * i:24 + 16 * i], 'big')
              for i in range(int.from_bytes(data[4:6], 'big'))}
    name = tables[b'name']
    count, strings = int.from_bytes(data[name + 2:name + 4], 'big'), name + int.from_bytes(data[name + 4:name + 6], 'big')
    for i in range(count):
        rec = data[name + 6 + 12 * i:name + 18 + 12 * i]
        pid, nid = int.from_bytes(rec[0:2], 'big'), int.from_bytes(rec[6:8], 'big')
        if nid == 5:
            raw = data[strings + int.from_bytes(rec[10:12], 'big'):][:int.from_bytes(rec[8:10], 'big')]
            return raw.decode('utf-16-be' if pid in (0, 3) else 'latin-1').removeprefix('Version ').split(';')[0]
    return ''


def table(rows):
    lines = ['| Component | Version | Used for | Licence | Licence texts |', '|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| [{r['name']}]({r['url']}) | {r['version']} | {r['use']} | {r['licence']} | `{r['licences']}` |")
    return '\n'.join(lines)


def credits(app, toolchain):
    out = app / 'licenses'
    internal = app / '_internal'
    for name in ('arm-gnu-toolchain', 'armips'):
        shutil.copytree(toolchain / 'licenses' / name, out / name)
    tc = json.loads((toolchain / 'credits.json').read_text(encoding='utf-8'))
    rows = [python_licences(out)]
    for key, (name, use, licence) in DISTS.items():
        dist = dist_licences(key, out)
        rows.append({'name': name, 'version': dist.version, 'use': use,
                     'licence': licence or dist.metadata.get('License-Expression'), 'url': DIST_URLS[key],
                     'licences': f'licenses/{key}/'})
    rows += tc['components']
    copy(ROOT / FONT / 'OFL.txt', out / 'cinzel' / 'OFL.txt')
    rows.append({'name': 'Cinzel font', 'version': font_version(ROOT / FONT / 'Cinzel.ttf'),
                 'use': 'Draws the Shop labels.', 'licence': 'OFL-1.1',
                 'url': 'https://github.com/NDISCOVER/Cinzel', 'licences': 'licenses/cinzel/'})
    rows += system_licences(out)
    sources = tc['sources'] + gcc_runtime_sources(internal)
    for r in rows:
        if r['licence'] is None:
            raise SystemExit(f"{r['name']}: no licence")
    text = ['# Credits', '',
            "Card Workshop's own code is under the MIT license (see `LICENSE`). This package also contains the parts "
            'below. Each one keeps its own licence, and the full texts are in `licenses/`.', '',
            table(rows), '',
            'The GPL and LGPL parts are shared under those licences. Their source code is attached to the same '
            'release as this package (https://github.com/BlueKitkallos/CardWorkshop/releases):', '']
    text += [f"- `{s['name']}`: {s['covers']}" for s in sources]
    if any(internal.rglob('*freetype*')):
        text += ['', 'Portions of this software are copyright © The FreeType Project (www.freetype.org). '
                     'All rights reserved.']
    (app / 'CREDITS.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    (ROOT / 'build' / 'sources.json').write_text(json.dumps(sources, indent=1) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('toolchain', type=Path, help='folder made by packaging/toolchain.py')
    a = ap.parse_args()
    if not (a.toolchain / 'bin').is_dir() or not (a.toolchain / 'credits.json').is_file():
        raise SystemExit(f'{a.toolchain}: not a folder made by packaging/toolchain.py')
    build = ROOT / 'build' / 'pyinstaller'
    args = ['--noconfirm', '--onedir', '--name', 'CardWorkshop', '--distpath', str(ROOT / 'dist'),
            '--workpath', str(build), '--specpath', str(build)]
    for name in ('ndspy', 'PIL'):
        args += ['--collect-submodules', name]
    for name in hidden_imports():
        args += ['--hidden-import', name]
    for name in EXCLUDE:
        args += ['--exclude-module', name]
    PyInstaller.__main__.run([*args, str(ROOT / 'packaging' / 'launcher.py')])
    app = ROOT / 'dist' / 'CardWorkshop'
    internal = app / '_internal'
    for pattern in SYSTEM_RUNTIME:
        for path in internal.glob(pattern):
            path.unlink()
    for name in ('tools', 'mod', 'variants'):
        shutil.copytree(ROOT / name, internal / name, ignore=DEV)
    shutil.copytree(a.toolchain, internal / 'toolchain', ignore=shutil.ignore_patterns('licenses', 'credits.json'))
    for name in ('LICENSE', 'README.md'):
        shutil.copy2(ROOT / name, app / name)
    credits(app, a.toolchain)


if __name__ == '__main__':
    main()
