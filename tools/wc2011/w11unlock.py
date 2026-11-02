"""Story-flag unlock conditions for Music Select themes, shop packs and CPU Duel opponents."""
from pathlib import Path

FLAG_RANGES = ((10000, 11279), (20000, 20249))


def story_flags(spec_path):
    for d in Path(spec_path).resolve().parents:
        names = d / 'story' / 'names.flags'
        if names.is_file():
            out = {}
            for line in names.read_text(encoding='utf-8').splitlines():
                name, sep, val = line.split('#', 1)[0].rpartition('=')
                if sep and name.strip():
                    out[name.strip()] = int(val.strip(), 0)
            return out
    raise SystemExit(f'{spec_path}: no story/names.flags in a folder above it')


def words(groups, flags, where):
    if not isinstance(groups, list) or not groups or not all(isinstance(g, list) and g for g in groups):
        raise SystemExit(f'{where}: "unlock" is a list of flag lists (any list whose flags are all set unlocks)')
    out = []
    for g in groups:
        for name in g:
            n = flags.get(name, name) if isinstance(name, str) else name
            if not isinstance(n, int) or not any(lo <= n <= hi for lo, hi in FLAG_RANGES):
                raise SystemExit(f'{where}: flag {name!r} is not in story/names.flags or a story flag number '
                                 f'(10000-11279, 20000-20249)')
            out.append(n)
        out.append(0)
    return out + [0]
