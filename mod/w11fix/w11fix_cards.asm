.open "ov03.bin", 0x02141700
.thumb
.org 0x0227e57c
    .word fix_reeze_filter_ptr
.org 0x02284ec4
    .word fix_faustian_filter_ptr
.org 0x0227df04
    .word fix_unibird_filter_ptr
.org 0x02285828
    .word fix_chain_whirlwind_can_ptr
.org 0x022767f8
    .word fix_elma_can_ptr
.org 0x02279528
    .word fix_aklys_can_ptr
.org 0x021c3f70
    bl fix_summon_mark
.org 0x021e510a
    bl fix_equip_timing
.org 0x021e8914
    bl fix_equip_timing
.org 0x0228dcc0
    .word fix_vylon_element_count_ptr
.org 0x022808b0
    .word fix_book_of_life_select_ptr
.org 0x02285418
    .word fix_triangle_resolve_ptr
.org 0x02285420
    .word fix_triangle_can_ptr
    .word fix_triangle_cost_ptr
.org 0x0226ae92
    bl fix_mode_answer
.close
