.open "arm9.bin", 0x02000000
.thumb
.org 0x0202a716
    bl community_pack_member_hook
.org 0x0202a616
    add r0, r6, 0
    bl w11pk_slot
    str r0, [sp, 4]
    nop
    nop
.close

.open "ov10.bin", 0x0214c840
.arm
.org 0x0214da10
    ldr pc, [pc, -4]
    .word w11pk_store_exit_ptr
.org 0x0214dfbc
    bl w11pk_append_hook
.org 0x0214e488
    ldr pc, [pc, -4]
    .word w11pk_completion_ptr
.org 0x02155270
    bl w11pk_cmp3d
.org 0x0215545c
    bl w11pk_cmp3d
.org 0x02155d9c
    bl w11pk_cmp3d
.org 0x02155ed0
    bl w11pk_cmp3d
.org 0x02155ff0
    bl w11pk_cmp3d
.org 0x021560d4
    bl w11pk_cmp3d
.org 0x021561dc
    bl w11pk_cmp3d
.org 0x0215764c
    bl w11pk_cmp3d
.org 0x02155810
    rsb r7, r6, 0x50
.org 0x02155848
    cmp r6, 0x50 + 1
.org 0x02155d7c
    rsb r7, r6, 0x50
.org 0x02155dc4
    cmp r6, 0x50 + 1
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
.open "arm9.bin", 0x02000000
.thumb
.org 0x0202bbb0
    mov r0, 7
.org 0x0202d164
    .word 0x1202
.org 0x0202c68c
    bl community_save_body
.org 0x0202c7de
    bl community_save_body
.org 0x0202debe
    bl community_save_body
.org 0x0202d902
    bl community_load_body
.org 0x0202d4a6
    bl community_body_init
.org 0x0202da7c
    bl community_body_init
.org 0x0202df2a
    bl community_body_init
.close
.open "ov31.bin", 0x0215ca40
.arm
.org 0x0217cd60
    blx community_body_init
.close
.open "ov10.bin", 0x0214c840
.arm
// Keep the native prologue and cleanup; replace only its 60-entry compaction.
.org 0x0215347c
    blx community_box_compact
    b 0x021535d0
.close
