/* Story duel setup. The script is unloaded during launch, so copy the extension
 * into resident RAM. Opening order is applied once; explicit future draws are
 * replanted only after a real shuffle. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define REG(a) (*(volatile u32 *)(a))
#define PLAYER(s) (0x0229ac94u + (s) * 0xb3cu)
#define CFG_SEED REG(0x020b8bec)
#define CFG_SIDE REG(0x020b8bf0)
#define CFG_FIRST REG(0x020b8c14)
#define CONTROL ((volatile u32 *)0x020b8bf4)
#define STORY_DUEL ((void (*)(const u16 *, const char *))0x02016d69)
#define CFG_RULE REG(0x020b8f18)
#define RULE_TOP_HAND10 0xf
#define DUEL_RESULT REG(0x0229dd64)
#define DAMAGE_EFFECT REG(0x02298bc0)
#define DAMAGE_BATTLE REG(0x02298bc4)
#define RETURN_SCRIPT ((volatile char *)0x021235c4)
#define REPLAY_BUF (*(volatile u32 **)0x020b9900)
#define REPLAY_DECLINE ((u32 (*)(void))0x0202daf5)
#define SET_CALLBACK ((void (*)(u32))0x02014ff1)
#define DUEL_LAUNCH 0x02019359u
#define VAR_DUEL_TAG 3
#define FLAG_DUEL_PENDING 10024
#define F_SPECTATE 1u
#define F_MUST_DAMAGE 2u
#define F_HAND10 4u
#define SMALL __attribute__((optimize("Os"), noinline))
#ifdef STORY_DUEL_TEST
extern void story_test_shuffle(u32 side);
extern void story_test_cmd(u32 op, u32 a, u32 b, u32 c);
extern void story_test_set(u32 id, u32 v);
#define SHUFFLE story_test_shuffle
#define CMD_PUSH story_test_cmd
#define STORY_SET story_test_set
#else
#define SHUFFLE ((void (*)(u32))0x021a7b7d)
#define CMD_PUSH ((void (*)(u32, u32, u32, u32))0x021c3bc9)
#define STORY_SET ((void (*)(u32, u32))0x0201b2ad)
#endif

extern u32 vm_state;
extern void vm_story_begin(void);
u32 story_spectate;
u32 story_setup_error;
struct StoryPlan { u16 turn, card; u8 side, action, phase, reserved; };
struct StoryField { u16 card; u8 side, zone; };
struct StorySetup { u16 version, flags; u32 seed; u16 slots[2][60]; u16 nplans, reserved; struct StoryPlan plans[16]; u32 draws[2][2]; struct StoryField field[8]; };
struct StorySetup story_setup;
static u32 setup_pending;
static u32 replay_skip;
static u32 field_taken;
static u32 rule_set;
static u32 plans_done;
static u32 main_inflight;
static u32 normal_draw_turn[2];
u32 story_next_main;
u32 story_plan_taken;
struct InitialDecks { u32 count[2]; u16 cards[2][60]; } story_initial_decks;

static u32 setup_valid(void)
{
    return story_setup.version == 2 && !(story_setup.flags & ~(F_SPECTATE | F_MUST_DAMAGE | F_HAND10));
}

SMALL static void setup_rules(void)
{
    field_taken = 0;
    rule_set = setup_pending && (story_setup.flags & F_HAND10);
    if (rule_set) CFG_RULE = RULE_TOP_HAND10;
}

void story_finish(void)
{
    if (rule_set) CFG_RULE = 0;
    rule_set = 0;
    setup_pending = 0;
    main_inflight = 0;
}

SMALL void story_result(void)
{
    const char *s = "data/black01.ws";
    u32 i = 0;
    replay_skip = story_spectate;
    if (!setup_pending || !(story_setup.flags & F_MUST_DAMAGE) || DUEL_RESULT != 2 || DAMAGE_EFFECT || DAMAGE_BATTLE)
        return;
    do RETURN_SCRIPT[i] = s[i]; while (s[i++]);
    STORY_SET(VAR_DUEL_TAG, 0);
    STORY_SET(FLAG_DUEL_PENDING, 1);
}

SMALL void story_replay_prompt(u32 scene)
{
    if (!replay_skip) {
        SET_CALLBACK(scene);
        return;
    }
    replay_skip = 0;
    *REPLAY_BUF = 0;
    REPLAY_DECLINE();
    SET_CALLBACK(DUEL_LAUNCH);
}

SMALL void story_start_cmd(u32 op, u32 a, u32 b, u32 c)
{
    u32 k;
    CMD_PUSH(op, a, b, c);
    for (k = 0; k < 8; k++) {
        const struct StoryField *f = &story_setup.field[k];
        if (field_taken & (1u << k))
            CMD_PUSH(0x43 | (f->side ? 0x8000 : 0), f->side | f->zone << 1 | 0x4000, f->card, 0);
    }
    field_taken = 0;
}

void story_config(const struct StorySetup *src)
{
    u32 i;
    vm_story_begin();
    for (i = 0; i < sizeof(story_setup); i++) ((u8 *)&story_setup)[i] = ((const u8 *)src)[i];
    setup_pending = setup_valid();
    story_spectate = setup_pending && (story_setup.flags & F_SPECTATE);
    setup_rules();
    story_setup_error = 0;
    plans_done = story_plan_taken = 0;
    main_inflight = 0;
    normal_draw_turn[0] = normal_draw_turn[1] = 0;
    story_initial_decks.count[0] = story_initial_decks.count[1] = 0;
    vm_state = story_spectate ? 3 : 0;
}

void story_duel(const u8 *block, const char *ret)
{
    u16 native[30];
    u32 i;
    const u8 *src = block + 60;
    u8 *dst = (u8 *)&story_setup;
    vm_story_begin();
    setup_pending = 0;
    story_spectate = 0;
    story_setup_error = 0;
    plans_done = story_plan_taken = 0;
    main_inflight = 0;
    normal_draw_turn[0] = normal_draw_turn[1] = 0;
    story_initial_decks.count[0] = story_initial_decks.count[1] = 0;
    /* Normal story duels must also clear a previous spectator session. */
    vm_state = 0;
    for (i = 0; i < 30; i++) native[i] = block[i * 2] | block[i * 2 + 1] << 8;
    if ((native[0] & 0x8000) && native[11] == 0x5344) {
        native[0] &= 0x7fff;
        native[11] = 0;
        for (i = 0; i < sizeof(story_setup); i++) dst[i] = src[i];
        setup_pending = setup_valid();
    }
    STORY_DUEL(native, ret);
    setup_rules();
    if (setup_pending) {
        CFG_SEED = story_setup.seed;
        story_spectate = story_setup.flags & F_SPECTATE;
        if (story_spectate) {
            CONTROL[0] = CONTROL[1] = 1;
            CFG_SIDE = 0;
            /* Explicit first choices take precedence; CPU janken is automatic. */
            vm_state = 3;
        }
    }
}

/* Also exposed to the research rig: exactly the production initialization. */
SMALL static u32 take_field(u32 side, volatile u32 *deck, u32 n)
{
    u32 k, j;
    for (k = 0; k < 8; k++) {
        const struct StoryField *f = &story_setup.field[k];
        if (!f->card || f->side != side) continue;
        for (j = n; j-- > 0;)
            if ((deck[j] & 0x3fff) == f->card) break;
        if (j >= n) {
            story_setup_error |= 1u << side;
            continue;
        }
        for (n--; j < n; j++) deck[j] = deck[j + 1];
        field_taken |= 1u << k;
    }
    REG(PLAYER(side) + 0x10) = n;
    return n;
}

void story_initial_shuffle(u32 side)
{
    u32 i, j, n = REG(PLAYER(side) + 0x10), out[60];
    u8 used[60];
    volatile u32 *deck = (volatile u32 *)(PLAYER(side) + 0x304);
    SHUFFLE(side);
    if (side > 1 || n > 60) return;
    if (!setup_pending) goto capture;
    n = take_field(side, deck, n);
    for (j = 0; j < n; j++) used[j] = 0;
    for (i = 0; i < 60; i++) {
        u32 id = story_setup.slots[side][i];
        if (!id) continue;
        if (i >= n) goto invalid;
        for (j = 0; j < n; j++)
            if (!used[j] && (deck[j] & 0x3fff) == id) break;
        if (j == n) goto invalid;
        used[j] = 1;
        out[i] = deck[j];
    }
    j = 0;
    for (i = 0; i < n; i++) {
        if (story_setup.slots[side][i]) continue;
        while (used[j]) j++;
        out[i] = deck[j++];
    }
    for (i = 0; i < n; i++) deck[i] = out[i];
capture:
    story_initial_decks.count[side] = n;
    for (i = 0; i < n; i++) story_initial_decks.cards[side][i] = deck[i] & 0x3fff;
    return;
invalid:
    /* A player's changed deck may not contain the authored cards. Keep the
     * entire shuffled deck intact, report the side, and let the duel proceed. */
    story_setup_error |= 1u << side;
    goto capture;
}

#define LEGAL ((u32 (*)(u32,u32,u32))0x0224bc41)
#define SPECIAL_LEGAL ((u32 (*)(u32,u32))0x0225e51d)
#define PICK ((void (*)(u32,u32,u32,u32))0x0224c28d)

/* Prefer one legal action, then leave all targets, costs and responses to the
 * normal CPU and rules engine. A failed preference is retried during that main
 * phase, so normal AI actions can make it possible later in the turn. */
int story_main(void)
{
    u32 p = REG(0x0229dd48), turn = REG(0x0229dd54) / 2 + 1;
    u32 phase = REG(0x0229dd5c), k, i, zone, count, word, at, mask;
    u32 save0, save8, save_side, save_reason;
    int result;
    if (setup_pending && !main_inflight && p < 2 &&
        REG(0x0229911c + p * 4) == 1 &&
        !(REG(0x0229e6cc) & 0x3f00) && !(REG(0x022c351c) & 0xf000)) {
        for (k = 0; k < story_setup.nplans && k < 16; k++) {
            const struct StoryPlan *a = &story_setup.plans[k];
            if ((plans_done & (1u << k)) || a->side != p || a->turn != turn || a->phase != phase)
                continue;
            for (zone = 0; zone <= 12; zone++) {
                if (zone == 10) count = 1;
                else if (zone < 10) count = 1;
                else count = REG(PLAYER(p) + (zone == 11 ? 0xc : 0x18));
                if (count > 120) count = 120;
                for (i = 0; i < count; i++) {
                    at = zone < 11 ? PLAYER(p) + 0x34 + zone * 20 :
                         PLAYER(p) + (zone == 11 ? 0x124 : 0x4e4) + 4 * i;
                    word = REG(at);
                    if ((word & 0x3fff) != a->card) continue;
                    if (zone == 12 && a->action != 2) continue;
                    if (zone < 11 && a->action != 3) continue;
                    save0 = REG(0x0229dde0); save8 = REG(0x0229dde8);
                    save_side = REG(0x0229de08); save_reason = REG(0x0229de1c);
                    REG(0x0229dde0) = REG(0x0229dde8) = 2;
                    REG(0x0229de08) = p;
                    if (zone == 12)
                        mask = SPECIAL_LEGAL(p, ((word & 0x7fffffff) >> 23) * 2 + ((word >> 14) & 1));
                    else mask = LEGAL(p, zone, i);
                    REG(0x0229dde0) = save0; REG(0x0229dde8) = save8;
                    REG(0x0229de08) = save_side; REG(0x0229de1c) = save_reason;
                    if (!(mask & (1u << a->action))) continue;
                    REG(0x0229de08) = p;
                    PICK(p, zone, zone == 12 ? i + 1 : i, a->action);
                    plans_done |= 1u << k;
                    story_plan_taken = k + 1;
                    return 1;
                }
            }
        }
    }
    result = ((int (*)(void))story_next_main)();
    main_inflight = result <= 0 && !REG(0x0229ddec);
    return result;
}

u32 story_normal_draw(u32 p, u32 n, u32 effect, u32 arg)
{
    if (p < 2) normal_draw_turn[p] = REG(0x0229dd54) / 2 + 1;
    return ((u32 (*)(u32,u32,u32,u32))0x021d0951)(p,n,effect,arg);
}

void story_effect_shuffle(u32 side)
{
    u32 n, i, j, pos, offset, card, turn, completed, hand, out[60];
    u16 slots[60];
    u8 used[60];
    volatile u32 *deck;
    SHUFFLE(side);
    if (!setup_pending || side > 1) return;
    n = REG(PLAYER(side) + 0x10);
    if (n > 60) return;
    deck = (volatile u32 *)(PLAYER(side) + 0x304);
    turn = REG(0x0229dd54);
    completed = (turn + 1) / 2;
    if (REG(0x0229dd48) == side) {
        completed = turn / 2;
        if (REG(0x0229dd5c) > 0 && REG(0x0229dd5c) < 6) completed++;
    }
    if (normal_draw_turn[side] > completed) completed = normal_draw_turn[side];
    hand = side == 1 && (story_setup.flags & F_HAND10) ? 10 : 5;
    for (i = 0; i < 60; i++) { used[i] = 0; slots[i] = 0; }
    for (pos = hand; pos < 60; pos++) {
        if (!(story_setup.draws[side][pos / 32] & (1u << (pos % 32)))) continue;
        if (pos - hand < completed) continue;
        offset = pos - hand - completed;
        if (offset >= n) continue;
        card = story_setup.slots[side][pos];
        if (!card) continue;
        for (j = 0; j < n; j++)
            if (!used[j] && (deck[j] & 0x3fff) == card) break;
        if (j == n) continue; /* The planted copy may have been drawn/searched. */
        used[j] = 1;
        slots[offset] = card;
        out[offset] = deck[j];
    }
    j = 0;
    for (i = 0; i < n; i++) {
        if (slots[i]) continue;
        while (used[j]) j++;
        out[i] = deck[j++];
    }
    for (i = 0; i < n; i++) deck[i] = out[i];
}
