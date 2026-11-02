"""Deck source lookup: edited decks take priority over the stock library."""
from pathlib import Path


def resolve_deck(path):
    path = Path(path)
    root = path.parent.parent if path.parent.name == 'base game' else path.parent
    if root.name == 'decks':
        for candidate in (root / path.name, root / 'base game' / path.name):
            if candidate.is_file():
                return str(candidate)
    return str(path)


def deck_files(root):
    root = Path(root)
    files = {p.name: p for p in sorted((root / 'base game').glob('*.json'))}
    files.update({p.name: p for p in sorted(root.glob('*.json'))})
    return list(files.values())


def promoted_decks(root):
    import json
    return [p for p in sorted(Path(root).glob('*.json'))
            if json.loads(p.read_text()).get('stock_file')]


def stock_sources(root):
    import json
    return [p for p in deck_files(root) if json.loads(p.read_text()).get('stock_file')]
