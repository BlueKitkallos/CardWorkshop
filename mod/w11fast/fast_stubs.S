    .syntax unified
    .global load_file
    .thumb_set load_file, 0x020168e9
    .global file_open
    .thumb_set file_open, 0x0201686d
    .global file_read
    .thumb_set file_read, 0x02016a49
    .global prop_record
    .thumb_set prop_record, 0x0202a085
    .global alloc_mem
    .thumb_set alloc_mem, 0x02016469
    .global free_mem
    .thumb_set free_mem, 0x020164dd
    .global heap_create
    .thumb_set heap_create, 0x0207c3fd
    .global duel_setup
    .type duel_setup, %function
    .set duel_setup, 0x02144d40
    .global duel_exit
    .type duel_exit, %function
    .set duel_exit, 0x021462a0

    .arm
    .global copy_hook
    .type copy_hook, %function
copy_hook:
    orr r3, r0, r1
    tst r3, #3
    bne 3f
    cmp r2, #32
    blo 3f
    cmp r1, r0
    bls 1f
    add r3, r0, r2
    cmp r1, r3
    blo 3f
1:
    push {r4-r10}
    bic r12, r2, #31
    and r2, r2, #31
2:
    ldmia r0!, {r3-r10}
    stmia r1!, {r3-r10}
    subs r12, r12, #32
    bne 2b
    pop {r4-r10}
3:
    cmp r2, #0
    bxeq lr
    ldr pc, =0x0208977c
    .pool

    .global prop_stock
    .type prop_stock, %function
prop_stock:
    push {r3, r4, r5, r6, r7, lr}
    ldr r7, =0x02121a5c
    mov r5, r0
    ldrsh r0, [r7, #4]
    mov r6, sp
    ldr r12, =0x02029c19
    bx r12
    .pool

    .global engine_step
    .thumb_set engine_step, 0x0219d471
    .global cpu_main_phase
    .thumb_set cpu_main_phase, 0x0226a445
    .global cpu_chain
    .thumb_set cpu_chain, 0x0226a8c9
    .global cpu_trigger
    .thumb_set cpu_trigger, 0x0226a75d
    .global os_get_tick
    .type os_get_tick, %function
    .set os_get_tick, 0x02052600
    .global card_index
    .thumb_set card_index, 0x02029e1d
    .global card_is_valid
    .thumb_set card_is_valid, 0x02029e61
    .global zone_modified_id
    .thumb_set zone_modified_id, 0x021a1585

    .global genre_hook
    .type genre_hook, %function
genre_hook:
    push {r0, r1, r4, lr}
    ldr r12, =genre_fast
    blx r12
    cmp r0, #0
    pop {r0, r1, r4, lr}
    bxne lr
    push {r4, lr}
    mov r4, r1
    ldr r1, =0x3fff
    and r0, r0, r1
    ldr r12, =0x02029e1d
    ldr lr, =0x0202a131
    bx r12
    .pool
