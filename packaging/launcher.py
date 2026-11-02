import os
from pathlib import Path
import runpy
import sys

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
TOOLCHAIN = BASE / 'toolchain' / 'bin'
if TOOLCHAIN.is_dir():
    os.environ.setdefault('ARM_TOOLCHAIN', str(TOOLCHAIN))
    os.environ.setdefault('ARMIPS', str(TOOLCHAIN / ('armips.exe' if os.name == 'nt' else 'armips')))
entry = BASE / 'tools' / 'pack_editor.py'
sys.argv[0] = str(entry)
runpy.run_path(str(entry), run_name='__main__')
