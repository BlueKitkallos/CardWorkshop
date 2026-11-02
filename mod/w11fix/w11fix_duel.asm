.open "ov03.bin", 0x02141700
.arm
.org 0x02149588
    blx fix_final_forecast
.close

.open "ov23.bin", 0x0214c840
.arm
.org 0x0214f2d0
    ldr pc, [pc, #-4]
    .word fix_rental_key_ptr
.close

.open "ov31.bin", 0x0215ca40
.org 0x02180d64
    .word 0x5f7f
.close
