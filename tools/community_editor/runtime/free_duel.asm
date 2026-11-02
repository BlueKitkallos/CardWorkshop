.open "ov07.bin", 0x0214c840
.arm
.org 0x2158c78
    add r1, r1, 0xf100
.org 0x2158c7c
    strh r0, [r1, 0x20]
.org 0x2158c88
    add r0, r0, 0xf300
.org 0x2158c8c
    strh r4, [r0, 0x20]
.org 0x2158cec
    add r1, r1, 0xf100
.org 0x2158cf0
    strh r0, [r1, 0x20]
.org 0x2158cfc
    add r0, r0, 0xf300
.org 0x2158d00
    strh r4, [r0, 0x20]
.org 0x2159284
    addne r2, r2, 0xf300
.org 0x2159288
    strneh r1, [r2, 0x20]
.org 0x21592d4
    addne r3, r3, 0xf300
.org 0x21592d8
    strneh r2, [r3, 0x20]
.org 0x2159c70
    add r0, r0, 0xf300
.org 0x2159c74
    ldrh r0, [r0, 0x20]
.org 0x2159cb0
    add r0, r0, 0xf300
.org 0x2159cb4
    ldrh r0, [r0, 0x20]
.org 0x215ae28
    add r0, r0, 0xf300
.org 0x215ae2c
    ldrh r0, [r0, 0x20]
.org 0x215af08
    add r0, r1, 0xf300
.org 0x215af0c
    ldrh r0, [r0, 0x20]
.org 0x215af30
    add r0, r0, 0xf100
.org 0x215af34
    ldrh r1, [r0, 0x20]
.org 0x215bdbc
    add r0, r0, 0xf300
.org 0x215bdc4
    ldrh r3, [r0, 0x20]
.org 0x215bdd8
    add r0, r0, 0xf300
.org 0x215bddc
    ldrh r3, [r0, 0x20]
.org 0x215beb8
    add r0, r1, 0xf100
.org 0x215bebc
    ldrh r0, [r0, 0x20]
.org 0x215bec0
    add r1, r1, 0x120
.org 0x215bec4
    add r8, r1, 0xf000
.org 0x215bee0
    add r0, r1, 0xf100
.org 0x215bee4
    ldrh r0, [r0, 0x20]
.org 0x215bee8
    add r1, r1, 0x120
.org 0x215beec
    add r8, r1, 0xf000
.org 0x215cc80
    add r0, r0, 0xf300
.org 0x215cc84
    ldrh r0, [r0, 0x20]
.org 0x215ccf8
    add r0, r0, 0xf100
.org 0x215ccfc
    ldrh r0, [r0, 0x20]
.org 0x215d008
    add r0, r0, 0xf300
.org 0x215d00c
    ldrh r0, [r0, 0x20]
.org 0x215d070
    add r0, r0, 0xf100
.org 0x215d074
    ldrh r0, [r0, 0x20]
.org 0x215d170
    add r0, r0, 0xf300
.org 0x215d174
    ldrh r0, [r0, 0x20]
.org 0x215d1d8
    add r0, r0, 0xf100
.org 0x215d1dc
    ldrh r0, [r0, 0x20]
.org 0x02158d20
    blx w11free_append
.org 0x0215bec8
    blx w11free_record_deck
.org 0x0215bef0
    blx w11free_record_deck
.org 0x0215bf4c
    blx w11free_record_deck
.org 0x0215bf60
    blx w11free_record_deck
.org 0x0215bfb8
    blx w11free_record_deck
.org 0x0215bfcc
    blx w11free_record_deck
.close
