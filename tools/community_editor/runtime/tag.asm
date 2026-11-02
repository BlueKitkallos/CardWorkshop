.open "arm9.bin", 0x02000000
.thumb
.org 0x02017778
    bx pc
    nop
.arm
    ldr pc, [pc, -4]
    .word w11tag_team_ptr
.thumb
.org 0x02019b66
    bl w11tag_name_hook
.close
.open "ov07.bin", 0x0214c840
.arm
.org 0x021592f0
    bl w11tag_append_shim
.org 0x0215bdc4
    bl w11tag_record_shim
.close
