import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carddb
import cardids

SINGLE_KEYS = ('extra_deck',)
PACK_FIRST, PACK_LAST = 54, 64


def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(f'not found: {path}')
    except json.JSONDecodeError as e:
        raise SystemExit(f'{path}: invalid JSON: {e}')


class CardSpecs:
    """Every card spec of a mod, checked against each other."""

    def __init__(self, paths, need_ids=True):
        if not paths:
            raise SystemExit('no card spec given (mod/cards/*.json is empty?)')
        self.specs = [(p, load_json(p)) for p in paths]
        for p, s in self.specs:
            if not isinstance(s.setdefault('cards', []), list):
                raise SystemExit(f'{p}: "cards" is not a list')
        self.test_only = any(s.get('test_only') for p, s in self.specs)
        dirs = {os.path.dirname(os.path.abspath(s.get('expanded_from', p))) for p, s in self.specs
                if s['cards'] and not s.get('test_only')} or \
            {os.path.dirname(os.path.abspath(paths[0]))}
        if len(dirs) > 1:
            raise SystemExit('the specs that define cards must all be in one folder (mod/cards): ' + ', '.join(sorted(dirs)))
        self.mod_dir = os.path.dirname(dirs.pop())
        self.art_dir = os.path.join(self.mod_dir, 'art')
        for p, s in self.specs:
            if s.get('test_only'):
                for c in s['cards']:
                    if 'id' not in c:
                        raise SystemExit(f'{p}: {c.get("name")}: a test-only card needs its id')
        for p, s in self.specs:
            if 'banlist' in s:
                raise SystemExit(f'{p}: "banlist" moved to its own file, variants/<variant>/banlists/<name>.json (docs/modding/banlists-and-points.md)')
        self.cards = [(p, c) for p, s in self.specs for c in s['cards']]
        self._unique('name', 'card name')
        self._unique('id', 'card id', optional=True)
        self._unique('konami_id', 'Konami id', optional=True)
        self._unique('password', 'passcode', skip='alt_art')
        self.lock = os.path.join(self.mod_dir, 'cards', 'ids.lock')
        self.lock_out = os.path.join(os.path.dirname(self.mod_dir), 'build', 'ids_test.lock') if self.test_only else self.lock
        self._locked_ids(need_ids)
        for key in SINGLE_KEYS:
            self.single(key)
        self.field_bg()
        self.dlg_text()

    def _unique(self, key, label, optional=False, skip=None):
        seen = {}
        for p, c in self.cards:
            if skip and c.get(skip) or key == 'password' and c.get(key) == 0:
                continue
            if key not in c:
                if optional:
                    continue
                raise SystemExit(f'{p}: card {c.get("name", c.get("id"))!r} has no "{key}"')
            v = c[key]
            if v in seen:
                raise SystemExit(f'{label} {v!r} is used twice: {seen[v][1].get("name")} ({seen[v][0]}) and '
                                 f'{c.get("name")} ({p})')
            seen[v] = p, c

    def _locked_ids(self, need_ids):
        try:
            locked = cardids.read_lock(self.lock)
            for (p, c), n in zip(self.cards, cardids.lock_positions(locked, self.cards)):
                if 'id' not in c:
                    if n is not None:
                        c['id'] = locked[n].id
                    elif need_ids:
                        raise SystemExit(f'{p}: {c["name"]}: no id yet, run make cards first')
        except cardids.IdError as e:
            raise SystemExit(str(e))

    def card_art(self, spec_path, name):
        return self.art(spec_path, name) if spec_path in self.generated_paths else os.path.join(self.art_dir, name)

    @property
    def test_paths(self):
        return {p for p, s in self.specs if s.get('test_only')}

    @property
    def generated_paths(self):
        return {p for p, s in self.specs if s.get('test_only') or 'expanded_from' in s}

    def art(self, spec_path, name):
        own = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(spec_path))), 'art', name)
        return own if os.path.exists(own) else os.path.join(self.art_dir, name)

    def single(self, key):
        """(path, spec) of the one spec that defines key, None if none does."""
        found = [(p, s) for p, s in self.specs if key in s]
        if len(found) > 1:
            raise SystemExit(f'"{key}" is set in {found[0][0]} and {found[1][0]}: only one spec may set it '
                            '(one new pack, one Extra Deck setting per mod)')
        return found[0] if found else None

    def packs(self):
        """[(pack_id, pack list, spec, path)] of every spec that defines a pack, by pack id."""
        out, seen = [], {}
        for p, s in self.specs:
            if 'pack_id' not in s:
                for k in ('pack_text', 'pack_art', 'pack_price', 'pack_stock', 'pack_unlock'):
                    if k in s:
                        raise SystemExit(f'{p}: "{k}" without "pack_id"')
                continue
            pid = s['pack_id']
            if not isinstance(pid, int) or not PACK_FIRST <= pid <= PACK_LAST:
                raise SystemExit(f'{p}: pack_id {pid!r}: new packs are {PACK_FIRST}-{PACK_LAST} (the store holds 11 more '
                                 f'entries, the unlock mask 64 packs)')
            if pid in seen:
                raise SystemExit(f'pack {pid} is defined in {seen[pid]} and {p}')
            key = f"pack{pid}"
            if key not in s:
                raise SystemExit(f'{p}: pack_id is {pid} but there is no "{key}" list')
            seen[pid] = p
            out.append((pid, s[key], s, p))
        return sorted(out, key=lambda x: x[0])

    def field_bg(self):
        out, src = {}, {}
        for p, s in self.specs:
            for k, v in s.get('field_bg', {}).items():
                if k in out:
                    raise SystemExit(f'field_bg {k} is set in {src[k]} and {p}')
                out[k], src[k] = v, p
        return out

    def dlg_text(self):
        out, src = [], {}
        for p, s in self.specs:
            for d in s.get('dlg_text', []):
                if d['name'] in src:
                    raise SystemExit(f'dlg_text {d["name"]!r} is set in {src[d["name"]]} and {p}')
                src[d['name']] = p
                out.append(d)
        return out


def load_db(ext2, mod2=None):
    """Card database of extracted/ with the new cards of mod/pac on top."""
    files = {}
    for d in (ext2, mod2):
        if d and os.path.isdir(d):
            for n in os.listdir(d):
                if n.startswith('card_'):
                    with open(os.path.join(d, n), 'rb') as f:
                        files[n] = f.read()
    return carddb.CardDB.load(files)


class CardIndex:
    """Find cards by English name, passcode (digits) or internal id ("id:4844")."""

    def __init__(self, db):
        self.cards = db.cards[1:]
        self.by_name, self.by_lower, self.by_pw, self.by_id = {}, {}, {}, {}
        for c in self.cards:
            self.by_name.setdefault(c.names['e'], []).append(c.id)
            self.by_lower.setdefault(c.names['e'].lower(), c.names['e'])
            if c.password:
                self.by_pw.setdefault(c.password, []).append(c.id)
            self.by_id[c.id] = c

    def deck_id(self, ids):
        return next((i for i in ids if any(getattr(self.by_id[i], 'packs', None) or ())),
                    next((i for i in ids if getattr(self.by_id[i], 'pwcost', 0)), ids[0]))

    def name(self, cid):
        return self.by_id[cid].names['e']

    def resolve(self, key, where):
        """Every id the key names; alternate artworks share a name and all match."""
        k = str(key).strip()
        if k.lower().startswith('id:'):
            try:
                cid = int(k[3:])
            except ValueError:
                raise SystemExit(f'{where}: {key!r}: write an id as "id:4844"')
            if cid not in self.by_id:
                raise SystemExit(f'{where}: no card has id {cid}')
            return [cid]
        if k.isdigit():
            ids = self.by_pw.get(int(k))
            if not ids:
                raise SystemExit(f'{where}: no card has passcode {k}')
            return ids
        if k in self.by_name:
            return self.by_name[k]
        if k.lower() in self.by_lower:
            raise SystemExit(f'{where}: unknown card {key!r}; did you mean {self.by_lower[k.lower()]!r}? (names are case-sensitive)')
        close = difflib.get_close_matches(k.lower(), list(self.by_lower), n=3, cutoff=0.6)
        hint = '; did you mean ' + ', '.join(repr(self.by_lower[c]) for c in close) + '?' if close else ''
        raise SystemExit(f'{where}: unknown card {key!r}{hint}')
