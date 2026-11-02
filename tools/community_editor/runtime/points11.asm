.include "points11_def.asm"

.open "arm9.bin", 0x02000000
.thumb
.org 0x0202ace4
    add r0, r4, 0
.org 0x0202acea
    bl bl11_open
.org 0x0202ad10
    bl bl11_copy
.org 0x0202b658
    bl bl11_text_file
    pop {r4, pc}
.org 0x0202b678
    bl bl11_text_table
    pop {r4, pc}
.org 0x0202e156
    mov r1, BL11_START
.org 0x02019a90
    bl bl11_starter
.close

.open "ov08.bin", 0x0214c840
.arm
.org 0x02168674
    blx bl11_avail
.org 0x021686bc
    cmp r6, 3 + BL11_EXT
.org 0x02168720
    cmp r8, 0x55 - BL11_EXT
.org 0x0215d838
    ldr pc, [pc, -4]
    .word bl11_exit_check_ptr
.org 0x0215d324
    blx bl11_dialog_open
.org 0x02166830
    blx bl11_dialog_open
.org 0x0216946c
    blx bl11_dialog_open
.org 0x0216ffc0
    .word bl11_msg_j
    .word bl11_msg_e
.org 0x021700e8
    .word bl11_msg_j
    .word bl11_msg_e
.org 0x02170510
    .word bl11_msg_j
    .word bl11_msg_e
.org 0x02170770
    .word bl11_msg_j
    .word bl11_msg_e
.org 0x021708f0
    .word bl11_msg_j
    .word bl11_msg_e
.org 0x0215fc08
    blx bl11_icon_status
.org 0x0215fc54
    cmp r8, 0x100
.org 0x0215fc80
    blx bl11_icon_grid
.org 0x0215fd88
    blx bl11_icon_status
.org 0x02160024
    cmp r0, 0x100
.org 0x02160058
    blx bl11_icon_row
.org 0x021605c0
    blx bl11_icon_status
.org 0x021607cc
    cmp r0, 0x100
.org 0x021607ec
    blx bl11_icon_detail
.org 0x02158bf4
    blx bl11_stats
.org 0x02159b68
    blx bl11_stats
.org 0x02159eb0
    blx bl11_stats
.org 0x0215a63c
    blx bl11_stats
.org 0x0215a760
    blx bl11_stats
.org 0x0215aa30
    blx bl11_stats
.org 0x02158bfc
    blx bl11_counters
.org 0x02152380
    blx bl11_view_status
.org 0x02152414
    blx bl11_view_insert
.org 0x0215a644
    blx bl11_counters
.close
