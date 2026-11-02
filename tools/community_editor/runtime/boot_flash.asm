.open "ov02.bin", 0x02151b00
.arm
.org 0x02151df0
    blx w11boot_logo_transfer
.org 0x02151e64
    blx w11boot_logo_transfer
.close
