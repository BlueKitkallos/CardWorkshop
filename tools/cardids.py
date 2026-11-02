import os
from dataclasses import dataclass

ID_MIN, ID_MAX = 0x100, 16382
WC2011_MAX_ID = 9448
STOCK_ID_COMPARES = frozenset({20, 259, 3714, 3722, 3742, 3743, 3745, 3746, 3749, 3751})
LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mod', 'cards', 'ids.lock')
LOCK_HEADER = '# id konami_id name, in card-list order (- = no Konami id). Written by make cards; commit it.\n'


class IdError(Exception):
    pass


@dataclass
class Entry:
    id: int
    konami: int | None
    name: str


def read_lock(path=LOCK):
    if not os.path.isfile(path):
        return []
    out, seen = [], {}
    with open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            if not line.strip() or line.startswith('#'):
                continue
            parts = line.rstrip('\n').split(' ', 2)
            if len(parts) != 3 or not parts[0].isdigit() or not (parts[1] == '-' or parts[1].isdigit()):
                raise IdError(f'{path}:{n}: want "<id> <konami_id or -> <name>", got {line.strip()!r}')
            e = Entry(int(parts[0]), None if parts[1] == '-' else int(parts[1]), parts[2])
            for key in (('id', e.id), ('name', e.name)) + ((('konami', e.konami),) if e.konami is not None else ()):
                if key in seen:
                    raise IdError(f'{path}:{n}: {e.name} has the same {key[0]} as {seen[key]}')
                seen[key] = e.name
            out.append(e)
    return out


def write_lock(path, entries):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(LOCK_HEADER)
        for e in entries:
            f.write(f'{e.id} {"-" if e.konami is None else e.konami} {e.name}\n')


def lock_positions(locked, cards):
    by_konami = {e.konami: n for n, e in enumerate(locked) if e.konami is not None}
    by_name = {e.name: n for n, e in enumerate(locked)}
    out = []
    for where, c in cards:
        k = c.get('konami_id')
        n = by_konami.get(k) if k is not None else None
        if n is None:
            n = by_name.get(c['name'])
            if n is not None and locked[n].konami is not None and locked[n].konami != k:
                raise IdError(f'{where}: {c["name"]}: ids.lock has it with Konami id {locked[n].konami}, the spec says '
                              f'{"none" if k is None else k}. Fix the spec, or the line in ids.lock if the spec is right.')
        out.append(n)
    return out


def avoid_reason(cid, stock, tables, konami=None):
    if not ID_MIN <= cid <= ID_MAX:
        return f'is outside {ID_MIN}-{ID_MAX}'
    if cid in stock:
        return f'is stock card {stock[cid]}'
    if cid in STOCK_ID_COMPARES:
        return 'is one the game compares card ids against (a stock special case)'
    if cid in tables and cid != konami:
        return 'is mentioned in the stock effect or CPU tables'
    return None


def assign(cards, locked, stock, tables):
    got, pos, new = {}, {}, []
    for i, n in enumerate(lock_positions(locked, cards)):
        where, c = cards[i]
        if n is None:
            new.append(i)
            continue
        e = locked[n]
        if 'id' in c and c['id'] != e.id:
            raise IdError(f'{where}: {c["name"]}: id {c["id"]}, but ids.lock gives it {e.id}. Decks store card ids: '
                          f'keep {e.id}.')
        got[i], pos[i] = e.id, n
    built = set(pos.values())
    gone = [e for n, e in enumerate(locked) if n not in built]
    if gone:
        raise IdError(f'ids.lock: {gone[0].name} (id {gone[0].id}) was built before and is gone from the specs. Old saves '
                      'store cards by list position, so removing it shifts every later card. Put it back, or delete '
                      'ids.lock if no save of this mod exists yet.')
    owner = {got[i]: cards[i][1]['name'] for i in got}
    konami_of_new = {cards[i][1]['konami_id']: cards[i][1]['name'] for i in new
                     if 'id' not in cards[i][1] and 'konami_id' in cards[i][1]}
    for i in new:
        where, c = cards[i]
        if 'id' not in c:
            continue
        cid = c['id']
        why = avoid_reason(cid, stock, tables, c.get('konami_id'))
        if why:
            raise IdError(f'{where}: {c["name"]}: id {cid} {why}')
        if cid in owner:
            raise IdError(f'{where}: {c["name"]}: id {cid} is already {owner[cid]}')
        if cid in konami_of_new:
            raise IdError(f'{where}: {c["name"]}: id {cid} is the Konami id of {konami_of_new[cid]}; leave "id" out or '
                          'pick another')
        got[i], owner[cid] = cid, c['name']
    for i in new:
        where, c = cards[i]
        k = c.get('konami_id')
        if i in got or k is None:
            continue
        if k in stock:
            raise IdError(f'{where}: {c["name"]}: konami_id {k} is stock card {stock[k]}')
        if avoid_reason(k, stock, tables, k) is None and k not in owner:
            got[i], owner[k] = k, c['name']
    nxt = WC2011_MAX_ID + 1
    for i in new:
        if i in got:
            continue
        while nxt <= ID_MAX and (nxt in owner or avoid_reason(nxt, stock, tables)):
            nxt += 1
        if nxt > ID_MAX:
            raise IdError(f'{cards[i][0]}: {cards[i][1]["name"]}: no free id left between {WC2011_MAX_ID + 1} and {ID_MAX}')
        got[i], owner[nxt] = nxt, cards[i][1]['name']
    return [(cards[i][0], cards[i][1], got[i]) for i in sorted(pos, key=pos.get) + sorted(new, key=got.get)]


def id_for_konami(konami_id, lock=LOCK):
    """The card id of a Konami id: the one in ids.lock, else the Konami id itself (stock cards keep theirs)."""
    locked = read_lock(lock)
    e = next((e for e in locked if e.konami == konami_id), None)
    if e is not None:
        return e.id
    taken = next((e for e in locked if e.id == konami_id), None)
    if taken is not None or konami_id > ID_MAX:
        raise KeyError(f'Konami id {konami_id} is not in {lock}' +
                       (f' and {taken.name} has that id' if taken else '') + ': add the card and run make cards')
    return konami_id
