#include "w11packs.h"
typedef unsigned int u32;
extern u32 original_pack_member(u32 id, u32 slot);
extern u32 original_pack_rarity(u32 id, u32 slot);
const u32 community_pack_extra[] = { W11_PK_EXTRA_TABLE };

static int extra_rarity(u32 id, u32 pack)
{
    u32 key = (id & 0x3fff) | (pack << 16);
    u32 lo = 0, hi = W11_PK_EXTRA_COUNT;
    while (lo < hi) {
        u32 mid = lo + (hi - lo) / 2;
        u32 row = community_pack_extra[mid + 2];
        u32 candidate = row & 0xffffff;
        if (candidate < key)
            lo = mid + 1;
        else if (candidate > key)
            hi = mid;
        else
            return row >> 24;
    }
    return -1;
}

u32 community_pack_member(u32 id, u32 slot, u32 pack)
{
    return extra_rarity(id, pack) >= 0 ? pack : original_pack_member(id, slot);
}

u32 community_pack_rarity(u32 id, u32 pack)
{
    int rarity = extra_rarity(id, pack);
    u32 slot = pack >= 97 ? 2 : (pack >= 32 && pack <= 42);
    return rarity >= 0 ? (u32)rarity : original_pack_rarity(id, slot);
}
