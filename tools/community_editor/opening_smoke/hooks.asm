.nds
.thumb
.include "symbols.asm"
.open "arm9.bin", 0x02000000
.org 0x02015fc8
    .word shop_rig_start_ptr
.org 0x020162e6
    bl shop_rig_frame
.org 0x0201634c
    bl shop_rig_frame
.close
