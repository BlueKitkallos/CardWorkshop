#include "../w11fix.h"

#define HAND_SCAN ((int (*)(u32, u32, u32))0x02340ed5)
#define RAVINE_FIELD_EVAL ((int (*)(FxCtx *, FxCtx *, u32))0x023107d9)

int fix_summon_scan(u32 p, u32 start, u32 x)
{
    if (start == 0 && FX_CONTROLLER[p & 1] == FX_CPU) {
        if (FX_FREE_ZONES(p) > 0 && fix_launcher_lead(p) && fix_queue_hand_summon(p, 0, 4)) {
            return 0;
        }
        if (FX_TURN_PLAYER == (p & 1) && (FX_PHASE == 2 || FX_PHASE == 4) && fix_gy_summon(p)) {
            return 1000;
        }
    }
    return HAND_SCAN(p, start, x);
}

int fix_ravine_field_eval(FxCtx *e, FxCtx *link, u32 param)
{
    if (fix_ravine_hold(FX_CTX_PLAYER(e))) {
        return 0;
    }
    return RAVINE_FIELD_EVAL(e, link, param);
}

void fix_duel_clear(void *dst, u32 size)
{
    ((void (*)(void *, u32))0x0214c1d4)(dst, size);
    fix_cpu_reset();
}
