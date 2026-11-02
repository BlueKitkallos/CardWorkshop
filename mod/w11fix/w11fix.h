#ifndef W11FIX_H
#define W11FIX_H

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed int s32;

typedef struct FxSlot {
    u32 card;
    u16 unk4;
    u16 defense;
    u16 active;
    u16 modifiers;
    u32 state;
    u32 flags;
} FxSlot;

typedef struct FxPlayer {
    u32 lp;
    u32 unk004;
    u32 unk008;
    u32 hand_count;
    u32 deck_count;
    u32 gy_count;
    u32 extra_count;
    u32 banished_count;
    u32 unk020[5];
    FxSlot slot[12];
    u32 hand[120];
    u32 deck[120];
    u32 extra[30];
    u32 gy[150];
    u32 banished[150];
    u16 banished_info[150];
    u32 unkb38;
} FxPlayer;

typedef struct FxCtx {
    u16 card_id;
    u8 controller;
    u8 slot;
    u8 kind;
    u8 category;
    u8 other;
    u8 unk7;
    u8 unk8;
    u8 neg_response;
    u8 neg_effect;
    u8 neg_skip;
    u16 uid;
    u8 uid_bits;
    u8 copied;
    u8 ntargets;
    u8 unk11;
    u16 target_total;
    u16 targets[5];
    u16 ring;
    u32 event;
} FxCtx;

_Static_assert(sizeof(FxSlot) == 0x14, "FxSlot");
_Static_assert(sizeof(FxPlayer) == 0xb3c, "FxPlayer");
_Static_assert(sizeof(FxCtx) == 0x24, "FxCtx");

#define FX_PLAYERS ((FxPlayer *)0x0229ac94)
#define FX_CONTROLLER ((volatile u32 *)0x0229911c)
#define FX_TURN_COUNT (*(volatile u32 *)0x0229dd54)
#define FX_TURN_PLAYER (*(volatile u32 *)0x0229dd48)
#define FX_PHASE (*(volatile u32 *)0x0229dd5c)
#define FX_CPU 1
#define FX_ZONE_HAND 11
#define FX_ZONE_GY 14
#define FX_ID(w) ((w) & 0x3fff)
#define FX_UID(w) (((((w) & 0x7fffffff) >> 23) << 1) | (((w) >> 14) & 1))
#define FX_CTX_PLAYER(e) (((e)->controller ^ (e)->other) & 1)

#define FX_ARCHETYPE ((u32 (*)(u32, u32))0x020240d9)
#define FX_CARD_FRAME ((u32 (*)(u32))0x0202abf9)
#define FX_CARD_ATK ((int (*)(u32))0x0202ac09)
#define FX_CARD_PROP ((u32 * (*)(u32))0x0202a085)
#define FX_IS_MONSTER ((int (*)(u32))0x02029e61)
#define FX_FREE_ZONES ((int (*)(u32))0x021ad871)
#define FX_ACTION_QUEUE ((void (*)(u32, u32, u32, u32))0x02269615)

u32 fx_frame(u32 id);

u32 fix_ns_allowed(u32 p, u32 index);
u32 fix_queue_hand_summon(u32 p, u32 index, u32 kind);
u32 fix_ravine_feeds(u32 p);
u32 fix_ravine_hold(u32 p);
u32 fix_gy_summon(u32 p);
void fix_cpu_reset(void);
u32 fix_launcher_lead(u32 p);
int fix_mode_answer(void *e, u32 mask);

#endif
