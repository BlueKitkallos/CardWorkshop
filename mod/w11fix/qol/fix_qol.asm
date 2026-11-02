.open "ov03.bin", 0x02141700
.thumb
.org 0x0219af56
    bl fix_duel_clear
.close

.open "ov05.bin", 0x022c5900
.thumb
.org 0x023417d6
    bl fix_summon_scan
.org 0x02392be8
    .word fix_ravine_field_eval_ptr
.close
