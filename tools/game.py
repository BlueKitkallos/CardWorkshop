#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILES = HERE / 'games'
sys.path.insert(0, str(HERE))
import pac


class UnknownGame(Exception):
    pass


def known_codes():
    return sorted(p.stem for p in PROFILES.glob('*.json'))


def load(code):
    path = PROFILES / f'{code}.json'
    if not path.exists():
        raise UnknownGame(f'no profile for game code {code!r} (known: {", ".join(known_codes())})')
    return json.loads(path.read_text(encoding='utf-8'))


def keep_header_crc32(out, source):
    """Set the reserved header word 0x16C of the ROM image `out` (bytearray) so its first 512 bytes have the CRC-32 of
    `source`'s: cheat databases (usrcheat.dat) find a game by its game code and that value."""
    head = bytearray(out[:0x200])
    head[0x16c:0x170] = bytes(4)
    base = zlib.crc32(head)
    basis = {}
    for i in range(32):
        struct.pack_into('<I', head, 0x16c, 1 << i)
        v, m = zlib.crc32(head) ^ base, 1 << i
        while v and v.bit_length() in basis:
            bv, bm = basis[v.bit_length()]
            v, m = v ^ bv, m ^ bm
        basis[v.bit_length()] = v, m
    need, word = zlib.crc32(bytes(source[:0x200])) ^ base, 0
    while need:
        bv, bm = basis[need.bit_length()]
        need, word = need ^ bv, word ^ bm
    struct.pack_into('<I', out, 0x16c, word)


def read_header(rom_path):
    with open(rom_path, 'rb') as f:
        head = f.read(0x10)
    if len(head) < 0x10:
        raise ValueError(f'{rom_path}: too small to be a DS ROM')
    return head[:0xc].rstrip(b'\0').decode('latin1'), head[0xc:0x10].decode('latin1')


def header_code(rom_path):
    return identify(*read_header(rom_path))


def identify(name, code):
    if code in known_codes() and load(code).get('header_name') == name:
        return code
    by_name = [c for c in known_codes() if load(c).get('header_name') == name]
    if len(by_name) == 1:
        return by_name[0]
    return code


def for_path(rom_path):
    return load(header_code(rom_path))


def for_rom(rom):
    return load(identify(bytes(rom.name).rstrip(b'\0').decode('latin1'), bytes(rom.idCode).decode('latin1')))


def require(rom_path, code, tool):
    got = header_code(rom_path)
    if got != code:
        name, raw = read_header(rom_path)
        raise SystemExit(f'{rom_path}: {name} {raw} is a {got} build; {tool} works on {code} builds only')


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def open_rom(rom_path):
    import ndspy.rom
    if not os.path.isfile(rom_path):
        raise SystemExit(f'ROM not found: {rom_path} (run `make setup`, or pass ROM=<path>)')
    if rom_path.lower().endswith('.zip'):
        import zipfile
        with zipfile.ZipFile(rom_path) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.nds')]
            if len(names) != 1:
                raise SystemExit(f'{rom_path}: expected one .nds inside, found {len(names)}')
            return ndspy.rom.NintendoDSRom(z.read(names[0]))
    return ndspy.rom.NintendoDSRom.fromFile(rom_path)


def rom_file(rom, path):
    fid = rom.filenames.idOf(path)
    if fid is None:
        raise KeyError(f'{path}: not in the ROM')
    return rom.files[fid]


def container_files(rom, container):
    if container.endswith('.pac'):
        return pac.files(rom_file(rom, container))
    prefix = container.rstrip('/') + '/'
    out = {}
    for fid in range(len(rom.files)):
        path = rom.filenames.filenameOf(fid)
        if path and path.startswith(prefix) and '/' not in path[len(prefix):]:
            out[path[len(prefix):]] = rom.files[fid]
    return out


def container_dir(container):
    return container[:-4] if container.endswith('.pac') else container.rstrip('/')


def find_roms(dirs, codes=None):
    codes = set(codes or known_codes())
    found = []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() != '.nds' or not p.is_file():
                continue
            try:
                code = header_code(p)
            except (OSError, ValueError):
                continue
            if code in codes:
                found.append((code, p))
    return found


def main():
    ap = argparse.ArgumentParser(description='Show the game profile (tools/games/<code>.json) that matches a ROM, '
                                             'or list the known profiles.')
    ap.add_argument('rom', nargs='?', help='a .nds file; its game code picks the profile')
    ap.add_argument('--sha1', action='store_true', help='also hash the ROM and compare with the clean dump in the profile')
    a = ap.parse_args()
    if not a.rom:
        for code in known_codes():
            p = load(code)
            print(f"{code}  {p['status']:11s} {p['title']}")
        return
    if not os.path.isfile(a.rom):
        sys.exit(f'ROM not found: {a.rom}')
    try:
        p = for_path(a.rom)
    except UnknownGame as e:
        sys.exit(str(e))
    print(f"{p['game_code']}  {p['title']}  status {p['status']}, storage {p['storage']}")
    if a.sha1:
        h = sha1(a.rom)
        want = p.get('clean_sha1')
        print(f'sha1 {h} ' + ('(clean dump)' if h == want else '(not the known clean dump)' if want else '(no reference sha1)'))


if __name__ == '__main__':
    main()
