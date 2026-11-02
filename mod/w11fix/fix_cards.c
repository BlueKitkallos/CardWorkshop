#include "w11fix.h"

#define ARCH_GUSTO 95
#define CARD_NAME_ID ((u32 (*)(u32, u32))0x021a3321)
#define TARGET_CRITERIA ((u32 (*)(FxCtx *, u32, u32, u32))0x021d6e41)
#define SPEED_REQUIREMENT ((const u32 *(*)(u32))0x02023699)

u32 fx_frame(u32 id)
{
    return id ? FX_CARD_FRAME(id) : 0;
}

static int target_side_taken(FxCtx *e, u32 player, u32 slot)
{
    u32 i, n = e->ntargets < 5 ? e->ntargets : 5;
    for (i = 0; i < n; i++) {
        u32 t = e->targets[i];
        if ((t & 1) == (player & 1) && ((t >> 1) & 0xf) != slot) {
            return 1;
        }
    }
    return 0;
}

u32 fix_reeze_filter(FxCtx *e, u32 player, u32 slot)
{
    if (!TARGET_CRITERIA(e, player, slot, 0x10410) || target_side_taken(e, player, slot)) {
        return 0;
    }
    if ((player & 1) != (e->controller & 1)) {
        return 1;
    }
    return FX_PLAYERS[player & 1].slot[slot].active && FX_ARCHETYPE(CARD_NAME_ID(player, slot), ARCH_GUSTO);
}

static u32 base_id_call(FxCtx *e, u32 fn, u32 player, u32 slot)
{
    const u32 *req = SPEED_REQUIREMENT(e->card_id);
    u16 id = e->card_id;
    u32 r;
    if (req && (*req >> 16)) {
        e->card_id = *req >> 16;
    }
    r = ((u32 (*)(FxCtx *, u32, u32))(fn | 1))(e, player, slot);
    e->card_id = id;
    return r;
}

u32 fix_faustian_filter(FxCtx *e, u32 player, u32 slot)
{
    return base_id_call(e, 0x021e3918, player, slot);
}

u32 fix_unibird_filter(FxCtx *e, u32 player, u32 slot)
{
    if ((player & 1) == (e->controller & 1) && slot == e->slot) {
        return 0;
    }
    return ((u32 (*)(FxCtx *, u32, u32))0x021e3f99)(e, player, slot);
}

u32 fix_chain_whirlwind_can(FxCtx *e)
{
    u32 ev = e->event;
    if (e->kind != 0x1d || !(ev & 0x8000) || (ev & 0x800000) || (ev & 0x40000000) || ((ev >> 10) & 0xf) > 10) {
        return 0;
    }
    return ((u32 (*)(FxCtx *))0x021f21a9)(e);
}

u32 fix_elma_can(FxCtx *e)
{
    if (e->event & 0x40000000) {
        return 0;
    }
    return ((u32 (*)(FxCtx *))0x021f0bdd)(e);
}

u32 fix_aklys_can(FxCtx *e)
{
    if (e->event & 0x40000000) {
        return 0;
    }
    return ((u32 (*)(FxCtx *))0x0224a115)(e);
}

static u32 through_other_effect(FxCtx *e)
{
    return ((u32 (*)(FxCtx *))0x021d2bc9)(e);
}

u32 fix_triangle_can(FxCtx *e, u32 a)
{
    u8 pass = e->unk7;
    u32 r;
    if (!through_other_effect(e)) {
        return ((u32 (*)(FxCtx *, u32))0x0220279d)(e, a);
    }
    e->unk7 = 1;
    r = (int)((u32 (*)(FxCtx *, u32, u32))0x021f0115)(e, (e->other ^ e->controller) & 1, e->card_id) > 0;
    e->unk7 = pass;
    return r;
}

u32 fix_triangle_cost(FxCtx *e, u32 a, u32 b, u32 c)
{
    if (through_other_effect(e)) {
        e->target_total = 0;
        return 1;
    }
    return ((u32 (*)(FxCtx *, u32, u32, u32))0x021e9215)(e, a, b, c);
}

u32 fix_triangle_resolve(FxCtx *e, u32 a, u32 b, u32 c)
{
    if (*(volatile u32 *)0x0229ab6c == 0x7f && through_other_effect(e)) {
        return 0;
    }
    return ((u32 (*)(FxCtx *, u32, u32, u32))0x0222f349)(e, a, b, c);
}

u32 fix_book_of_life_select(FxCtx *e, u32 a, u32 b, u32 c)
{
    volatile u32 *step = (volatile u32 *)0x0229ab7c;
    u32 s = *step;
    if (SPEED_REQUIREMENT(e->card_id) && (s == 0 || s == 3)) {
        ((void (*)(u32, u32))0x0219a819)(e->controller, s ? 0x56 : 0xf0);
        *step = s + 1;
        return 0;
    }
    return ((u32 (*)(FxCtx *, u32, u32, u32))0x022373d5)(e, a, b, c);
}

static int synchro_summon_in_events(void)
{
    u32 i, n = *(volatile u32 *)0x0229abac, f;
    for (i = 0; i < n; i++) {
        if (((volatile u8 *)0x0229abb4)[i] != 9) {
            continue;
        }
        f = fx_frame(*(volatile u32 *)(0x0229c33c + 8 * (((volatile u32 *)0x0229abd4)[i] & 0x1ff)) & 0x3fff);
        if (f >= 17 && f <= 19) {
            return 1;
        }
    }
    return 0;
}

static int rule_destroyed_equip(u32 ev)
{
    u32 zone = (ev >> 10) & 0xf;
    return (ev & 0x40000000) && zone >= 5 && zone <= 9;
}

u32 fix_equip_timing(FxCtx *e)
{
    u32 r = ((u32 (*)(FxCtx *))0x021ee0e1)(e);
    if (r && e->kind == 0x1d && rule_destroyed_equip(e->event) && synchro_summon_in_events()) {
        return 0;
    }
    return r;
}

u32 fix_vylon_element_count(FxCtx *e)
{
    u32 r = ((u32 (*)(FxCtx *))0x0223913d)(e), ev = e->event, id;
    u16 *count = (u16 *)((u8 *)e + 0x18);
    if (*count || ((ev >> 9) & 1) != e->controller || !rule_destroyed_equip(ev) || (ev & 0x800000) ||
        !(ev & 0x20000) || !(ev & 0x8000) || !synchro_summon_in_events()) {
        return r;
    }
    id = *(volatile u32 *)(0x0229c33c + 8 * (ev & 0x1ff)) & 0x3fff;
    if (((u32 (*)(u32))0x02023ed5)(id) &&
        (((u32 (*)(u32))0x02029e61)(id) || ((u32 (*)(u32))0x0202abe9)(id) == 3)) {
        *count = 1;
    }
    return r;
}

void fix_summon_mark(void)
{
    u32 player = (*(volatile u16 *)0x02299b60 >> 15) & 1;
    volatile u32 *turn = (volatile u32 *)(0x0229adb4 + player * 0xb3c);
    u32 before = *turn, first = *(volatile u32 *)0x0229a370 == 0;
    ((void (*)(void))0x021c2a39)();
    if (first && *(volatile u16 *)0x02299b66 == 7) {
        *turn = (*turn & ~0x40000u) | (before & 0x40000) | 0x10000;
    }
}
