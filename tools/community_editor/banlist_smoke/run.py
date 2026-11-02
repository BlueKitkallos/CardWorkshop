"""No-input native banlist probe; requires the combined integration fixture."""
from pathlib import Path
import json
import struct
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
import game,inject,mlstate

out=ROOT/'build/community-editor-banlist-smoke';out.mkdir(exist_ok=True)
rom=game.open_rom(str(ROOT/'build/community-editor-combined/combined.nds'))
ov=rom.loadArm9Overlays([8])[8]
word=struct.unpack_from('<I',ov.data,0x0215fc08-ov.ramAddress)[0]
assert word>>25==0x7d,hex(word)
offset=((word&0xffffff)<<2)|((word>>24&1)<<1)
if offset&0x2000000:offset-=0x4000000
icon=0x0215fc08+8+offset|1
with tempfile.TemporaryDirectory(prefix='wc-banlist-rig-') as folder:
 src=Path(folder)
 for name in ['rig.c','hooks.asm']:(src/name).write_bytes((Path(__file__).parent/name).read_bytes())
 (src/'stubs.S').write_text(f'''.syntax unified
.global community_probe_icon
.thumb_set community_probe_icon, {icon:#x}
.global scene_change
.thumb_set scene_change, 0x02016cf5
.global pad_read
.thumb_set pad_read, 0x02014efd
''')
 inject.apply(rom,str(src),str(out/'work'),windows=False)
image=out/'probe.nds';rom.saveToFile(str(image));image.with_suffix('.sav').write_bytes(b'\xff'*0x10000)
syms=mlstate.symbols(str(out/'work'));m=mlstate.Melon(str(image),mlstate.melon_config(str(out),True))
try:
 time.sleep(12)
 state=image.with_suffix('.ml1');m.snapshot(str(state),1)
finally:m.stop()
ram=mlstate.main_ram(str(state));row=struct.unpack_from('<7I',ram,syms['banlist_smoke']-mlstate.MAIN)
result=dict(zip(['magic','state','frame','classic_status','point_status','source','index'],row))
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2),flush=True)
assert row[1]==3 and row[3]==1 and row[4]==0x10+99 and row[5]==0 and row[6]==4,result
