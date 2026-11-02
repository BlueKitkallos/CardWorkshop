#include "menu11.h"
typedef unsigned int u32;
#define MEM(a) (*(volatile u32 *)(a))
#define ROWS ((volatile u32 *)0x0215c5b0)
#define RETURN_ID MEM(0x020b8f3c)
#define STOCK_WIRELESS ((volatile u32 *)0x0215c498)
static u32 wireless[5], wireless_rows[35], settings[40], settings_n, duelist[25], shop[10];

void menu11_init(void) {
    unsigned i, j = 0, n = 0, w = 0;
    volatile u32 *src = (volatile u32 *)0x0215c524;
    for (i = 0; i < 7; ++i) {
        unsigned k;
#if W11_NO_WFC
        if (STOCK_WIRELESS[i * 5] == 0x3002 || STOCK_WIRELESS[i * 5] == 0x3003) continue;
#endif
        for (k = 0; k < 5; ++k) wireless_rows[w * 5 + k] = STOCK_WIRELESS[i * 5 + k];
        ++w;
    }
    wireless[0] = 0x3000; wireless[1] = W11MENU_LEGACY - 3000; wireless[2] = W11MENU_LEGACY_DESC - 3000;
    wireless[3] = w; wireless[4] = (u32)wireless_rows;
    if (ROWS[19] != (u32)settings && ROWS[19] != (u32)wireless_rows) {
        volatile u32 *rows = (volatile u32 *)ROWS[19];
        settings_n = ROWS[18] < 7 ? ROWS[18] : 7;
        for (i = 0; i < settings_n * 5; ++i) settings[i] = rows[i];
    }
    settings[settings_n * 5] = 0x6000; settings[settings_n * 5 + 1] = W11MENU_LEGACY - 3000;
    settings[settings_n * 5 + 2] = W11MENU_LEGACY_DESC - 3000;
    settings[settings_n * 5 + 3] = 0; settings[settings_n * 5 + 4] = 0;
    for (i = 0; i < 7; ++i) {
        unsigned k;
        u32 *out;
        if (src[i * 5] == 0x5003 || src[i * 5] == 0x5005) {
            out = shop + n; n += 5;
        } else { out = duelist + j; j += 5; }
        for (k = 0; k < 5; ++k) out[k] = src[i * 5 + k];
    }
    shop[1] = W11MENU_CARD_SHOP - 3000;
    ROWS[11] = W11MENU_SHOP - 3000;
    ROWS[12] = W11MENU_SHOP_DESC - 3000;
    ROWS[13] = 2; ROWS[14] = (u32)shop;
    ROWS[18] = settings_n + 1; ROWS[19] = (u32)settings;
    ROWS[23] = 5; ROWS[24] = (u32)duelist;
    MEM(0x0215c2a4) = 13;
    /* The native init needs a nonzero low nibble to restore a submenu; 3008/4007 are never dispatched. */
    if (RETURN_ID == 0x5003 || RETURN_ID == 0x5005) RETURN_ID = 0x3008;
    else if ((RETURN_ID & 0xf000) == 0x3000 && (RETURN_ID & 0xfff)) {
        ROWS[18] = w;
        ROWS[19] = (u32)wireless_rows;
        RETURN_ID = 0x4007;
    }
}

int menu11_activate(u32 *ctx) {
    if (ctx[0] == 2 && ctx[10] == 0 &&
        *(u32 *)ctx[14 + ctx[5]] == 0x6000) {
        ctx[13] = (u32)wireless;
        ((void (*)(u32 *))0x021550a4)(ctx);
        return 1;
    }
    return 0;
}

int menu11_gate(u32 *ctx, u32 action) {
    if (ctx[0] != 2 || ctx[10] != 0) return 0;
    if (action == 1 && *(u32 *)ctx[14 + ctx[5]] == 0x6000) {
        ctx[13] = (u32)wireless;
        ((void (*)(u32 *))0x021550a4)(ctx);
        ctx[48] = ctx[51] = ctx[52] = 0;
        ((void (*)(u32, u32, u32, u32))0x02034b80)(0x4a, -1u, 0, 1);
        /* 2 = consumed without a scene confirmation, or the caller latches ctx[48]. */
        return 2;
    }
    if (action == 2 && (ctx[13] == (u32)wireless || ROWS[19] == (u32)wireless_rows)) {
        ROWS[18] = settings_n + 1;
        ROWS[19] = (u32)settings;
        ctx[13] = 0x0215c5ec;
        ((void (*)(u32 *))0x021550a4)(ctx);
        ctx[5] = (ctx[6] & 0xffff) - 1;
        ((void (*)(u32 *, u32))0x021548f8)(ctx, 0);
        ctx[48] = ctx[51] = ctx[52] = 0;
        return 1;
    }
    return 0;
}
