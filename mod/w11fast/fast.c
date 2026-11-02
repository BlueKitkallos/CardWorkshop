typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

extern u32 load_file(const char *path, u32 heap, u32 flags);
extern u32 file_open(u32 *file, const char *path, char *buf);
extern void file_read(const char *path, void *dst, u32 offset, u32 size);
extern void free_mem(u32 p);
extern int duel_setup(void);
extern int duel_exit(void);
extern u32 card_index(u32 id);
extern u32 alloc_mem(u32 size, int align, u32 flags);
extern void zone_filter_build(u8 *filter);
extern u32 heap_create(u32 start, u32 size, u32 opt);
extern u32 prop_stock(u32 index);
extern const u32 *prop_record(u32 id);

#define EXIT_FRAME (*(volatile u32 *)0x022943fc)
#define EXIT_LAST_FRAME 15
#define WHOLE_TABLE (*(const u32 *)(*(const u32 *)0x02121a6c + 0x38))
#define CHUNK 1024
#define ZONE_FILTER 256
#define PROP_CAP 512

static const char prop_path[] = "bin2/CARD_Prop.bin";

u32 genre_table;
u32 genre_count = 0;
u32 prop_block;
u32 prop_n;
u32 prop_words;
u32 prop_used;
u8 *prop_frame;
u32 *prop_bits;
u16 *prop_base;
u32 *prop_recs;
u8 *zone_filter;

static void drop_tables(void)
{
    prop_n = 0;
    prop_block = 0;
    zone_filter = 0;
    genre_table = 0;
}

static __attribute__((cold)) void tables_load(void)
{
    u32 file[3], n, w, at, size, blk, tmp, i;
    char buf[256];
    if (!file_open(file, prop_path, buf))
        return;
    n = file[1] / 8;
    if (!n || n > 0x4000)
        return;
    w = (n + 31) >> 5;
    at = (n + 3) & ~3u;
    size = at + w * 4 + ((w * 2 + 3) & ~3u) + ZONE_FILTER + PROP_CAP * 8;
    blk = alloc_mem(size, 4, 0);
    if (!blk)
        return;
    tmp = alloc_mem(CHUNK, 32, 0);
    if (!tmp) {
        free_mem(blk);
        return;
    }
    prop_frame = (u8 *)blk;
    for (i = 0; i < n; i += CHUNK / 8) {
        u32 k, m = n - i < CHUNK / 8 ? n - i : CHUNK / 8;
        const u32 *src = (const u32 *)tmp;
        file_read(prop_path, (void *)tmp, i * 8, m * 8);
        for (k = 0; k < m; k++)
            prop_frame[i + k] = (src[2 * k + 1] & 0x3f) >> 1;
    }
    free_mem(tmp);
    prop_bits = (u32 *)(blk + at);
    prop_base = (u16 *)(blk + at + w * 4);
    zone_filter = (u8 *)prop_base + ((w * 2 + 3) & ~3u);
    prop_recs = (u32 *)(zone_filter + ZONE_FILTER);
    for (i = 0; i < w; i++) {
        prop_bits[i] = 0;
        prop_base[i] = 0;
    }
    zone_filter_build(zone_filter);
    prop_words = w;
    prop_used = 0;
    prop_block = blk;
    prop_n = n;
}

int fast_setup(void)
{
    int r = duel_setup();
    if (r && !prop_block)
        tables_load();
    if (r && !genre_table && genre_count)
        genre_table = load_file("bin2/CARD_Genre.bin", 4, 0);
    return r;
}

int fast_exit(void)
{
    if (EXIT_FRAME >= EXIT_LAST_FRAME) {
        u32 p[2] = { genre_table, prop_block };
        int i;
        drop_tables();
        for (i = 0; i < 2; i++)
            if (p[i])
                free_mem(p[i]);
    }
    return duel_exit();
}

u32 fast_heap_create(u32 start, u32 size, u32 opt)
{
    drop_tables();
    return heap_create(start, size, opt);
}

static inline __attribute__((always_inline)) u32 ones(u32 x)
{
    x = x - ((x >> 1) & 0x55555555u);
    x = (x & 0x33333333u) + ((x >> 2) & 0x33333333u);
    x = (x + (x >> 4)) & 0x0f0f0f0fu;
    return (x * 0x01010101u) >> 24;
}

static __attribute__((cold, noinline)) u32 prop_add(u32 i, u32 w, u32 m, u32 r)
{
    const u32 *src = (const u32 *)prop_stock(i);
    u32 *rec = prop_recs + 2 * r, k;
    for (k = 2 * prop_used; k > 2 * r; k -= 2) {
        prop_recs[k] = prop_recs[k - 2];
        prop_recs[k + 1] = prop_recs[k - 1];
    }
    rec[0] = src[0];
    rec[1] = src[1];
    prop_bits[w] |= m;
    for (k = w + 1; k < prop_words; k++)
        prop_base[k]++;
    prop_used++;
    return (u32)rec;
}

__attribute__((target("arm"))) u32 prop_hook(u32 i)
{
    if (i < prop_n) {
        u32 w = i >> 5, m = 1u << (i & 31), word = prop_bits[w];
        u32 r = prop_base[w] + ones(word & (m - 1));
        if (word & m)
            return (u32)(prop_recs + 2 * r);
        if (prop_used < PROP_CAP)
            return prop_add(i, w, m, r);
    }
    return prop_stock(i);
}

u32 frame_hook(u32 id)
{
    if (prop_n && !WHOLE_TABLE) {
        u32 i = card_index(id & 0x3fff) & 0x3fff;
        if (i < prop_n)
            return prop_frame[i];
    }
    return (prop_record(id)[1] & 0x3f) >> 1;
}

int genre_fast(u32 id, u32 *out)
{
    const u32 *t = (const u32 *)genre_table;
    u32 i;
    if (!t)
        return 0;
    i = card_index(id & 0x3fff) & 0x3fff;
    if (i >= genre_count)
        return 0;
    out[0] = t[2 * i];
    out[1] = t[2 * i + 1];
    return 1;
}
