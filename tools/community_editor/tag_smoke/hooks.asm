.nds
.thumb
.include "symbols.asm"
.open "arm9.bin", 0x02000000
.org 0x02015fc8
    .word tag_rig_start_ptr
.close
