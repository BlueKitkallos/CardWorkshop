import atexit
import json
import os
import re

LANGS = 'fgis'
NAMES = {'f': 'French', 'g': 'German', 'i': 'Italian', 's': 'Spanish'}
NEEDED = 'translations-needed.json'

_tables = {}
_seen = {}
_out = None


def table_path(folder, lang):
    return os.path.join(folder, f'{lang}.json')


def read_table(folder, lang):
    p = table_path(folder, lang)
    if not os.path.isfile(p):
        return {}
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def write_table(folder, lang, table):
    os.makedirs(folder, exist_ok=True)
    with open(table_path(folder, lang), 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(table.items())), f, ensure_ascii=False, indent=1)
        f.write('\n')


def load(folder, out):
    global _out
    for lang in LANGS:
        _tables[lang] = read_table(folder, lang)
    if _out is None:
        atexit.register(_save)
    _out = out


def tr(text, lang, kind, where=None):
    if _out is None or not text:
        return text
    _seen.setdefault(text, {'text': text, 'kind': kind, 'where': where})
    return _tables.get(lang, {}).get(text, text) if lang in LANGS else text


def _save():
    os.makedirs(_out, exist_ok=True)
    rows = [{**v, 'missing': [l for l in LANGS if v['text'] not in _tables[l]]} for v in _seen.values()]
    with open(os.path.join(_out, NEEDED), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


ESCAPES = re.compile(r'\\Na0001|\\Nd00|\\It00|\\wa\d{3}|\\co\d\d|\\Dw')
WIDTH = {'\\Na0001': 8, '\\Nd00': 20, '\\It00': 12}
GENDER = re.compile(r'@M(.*?)@F(.*?)@O', re.S)


def width(row):
    row = row.replace('<i>', '').replace('</i>', '')
    return max(len(ESCAPES.sub(lambda m: 'X' * WIDTH.get(m[0], 0), GENDER.sub(lambda m: m[k], row)))
               for k in (1, 2))


def wrap(text, limit):
    text = GENDER.sub(lambda m: m[0].replace(' ', '\0'), text)
    words = re.sub(r' ([!?:;»])', '\0\\1', text.replace('« ', '«\0')).split(' ')
    rows, cur = [], ''
    for w in words:
        if cur and width(f'{cur} {w}'.replace('\0', ' ')) > limit:
            rows.append(cur)
            cur = w
        else:
            cur = f'{cur} {w}' if cur else w
    rows.append(cur)
    return '\n'.join(rows).replace('\0', ' ')
