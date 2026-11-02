.open "ov10.bin", 0x0214c840
.arm
.org 0x02157e04
    ldr pc, =community_open_entry_ptr
.pool
.org 0x0214d72c
    bl w11open_scene_hook
.org 0x02152954
    ldr pc, =w11open_start_ptr
.pool
.org 0x02152cb0
    ldr pc, =w11open_tick_ptr
.pool
.org 0x02157f30
    b w11open_finish_hook
.close
.open "arm9.bin", 0x02000000
.thumb
.org 0x02025b80
    bl w11open_texture
.org 0x02025e84
    bl w11open_camera_display
.org 0x020261c4
    bl w11open_camera_visibility
.org 0x0202662a
    bl w11open_camera_visibility
.close
