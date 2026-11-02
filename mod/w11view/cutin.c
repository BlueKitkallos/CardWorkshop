typedef unsigned int u32;
typedef unsigned short u16;

#define REG(a) (*(volatile u32 *)(a))
#define HW(a) (*(volatile u16 *)(a))

#define VCOUNT HW(0x04000006)
#define DISPCNT_SUB REG(0x04001000)
#define MASTER_BRIGHT_SUB HW(0x0400106c)
#define SUB_LAYERS 0x1f00u
#define SUB_WINDOWS 0xe000u
#define SUB_WINDOWS_DUEL 0x6000u
#define SUB_BLACK 0x8010u
#define CUTIN_SETUP ((void (*)(u32, u32))0x0218bf0c)
#define FRAME_UPDATE ((void (*)(void))0x020176f1)

static u32 restore_wait;
static u16 restore_bright;

static void vblank_wait(void)
{
    while (VCOUNT < 192 || VCOUNT >= 250)
        ;
}

void cutin_request(u32 ctrl, u32 state)
{
    if (state == 1) {
        vblank_wait();
        DISPCNT_SUB &= ~SUB_LAYERS;
    }
    CUTIN_SETUP(ctrl, state);
}

void cutin_restored(void)
{
    DISPCNT_SUB = (DISPCNT_SUB & ~SUB_WINDOWS) | SUB_WINDOWS_DUEL;
    if (!restore_wait)
        restore_bright = MASTER_BRIGHT_SUB;
    MASTER_BRIGHT_SUB = SUB_BLACK;
    restore_wait = 2;
}

void cutin_frame_start(void)
{
    if (restore_wait && !--restore_wait) {
        vblank_wait();
        MASTER_BRIGHT_SUB = restore_bright;
    }
    FRAME_UPDATE();
}
