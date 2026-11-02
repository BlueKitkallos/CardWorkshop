"""Session-local WC2010 imports. No game assets ship with the editor."""
from pathlib import Path
import tempfile
import contextlib
import io
import zipfile

import game
import w11opening
from opening_audio import build as build_audio

REGIONS = {b'BYXE': 'USA', b'BYXP': 'Europe'}


def prepare(donor_path, target):
    donor_path = Path(donor_path)
    if donor_path.suffix.lower() == '.zip':
        with zipfile.ZipFile(donor_path) as z:
            entries = [entry for entry in z.infolist() if entry.filename.lower().endswith('.nds')]
            if len(entries) != 1 or entries[0].file_size > 256 * 1024 * 1024:
                raise ValueError('Choose a ZIP containing one WC2010 ROM, up to 256 MiB.')
    elif donor_path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('The WC2010 ROM must be 256 MiB or smaller.')
    donor = game.open_rom(str(donor_path))
    code = bytes(donor.idCode)
    if code not in REGIONS:
        raise ValueError('Choose a WC2010 ROM from the USA or Europe.')
    loose, header, audio = build_audio(donor,target)
    changes = {}
    with tempfile.TemporaryDirectory(prefix='wc-opening-import-') as folder:
        with contextlib.redirect_stdout(io.StringIO()):
            w11opening.build(str(donor_path),folder)
        for path in Path(folder).rglob('*'):
            if path.is_file():
                arc, name = path.relative_to(folder).as_posix().rsplit('/',1)
                changes.setdefault(arc+'.pac',{})[name] = path.read_bytes()
    return {'changes':changes,'loose':loose,'header':header,'audio':audio,
            'donor_sha1':game.sha1(donor_path),'game':f'WC2010 {REGIONS[code]}'}


def load(rom, assets=None):
    if assets is None:
        raise ValueError('Import a WC2010 ROM for Better pack opening.')
    return {arc:dict(files) for arc,files in assets['changes'].items()},dict(assets['loose'])
