#include "menu11.h"
typedef unsigned int u32;
#define MEM(a) (*(volatile u32 *)(a))
#define ROWS ((volatile u32 *)0x0215c5b0)
#define RETURN_ID MEM(0x020b8f3c)
#define ROW_LEGACY 0x6000
#define ROW_RESET 0x6006
#define SELECTED(ctx) (*(u32 *)(ctx)[14 + (ctx)[5]])
#define ROW(out, id, label, desc) ((out)[0] = (id), (out)[1] = (label) - 3000, (out)[2] = (desc) - 3000, (out)[3] = 0, (out)[4] = 0)
static u32 duelist[25], shop[15], shop_n;

static void show_list(u32 *ctx, u32 category, u32 cursor) {
    ctx[13] = category;
    ((void (*)(u32 *))0x021550a4)(ctx);
    ctx[5] = cursor;
    ((void (*)(u32 *, u32))0x021548f8)(ctx, 0);
    ctx[48] = ctx[51] = ctx[52] = 0;
}

#ifdef W11MENU_LEGACY
#define STOCK_WIRELESS ((volatile u32 *)0x0215c498)
#define SHOP_CATEGORY 0x0215c5d8u
static u32 wireless[5], wireless_rows[35], wireless_n;

static void open_legacy(u32 *ctx) {
    ctx[13] = (u32)wireless;
    ((void (*)(u32 *))0x021550a4)(ctx);
}
#endif

#ifdef W11MENU_RESET
#define DLG 0x02236d40u
#define DLG_OPEN ((void (*)(u32, u32, u32))0x02156880)
#define DLG_END ((u32 (*)(u32))0x02156d70)
#define TEXT ((u32 (*)(u32))0x0202b64d)
#define STOCK_SAVE ((u32 (*)(void))0x0202de8d)
#define SAVE_STORY ((void (*)(void))0x0202deb5)
#define TEXT_SAVING 0x2e
#define RESET_FIRST_YES 1
#define RESET_CONFIRMING 2
#define RESET_CONFIRMED 3
#define RESET_SAVING 4
#define QUIZ_FIRST 0x6007
#define QUIZ_RIGHT 0x6009
#define QUIZ_LAST 0x600a
#define MENU_CTX ((u32 *)0x02236450)
#define RECORDS_CATEGORY 0x0215c614u
#define STOCK_RECORDS ((volatile u32 *)0x0215c344)
extern void softreset11_apply(void);
static u32 reset_state, quiz[5], quiz_rows[20], records[30];

static void quiz_open(void) {
    static const u32 labels[4] = {W11MENU_QUIZ_1200, W11MENU_QUIZ_1500, W11MENU_QUIZ_1400, W11MENU_QUIZ_1800};
    unsigned i;
    for (i = 0; i < 4; ++i) ROW(quiz_rows + i * 5, QUIZ_FIRST + i, labels[i], W11MENU_RESET_QUIZ);
    quiz[0] = ROWS[25]; quiz[1] = ROWS[26]; quiz[2] = ROWS[27];
    quiz[3] = 4; quiz[4] = (u32)quiz_rows;
    show_list(MENU_CTX, (u32)quiz, 0);
}

static void quiz_close(u32 *ctx) {
    reset_state = 0;
    show_list(ctx, RECORDS_CATEGORY, ROWS[28] - 1);
}

static void reset_answer(void) {
    if (MEM(DLG + 0xc)) reset_state = 0;
    else reset_state = reset_state == RESET_CONFIRMING ? RESET_CONFIRMED : RESET_FIRST_YES;
}

static void reset_dialog(u32 text) {
    DLG_OPEN(DLG, 2, TEXT(text));
    MEM(DLG + 0xc) = 1;
    MEM(DLG + 0x30) = (u32)reset_answer;
}

static void reset_ask(u32 *ctx) {
    reset_state = 0;
    reset_dialog(W11MENU_RESET_ASK);
    ctx[48] = ctx[51] = ctx[52] = 0;
    ((void (*)(u32, u32, u32, u32))0x02034b80)(0x4a, -1u, 0, 1);
}

u32 menu11_dialog_end(u32 dlg) {
    u32 r = DLG_END(dlg);
    if (reset_state == RESET_FIRST_YES) {
        reset_state = RESET_CONFIRMING;
        reset_dialog(W11MENU_RESET_CONFIRM);
    } else if (reset_state == RESET_CONFIRMED) {
        quiz_open();
    }
    return r;
}

static int quiz_answer(u32 *ctx) {
    u32 row = SELECTED(ctx);
    if (ctx[13] != (u32)quiz || row < QUIZ_FIRST || row > QUIZ_LAST) return 0;
    quiz_close(ctx);
    if (row == QUIZ_RIGHT) {
        reset_state = RESET_SAVING;
        DLG_OPEN(DLG, 3, TEXT(TEXT_SAVING));
    }
    return 1;
}

u32 menu11_dialog_save(void) {
    if (reset_state != RESET_SAVING) return STOCK_SAVE();
    reset_state = 0;
    softreset11_apply();
    SAVE_STORY();
    return 1;
}
#endif

void menu11_init(void) {
    unsigned i, j = 0, n = 0, d = 0;
    volatile u32 *src = (volatile u32 *)0x0215c524;
    shop_n = 0;
#ifdef W11MENU_LEGACY
    wireless_n = 0;
    for (i = 0; i < 7; ++i) {
        unsigned k;
#if W11_NO_WFC
        if (STOCK_WIRELESS[i * 5] == 0x3002 || STOCK_WIRELESS[i * 5] == 0x3003) continue;
#endif
        for (k = 0; k < 5; ++k) wireless_rows[wireless_n * 5 + k] = STOCK_WIRELESS[i * 5 + k];
        ++wireless_n;
    }
    ROW(wireless, 0x3000, W11MENU_LEGACY, W11MENU_LEGACY_DESC);
    wireless[3] = wireless_n; wireless[4] = (u32)wireless_rows;
#endif
    for (i = 0; i < 7; ++i) {
        unsigned k;
        u32 *out;
        if (src[i * 5] == 0x5003 || src[i * 5] == 0x5005) {
            out = shop + n; n += 5; ++shop_n;
        } else { out = duelist + j; j += 5; ++d; }
        for (k = 0; k < 5; ++k) out[k] = src[i * 5 + k];
    }
#ifdef W11MENU_RESET
    for (i = 0; i < 25; ++i) records[i] = STOCK_RECORDS[i];
    ROW(records + 25, ROW_RESET, W11MENU_RESET, W11MENU_RESET);
    ROWS[28] = 6; ROWS[29] = (u32)records;
#endif
#ifdef W11MENU_LEGACY
    ROW(shop + n, ROW_LEGACY, W11MENU_LEGACY, W11MENU_LEGACY_DESC);
    ++shop_n;
#endif
    shop[1] = W11MENU_CARD_SHOP - 3000;
    ROWS[11] = W11MENU_SHOP - 3000;
    ROWS[12] = W11MENU_SHOP_DESC - 3000;
    ROWS[13] = shop_n; ROWS[14] = (u32)shop;
    ROWS[23] = d; ROWS[24] = (u32)duelist;
    MEM(0x0215c2a4) = 13;
    /* The native init needs a nonzero low nibble to restore a submenu; 3008 is never dispatched. */
    if (RETURN_ID == 0x5003 || RETURN_ID == 0x5005) RETURN_ID = 0x3008;
#ifdef W11MENU_LEGACY
    else if ((RETURN_ID & 0xf000) == 0x3000 && (RETURN_ID & 0xfff) && (RETURN_ID & 0xfff) < 8) {
        ROWS[13] = wireless_n;
        ROWS[14] = (u32)wireless_rows;
        RETURN_ID = 0x3008;
    }
#endif
}

int menu11_activate(u32 *ctx) {
    if (ctx[0] != 2 || ctx[10] != 0) return 0;
#ifdef W11MENU_LEGACY
    if (SELECTED(ctx) == ROW_LEGACY) {
        open_legacy(ctx);
        return 1;
    }
#endif
#ifdef W11MENU_RESET
    if (SELECTED(ctx) == ROW_RESET) {
        reset_ask(ctx);
        return 1;
    }
    if (quiz_answer(ctx)) return 1;
#endif
    return 0;
}

int menu11_gate(u32 *ctx, u32 action) {
    if (ctx[0] != 2 || ctx[10] != 0) return 0;
#ifdef W11MENU_LEGACY
    if (action == 1 && SELECTED(ctx) == ROW_LEGACY) {
        open_legacy(ctx);
        ctx[48] = ctx[51] = ctx[52] = 0;
        ((void (*)(u32, u32, u32, u32))0x02034b80)(0x4a, -1u, 0, 1);
        /* 2 = consumed without a scene confirmation, or the caller latches ctx[48]. */
        return 2;
    }
    if (action == 2 && (ctx[13] == (u32)wireless || ROWS[14] == (u32)wireless_rows)) {
        ROWS[13] = shop_n;
        ROWS[14] = (u32)shop;
        show_list(ctx, SHOP_CATEGORY, shop_n - 1);
        return 1;
    }
#endif
#ifdef W11MENU_RESET
    if (action == 1 && SELECTED(ctx) == ROW_RESET) {
        reset_ask(ctx);
        return 2;
    }
    if (action == 1 && quiz_answer(ctx)) return 2;
    if (action == 2 && ctx[13] == (u32)quiz) {
        quiz_close(ctx);
        return 1;
    }
#endif
    return 0;
}
