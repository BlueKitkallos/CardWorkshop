    .syntax unified
    .arm
    .global w11open_finish_hook
    .type w11open_finish_hook, %function
w11open_finish_hook:
    push {r3, r4, r5, lr}
    blx w11open_finish
    ldr r12, =0x02157f34
    bx r12


    .global w11open_scene_hook
    .type w11open_scene_hook, %function
w11open_scene_hook:
    push {r0-r3, r12, lr}
    blx w11open_scene_reset
    pop {r0-r3, r12, lr}
    ldr r12, =0x0214ce00
    bx r12
