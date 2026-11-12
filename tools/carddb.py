#!/usr/bin/env python3
import argparse
import csv
import functools
import json
import re
import struct
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGS = "efgijrs"
ID_BASE = 3900
NAME_CAP = 127

FRAMES = {
    0: "normal", 1: "effect", 2: "fusion", 3: "fusion_effect", 4: "ritual",
    5: "ritual_effect", 6: "toon", 7: "spirit", 8: "union", 9: "gemini",
    10: "token", 11: "god", 12: "synchro", 13: "spell", 14: "trap", 15: "xyz",
}
PENDING_FRAMES = {15}
EXTRA_DECK_FRAMES = {2, 3, 12, 15}
ATTRIBUTES = {
    0: "none", 1: "light", 2: "dark", 3: "water", 4: "fire", 5: "earth",
    6: "wind", 7: "divine", 8: "spell", 9: "trap",
}
RACES = {
    0: "none", 1: "dragon", 2: "zombie", 3: "fiend", 4: "pyro", 5: "sea_serpent",
    6: "rock", 7: "machine", 8: "fish", 9: "dinosaur", 10: "insect", 11: "beast",
    12: "beast_warrior", 13: "plant", 14: "aqua", 15: "warrior", 16: "winged_beast",
    17: "fairy", 18: "spellcaster", 19: "thunder", 20: "reptile", 21: "divine_beast",
    22: "spell", 23: "trap", 24: "psychic", 25: "wyrm", 26: "cyberse", 27: "illusion", 28: "creator_god",
}
STOCK_RACE_MAX = 23
ICONS = {
    0: "normal", 1: "counter", 2: "field", 3: "equip", 4: "continuous",
    5: "quick_play", 6: "ritual",
}
RARITIES = {0: "common", 2: "ultra", 3: "super", 4: "rare"}
GENRES = {
    0: "recover_lp", 1: "reduce_lp", 2: "increase_draw", 3: "special_summon",
    4: "negate_effect", 5: "search_deck", 6: "recover_from_graveyard",
    7: "atk_def_change", 8: "change_position", 9: "change_control",
    10: "destroy_monster", 11: "destroy_spell_trap", 12: "hand_destruction",
    13: "deck_destruction", 14: "remove_from_play", 15: "return_card", 16: "pierce",
    17: "direct_attack", 18: "multiple_attack", 19: "cannot_be_destroyed",
    20: "restrict_attack", 21: "cannot_normal_summon", 22: "flip_effect", 23: "toon",
    24: "spirit", 25: "union", 26: "gemini", 27: "lv_monster", 28: "elemental_hero",
    29: "fusion", 30: "token", 31: "spell_counter", 32: "gamble", 33: "attribute",
    34: "type",
}
UNKNOWN_ATK = 511
MAX_WIDE_ID = 16382

STATS = ("atk", "def_")
PROP_LAYOUTS = {
    "wc2008": {
        "id": (0, 0, 13), "atk": (0, 13, 9), "def_": (0, 22, 9), "flag31": (0, 31, 1),
        "frame": (1, 0, 4), "attribute": (1, 4, 4), "level": (1, 8, 4), "icon": (1, 12, 3),
        "race": (1, 15, 5), "rarity": (1, 20, 4), "tuner": (1, 24, 1), "no_effect": (1, 25, 1),
        "w1_rsv": (1, 26, 6),
    },
    "wc2008w": {
        "id": (0, 0, 14), "atk": (0, 14, 9), "def_": (0, 23, 9),
        "frame": (1, 0, 4), "attribute": (1, 4, 4), "level": (1, 8, 4), "icon": (1, 12, 3),
        "race": (1, 15, 5), "rarity": (1, 20, 4), "tuner": (1, 24, 1), "no_effect": (1, 25, 1),
        "w1_rsv": (1, 26, 5), "flag31": (1, 31, 1),
    },
    "wc2011": {
        "id": (0, 0, 14), "atk": (0, 14, 9), "def_": (0, 23, 9),
        "w1_bit0": (1, 0, 1), "frame": (1, 1, 5), "attribute": (1, 6, 4), "level": (1, 10, 4),
        "icon": (1, 14, 3), "race": (1, 17, 5), "rarity": (1, 22, 10),
    },
}
LAYOUT_NAMES = {
    "wc2011": {
        "frames": {15: "normal_tuner", 16: "tuner", 17: "synchro", 18: "synchro_effect", 19: "synchro_tuner"},
        "races": {21: "psychic", 22: "divine_beast", 23: "spell", 24: "trap"},
    },
}
CARD_TABLES = ("prop", "pass", "pack", "genre", "kana", "pwcost", "link", "intid")

_CP1252_HOLES = {0x81, 0x8D, 0x8F, 0x90, 0x9D}
_WEST_DEC = []
for _b in range(256):
    if _b == 0x9D:
        _WEST_DEC.append("●")
    elif _b in _CP1252_HOLES:
        _WEST_DEC.append(chr(_b))
    else:
        _WEST_DEC.append(bytes([_b]).decode("cp1252"))
_WEST_ENC = {c: b for b, c in enumerate(_WEST_DEC)}


def decode_text(raw, lang):
    if lang in "jr":
        return raw.decode("cp932")
    if lang == "k":
        return raw.decode("euc-kr")
    return "".join(_WEST_DEC[b] for b in raw)


def encode_text(text, lang):
    if lang in "jr":
        return text.encode("cp932")
    if lang == "k":
        return text.encode("euc-kr")
    try:
        return bytes(_WEST_ENC[c] for c in text)
    except KeyError as e:
        raise ValueError(f"character {e.args[0]!r} not encodable for lang {lang}") from None


def text_limits(db):
    return {"names": {l: NAME_CAP for l in db.langs},
            "descs": {l: max(len(encode_text(c.descs[l], l)) for c in db.cards) for l in db.langs}}


def read_strtab(index, data, cols, col, lang, sentinel=True):
    n = len(index) // (4 * cols)
    offs = [struct.unpack_from("<I", index, (i * cols + col) * 4)[0] for i in range(n)]
    if not sentinel:
        offs.append(len(data))
    if offs[-1] != len(data):
        raise ValueError("string table sentinel does not match data size")
    prefix = data[:offs[0]]
    out = []
    for a, b in zip(offs, offs[1:]):
        end = data.index(b"\0", a)
        if end >= b:
            raise ValueError(f"string at {a:#x} overruns next entry")
        out.append(decode_text(data[a:end], lang))
    return prefix, out


def build_strtab(prefix, strings, lang):
    buf = bytearray(prefix)
    offs = []
    for s in strings:
        offs.append(len(buf))
        raw = encode_text(s, lang)
        if b"\0" in raw:
            raise ValueError("NUL inside string")
        buf += raw + b"\0" * (4 - len(raw) % 4)
    offs.append(len(buf))
    return bytes(buf), offs


def write_index(columns):
    out = bytearray()
    for row in zip(*columns):
        for v in row:
            out += struct.pack("<I", v)
    return bytes(out)


@dataclass
class Card:
    id: int = 0
    atk: int = 0
    def_: int = 0
    flag31: int = 1
    frame: int = 0
    attribute: int = 0
    level: int = 0
    icon: int = 0
    race: int = 0
    rarity: int = 0
    tuner: int = 0
    no_effect: int = 0
    password: int = 0
    pack_rarity: list = field(default_factory=lambda: [0, 0, 0])
    packs: list = field(default_factory=lambda: [0, 0, 0])
    pack_tail: int = 0
    genre: int = 0
    kana: int = 0
    pwcost: int = 250
    names: dict = field(default_factory=lambda: {l: "" for l in LANGS})
    descs: dict = field(default_factory=lambda: {l: "" for l in LANGS})
    extra: dict = field(default_factory=dict)

    def unpack_prop(self, raw, layout="wc2008"):
        words = struct.unpack("<II", raw)
        for name, (w, shift, width) in PROP_LAYOUTS[layout].items():
            v = (words[w] >> shift) & ((1 << width) - 1)
            if name in STATS:
                v *= 10
            if hasattr(self, name):
                setattr(self, name, v)
            else:
                self.extra[name] = v

    def pack_prop(self, layout="wc2008"):
        words = [0, 0]
        for name, (w, shift, width) in PROP_LAYOUTS[layout].items():
            mask = (1 << width) - 1
            v = getattr(self, name) if hasattr(self, name) else self.extra.get(name, 0)
            if name in STATS:
                q = UNKNOWN_ATK if v < 0 else v // 10
                if not 0 <= q <= mask or (v >= 0 and v % 10):
                    raise ValueError(f"card {self.id}: stat {v} not encodable")
                v = q
            elif name == "id" and not 0 <= v <= mask:
                raise ValueError(f"card id {v} out of range")
            words[w] |= (v & mask) << shift
        return struct.pack("<II", *words)

    @property
    def frame_name(self):
        return FRAMES.get(self.frame, str(self.frame))

    @property
    def genres(self):
        return [GENRES.get(i, str(i)) for i in range(64) if self.genre >> i & 1]


def default_profile():
    return json.loads((HERE / "games" / "YG8P.json").read_text(encoding="utf-8"))


def table_name(template, lang=None, pack_lang=None):
    return template.format(l=lang or "", L=(lang or "").upper(), pl=pack_lang or "")


def reader(d):
    if isinstance(d, dict):
        return d.__getitem__
    d = Path(d)
    if not d.is_dir():
        raise FileNotFoundError(f"{d}: not a directory (run `make extract` or `make setup` first)")
    return lambda n: (d / n).read_bytes()


class CardDB:
    def __init__(self, profile=None):
        spec = (profile or default_profile())["card_db"]
        self.spec = spec
        self.langs = spec["langs"]
        self.id_base = spec["id_base"]
        self.layout = spec["prop_layout"]
        self.mod_layout = spec.get("prop_layout_mod", self.layout)
        self.flag_bits = spec.get("intid_flag_bits", 0)
        self.tables = spec["files"]
        self.cards = []
        self.sort = {l: [] for l in self.langs}
        self.links = []
        self.intid_size = 3504
        self.intid_flags = {}
        self.prefix = {}
        self.kana_pairs = {}

    @property
    def max_id(self):
        return self.id_base + self.intid_size - 1

    def has(self, table):
        return table in self.tables

    def name(self, table, lang=None):
        return table_name(self.tables[table], lang)

    @classmethod
    def load(cls, d, profile=None):
        db = cls(profile)
        rd = reader(d)
        prop = rd(db.name("prop"))
        n = len(prop) // 8
        wide = db.mod_layout != db.layout and n and struct.unpack_from("<I", prop, 4)[0] >> 31
        if wide:
            db.layout = db.mod_layout
        db.cards = [Card() for _ in range(n)]
        pw = struct.unpack(f"<{n}I", rd(db.name("pass")))
        pack = rd(db.name("pack")) if db.has("pack") else None
        genre = rd(db.name("genre")) if db.has("genre") else None
        kana = struct.unpack(f"<{n}H", rd(db.name("kana"))) if db.has("kana") else None
        cost = struct.unpack(f"<{n}H", rd(db.name("pwcost"))) if db.has("pwcost") else None
        for i, c in enumerate(db.cards):
            c.unpack_prop(prop[i * 8:i * 8 + 8], db.layout)
            c.password = pw[i]
            if pack is not None:
                p = pack[i * 8:i * 8 + 8]
                c.pack_rarity = list(p[0:3])
                c.packs = list(p[3:6])
                c.pack_tail = struct.unpack_from("<H", p, 6)[0]
            if genre is not None:
                c.genre = struct.unpack_from("<Q", genre, i * 8)[0]
            if kana is not None:
                c.kana = kana[i]
            if cost is not None:
                c.pwcost = cost[i]
        for l in db.langs:
            db.sort[l] = list(struct.unpack(f"<{n}H", rd(db.name("sort", l))))
            if db.has("kana1"):
                db.kana_pairs[l] = [list(struct.unpack(f"<{n}H", rd(db.name(t, l)))) for t in ("kana1", "kana2")]
            idx = rd(db.name("indx", l))
            if len(idx) != (n + 1) * 8:
                raise ValueError(f"{db.name('indx', l)} holds {len(idx) // 8} entries, expected {n + 1}")
            for col, kind in ((0, "name"), (1, "desc")):
                pre, strs = read_strtab(idx, rd(db.name(kind, l)), 2, col, l)
                db.prefix[(kind, l)] = pre
                for c, s in zip(db.cards, strs):
                    getattr(c, kind + "s")[l] = s
        if db.has("link"):
            link = rd(db.name("link"))
            v = struct.unpack(f"<{len(link) // 2}H", link)
            db.links = list(zip(v[0::2], v[1::2]))
        if wide:
            db.cards[0].flag31 = 0
        intid = rd(db.name("intid"))
        db.intid_size = len(intid) // 2
        first = struct.unpack_from("<H", intid, 0)[0] & ((1 << (16 - db.flag_bits)) - 1) if intid else 0
        if 0 < first < n:
            db.id_base = db.cards[first].id
        if db.flag_bits:
            shift = 16 - db.flag_bits
            db.intid_flags = {k: v >> shift for k, v in enumerate(struct.unpack(f"<{db.intid_size}H", intid))
                              if v >> shift}
        if db.build_intid() != intid:
            raise ValueError(f"{db.name('intid')} is not derivable from card ids")
        return db

    def build_intid(self):
        t = [0] * self.intid_size
        shift = 16 - self.flag_bits
        for i, c in enumerate(self.cards):
            if i == 0:
                continue
            k = c.id - self.id_base
            if not 0 <= k < self.intid_size:
                raise ValueError(f"card id {c.id} outside {self.id_base}..{self.max_id}")
            if t[k]:
                raise ValueError(f"duplicate card id {c.id}")
            if i >> shift:
                raise ValueError(f"card index {i} does not fit the intid table")
            t[k] = i
        for k, fl in self.intid_flags.items():
            t[k] |= fl << shift
        return struct.pack(f"<{len(t)}H", *t)

    @property
    def wide_ids(self):
        return self.mod_layout != self.spec["prop_layout"]

    def fit_intid(self):
        ids = [c.id for c in self.cards[1:]]
        lo, hi = min(ids), max(ids)
        if hi > MAX_WIDE_ID:
            raise ValueError(f"card id {hi} above {MAX_WIDE_ID}")
        n = hi - lo + 1
        while not arm_imm(n):
            n += 1
        self.id_base, self.intid_size = lo, n

    def pack_props(self, layout):
        out = bytearray(b"".join(c.pack_prop(layout) for c in self.cards))
        if layout != self.spec["prop_layout"] and out:
            out[7] |= 0x80
        return bytes(out)

    def files(self, layout=None):
        layout = layout or self.layout
        if layout != self.spec["prop_layout"]:
            self.fit_intid()
        n = len(self.cards)
        builders = {
            "prop": lambda: self.pack_props(layout),
            "pass": lambda: struct.pack(f"<{n}I", *(c.password for c in self.cards)),
            "pack": lambda: b"".join(bytes(c.pack_rarity) + bytes(c.packs) + struct.pack("<H", c.pack_tail)
                                     for c in self.cards),
            "genre": lambda: b"".join(struct.pack("<Q", c.genre) for c in self.cards),
            "kana": lambda: struct.pack(f"<{n}H", *(c.kana for c in self.cards)),
            "pwcost": lambda: struct.pack(f"<{n}H", *(c.pwcost for c in self.cards)),
            "link": lambda: b"".join(struct.pack("<HH", a, b) for a, b in self.links),
            "intid": self.build_intid,
        }
        out = {self.name(t): builders[t]() for t in CARD_TABLES if self.has(t)}
        if self.has("kana2_j"):
            out[self.name("kana2_j")] = struct.pack(f"<{n}H", *self.kana_pairs["j"][1])
        for l in self.langs:
            out[self.name("sort", l)] = struct.pack(f"<{n}H", *self.sort[l])
            if self.has("sort2"):
                inv = [0] * n
                for i, r in enumerate(self.sort[l]):
                    if i:
                        inv[r] = i
                out[self.name("sort2", l)] = struct.pack(f"<{n}H", *inv)
            if self.has("kana1"):
                for t, v in zip(("kana1", "kana2"), self.kana_pairs[l]):
                    out[self.name(t, l)] = struct.pack(f"<{n}H", *v)
            cols = []
            for kind in ("name", "desc"):
                data, offs = build_strtab(self.prefix.get((kind, l), b"\0" * 4),
                                          [getattr(c, kind + "s")[l] for c in self.cards], l)
                out[self.name(kind, l)] = data
                cols.append(offs)
            out[self.name("indx", l)] = write_index(cols)
        return out

    def save(self, d):
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        for name, data in self.files().items():
            (d / name).write_bytes(data)

    def by_id(self, cid):
        for i, c in enumerate(self.cards):
            if i and c.id == cid:
                return i, c
        raise KeyError(cid)

    def by_password(self, pw):
        for i, c in enumerate(self.cards):
            if pw and c.password == pw:
                return i, c
        raise KeyError(pw)

    def next_free_id(self):
        used = {c.id for c in self.cards}
        for cid in range(self.id_base, self.max_id + 1):
            if cid not in used:
                return cid
        raise ValueError("no free card id left in the intid table")

    def append(self, card):
        if card.id == 0:
            card.id = self.next_free_id()
        self.cards.append(card)
        if self.wide_ids and not self.id_base <= card.id <= self.max_id:
            self.fit_intid()
        by_reading = self.spec.get("sort_by_reading", False)
        for l in self.langs:
            key = _sort_key(card, l, by_reading)
            ranks = self.sort[l]
            pos = 1 + sum(1 for i in range(1, len(ranks)) if _sort_key(self.cards[i], l, by_reading) < key)
            self.sort[l] = [r + 1 if r >= pos else r for r in ranks] + [pos]
            if self.has("kana1"):
                for v, k in zip(self.kana_pairs[l], kana_pair(card, l)):
                    v.append(k)
        self.build_intid()
        return len(self.cards) - 1

    def frame_name(self, card):
        return LAYOUT_NAMES.get(self.layout, {}).get("frames", {}).get(card.frame) or card.frame_name

    def race_name(self, card):
        return LAYOUT_NAMES.get(self.layout, {}).get("races", {}).get(card.race) or RACES.get(card.race, card.race)


def _sort_key(card, lang, by_reading=False):
    name = card.names[lang]
    if lang in "jr":
        if by_reading:
            return (0, reading(card.names["r"]))
        return (card.kana, name.encode("cp932"))
    return (0, _fold(name))


@functools.lru_cache(maxsize=None)
def _fold(name):
    return "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)).casefold()


KANA_SKIP = set(" 　・－-「」『』＝=")
KANA_WEST = {"¡": "!", "¿": "?", "æ": "a", "Æ": "A"}


@functools.lru_cache(maxsize=None)
def reading(ruby_name):
    """Hiragana reading of a Japanese name with $Rbase(reading) ruby."""
    s = unicodedata.normalize("NFKC", re.sub(r"\$R[^(]*\(([^)]*)\)", r"\1", ruby_name))
    return "".join(chr(ord(ch) - 0x60) if 0x30a1 <= ord(ch) <= 0x30f6 else ch for ch in s if ch not in KANA_SKIP)


def kana_pair(card, lang):
    """(first, second) search letters of a card name, the per-language CARD_Kana1/CARD_Kana2 entries of WC2011."""
    if lang in "jr":
        chars = [unicodedata.normalize("NFKC", ch) for ch in reading(card.names["r"])][:2]
        out = []
        for ch in chars:
            raw = ("ぶ" if ch == "ゔ" else ch).encode("cp932")
            out.append(int.from_bytes(raw, "big") if len(raw) == 2 else (raw[0] if raw else 0))
        return tuple(out + [0] * (2 - len(out)))
    out = []
    for ch in card.names[lang][:2]:
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))[:1] or ch
        base = KANA_WEST.get(base, base)
        out.append(ord(base) if ord(base) < 0x80 else 0x8145 if base == "·" else ord("?"))
    return tuple(out + [0] * (2 - len(out)))


PACK_LANGS = {"eng": "e", "fra": "f", "ger": "g", "ita": "i", "jpn": "j", "kor": "k", "spa": "s"}


class PackText:
    def __init__(self, profile=None):
        spec = (profile or default_profile())["pack_text"]
        self.langs = spec["langs"]
        self.tables = spec["files"]
        self.names = {}
        self.descs = {}
        self.prefix = {}

    def name(self, table, pl):
        return table_name(self.tables[table], pack_lang=pl)

    @classmethod
    def load(cls, d, profile=None):
        pt = cls(profile)
        rd = reader(d)
        for pl, l in pt.langs.items():
            idx = rd(pt.name("indx", pl))
            for col, kind, store in ((0, "name", pt.names), (1, "desc", pt.descs)):
                pre, strs = read_strtab(idx, rd(pt.name(kind, pl)), 2, col, l, False)
                pt.prefix[(kind, pl)] = pre
                store[pl] = strs
        return pt

    def files(self):
        out = {}
        for pl, l in self.langs.items():
            cols = []
            for kind, store in (("name", self.names), ("desc", self.descs)):
                data, offs = build_strtab(self.prefix.get((kind, pl), b""), store[pl], l)
                out[self.name(kind, pl)] = data
                cols.append(offs[:-1])
            out[self.name("indx", pl)] = write_index(cols)
        return out


def arm_imm(v):
    return any(((v << r | v >> (32 - r)) & 0xffffffff) < 256 for r in range(0, 32, 2))


def dump_csv(db, path):
    langs = db.langs
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "id", "password", "frame", "attribute", "race", "icon", "level",
                    "atk", "def", "rarity", "flag31", "packs", "pack_rarity", "pwcost", "genres"]
                   + [f"name_{l}" for l in langs])
        for i, c in enumerate(db.cards):
            stat = lambda v: "?" if v == UNKNOWN_ATK * 10 else v
            mon = c.frame not in (13, 14)
            w.writerow([i, c.id, f"{c.password:08d}", db.frame_name(c), ATTRIBUTES.get(c.attribute, c.attribute),
                        db.race_name(c), "" if mon else ICONS.get(c.icon, c.icon),
                        c.level if mon else "", stat(c.atk) if mon else "", stat(c.def_) if mon else "",
                        RARITIES.get(c.rarity, c.rarity), c.flag31,
                        " ".join(str(p) for p in c.packs if p),
                        " ".join(RARITIES.get(r, str(r)) for p, r in zip(c.packs, c.pack_rarity) if p),
                        c.pwcost, " ".join(c.genres)]
                       + [c.names[l].replace("\r\n", " ") for l in langs])


def compare(originals, rebuilt):
    bad = [name for name, data in sorted(rebuilt.items()) if originals(name) != data]
    print(f"{len(rebuilt)} files rebuilt, {len(rebuilt) - len(bad)} byte-identical")
    for b in bad:
        print("MISMATCH", b)
    return not bad


def verify(src, pack_src, profile=None):
    db = CardDB.load(src, profile)
    rebuilt = {Path(src) / k: v for k, v in db.files().items()}
    rebuilt.update({Path(pack_src) / k: v for k, v in PackText.load(pack_src, profile).files().items()})
    ok = compare(lambda p: Path(p).read_bytes(), rebuilt)
    if db.mod_layout == db.layout:
        return ok
    wide = db.files(db.mod_layout)
    back = CardDB.load(wide, profile)
    print(f"through layout {db.mod_layout}: ids {back.id_base}..{back.max_id}")
    return compare(lambda p: Path(p).read_bytes(),
                   {Path(src) / k: v for k, v in back.files(db.layout).items()}) and ok


def load_from_rom(rom_path):
    import game
    rom = game.open_rom(rom_path)
    try:
        prof = game.for_rom(rom)
    except game.UnknownGame as e:
        raise SystemExit(str(e))
    files = game.container_files(rom, prof["card_db"]["container"])
    return rom, prof, files


def verify_rom(rom_path):
    import game
    rom, prof, files = load_from_rom(rom_path)
    print(f"{prof['game_code']} {prof['title']}: card DB in {prof['card_db']['container']}, "
          f"layout {prof['card_db']['prop_layout']}")
    try:
        db = CardDB.load(files, prof)
    except (KeyError, ValueError, UnicodeDecodeError) as e:
        print(f"FAILED to load the card DB: {e}")
        return False
    rebuilt = {f"card_db:{k}": v for k, v in db.files().items()}
    known = set(db.files())
    rest = sorted(n for n in files if n.lower().startswith("card_") and n.endswith(".bin") and n not in known)
    ok_pack = True
    if prof.get("pack_text"):
        try:
            ptf = game.container_files(rom, prof["pack_text"]["container"])
            rebuilt.update({f"pack_text:{k}": v for k, v in PackText.load(ptf, prof).files().items()})
        except (KeyError, ValueError, UnicodeDecodeError) as e:
            print(f"pack text not loaded: {e}")
            ok_pack = False
    else:
        ptf = {}
    src = {"card_db": files, "pack_text": ptf}
    ok = compare(lambda k: src[k.split(":", 1)[0]][k.split(":", 1)[1]], rebuilt)
    print(f"{len(db.cards)} cards, ids {min(c.id for c in db.cards[1:])}..{max(c.id for c in db.cards[1:])}, "
          f"languages {db.langs}")
    if rest:
        print("card tables not decoded (left as they are): " + " ".join(rest))
    return ok and ok_pack


def main():
    ap = argparse.ArgumentParser(
        description="Read, check and dump the card database. Reads the extracted bin2/bin folders "
                    "(WC2008) or, with --rom, any ROM that has a profile in tools/games/.",
        epilog="verify: rebuild every card table and compare byte for byte. csv: dump all cards to --out. "
               "show KEY: print the cards whose English name contains KEY, or whose id or password is KEY.")
    ap.add_argument("cmd", choices=["verify", "csv", "show"])
    ap.add_argument("key", nargs="?", help="search text for show")
    ap.add_argument("--rom", help="read the card DB straight from this ROM (game detected from its header)")
    ap.add_argument("--src", default="extracted/Data_arc_pac/bin2",
                    help="folder with the card_*.bin files (default: %(default)s)")
    ap.add_argument("--packs", default="extracted/Data_arc_pac/bin",
                    help="folder with the pack_*.bin files, for verify (default: %(default)s)")
    ap.add_argument("--out", default="build/cards.csv", help="csv output path (default: %(default)s)")
    a = ap.parse_args()
    if a.cmd == "show" and not a.key:
        ap.error("show needs a KEY")
    try:
        if a.cmd == "verify":
            sys.exit(0 if (verify_rom(a.rom) if a.rom else verify(a.src, a.packs)) else 1)
        if a.rom:
            _, prof, files = load_from_rom(a.rom)
            db = CardDB.load(files, prof)
        else:
            db = CardDB.load(a.src)
    except FileNotFoundError as e:
        sys.exit(str(e))
    if a.cmd == "csv":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        dump_csv(db, a.out)
        print(f"{len(db.cards)} cards -> {a.out}")
    else:
        k = a.key.lower()
        for i, c in enumerate(db.cards):
            if k in c.names["e"].lower() or k == str(c.id) or k == str(c.password):
                print(i, c.id, c.password, db.frame_name(c), ATTRIBUTES.get(c.attribute), db.race_name(c),
                      ICONS.get(c.icon) if c.frame in (13, 14) else f"lv{c.level} {c.atk}/{c.def_}",
                      c.names["e"])


if __name__ == "__main__":
    main()
