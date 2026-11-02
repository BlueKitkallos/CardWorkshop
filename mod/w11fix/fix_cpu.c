#include "w11fix.h"

#define ARCH_INFERNITY 71
#define ARCH_DRAGUNITY 74
#define TYPE_DRAGON 1
#define ID_DGN_DUX 8388
#define ID_DGN_LEGIONNAIRE 8389
#define ID_DRAGON_RAVINE 9049
#define ID_LAUNCHER 8823
#define PROC_ROWS ((const u32 *)0x0228ddf8)
#define PROC_ROW_N 60
#define PROC_SUMMON 0x0224c7c1
#define ZONE_OPEN ((u32 (*)(u32, u32))0x0225e51d)
#define SUMMON_OPTIONS ((u32 (*)(u32, u32))0x0225d6d5)
#define MONSTER_STATS ((void (*)(u32, u32, u32 *))0x021b44b5)

static int is_monster(u32 id)
{
    return id != 0 && FX_IS_MONSTER(id);
}

static u32 prop1(u32 id)
{
    return id ? FX_CARD_PROP(id)[1] : 0;
}

static int hand_has(u32 p, u32 id)
{
    FxPlayer *ps = &FX_PLAYERS[p & 1];
    for (u32 i = 0; i < ps->hand_count; i++) {
        if (FX_ID(ps->hand[i]) == id) {
            return 1;
        }
    }
    return 0;
}

static int gy_has(u32 p, int (*pred)(u32))
{
    FxPlayer *ps = &FX_PLAYERS[p & 1];
    for (u32 i = 0; i < ps->gy_count; i++) {
        if (pred(FX_ID(ps->gy[i]))) {
            return 1;
        }
    }
    return 0;
}

static int dgn_equip_target(u32 id)
{
    u32 w = prop1(id);
    return is_monster(id) && ((w >> 17) & 0x1f) == TYPE_DRAGON && ((w >> 10) & 0xf) <= 3 &&
           FX_ARCHETYPE(id, ARCH_DRAGUNITY);
}

static int infernity_monster(u32 id)
{
    return is_monster(id) && FX_ARCHETYPE(id, ARCH_INFERNITY);
}

u32 fix_ns_allowed(u32 p, u32 index)
{
    volatile u32 *mode = (volatile u32 *)0x0229dde0, *mode2 = (volatile u32 *)0x0229dde8, *who = (volatile u32 *)0x0229de08;
    u32 m0 = *mode, m1 = *mode2, w = *who;
    *who = p;
    *mode = *mode2 = 2;
    u32 mask = ((u32 (*)(u32, u32, u32))0x0224bc41)(p, FX_ZONE_HAND, index);
    *mode = m0;
    *mode2 = m1;
    *who = w;
    return (mask & 0x10) && (SUMMON_OPTIONS(p, FX_UID(FX_PLAYERS[p & 1].hand[index])) & 0x10);
}

u32 fix_queue_hand_summon(u32 p, u32 index, u32 kind)
{
    if (*(volatile u32 *)0x0229ddf0 || !fix_ns_allowed(p, index)) return 0;
    *(volatile u32 *)0x0229de08 = p;
    FX_ACTION_QUEUE(p, FX_ZONE_HAND, index, kind);
    *(volatile u32 *)0x0229ddf0 = 1;
    return 1;
}

u32 fix_ravine_feeds(u32 p)
{
    return (hand_has(p, ID_DGN_DUX) || hand_has(p, ID_DGN_LEGIONNAIRE)) && !gy_has(p, dgn_equip_target);
}

u32 fix_ravine_hold(u32 p)
{
    FxPlayer *ps = &FX_PLAYERS[p & 1];
    return FX_CONTROLLER[p] == FX_CPU && ps->hand_count == 1 && is_monster(FX_ID(ps->hand[0])) &&
           fix_ns_allowed(p, 0);
}

int fix_mode_answer(void *ctx, u32 mask)
{
    FxCtx *e = ctx;
    u32 p = FX_CTX_PLAYER(e);
    if (e->card_id == ID_DRAGON_RAVINE && (mask & 3) == 3 && FX_CONTROLLER[p] == FX_CPU) {
        return fix_ravine_feeds(p);
    }
    return ((int (*)(void *, u32))(0x023901c0 | 1))(ctx, mask);
}

static int gy_procedure(u32 id)
{
    for (u32 r = 0; r < PROC_ROW_N; r++) {
        const u32 *row = PROC_ROWS + 4 * r;
        if (row[0] == id && row[1] == FX_ZONE_GY && row[3] == PROC_SUMMON) {
            return 1;
        }
    }
    return 0;
}

static int max_face_up_atk(u32 p)
{
    int best = 0;
    for (u32 s = 0; s < 5; s++) {
        FxSlot *f = &FX_PLAYERS[p & 1].slot[s];
        if (!FX_ID(f->card) || !f->active) {
            continue;
        }
        u32 out[10];
        MONSTER_STATS(p & 1, s, out);
        int a = (s32)out[4];
        best = a > best ? a : best;
    }
    return best;
}

static u32 gy_ss_tried[2];

void fix_cpu_reset(void)
{
    gy_ss_tried[0] = gy_ss_tried[1] = 0;
}

u32 fix_gy_summon(u32 p)
{
    FxPlayer *ps = &FX_PLAYERS[p & 1];
    int keep = max_face_up_atk(p);
    for (u32 i = 0; i < ps->gy_count; i++) {
        u32 w = ps->gy[i], id = FX_ID(w), key = (FX_TURN_COUNT + 1) << 16 | FX_UID(w);
        if (gy_ss_tried[p & 1] != key && gy_procedure(id) && FX_CARD_ATK(id) > keep && (ZONE_OPEN(p, FX_UID(w)) & 4)) {
            gy_ss_tried[p & 1] = key;
            FX_ACTION_QUEUE(p, FX_ZONE_GY, i + 1, 2);
            return 1;
        }
    }
    return 0;
}

u32 fix_launcher_lead(u32 p)
{
    FxPlayer *ps = &FX_PLAYERS[p & 1];
    if (ps->hand_count != 1 || FX_FREE_ZONES(p) <= 1 || !gy_has(p, infernity_monster)) {
        return 0;
    }
    for (u32 s = 5; s < 10; s++) {
        FxSlot *f = &ps->slot[s];
        if (f->active && FX_ID(f->card) == ID_LAUNCHER) {
            return 1;
        }
    }
    return 0;
}
