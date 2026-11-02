.open "ov18.bin", 0x0214c840
.arm
.org 0x0215173c
    b menu11_init_hook
.org 0x02154d40
    b menu11_activate_hook
.org 0x021548f8
    b menu11_gate_hook
.close
