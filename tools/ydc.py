#!/usr/bin/env python3
import argparse
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HEADER = bytes.fromhex("01cccccc7f217741")


@dataclass
class Deck:
    main: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    side: list = field(default_factory=list)
    header: bytes = DEFAULT_HEADER

    @classmethod
    def parse(cls, data):
        if data[0] != 1:
            raise ValueError(f"unknown ydc version {data[0]}")
        o = 8
        secs = []
        for _ in range(3):
            n = struct.unpack_from("<H", data, o)[0]
            o += 2
            secs.append(list(struct.unpack_from(f"<{n}H", data, o)))
            o += 2 * n
        if o != len(data):
            raise ValueError(f"{len(data) - o} trailing bytes")
        return cls(secs[0], secs[1], secs[2], bytes(data[:8]))

    @classmethod
    def load(cls, path):
        return cls.parse(Path(path).read_bytes())

    def build(self):
        out = bytearray(self.header)
        for sec in (self.main, self.extra, self.side):
            out += struct.pack(f"<H{len(sec)}H", len(sec), *sec)
        return bytes(out)

    def save(self, path):
        Path(path).write_bytes(self.build())


def rom_decks(rom):
    import game
    prof = game.for_rom(rom)
    return {f'deck/{k}': v for k, v in sorted(game.container_files(rom, f"{prof['archive_root']}/deck.pac").items())
            if k.endswith('.ydc')}


def main():
    ap = argparse.ArgumentParser(description="Read deck files (.ydc from deck.pac). show: list the cards with names. "
                                             "verify: parse and rebuild, check byte-identical.")
    ap.add_argument("cmd", choices=["show", "verify"])
    ap.add_argument("paths", nargs="*", help=".ydc files or folders of them (e.g. extracted/Data_arc_pac/deck); with "
                                             "--rom and no path, every deck of the ROM's deck.pac")
    ap.add_argument("--db", default="extracted/Data_arc_pac/bin2",
                    help="card DB folder for names (default: %(default)s)")
    ap.add_argument("--rom", help="read the card DB (and, with no path, the decks) from this ROM with its game "
                                  "profile, e.g. the WC2011 ROM (BYYP)")
    a = ap.parse_args()
    for x in a.paths:
        if not Path(x).exists():
            sys.exit(f"not found: {x}")
    if not a.paths and not a.rom:
        sys.exit("give deck paths, or --rom")
    sys.path.insert(0, str(Path(__file__).parent))
    rom = None
    if a.rom:
        from carddb import load_from_rom
        rom, prof, dbfiles = load_from_rom(a.rom)
    paths = [p for x in a.paths for p in (sorted(Path(x).glob("*.ydc")) if Path(x).is_dir() else [Path(x)])]
    decks = {str(p): p.read_bytes() for p in paths} if paths else rom_decks(rom)
    if a.cmd == "verify":
        bad = [k for k, v in decks.items() if Deck.parse(v).build() != v]
        print(f"{len(decks)} decks, {len(decks) - len(bad)} byte-identical")
        for k in bad:
            print("MISMATCH", k)
        sys.exit(1 if bad else 0)
    from carddb import CardDB
    db = CardDB.load(dbfiles, prof) if rom else CardDB.load(a.db)
    names = {c.id: c.names["e"] for i, c in enumerate(db.cards) if i}
    for k, v in decks.items():
        d = Deck.parse(v)
        print(f"== {Path(k).name}  main {len(d.main)}  extra {len(d.extra)}  side {len(d.side)}")
        for label, sec in (("main", d.main), ("extra", d.extra), ("side", d.side)):
            for cid in sec:
                print(f"  {label:5} {cid:5} {names.get(cid, '???')}")

if __name__ == "__main__":
    main()
