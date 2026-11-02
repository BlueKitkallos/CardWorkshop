#include "w11packs.h"
    .syntax unified
    .arm

    .global w11pk_append_hook
    .type w11pk_append_hook, %function
    .balign 4
w11pk_append_hook:
    push {r1, r2, r3, r4, r12, lr}
    mov r0, r5
    mov r1, r6
    blx w11pk_append
    add r6, r6, r0
    mov r2, #0x34
    mla r5, r0, r2, r5
    pop {r1, r2, r3, r4, r12, lr}
    add r0, r3, #0x2800
    bx lr

    .global w11pk_cmp3d
    .type w11pk_cmp3d, %function
w11pk_cmp3d:
    cmp r0, #W11_PK_FIRST
    bhs 1f
    cmp r0, #0x3d
    bx lr
1:
    cmp r0, r0, lsl #1
    bx lr

