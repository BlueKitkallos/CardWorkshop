/* No-input native shop probe. Boot callback constructs a fresh profile and
 * enters the shop directly; it does not navigate menus or play a duel. */
typedef unsigned int u32;
typedef unsigned short u16;
#define W(a) (*(volatile u32 *)(a))
#define STORE ((volatile unsigned char *)0x02158d10)
#define ENTRY(i) (STORE + 0x30 + (i) * 0x34)
#define CTX 0x02159f48u
extern void body_init(void), pad_read(void);
extern void scene_change(u32, u32, u32);
extern int pack_card_list(u32, u32 *, u32);
extern void shop_draw(u32, volatile u16 *, u32);
extern int shop_filter(u32, u32, u32 *, u32);
extern u32 char_deck(u32);
extern u32 duelist_chara(u32);
extern void load_side(u32, u32);
extern u32 team_pair(u32);
extern const char *team_name(u32);
#define SIDE1(a, size) ((a) + (size))
struct {
    u32 magic, state, frame, count, cpu_deck;
    struct { u32 id, count, rarity_count[4], probe_mask; u16 draw[6]; } packs[4];
    struct { u32 chara, deck, portrait, rating, key, talk, main_count; u16 main[4]; char name[60], deck_name[60]; } cpus[2];
    struct { u32 stock0, pair, member[2]; char name[40], member_name[60]; } tags[2];
} community_smoke = {0x434d534bu};

static void copy_text(char *out, u32 from)
{
    for (u32 i = 0; i < 58; i++) out[i] = *(volatile char *)(from + i);
    out[58] = 0;
}

static void probe_tags(void)
{
    for (u32 k = 0; k < 2; k++) {
        u32 team = 49 + k, pair = team_pair(team);
        const char *name = team_name(team);
        community_smoke.tags[k].stock0 = team_pair(0);
        community_smoke.tags[k].pair = pair;
        for (u32 i = 0; i < 39 && name[i]; i++) community_smoke.tags[k].name[i] = name[i];
        for (u32 m = 0; m < 2; m++)
            community_smoke.tags[k].member[m] = duelist_chara(m ? pair >> 16 : pair & 0xffff);
        load_side(1, community_smoke.tags[k].member[0]);
        copy_text(community_smoke.tags[k].member_name, SIDE1(0x020b8888, 0x3a));
    }
}

static void probe_cpus(void)
{
    const u32 duelists[2] = {0x71, 0xd5};
    for (u32 k = 0; k < 2; k++) {
        u32 chara = duelist_chara(duelists[k]);
        load_side(1, chara);
        community_smoke.cpus[k].chara = chara;
        community_smoke.cpus[k].deck = W(SIDE1(0x020b8874, 4));
        community_smoke.cpus[k].portrait = W(SIDE1(0x020b8b18, 4));
        community_smoke.cpus[k].rating = *(volatile u16 *)SIDE1(0x020b8a68, 2);
        community_smoke.cpus[k].key = *(volatile u16 *)SIDE1(0x020b8a60, 2);
        community_smoke.cpus[k].talk = *(volatile unsigned char *)SIDE1(0x020b8b38, 0x1c);
        community_smoke.cpus[k].main_count = W(SIDE1(0x020b8c18, 0xc0));
        for (u32 i = 0; i < 4; i++)
            community_smoke.cpus[k].main[i] = *(volatile u16 *)(SIDE1(0x020b8c18, 0xc0) + 0xc + 2 * i);
        copy_text(community_smoke.cpus[k].name, SIDE1(0x020b8888, 0x3a));
        copy_text(community_smoke.cpus[k].deck_name, SIDE1(0x020b8974, 0x3a));
    }
}

int smoke_start(void)
{
    if (community_smoke.state) return 0;
    community_smoke.state = 1;
    W(0x021264a4) = (W(0x021264a4) & ~0x700u) | 0x100u;
    body_init();
    scene_change(7, 10, 0x0214d6f4);
    return 0;
}

static void probe(void)
{
    const u32 want[4] = {1,2,3,97};
    static u32 ids[4306], pool[4306];
    community_smoke.count = *(volatile u16 *)(STORE + 0x10a4);
    community_smoke.cpu_deck = char_deck(465);
    for (u32 k = 0; k < 4; k++) {
        for (u32 i = 0; i < community_smoke.count; i++) {
            if (*(volatile u16 *)ENTRY(i) != want[k]) continue;
            community_smoke.packs[k].id = want[k];
            community_smoke.packs[k].count = pack_card_list(want[k], ids, 4306);
            u32 *list = (u32 *)(CTX + 0x88bc);
            for (u32 n=0; n <= community_smoke.packs[k].count; n++) list[n]=ids[n];
            for (u32 mask=0; mask<4; mask++) {
                u32 n = shop_filter(CTX, i, pool, 1u << mask);
                community_smoke.packs[k].rarity_count[mask] = n;
                for (u32 j=0; j<n; j++) if(pool[j]==4007) community_smoke.packs[k].probe_mask |= 1u<<mask;
            }
            W((u32)ENTRY(i)+0x10) |= 1;
            *(volatile u16 *)(CTX + 0xcc10)=1;
            shop_draw(CTX,community_smoke.packs[k].draw,0);
            W((u32)ENTRY(i)+0x10) &= ~1u;
            *(volatile u16 *)(CTX + 0xcc10)=0;
        }
    }
    probe_cpus();
    probe_tags();
    community_smoke.state=3;
}
void smoke_frame(void)
{
    pad_read();
    if (community_smoke.state==1 && W((u32)STORE+0x10d8) && *(volatile u16 *)(STORE+0x10a4)) {
        community_smoke.state=2;
        community_smoke.frame=W(0x020b7cc4);
    } else if (community_smoke.state==2 && W(0x020b7cc4)-community_smoke.frame>60) probe();
}
