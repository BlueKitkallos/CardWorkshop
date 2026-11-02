#include "points11.h"

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;

#define LIST_LOAD ((u16 *(*)(u32, u32, u8 *))(0x0202ac90 | 1))
#define FILE_LOAD ((void *(*)(const char *, u32, u32))(0x020168e8 | 1))
#define FILE_READ ((void (*)(const char *, void *, u32, u32))(0x02016a48 | 1))
#define MEMCPY ((void (*)(const void *, void *, u32))0x02089774)
#define AVAIL ((u32 (*)(u32, u32))(0x0202ed00 | 1))
#define STOCK_PATH ((const char *)0x020ab848)
#define LOADED_SRC (*(volatile u16 *)0x02122114)
#define LOADED_IDX (*(volatile u16 *)0x02122116)
#define CUR_SRC (*(volatile u32 *)0x02126460 & 1)
#define CUR_IDX (*(volatile u8 *)0x02127305)
#define LANG_WORD (*(volatile u32 *)0x021264a4)
#define TEXT_BUF ((u32 *)0x02122118)
#define TEXT_INDX ((const char *)0x020abb8c)
#define TEXT_TEXT ((const char *)0x020abba4)
#define ED ((u8 *)0x021fe2c4)
#define ED_COUNT 0x12948
#define SEC_MAIN (*(volatile s32 *)0x0217c9b4)
#define SEC_SIDE (*(volatile s32 *)0x0217c9b0)
#define SEC_EXTRA (*(volatile s32 *)0x0217c9ac)
#define ARR_MAIN 0x11d48
#define ARR_SIDE 0x12148
#define ARR_EXTRA 0x12348
#define MAIN_COPIES ((volatile u16 *)0x02210c16)
#define LIMIT_CHECK ((u32 (*)(u8 *))0x02152de4)
#define UI_MSG 0x178
#define MSG_J ((const u8 *)0x021772b4)
#define MSG_E ((const u8 *)0x0217769c)
#define MSG_N 50
#define MSG_SIZE 0x14
#define MSG_LIMIT 1
#define MSG_UNDER_40 2
#define MSG_EXIT 0x1c
#define MSG_DIALOG 6
#define MSG_FORMAT_STRING 2
#define MSG_TEXT 0x10
#define MAIN_MIN 40
#define FIRST_EXT 3
#define MAGIC 0x31544e50

static struct {
    u32 magic;
    u16 cap, n;
    u16 ids[BL11_POINT_MAX];
    u8 pts[BL11_POINT_MAX];
} pt;

static u32 open_idx;
u8 bl11_msg_j[(MSG_N + 1) * MSG_SIZE] __attribute__((aligned(4)));
u8 bl11_msg_e[(MSG_N + 1) * MSG_SIZE] __attribute__((aligned(4)));
static u32 msg_ready;
static char msg_arg[16];

static u32 rd16(const u8 *p)
{
    return p[0] | p[1] << 8;
}

void *bl11_open(u32 idx, u32 a, u32 b)
{
    const char *path = STOCK_PATH;
    u32 k;
    open_idx = idx;
    if (idx >= FIRST_EXT && idx < FIRST_EXT + BL11_EXT) {
        path = BL11_PATHS;
        for (k = idx - FIRST_EXT; k; k--)
            while (*path++)
                ;
    }
    return FILE_LOAD(path, a, b);
}

void bl11_copy(const u8 *file, u8 *dst, u32 size)
{
    const u8 *t = file + 8 + 2 * rd16(file);
    u32 i, n;
    MEMCPY(file, dst, size);
    pt.magic = 0;
    if (open_idx != BL11_POINT_INDEX || rd16(t) != (MAGIC & 0xffff) || rd16(t + 2) != MAGIC >> 16)
        return;
    n = rd16(t + 6);
    if (n > BL11_POINT_MAX)
        return;
    pt.cap = rd16(t + 4);
    pt.n = n;
    for (i = 0; i < n; i++) {
        pt.ids[i] = rd16(t + 8 + 2 * i);
        pt.pts[i] = t[8 + 2 * n + i];
    }
    pt.magic = MAGIC;
}

u32 bl11_avail(u32 src, u32 idx)
{
    if (src == 0 && idx >= FIRST_EXT && idx < FIRST_EXT + BL11_EXT)
        return 1;
    return AVAIL(src, idx);
}

static u32 cap(void)
{
    LIST_LOAD(CUR_SRC, CUR_IDX, 0);
    return LOADED_SRC == 0 && LOADED_IDX == BL11_POINT_INDEX && pt.magic == MAGIC ? pt.cap : 0;
}

static u32 points(u32 id)
{
    u32 lo = 0, hi = pt.n;
    while (lo < hi) {
        u32 mid = (lo + hi) >> 1;
        if (pt.ids[mid] < id)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo < pt.n && pt.ids[lo] == id ? pt.pts[lo] : 0;
}

static u32 section_points(s32 sec, u32 arr)
{
    const u8 *a = ED + arr;
    u32 i, n = *(const u16 *)(ED + ED_COUNT + sec * 2), total = 0;
    for (i = 0; i < n; i++, a += 4)
        total += points(*(const u16 *)a) * a[2];
    return total;
}

static u32 deck_points(void)
{
    return section_points(SEC_MAIN, ARR_MAIN) + section_points(SEC_EXTRA, ARR_EXTRA) +
           section_points(SEC_SIDE, ARR_SIDE);
}

static char *utoa(char *p, u32 v)
{
    char tmp[10];
    u32 k = 0;
    do {
        tmp[k++] = '0' + v % 10;
        v /= 10;
    } while (v);
    while (k)
        *p++ = tmp[--k];
    return p;
}

static void msg_init(void)
{
    u32 i;
    if (msg_ready)
        return;
    for (i = 0; i < MSG_N * MSG_SIZE; i++) {
        bl11_msg_j[i] = MSG_J[i];
        bl11_msg_e[i] = MSG_E[i];
    }
    for (i = 0; i < MSG_SIZE; i++) {
        bl11_msg_j[MSG_N * MSG_SIZE + i] = MSG_J[MSG_LIMIT * MSG_SIZE + i];
        bl11_msg_e[MSG_N * MSG_SIZE + i] = MSG_E[MSG_LIMIT * MSG_SIZE + i];
    }
    *(u16 *)(bl11_msg_j + MSG_N * MSG_SIZE + 2) = MSG_FORMAT_STRING;
    *(u16 *)(bl11_msg_e + MSG_N * MSG_SIZE + 2) = MSG_FORMAT_STRING;
    *(u16 *)(bl11_msg_j + MSG_N * MSG_SIZE + MSG_TEXT) = BL11_POINT_TEXT;
    *(u16 *)(bl11_msg_e + MSG_N * MSG_SIZE + MSG_TEXT) = BL11_POINT_TEXT;
    msg_ready = 1;
}

u32 bl11_dialog_open(void *dlg, u32 id, u32 param)
{
    msg_init();
    return ((u32 (*)(void *, u32, u32))0x0216ffc8)(dlg, id, param);
}

u32 bl11_exit_check(u8 *ui)
{
    u32 *msg = (u32 *)(ui + UI_MSG);
    u32 id, c, total;
    char *p;
    msg[0] = MSG_DIALOG;
    msg[2] = 0;
    if (MAIN_COPIES[SEC_MAIN] < MAIN_MIN) {
        msg[1] = MSG_UNDER_40;
        return 0;
    }
    id = LIMIT_CHECK(ED);
    if (id) {
        msg[1] = MSG_LIMIT;
        msg[2] = id;
        return 0;
    }
    c = cap();
    if (c && (total = deck_points()) > c) {
        msg_init();
        msg_arg[0] = (LANG_WORD & 0x7ff) >> 8;
        p = utoa(msg_arg + 1, total);
        *p++ = '/';
        *utoa(p, c) = 0;
        msg[1] = MSG_N;
        msg[2] = (u32)msg_arg;
        return 0;
    }
    msg[1] = MSG_EXIT;
    return 1;
}

static u32 text_id(u32 id)
{
    static const u16 map[][2] = {
#define X(a, b) {a, b},
        BL11_TEXT_MAP
#undef X
    };
    u32 i;
    if (CUR_SRC == 0 && CUR_IDX == BL11_POINT_INDEX)
        for (i = 0; i < sizeof map / sizeof map[0]; i++)
            if (map[i][0] == id)
                return map[i][1];
    return id;
}

const char *bl11_text_file(u32 id)
{
    id = text_id(id);
    FILE_READ(TEXT_INDX, TEXT_BUF, id << 2, 8);
    FILE_READ(TEXT_TEXT, TEXT_BUF, TEXT_BUF[0], TEXT_BUF[1] - TEXT_BUF[0]);
    return (const char *)TEXT_BUF;
}

const char *bl11_text_table(u32 id, const u8 *st)
{
    return (const char *)(*(const u32 *)(st + 0x20) + (*(const u32 *const *)(st + 0x1c))[text_id(id)]);
}

#define GLYPH ((void (*)(void *, u32, u32, s32, s32))0x021710b0)
#define BANK ((u8 *)0x02221ea4)
#define BANK_WIDTH 0x14
#define BANK_CANVAS 0x6c
#define BANK_FILL 0x70
#define UI_MODE 0x10c
#define MODE_DECK 0
#define MODE_TURBO 3
#define UNLIMITED 3
#define ICON_POINTS 0x10
#define DIGITS_SMALL 2
#define TILE_SLASH 14
#define DIGIT_W 4
#define SCREEN_W 256
#define SCREEN_H 192
#define TOTAL_Y 3
#define TOTAL_RIGHT 6
#define TOTAL_CLEAR_W 48
#define GLYPH_H 8
#define OUTLINE_RED 0xd
#define BG_MAP ((volatile u16 *)0x06203000)
#define MAP_W 32
#define CANVAS_TILE0 2
#define TOTAL_ROWS 2
#define PAL_TEXT 1
#define PAL_RED 4
#define PAL_YELLOW 10
#define FILL_YELLOW 0xe
#define CARD_DX (-1)
#define CARD_DY (-1)
#define CARD_W 21
#define CARD_H 25
#define ROW_DX (-2)
#define ROW_DY (-2)
#define ROW_W 23
#define ROW_H 27
#define FONT_W 3
#define FONT_H 5
#define ICON_H 8
#define ICON_BORDER 5
#define ICON_WHITE 0xf

static void pixel(s32 x, s32 y, u32 c)
{
    u32 w = *(u32 *)(BANK + BANK_WIDTH);
    u32 a = *(u32 *)(BANK + BANK_CANVAS) + ((y >> 3) * w + (x >> 3)) * 32 + (y & 7) * 4 + ((x & 7) >> 1);
    volatile u16 *h = (volatile u16 *)(a & ~1);
    u32 sh = (a & 1) * 8 + (x & 1) * 4;
    if (x < 0 || y < 0 || x >= SCREEN_W || y >= SCREEN_H)
        return;
    *h = (*h & ~(0xf << sh)) | c << sh;
}

static void outline(s32 x, s32 y, s32 w, s32 h)
{
    s32 i;
    for (i = 0; i < w; i++) {
        pixel(x + i, y, OUTLINE_RED);
        pixel(x + i, y + h - 1, OUTLINE_RED);
    }
    for (i = 0; i < h; i++) {
        pixel(x, y + i, OUTLINE_RED);
        pixel(x + w - 1, y + i, OUTLINE_RED);
    }
}

static void point_icon(u32 v, s32 x, s32 y)
{
    static const u8 font[10][FONT_H] = {
        {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
        {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 2, 2}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7},
    };
    char buf[10];
    s32 n = utoa(buf, v) - buf, w = (FONT_W + 1) * n + 3, i, j, k;
    for (j = 0; j < ICON_H; j++)
        for (i = 0; i < w; i++) {
            u32 edge_x = i == 0 || i == w - 1, edge_y = j == 0 || j == ICON_H - 1;
            if (!(edge_x && edge_y))
                pixel(x + i, y + j, edge_x || edge_y ? ICON_BORDER : OUTLINE_RED);
        }
    for (k = 0; k < n; k++)
        for (j = 0; j < FONT_H; j++)
            for (i = 0; i < FONT_W; i++)
                if (font[buf[k] - '0'][j] >> (FONT_W - 1 - i) & 1)
                    pixel(x + 2 + (FONT_W + 1) * k + i, y + 2 + j, ICON_WHITE);
}

u32 bl11_icon_status(u32 id)
{
    u32 s = ((u32 (*)(u32))(0x0202ad60 | 1))(id), p;
    if (s == UNLIMITED && cap() && (p = points(id)))
        return ICON_POINTS + p;
    return s;
}

static void icon(void *bank, u32 group, u32 v, s32 x, s32 y, u32 row)
{
    if (v < UNLIMITED)
        GLYPH(bank, group, v, x, y);
    if (v < ICON_POINTS)
        return;
    v -= ICON_POINTS;
    if (row)
        outline(x + ROW_DX, y + ROW_DY, ROW_W, ROW_H);
    else
        outline(x + CARD_DX, y + CARD_DY, CARD_W, CARD_H);
    point_icon(v, x, y);
}

void bl11_icon_grid(void *bank, u32 group, u32 v, s32 x, s32 y)
{
    icon(bank, group, v, x, y, 0);
}

void bl11_icon_row(void *bank, u32 group, u32 v, s32 x, s32 y)
{
    icon(bank, group, v, x, y, 1);
}

void bl11_icon_detail(void *bank, u32 group, u32 v, s32 x, s32 y)
{
    if (v < UNLIMITED)
        GLYPH(bank, group, v, x, y);
    else if (v >= ICON_POINTS)
        point_icon(v - ICON_POINTS, x, y);
}

static s32 draw_num(u32 v, s32 x, s32 y)
{
    char buf[10];
    char *e = utoa(buf, v), *p;
    for (p = buf; p < e; p++, x += DIGIT_W)
        GLYPH(BANK, DIGITS_SMALL, *p - '0', x, y);
    return x;
}

static void total_palette(u32 pal)
{
    u32 row, col;
    for (row = 0; row < TOTAL_ROWS; row++)
        for (col = (SCREEN_W - TOTAL_CLEAR_W) / 8; col < MAP_W; col++) {
            volatile u16 *e = BG_MAP + row * MAP_W + col;
            if ((*e & 0x3ff) == CANVAS_TILE0 + row * MAP_W + col)
                *e = (*e & 0x0fff) | pal << 12;
        }
}

static void draw_total(u8 *ui)
{
    u32 c, total, n, mode = *(u32 *)(ui + UI_MODE), *fill = (u32 *)(BANK + BANK_FILL), old;
    s32 x, y;
    if ((mode != MODE_DECK && mode != MODE_TURBO) || !(c = cap()))
        return;
    for (y = 0; y < GLYPH_H; y++)
        for (x = SCREEN_W - TOTAL_CLEAR_W; x < SCREEN_W; x++)
            pixel(x, y + TOTAL_Y, 0);
    total = deck_points();
    for (n = 1, x = total; x >= 10; x /= 10)
        n++;
    for (x = c; x >= 10; x /= 10)
        n++;
    total_palette(total > c ? PAL_RED : total == c ? PAL_YELLOW : PAL_TEXT);
    old = *fill;
    if (total >= c)
        *fill = total > c ? OUTLINE_RED : FILL_YELLOW;
    x = draw_num(total, SCREEN_W - TOTAL_RIGHT - (n + 1) * DIGIT_W, TOTAL_Y);
    GLYPH(BANK, DIGITS_SMALL, TILE_SLASH, x, TOTAL_Y);
    draw_num(c, x + DIGIT_W, TOTAL_Y);
    *fill = old;
}

u32 bl11_stats(u8 *ui)
{
    u32 r = ((u32 (*)(u8 *))0x02160b74)(ui);
    draw_total(ui);
    return r;
}

u32 bl11_counters(u8 *ui)
{
    u32 r = ((u32 (*)(u8 *))0x02160e90)(ui);
    draw_total(ui);
    return r;
}

#define STATUS ((u32 (*)(u32))(0x0202ad60 | 1))
#define ED_MOVE ((u32 (*)(u8 *, s32, s32, u32, u32))0x021534b8)
#define ED_COPIES 0x12952
#define ARR_TRUNK 0xda00
#define LISTED 0

u32 bl11_view_status(u32 id)
{
    u32 s = STATUS(id);
    if (s == UNLIMITED && cap() && points(id))
        return LISTED;
    return s;
}

u32 bl11_view_insert(u8 *ui, s32 dst, s32 src, u32 id, u32 n)
{
    u8 *a = ui + ARR_TRUNK;
    u32 i, k;
    if (STATUS(id) != UNLIMITED)
        return ED_MOVE(ui, dst, src, id, n);
    k = *(u16 *)(ui + ED_COUNT + src * 2);
    for (i = 0; i < k; i++, a += 4)
        if (*(u16 *)a == id) {
            a[2] -= n;
            *(u16 *)(ui + ED_COPIES + src * 2) -= n;
            break;
        }
    return 1;
}

#define DECK ((u8 *)0x02124158)
#define DECK_COUNTS 0x1c
#define DECK_IDS 0x28
#define DECK_SLOTS 90
#define DECK_SIDE 60
#define DECK_EXTRA 75
#define CARD_ADD ((void (*)(u32, u32))(0x0202afcc | 1))
#define CARD_CLOSE ((void (*)(void))(0x02029850 | 1))
#define STARTER_N (BL11_STARTER_MAIN + BL11_STARTER_SIDE + BL11_STARTER_EXTRA)

static const u16 starter_ids[] = { BL11_STARTER_IDS 0 };

void bl11_starter(void)
{
    u32 *count = (u32 *)(DECK + DECK_COUNTS);
    u16 *ids = (u16 *)(DECK + DECK_IDS);
    u32 k;
    if (!BL11_STARTER_MAIN) {
        CARD_CLOSE();
        return;
    }
    for (k = 0; k < DECK_SLOTS; k++)
        ids[k] = 0;
    count[0] = BL11_STARTER_MAIN;
    count[1] = BL11_STARTER_SIDE;
    count[2] = BL11_STARTER_EXTRA;
    for (k = 0; k < STARTER_N; k++) {
        if (k < BL11_STARTER_MAIN)
            ids[k] = starter_ids[k];
        else if (k < BL11_STARTER_MAIN + BL11_STARTER_SIDE)
            ids[DECK_SIDE + k - BL11_STARTER_MAIN] = starter_ids[k];
        else
            ids[DECK_EXTRA + k - BL11_STARTER_MAIN - BL11_STARTER_SIDE] = starter_ids[k];
        CARD_ADD(starter_ids[k], 1);
    }
    CARD_CLOSE();
}
