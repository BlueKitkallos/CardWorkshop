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

#ifdef THINK_CAP_TICKS
extern void cpu_end(int side, int r, int floor);
extern int cpu_ai_pop(void);
extern int cpu_hyp_pop(void);
extern int cpu_flag(int f);
extern void cpu_note(int side, int a, int b, int act);
extern void cpu_act(int act);
extern void cpu_pass(int side, int act);
extern int cpu_can_end(int side);

#define TURN_SIDE (*(volatile int *)0x0229dd48)
#define HYP_STATE REG(0x022c351c)
#define MAIN_STAGE REG(0x022c4254)
#define THINK_GAP (THINK_CAP_TICKS / 20)
#define ACT_BATTLE 3
#define ACT_END 5
#define PASS 4
#define PASS_ALT 5
#define FLAG_NOTE 7
#define FLAG_PASS_ALT 0x12

__attribute__((section(".think"), used)) volatile u32 think_box[5] = {0x4b4e4854};
static u32 think_kind, think_t0, think_last;

static int think_over(u32 kind)
{
    u32 now = (u32)os_get_tick();
    if (think_kind != kind || now - think_last > THINK_GAP)
        think_kind = 0;
    return think_kind && now - think_t0 > THINK_CAP_TICKS;
}

static void think_track(u32 kind, u32 busy)
{
    u32 now = (u32)os_get_tick();
    if (!busy) {
        if (think_kind == kind && now - think_t0 > think_box[1 + kind])
            think_box[1 + kind] = now - think_t0;
        think_kind = 0;
    } else if (!think_kind) {
        think_kind = kind;
        think_t0 = now;
    }
    think_last = now;
}

static void think_unwind(void)
{
    int n;
    think_kind = 0;
    think_box[1]++;
    for (n = 16; n && (HYP_STATE & 0xf000) && cpu_hyp_pop(); n--)
        ;
    HYP_STATE &= ~0xf000;
    for (n = 64; n && cpu_ai_pop(); n--)
        ;
}

static int drop_main(void)
{
    int side = TURN_SIDE;
    int act;
    think_unwind();
    MAIN_STAGE = 0;
    act = cpu_can_end(side) ? ACT_END : ACT_BATTLE;
    if (cpu_flag(FLAG_NOTE))
        cpu_note(side, 0, 0, act + 13);
    else
        cpu_act(act);
    cpu_end(side, 0, 0);
    return act;
}

static int drop_chain(int side)
{
    think_unwind();
    cpu_pass(side, cpu_flag(FLAG_PASS_ALT) ? PASS_ALT : PASS);
    cpu_end(side, 0, 0);
    return 0;
}

static int drop_trigger(int side)
{
    think_unwind();
    cpu_end(side, 0, 0);
    return 0;
}
#endif

int fast_main_phase(void)
{
#ifdef THINK_CAP_TICKS
    if (think_over(1)) {
        pending = 0;
        return drop_main();
    }
#endif
    int r = cpu_main_phase();
    pending = r < 1 && (MAIN_DONE_FLAG == 0 || MAIN_HOLD_FLAG != 0);
#ifdef THINK_CAP_TICKS
    think_track(1, r < 0);
#endif
    return r;
}

int fast_chain(int a, int b, int c, int d)
{
#ifdef THINK_CAP_TICKS
    if (think_over(2)) {
        pending = 0;
        return drop_chain(a);
    }
#endif
    int r = cpu_chain(a, b, c, d);
    pending = r < 0;
#ifdef THINK_CAP_TICKS
    think_track(2, pending);
#endif
    return r;
}

int fast_trigger(int a, int b, int c, int d)
{
#ifdef THINK_CAP_TICKS
    if (think_over(3)) {
        pending = 0;
        return drop_trigger(a);
    }
#endif
    int r = cpu_trigger(a, b, c, d);
    pending = r == -1;
#ifdef THINK_CAP_TICKS
    think_track(3, pending);
#endif
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
