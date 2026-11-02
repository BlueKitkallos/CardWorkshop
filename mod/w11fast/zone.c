typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned long long u64;

extern int card_is_valid(u32 id);
extern int zone_modified_id(u32 player, int slot, u32 card);
extern unsigned char *zone_filter;

#define PLAYER_BASE 0x0229ac94u
#define PLAYER_SIZE 0xb3cu
#define MOD_BASE 0x0229d33cu
#define NAME_LIST ((const short *)0x0209ba8c)
#define NAME_LIST_N 9
#define FOLLOW_LIST ((const short *)0x0209c8f8)
#define FOLLOW_LIST_N 13

static inline __attribute__((always_inline)) int in_list(int id, const short *t, int n)
{
    int lo = 0, hi = n - 1, mid;
    while (lo < hi) {
        mid = (lo + hi) >> 1;
        if (t[mid] < id)
            lo = mid + 1;
        else
            hi = mid;
    }
    return t[lo] == id;
}

static inline __attribute__((always_inline)) int listed(const unsigned char *f, int id, const short *t, int n)
{
    return (!f || f[(id >> 3) & 0xff] >> (id & 7) & 1) && in_list(id, t, n);
}

__attribute__((cold)) void zone_filter_build(unsigned char *f)
{
    int i;
    for (i = 0; i < 256; i++)
        f[i] = 0;
    for (i = 0; i < NAME_LIST_N; i++)
        f[(NAME_LIST[i] >> 3) & 0xff] |= 1 << (NAME_LIST[i] & 7);
    for (i = 0; i < FOLLOW_LIST_N; i++)
        f[(FOLLOW_LIST[i] >> 3) & 0xff] |= 1 << (FOLLOW_LIST[i] & 7);
}

__attribute__((target("arm"))) u64 zone_card_id(u32 player, int slot, int follow)
{
    u32 base = PLAYER_BASE + (player & 1) * PLAYER_SIZE + slot * 20;
    u32 id = *(volatile u32 *)(base + 0x34) & 0x3fff;
    if (slot > 4) {
        if (id == 0x2150) {
            int r = zone_modified_id(player, slot, 0x2150);
            id = r < 0 ? 0x2150 : (u32)r;
        }
    } else if (listed(zone_filter, (int)id, NAME_LIST, NAME_LIST_N)) {
        u32 node = *(volatile u16 *)(base + 0x3e);
        while (node) {
            const volatile u16 *e = (const volatile u16 *)(MOD_BASE + node * 10);
            u32 kind = e[1] & 0xf, card = e[0];
            node = e[4];
            if (kind == 2 || (kind == 3 && card == 0x221e)) {
                if ((card == 0x1a74 || card == 0x1e7e || card == 0x221e) && card_is_valid(e[2]))
                    id = e[2];
            }
        }
    } else if (follow && listed(zone_filter, (int)id, FOLLOW_LIST, FOLLOW_LIST_N)) {
        int r = zone_modified_id(player, slot, 0x1dda);
        if (r > 0)
            id = (u32)r;
    }
    return (u64)(u32)follow << 32 | id;
}
