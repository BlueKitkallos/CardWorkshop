    .syntax unified
    .text

    .arm
    .global w11tag_append_shim
w11tag_append_shim:
    strh r8, [r3, #0xae]
    push {r0-r3, r12, lr}
    blx w11tag_append
    pop {r0-r3, r12, lr}
    bx lr

    .global w11tag_record_shim
w11tag_record_shim:
    ldrh r3, [r0, #0x20]
    cmp r3, #49
    bxlo lr
    ldr r3, =w11tag_zero
    sub r3, r3, #0x2100000
    sub r3, r3, #0x24000
    sub r3, r3, #0x700
    sub r3, r3, #0xc8
    lsr r3, r3, #2
    bx lr
    .pool

    .section .rodata
    .balign 4
w11tag_zero:
    .word 0

    .text
    .thumb
    .global w11tag_name_hook
    .thumb_func
w11tag_name_hook:
    push {r0, r1, r2, lr}
    bl w11tag_text
    adds r1, r0, #1
    beq 1f
    add sp, #16
    ldr r3, =0x0202b64d
    blx r3
    pop {r3, pc}
1:
    pop {r0, r1, r2, r3}
    mov lr, r3
    cmp r0, #0x1e
    bge 2f
    ldr r1, =0x02019b79
    bx r1
2:
    bx lr
    .pool
