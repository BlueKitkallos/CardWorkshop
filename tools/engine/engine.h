#ifndef ENGINE_H
#define ENGINE_H

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed short s16;
typedef signed int s32;

enum Zone {
    ZONE_MONSTER0 = 0,
    ZONE_SPELL0 = 5,
    ZONE_FIELD = 10,
    ZONE_HAND = 11,
    ZONE_EXTRA = 12,
    ZONE_DECK = 13,
    ZONE_GY = 14,
    ZONE_BANISHED = 15,
};

enum Controller { CTRL_HUMAN = 0, CTRL_CPU = 1, CTRL_REMOTE = 2 };

#define CARD_ID_MASK 0x3fff
#define CARD_ID(w) ((w) & CARD_ID_MASK)
#define CARD_OWNER(w) (((w) >> 30) & 1)
#define CARD_UID(w) (((((w) & 0x3fffffff) >> 22) << 1) | CARD_OWNER(w))
#define CARD_WORD(id, owner, uid) ((id) | (owner) << 30 | ((uid) >> 1) << 22)

typedef struct FieldSlot {
    u32 card;
    u16 unk4;
    u16 unk6;
    u16 active;
    u16 modifiers;
    u32 state;
    u32 flags;
} FieldSlot;

typedef struct PlayerState {
    u32 lp;
    u32 unk004;
    u32 unk008;
    u32 hand_count;
    u32 deck_count;
    u32 gy_count;
    u32 extra_count;
    u32 banished_count;
    u32 unk020[4];
    FieldSlot slot[12];
    u32 hand[160];
    u32 deck[160];
    u32 extra[60];
    u32 gy[220];
    u32 banished[220];
    u32 unkdf0[111];
} PlayerState;

typedef struct EffectCtx {
    u16 card_id;
    u16 flags;
    u16 src;
    u16 targets;
    u16 value0;
    u16 value1;
    u32 wc;
    u32 w10;
    u32 event;
} EffectCtx;

#define CTX_PLAYER(e) ((((e)->flags & 0x7fff) >> 14) ^ ((e)->flags & 1))
#define CTX_SLOT(e) (((e)->flags & 0x3f) >> 1)
#define CTX_KIND(e) (((e)->flags & 0xfff) >> 6)
#define CTX_CATEGORY(e) (((e)->flags & 0x3fff) >> 12)
#define CTX_SRC_UID(e) (((e)->src & 0x3fff) >> 5)
#define CTX_TARGET_COUNT(e) ((e)->targets >> 8)

typedef int (*EffectResolveFn)(EffectCtx *e, int arg);
typedef int (*EffectTargetFn)(EffectCtx *e, int player, int slot);
typedef int (*EffectCheckFn)(EffectCtx *e, void *card);
typedef void (*CandidateFn)(u32 player, u32 card_id, u32 arg);

typedef struct EffectRecord {
    u32 card_id;
    EffectResolveFn resolve;
    EffectTargetFn target_filter;
    EffectCheckFn can_activate;
    EffectCheckFn cost;
    EffectCheckFn select_targets;
} EffectRecord;

typedef struct CandidateRow {
    u32 card_id;
    CandidateFn build;
} CandidateRow;

_Static_assert(sizeof(FieldSlot) == 0x14, "FieldSlot");
_Static_assert(sizeof(PlayerState) == 0xfac, "PlayerState");
_Static_assert(sizeof(EffectCtx) == 0x18, "EffectCtx");
_Static_assert(sizeof(EffectRecord) == 0x18, "EffectRecord");

#define RESOLVE_START 0x80
#define RESOLVE_DONE 0

extern PlayerState duel_players[2];
extern u32 player_controller[2];
extern u32 effect_step;
extern EffectCtx chain[];
extern u32 chain_len;
extern u32 chain_count;
extern u32 chain_activating;
extern u32 chain_resolving;
extern u32 candidates[512];
extern u16 candidate_zones[512];
extern u32 candidate_count;
extern u32 candidate_selected;
extern u32 turn_player;
extern u32 self_player;
extern CandidateRow table_candidates[516];
extern EffectRecord table_effects_gy[258];
extern EffectRecord table_effects_ignition[307];
extern EffectRecord table_effects_trigger[638];
extern EffectRecord table_effects_activate[960];

int main_table_find(u32 card_id);
int card_candidates(u32 player, u32 card_id, u32 arg);
int card_candidates_count(u32 player, u32 card_id, u32 arg, u32 unused);
void candidate_add(u32 player, u32 zone, u32 index);
EffectRecord *effect_record_find(EffectCtx *e);
int effect_can_activate(EffectCtx *e, void *card);
int effect_target_ok(EffectCtx *e, u32 player, u32 slot, u32 arg);
int effect_count_targets(EffectCtx *e);
int effect_cost(EffectCtx *e, void *card);
int effect_select_targets(EffectCtx *e, void *card);
int effect_resolve(EffectCtx *e, int arg);

void duel_cmd_push(u32 op, u32 a, u32 b, u32 c);
void cmd_move_card(u32 from_player, u32 from_zone, u32 uid, u32 to_player, u32 to_zone, u32 to_index, u32 flags);
void hand_to_gy(u32 player, u32 *card, u32 reason, u32 dest_zone, int by_effect, int as_cost);
void discard_by_effect(u32 player, int hand_index, int by_opponent, u32 arg);
void discard_as_cost(u32 player, int hand_index);
void hand_to_deck(u32 player, int hand_index, int bottom);
int gy_to_deck(u32 player, u32 uid, int bottom, u32 arg);
int deck_to_hand(u32 player, u32 *card);
void deck_mill(u32 player, u32 count, u32 by_player, u32 banish);
void deck_shuffle(u32 player);
int draw_cards(u32 player, u32 count);
void destroy_slot(EffectCtx *e, u32 player, u32 slot);
void destroy_mask(EffectCtx *e, u32 slot_mask, u32 dest_zone, u32 reason);
void lp_pay(u32 player, u32 amount);
void attach_modifier_cmd(u32 player, u32 slot, u32 card_id, u32 duration, u32 value);
int slot_has_modifier(u32 player, u32 zone, u32 card_id);
int cost_once_per_turn(EffectCtx *e);
int cond_once_per_turn(EffectCtx *e);
int trigger_register(u32 packed, u32 uid, u32 event);
int trigger_check(u32 packed, u32 uid, u32 event);
u32 *zone_card_ptr(u32 player, u32 zone, u32 index);
int uid_field_pos(u32 uid);
int uid_gy_index(u32 player, u32 uid);
void select_cards(u32 player, u32 mode, u32 card_id, u32 arg);
u32 *selected_card(void);
void show_message(u32 player, u32 msg);
void show_opponent_hand(u32 player);
void anim_lock(void);
void anim_unlock(void);
int resolve_draw_n(EffectCtx *e);
void resolve_destroy_target(EffectCtx *e);
int ctx_target_get(EffectCtx *e, int i, u32 *out);
u32 ctx_target_uid(EffectCtx *e, int i);
u32 ctx_candidate_arg(EffectCtx *e);
int card_is_monster(u32 card_id);
int card_atk(u32 card_id);
int card_attribute(u32 card_id);
int card_kind(u32 card_id);
int card_id_to_index(u32 card_id);
u32 uid_locate(u32 uid);
u32 *uid_card(u32 uid);
void special_summon(u32 player, u32 *card, u32 unk, u32 flags);
int fusion_material_matches(u32 code, u32 uid);
void format_message(char *buf, u32 msg, u32 number);
u32 ctx_copied_id(EffectCtx *e);
int free_monster_zones(u32 player);
int can_special_summon(u32 player);
int can_special_summon_id(u32 player, u32 id);
int uid_goes_to_gy(u32 uid);
int gy_to_hand(EffectCtx *e, u32 player, u32 *card);
int banished_to_hand(EffectCtx *e, u32 player, u32 *card);
void gy_banish(u32 player, u32 *card, u32 flags);
void banished_to_gy(u32 player, u32 uid);
void deck_index_to_gy(u32 player, u32 index, u32 by);
void deck_uid_to_gy(u32 player, u32 uid, u32 by_opponent);
void select_number(u32 player, u32 card_id, u32 max);
extern u32 selected_number;
extern u32 cost_step;
int hand_effect_monster(u32 id);
int cost_confirm(EffectCtx *e, void *card);
int select_targets_generic(EffectCtx *e, void *card);
int card_genre(u32 id, u32 bit);
void damage_calc(u32 arg);
int resolve_field_spell(EffectCtx *e, int arg);
void set_face_down(EffectCtx *e, u32 player, u32 slot);
int negate_chain_link(EffectCtx *e, EffectCtx *link, int destroy);
void monster_stats_raw(u32 player, u32 slot, int *out, u32 unk);
void ask_yes_no(u32 msg, u32 uid);
void activation_announce(EffectCtx *e);
int spell_speed_of(u32 id);
int resolve_negated(EffectCtx *e, int arg);

typedef struct CpuRow {
    u32 card_id;
    int (*eval)(EffectCtx *e, void *link);
} CpuRow;

int cpu_try_row(u32 player, const CpuRow *row);
int cpu_try_response(u32 player, const CpuRow *row, void *link);
int cpu_stage_general(u32 player);
int cpu_stage_set(u32 player, u32 arg);
int cpu_respond_rows(u32 player, void *link);
int cpu_event_card_ok(u32 player, u32 id);
void cpu_queue_action(u32 player, u32 zone, u32 index, u32 kind);
int can_normal_summon(u32 player, u32 uid);
int summon_allowed(u32 player);
int start_summon(u32 face_up, u32 special, u32 tributes_plus_one);
u32 summon_options(u32 player, u32 uid);
int cpu_summon_chosen(u32 player);
extern s16 cpu_summon_index;
extern u16 cpu_summon_flags;
extern u32 action_uid;
extern u32 action_owner;
void ctx_add_target(EffectCtx *e, u32 player, u32 slot);
int hand_index_of(u32 player, u32 id);
void monster_stats(u32 player, u32 slot, int *out);
extern u32 cpu_action_count[2];
extern u32 action_pending;
extern u32 action_player;

extern u32 chain_task_cost;
extern u32 chain_task_targets;
extern u32 chain_task_respond;
extern u32 chain_task_resolve;
extern u32 turn_count;
extern u32 duel_phase;
extern u32 event_count;
extern EffectCtx pending_triggers[32];
extern u32 pending_count;
extern u16 table_fusion_materials[131][4];

#endif
