    .section .vmhead, "aw"
    .global vm_state
vm_state:
    .word 0
    .word 0x31314453
    .word story_config
    .word story_initial_decks

    .text
    .arm
    .global vm_menu_default
vm_menu_default:
    ldr r0, =0x2007
    cmp lr, r0
    beq 1f
    ldr r0, =0x2008
    cmp lr, r0
    movne r0, #1
    ldmnefd sp!, {r4, r5, r6, r7, r8, pc}
    blx pe_menu_go
    mov r0, r7
    ldmfd sp!, {r4, r5, r6, r7, r8, pc}
1:  blx vm_menu_go
    mov r0, r7
    ldmfd sp!, {r4, r5, r6, r7, r8, pc}

    .global vm_viewer_r1
vm_viewer_r1:
    ldr r1, =0x02299118
    ldr r1, [r1]
    and r1, r1, #1
    ldr ip, =vm_state
    ldr ip, [ip]
    cmp ip, #3
    moveq r1, #2
    bx lr

    .global vm_card_view
vm_card_view:
    ldr ip, =vm_state
    ldr ip, [ip]
    cmp ip, #3
    bxeq lr
    push {r0, r1, r2, r3}
    ldr pc, =0x0215ebb0

    .global vm_tile_check
vm_tile_check:
    ldrh r2, [r0, #10]
    tst r2, #0x4000
    bxne lr
    ldr r3, =vm_state
    ldr r3, [r3]
    cmp r3, #3
    beq 1f
    ldr r3, =0x02299118
    ldr r3, [r3]
    and r3, r3, #1
    and r2, r2, #1
    cmp r2, r3
    bxeq lr
1:  mov r0, #0
    str r0, [r1]
    bx lr

    .global vm_viewer_r2
vm_viewer_r2:
    ldr r2, =0x02299118
    ldr r2, [r2]
    and r2, r2, #1
    ldr ip, =vm_state
    ldr ip, [ip]
    cmp ip, #3
    moveq r2, #2
    bx lr
    .pool

    .global pe_text_hook
    .arm
pe_text_hook:
    sub ip, r0, #0x7f00
    cmp ip, #2
    ldrlo ip, =pe_text
    bxlo ip
    push {r4, lr}
    ldr r1, =0x0202b684
    ldr r1, [r1]
    ldr r1, [r1, #0x10]
    ldr r2, [r1, #0x20]
    cmp r2, #0
    ldreq ip, =0x0202b659
    ldrne ip, =0x0202b679
    bx ip
    .pool
