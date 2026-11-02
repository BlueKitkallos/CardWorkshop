.nds
.thumb
.include "symbols.asm"
.open "arm9.bin", 0x02000000
.org 0x0202a716
    bl community_pack_member_hook
.close
.open "ov10.bin", 0x0214c840
.arm
.org 0x02155980
    mov r1, r4
    blx community_pack_rarity
    b 0x0215599c
.org 0x02157a10
    mov r1, r0
    mov r0, r6
    blx community_pack_rarity
    b 0x02157a30
.close
