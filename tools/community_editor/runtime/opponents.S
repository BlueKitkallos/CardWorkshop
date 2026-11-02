    .syntax unified
    .thumb
    .text

    .global w11npc_story_hook
    .thumb_func
w11npc_story_hook:
    ldr r1, =w11npc_story
    ldr r2, =w11npc_story_n
    ldr r2, [r2]
1:
    cmp r2, #0
    beq 3f
    ldrh r3, [r1]
    cmp r0, r3
    beq 2f
    adds r1, #4
    subs r2, #1
    b 1b
2:
    ldrh r0, [r1, #2]
    pop {r3, pc}
3:
    movs r1, #0x4b
    lsls r1, r1, #2
    bx lr

    .global w11npc_deck_hook
    .thumb_func
w11npc_deck_hook:
    ldr r1, =w11npc_chara
    ldr r2, =w11npc_chara_n
    ldr r2, [r2]
1:
    cmp r2, #0
    beq 3f
    ldrh r3, [r1]
    cmp r0, r3
    beq 2f
    adds r1, #4
    subs r2, #1
    b 1b
2:
    ldrh r0, [r1, #2]
    pop {r3, pc}
3:
    ldr r3, =0x7ef
    cmp r0, r3
    bx lr
    .pool

    .global w11npc_deckname_hook
    .thumb_func
w11npc_deckname_hook:
    ldr r1, =w11npc_deckname
    ldr r2, =w11npc_deckname_n
    ldr r2, [r2]
1:
    cmp r2, #0
    beq 3f
    ldrh r3, [r1]
    cmp r0, r3
    beq 2f
    adds r1, #4
    subs r2, #1
    b 1b
2:
    ldrh r0, [r1, #2]
    ldr r3, =0x0202b64d
    blx r3
    pop {r3, pc}
3:
    cmp r0, #1
    bgt 4f
    bx lr
4:
    ldr r1, =0x020181af
    bx r1
    .pool

    .global w11npc_lim_file
    .thumb_func
w11npc_lim_file:
    adds r4, r0, #0
    ldr r2, =0x12d
    cmp r4, r2
    bge 1f
    ldr r2, =0x11e
    bx lr
1:
    ldr r2, =0x7fffffff
    bx lr

    .global w11npc_lim_name
    .thumb_func
w11npc_lim_name:
    ldr r1, =0x12d
    cmp r0, r1
    bge 1f
    ldr r1, =0x11e
    cmp r0, r1
    bx lr
1:
    ldr r1, =0x7fffffff
    cmp r0, r1
    bx lr

    .global w11npc_lim_load
    .thumb_func
w11npc_lim_load:
    adds r4, r2, #0
    ldr r0, =0x12d
    cmp r4, r0
    bge 1f
    ldr r0, =0x11e
    bx lr
1:
    ldr r0, =0x7fffffff
    bx lr

    .global w11npc_lim_word
    .thumb_func
w11npc_lim_word:
    ldr r0, =0x12d
    cmp r4, r0
    bge 1f
    ldr r0, =0x11e
    cmp r4, r0
    bx lr
1:
    ldr r0, =0x7fffffff
    cmp r4, r0
    bx lr

    .global w11npc_charname_hook
    .thumb_func
w11npc_charname_hook:
    ldr r1, =w11npc_charname
    ldr r2, =w11npc_charname_n
    ldr r2, [r2]
1:
    cmp r2, #0
    beq 3f
    ldrh r3, [r1]
    cmp r0, r3
    beq 2f
    adds r1, #4
    subs r2, #1
    b 1b
2:
    ldrh r0, [r1, #2]
    ldr r3, =0x0202b64d
    blx r3
    pop {r3, r4, r5, pc}
3:
    adds r5, r0, #0
    cmp r5, #1
    bx lr
    .pool
