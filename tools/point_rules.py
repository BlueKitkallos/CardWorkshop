"""Explicit story-opponent point allowances; competitive/player decks keep the cap."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECKS = ROOT / 'variants/dimension-break/decks'
JADEN_STORY_DECK = DECKS / 'jaden.json'
HERMOS = {'The Claw of Hermos': 1, 'Red-Eyes Black Dragon Sword': 1, 'Rocket Hermos Cannon': 1,
          'Goddess Bow': 1, 'Time Magic Hammer': 1}
STORY_DECKS = {
    JADEN_STORY_DECK: ('Jaden story opponent: point cap waived', None),
    DECKS / 'joey.json': ('Joey story opponent: Claw of Hermos and Hermos Fusions free', HERMOS),
    DECKS / 'joey_turbo.json': ('Joey story opponent: Claw of Hermos and Hermos Fusions free', HERMOS),
}


def _entry(path, deck):
    entry = STORY_DECKS.get(Path(path).resolve())
    if entry is None:
        return None
    if deck is None:
        deck = json.loads(Path(path).read_text())
    return entry if deck.get('points_exception') == 'story_opponent' else None


def story_point_allowance(path, deck=None):
    """Only the listed shipped story decks can opt into an authorized exception."""
    entry = _entry(path, deck)
    return entry[0] if entry else None


def story_free_cards(path, deck=None):
    """Copies by name that do not count toward the cap; None when the whole cap is waived."""
    entry = _entry(path, deck)
    return entry[1] if entry else None


def rom_points(spec_path=ROOT / 'variants/retro-genesys/banlists/retro-genesys.json'):
    spec = json.loads(Path(spec_path).read_text())
    data = json.loads((ROOT / spec['points_file']).read_text())
    return {**data['points'], **spec.get('rom_only_points', {})}, data.get('point_cap', 100)
