#include "w11packs.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef int s32;

#define STORE ((volatile u8 *)0x02158d10)
#define ENTRY(i) (STORE + 0x30 + (i) * 0x34)
#define STORE_COUNT (*(volatile u16 *)(STORE + 0x10a4))
#define STORE_MASK ((volatile u32 *)(STORE + 0x10ac))
#define STORE_ANY (*(volatile u32 *)(STORE + 0x10b8))
#define STORE_LAYOUT ((volatile u32 *)(STORE + 0x10c4))
#define STORE_STOCK (*(volatile u16 *)(STORE + 0x10d4))
#define ENTRIES 0x51
#define STOCK 50
#define STRUCT_FIRST 0x3d
#define RECORDS 0x021262ccu
#define STRUCT_OFFER (*(volatile u16 *)0x02126880)
#define STRUCT_STATE (*(volatile u8 *)0x02127392)
#define LIST_MAX 0x10d2
#define SAVE_OFFSET 0x3ff00u
#define SAVE_MAGIC 0x31504357u

extern void store_box_roll(volatile u8 *store, u32 pack);
extern int store_bought(volatile u8 *store, u32 entry);
extern int pack_card_list(u32 pack, u32 *out, u32 max);
extern u32 card_owned(u32 id);
extern void *heap_alloc(u32 size, u32 align, u32 kind);
extern void heap_free(void *p);
extern int backup_write(u32 off, const void *src, u32 n);
extern int backup_read(u32 off, void *dst, u32 n);
extern volatile u32 save_error;

typedef struct {
    u32 magic;
    u16 first;
    u16 count;
    u32 sum;
    u8 rec[W11_PK_MAX][4];
} PackSave;

static PackSave pk;
static const u16 packs[][2] = { W11_PK_TABLE };

static int added(u32 id)
{
    return id >= W11_PK_FIRST;
}

static int booster(u32 id)
{
    return id < STRUCT_FIRST || added(id);
}

static volatile u8 *record(u32 id)
{
    if (added(id) && id < W11_PK_FIRST + W11_PK_MAX)
        return pk.rec[id - W11_PK_FIRST];
    return (volatile u8 *)(RECORDS + id * 4);
}

u32 w11pk_slot(u32 pack)
{
    if (added(pack))
        return W11_PK_SLOT;
    return pack >= 0x20 && pack <= 0x2a;
}

int w11pk_append(volatile u8 *e, int count)
{
    int k, n = 0, i;
    for (k = 0; k < W11_PK_COUNT && packs[k][0] && count + n < ENTRIES - 1; k++, n++, e += 0x34) {
        u32 id = packs[k][0];
        volatile u8 *r = record(id);
        if (!r[0])
            r[0] = 4;
        *(volatile u16 *)e = id;
        *(volatile u16 *)(e + 8) = packs[k][1];
        STORE_STOCK = STOCK;
        *(volatile u16 *)(e + 0xc) = STOCK;
        store_box_roll(STORE, id);
        *(volatile u16 *)(e + 0xc) = STORE_STOCK;
        *(volatile u16 *)(e + 0xa) = r[0];
        for (i = 0; i < 4; i++)
            ((volatile u32 *)(e + 0x18))[i] = STORE_LAYOUT[i];
        *(volatile u32 *)(e + 0x28) = r[1];
        if (STORE_STOCK)
            STORE_ANY = 1;
    }
    return n;
}

void w11pk_completion(volatile u8 *store)
{
    u32 *list = heap_alloc(LIST_MAX * 4, 4, 0);
    u32 i, n, own, pct;
    for (i = 0; i < *(volatile u16 *)(store + 0x10a4); i++) {
        volatile u8 *e = store + 0x30 + i * 0x34;
        u32 id = *(volatile u16 *)e;
        if (!booster(id)) {
            *(volatile s32 *)(e + 4) = -1;
            continue;
        }
        pack_card_list(id, list, LIST_MAX);
        for (n = 0, own = 0; list[n]; n++)
            own += card_owned(list[n]) != 0;
        pct = n ? own * 100 / n : 0;
        *(volatile u32 *)(e + 4) = pct;
        record(id)[2] = pct;
    }
    heap_free(list);
}

void w11pk_store_exit(volatile u8 *store)
{
    u32 i;
    for (i = 0; i < ENTRIES; i++) {
        volatile u8 *e = store + 0x30 + i * 0x34;
        u32 id = *(volatile u16 *)e;
        volatile u8 *r = record(id);
        if (added(id) || (*(volatile u32 *)(store + 0x10ac + (i >> 5) * 4) >> (i & 31) & 1))
            r[1] = *(volatile u32 *)(e + 0x28);
        if (store_bought(store, i) <= 0)
            continue;
        r[3] = 0;
        r[0] = 1;
        if (!booster(id)) {
            STRUCT_STATE = 0;
            STRUCT_OFFER &= 0xff;
        }
    }
}

static u32 save_sum(const PackSave *s)
{
    u32 h = s->magic ^ (s->first | (u32)s->count << 16), n;
    const u8 *p = &s->rec[0][0];
    for (n = 0; n < sizeof(s->rec); n++)
        h = (h << 5 | h >> 27) + p[n];
    return h;
}

void w11pk_clear(void)
{
    u32 n;
    u8 *p = &pk.rec[0][0];
    for (n = 0; n < sizeof(pk.rec); n++)
        p[n] = 0;
}

void w11pk_save(void)
{
    pk.magic = SAVE_MAGIC;
    pk.first = W11_PK_FIRST;
    pk.count = W11_PK_MAX;
    pk.sum = save_sum(&pk);
    save_error |= backup_write(SAVE_OFFSET, &pk, sizeof(pk)) == 0;
}

void w11pk_load(void)
{
    static PackSave tmp;
    u32 n;
    if (save_error)
        return;
    if (!backup_read(SAVE_OFFSET, &tmp, sizeof(tmp))) {
        save_error = 1;
        return;
    }
    if (tmp.magic != SAVE_MAGIC || tmp.first != W11_PK_FIRST || tmp.count != W11_PK_MAX || tmp.sum != save_sum(&tmp)) {
        w11pk_clear();
        return;
    }
    for (n = 0; n < sizeof(pk.rec); n++)
        (&pk.rec[0][0])[n] = (&tmp.rec[0][0])[n];
}


/* The stock compactor assumes entry == pack id - 1 and stops at 60 entries. */
void community_box_compact_words(volatile u32 *layout)
{
    volatile u32 result[4];
    u32 next = 0;
    for (u32 i = 0; i < 4; i++) result[i] = 0;
    for (u32 i = 0; i < 64; i++) {
        u32 rarity = (layout[i / 16] >> (2 * (i % 16))) & 3;
        if (rarity) {
            result[next / 16] |= rarity << (2 * (next % 16));
            next++;
        }
    }
    for (u32 i = 0; i < 4; i++)
        layout[i] = result[i];
}

void community_box_compact(void)
{
    u32 count = STORE_COUNT;
    if (count > ENTRIES)
        count = ENTRIES;
    for (u32 i = 0; i < count; i++) {
        volatile u8 *entry = ENTRY(i);
        if (booster(*(volatile u16 *)entry) && store_bought(STORE, i) > 0)
            community_box_compact_words((volatile u32 *)(entry + 0x18));
    }
}
