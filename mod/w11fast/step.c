typedef unsigned int u32;
typedef unsigned long long u64;

extern int engine_step(void);
extern int cpu_main_phase(void);
extern int cpu_chain(int a, int b, int c, int d);
extern int cpu_trigger(int a, int b, int c, int d);
extern u64 os_get_tick(void);

#define REG(a) (*(volatile u32 *)(a))
#define CMD_COUNT REG(0x0229a368)
#define CMD_STATE REG(0x0229de28)
#define MAIN_DONE_FLAG REG(0x0229ddec)
#define MAIN_HOLD_FLAG REG(0x0229ddf0)
#ifndef STEP_BUDGET
#define STEP_BUDGET 5200
#endif

static u32 pending;

int fast_main_phase(void)
{
    int r = cpu_main_phase();
    pending = r < 1 && (MAIN_DONE_FLAG == 0 || MAIN_HOLD_FLAG != 0);
    return r;
}

int fast_chain(int a, int b, int c, int d)
{
    int r = cpu_chain(a, b, c, d);
    pending = r < 0;
    return r;
}

int fast_trigger(int a, int b, int c, int d)
{
    int r = cpu_trigger(a, b, c, d);
    pending = r == -1;
    return r;
}

int fast_step(void)
{
    u32 t0 = (u32)os_get_tick();
    int r;
    for (;;) {
        pending = 0;
        r = engine_step();
        if (r || !pending || CMD_COUNT || CMD_STATE)
            return r;
        if ((u32)os_get_tick() - t0 > STEP_BUDGET)
            return r;
    }
}
