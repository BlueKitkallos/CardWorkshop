.syntax unified
.arm
.global menu11_init_hook
.type menu11_init_hook, %function
menu11_init_hook:
    push {r0-r3, r12, lr}
    blx menu11_init
    pop {r0-r3, r12, lr}
    push {r3-r11, lr}
    ldr r12, =0x02151740
    bx r12

.global menu11_activate_hook
.type menu11_activate_hook, %function
menu11_activate_hook:
    push {r0-r3, r12, lr}
    blx menu11_activate
    cmp r0, #0
    pop {r0-r3, r12, lr}
    bxne lr
    push {r3, lr}
    ldr r12, =0x02154d44
    bx r12

.global menu11_gate_hook
.type menu11_gate_hook, %function
menu11_gate_hook:
    push {r0-r3, r12, lr}
    blx menu11_gate
    cmp r0, #0
    beq 1f
    cmp r0, #2
    pop {r0-r3, r12, lr}
    moveq r0, #0
    movne r0, #1
    bx lr
1:
    pop {r0-r3, r12, lr}
    b debug11_gate_hook
