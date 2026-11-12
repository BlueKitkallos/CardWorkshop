typedef unsigned int u32;
#define W(a) (*(volatile u32 *)(a))
extern void w11_body_init(void), scene_change(u32,u32,u32), pad_read(void);
volatile u32 menu_rig_mode, menu_rig_phase, menu_rig_frame;
int menu_rig_scene(void) {
    if (!menu_rig_mode) return 0;
    /* The boot fixture bypasses the title scene's sub-screen VRAM setup. */
    *(volatile unsigned char *)0x04000242 = 0x84;
    *(volatile unsigned char *)0x04000243 = 0x84;
    W(0x04001000) = (W(0x04001000) & ~0x80u) | 0x10000;
    ((void (*)(void))0x0214e1f4)();
    W(0x020b8f3c) = menu_rig_mode == 7 ? 0x6000 : menu_rig_mode == 6 ? 0x3001 : menu_rig_mode == 1 ? 0 : menu_rig_mode == 3 ? 0x5000 : menu_rig_mode >= 4 ? 0x4000 : 0x3000;
    menu_rig_phase = 1;
    menu_rig_frame = W(0x020b7cc4);
    return 0;
}
int shop_rig_start(void) {
    w11_body_init();
    scene_change(7, 18, (u32)menu_rig_scene | 1);
    return 0;
}
extern void sr_rig_frame(void) __attribute__((weak));
void shop_rig_frame(void) {
    u32 *ctx = (u32 *)0x02236450;
    pad_read();
    if (sr_rig_frame && menu_rig_phase == 2) sr_rig_frame();
    if (menu_rig_phase == 1 && W(0x020b7cc4) - menu_rig_frame > 90 && (ctx[0] == 1 || (menu_rig_mode == 6 && ctx[0] == 2))) {
        /* Suppress the first-visit save notice in this direct fixture. */
        ((void (*)(u32))0x02156d70)(0x02236d40);
        for (u32 i = 0; i < 27; ++i)
            ((volatile unsigned short *)0x0215e6b0)[i] = 0;
        if (menu_rig_mode != 1 && menu_rig_mode != 6) {
            ctx[0] = 2;
            ((void (*)(u32 *))0x021550a4)(ctx);
            if (menu_rig_mode == 5) {
                ctx[5] = (ctx[6] & 0xffff) - 1;

            }
        }
        menu_rig_phase = 2;
    }
}
