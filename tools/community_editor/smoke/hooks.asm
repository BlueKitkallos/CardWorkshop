.nds
.thumb
.include "symbols.asm"
.open "arm9.bin", 0x02000000
.org 0x02015fc8
    .word smoke_start_ptr
.org 0x020162e6
    bl smoke_frame
.org 0x0201634c
    bl smoke_frame
.close
