    .syntax unified
    .thumb
    .global community_pack_member_hook
    .thumb_func
community_pack_member_hook:
    movs r2, r6
    ldr r3, =community_pack_member
    bx r3
    .ltorg
