#include "w11fix.h"

void fix_final_forecast(u32 player, u32 slot, u32 target, u16 *out)
{
    FxSlot *t;
    ((void (*)(u32, u32, u32, u16 *))0x0226a3a9)(player, slot, target, out);
    if (target > 4) {
        return;
    }
    t = &FX_PLAYERS[(player & 1) ^ 1].slot[target];
    if ((t->card & 0x3fff) && !t->active) {
        *out &= ~0xe;
    }
}

u32 fix_rental_key(u32 menu, u32 index)
{
    u16 row[6];
    if (index >= 30) {
        return 0;
    }
    ((void (*)(const char *, u32, u32, void *))0x02017861)("/Bin/EnemyStatus.bin", (0x11e + index % 15) * 12, 12, row);
    return row[5];
}
