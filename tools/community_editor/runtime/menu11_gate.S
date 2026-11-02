.syntax unified
.arm
.global debug11_gate_hook
.type debug11_gate_hook, %function
debug11_gate_hook:
    push {r3-r9, lr}
    ldr r12, =0x021548fc
    bx r12
.pool
