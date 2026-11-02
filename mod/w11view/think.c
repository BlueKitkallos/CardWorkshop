typedef unsigned int u32;

#define REG(a) (*(volatile u32 *)(a))
#define DISPCNT REG(0x04000000)
#define DISPCNT_BG3 0x800u
#define THINK_COUNT REG(0x020b8f30)
#define THINK_OFF ((void (*)(void))0x02146944)
#define THINK_MIN 30u

u32 think_next_step = 0;
static u32 holding;

static int bubble_young(void)
{
    u32 n = THINK_COUNT;
    return (DISPCNT & DISPCNT_BG3) && n && n <= THINK_MIN;
}

void think_stop(void)
{
    if (bubble_young()) {
        holding = 1;
        return;
    }
    THINK_OFF();
}

int think_step(void)
{
    if (holding) {
        if (bubble_young())
            return 0;
        holding = 0;
        THINK_OFF();
    }
    return ((int (*)(void))think_next_step)();
}
