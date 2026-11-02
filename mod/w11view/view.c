typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define REG(a) (*(volatile u32 *)(a))
#define HW(a) (*(volatile u16 *)(a))

#define SCENE ((void (*)(u32, u32, u32))0x02016cf5)
#define SET_CALLBACK ((void (*)(u32))0x02014ff1)
#define DUEL_MODE_RESET ((void (*)(u32, u32))0x02018e6d)
#define BUSTUP_LOAD ((void (*)(u32))0x0214d5e8)
#define BUSTUP_LEFT_X 0xfffffef0u
#define SPRINTF ((int (*)(char *, const char *, ...))0x020508f0)
#define FILE_EXISTS ((int (*)(const char *))0x02016849)
#define BUSTUP_FILE_NO ((int (*)(u32))0x02017e99)
#define RESULT_PANEL ((void (*)(u32))0x0219ae95)
#define PORTRAIT ((volatile u32 *)0x020b8b18)
#define GAME_LANG REG(0x020b7cbc)
#define OAM_HFLIP 0x1000u
#define OAM_AFFINE 0x100u
#define CELL0_SHIFT 32
#define LIST_SCENE 0x02157000u
#define DUEL_LAUNCH 0x02019359u
#define CALLBACK REG(0x020b7c8c)
#define MENU_ID REG(0x020b8f3c)
#define LIST_PICK HW(0x020b8f40)
#define MENU_RETURN REG(0x020b8f38)
#define LAUNCH_STEP REG(0x020b8834)
#define CFG_CONTROL ((volatile u32 *)0x020b8bf4)
#define CFG_FIRST REG(0x020b8c14)
#define CFG_SIDE REG(0x020b8bf0)
#define JANKEN_PICK ((int (*)(u32))0x021511c8)
#define TIME_UP REG(0x020b8be0)
#define DECIDED REG(0x0229dd44)
#define DP REG(0x02124094)
#define PAD_HELD HW(0x020b87de)
#define BRIGHT_MAIN HW(0x020b9130)
#define BRIGHT_SUB HW(0x020b9132)
#define BRIGHT_BLACK ((u16)-16)
#define MASTER_BRIGHT_MAIN HW(0x0400006c)
#define MASTER_BRIGHT_SUB HW(0x0400106c)
#define MASTER_BLACK 0x8010u
#define PAD_NEW ((volatile u16 *)0x020b87e0)
#define KEY_B 2u
#define KEY_START 8u
#define KEY_A 1u
#define KEY_HAND_MOVE 0x30u
#define KEY_HAND_LOCK 0x4000u
#define VIEW_ID 0x2007u
#define JANKEN 2u

enum { VM_OFF, VM_PICK1, VM_PICK2, VM_DUEL };

extern u32 vm_state;
extern u32 story_spectate;
extern u32 inspect_paused;
extern void inspect_input(void);
extern void story_finish(void);
extern void inspect_reset(void);
u32 vm_next_loop = 0;
u32 vm_next_exit = 0;
u32 vm_items[7 * 5];
static u32 dp_start, dp_saved;
static u32 in_duel;
static u32 jk_wait;

void vm_story_begin(void)
{
    dp_saved = 0;
    jk_wait = 0;
    inspect_reset();
}

static const struct { u32 addr; u16 size, stride; } fields[] = {
    { 0x020b8864, 4, 4 }, { 0x020b8874, 4, 4 }, { 0x020b8884, 1, 1 }, { 0x020b8888, 0x3a, 0x3a },
    { 0x020b8970, 1, 1 }, { 0x020b8974, 0x3a, 0x3a }, { 0x020b8a5c, 1, 1 }, { 0x020b8a60, 2, 2 },
    { 0x020b8a68, 2, 2 }, { 0x020b8a70, 0xc, 0xc }, { 0x020b8b18, 4, 4 }, { 0x020b8b28, 2, 2 },
    { 0x020b8b30, 2, 2 }, { 0x020b8b38, 0x1c, 0x1c }, { 0x020b8ba8, 1, 1 }, { 0x020b8bac, 1, 1 },
    { 0x020b8bb0, 1, 1 }, { 0x020b8bb4, 1, 1 }, { 0x020b8bb8, 1, 1 }, { 0x020b8bbc, 5, 5 },
    { 0x020b8c18, 0xc0, 0xc0 },
};
#define N_FIELDS (sizeof(fields) / sizeof(fields[0]))

static u8 first_pick[384];

static void copy_side(int to_buf)
{
    u8 *p = first_pick;
    u32 i, k;
    for (i = 0; i < N_FIELDS; i++) {
        volatile u8 *side0 = (volatile u8 *)fields[i].addr;
        volatile u8 *side1 = side0 + fields[i].stride;
        for (k = 0; k < fields[i].size; k++, p++) {
            if (to_buf)
                *p = side1[k];
            else
                side0[k] = *p;
        }
    }
}

void vm_menu_go(void)
{
    vm_state = VM_PICK1;
    MENU_ID = VIEW_ID;
    SCENE(7, 5, LIST_SCENE);
}

void vm_list_exit(u32 a, u32 b, u32 cb)
{
    if (MENU_ID != VIEW_ID || (vm_state != VM_PICK1 && vm_state != VM_PICK2)) {
        vm_state = VM_OFF;
        SCENE(a, b, cb);
        return;
    }
    if (vm_state == VM_PICK1) {
        copy_side(1);
        vm_state = VM_PICK2;
        SCENE(7, 5, LIST_SCENE);
        return;
    }
    DUEL_MODE_RESET(0, LIST_PICK + 1);
    copy_side(0);
    CFG_CONTROL[0] = 1;
    CFG_CONTROL[1] = 1;
    CFG_FIRST = JANKEN;
    LAUNCH_STEP = 0;
    dp_saved = 0;
    jk_wait = 1;
    vm_state = VM_DUEL;
    SET_CALLBACK(DUEL_LAUNCH);
}

int vm_loop(void)
{
    in_duel = 1;
    if (vm_state == VM_DUEL) {
        inspect_input();
        if (!dp_saved) {
            dp_start = DP;
            dp_saved = 1;
        }
        if (DECIDED == 1)
            DP = dp_start;
        else {
            if (!story_spectate && (PAD_NEW[0] | PAD_NEW[1]) & KEY_START)
                TIME_UP = 1;
            if (!inspect_paused) {
                PAD_HELD = 0;
                PAD_NEW[0] = 0;
                PAD_NEW[1] = 0;
                PAD_NEW[2] = 0;
            }
        }
    }
    return ((int (*)(void))vm_next_loop)();
}

static int left_art_exists(u32 side)
{
    char path[64];
    u32 id = PORTRAIT[side] & 0x7fffffffu;
    const char *variant = id >= 10000 ? "B" : "";
    const char *lang = GAME_LANG ? "_e" : "_j";
    int no = BUSTUP_FILE_NO(id);
    SPRINTF(path, "/duel2d/BustupL/bu%03d%s_L%s.LZncer", no, variant, lang);
    if (FILE_EXISTS(path))
        return 1;
    SPRINTF(path, "/duel2d/BustupL/bu%03d%s_L.LZncer", no, variant);
    return FILE_EXISTS(path);
}

static const u8 obj_width[3][4] = { { 8, 16, 32, 64 }, { 16, 32, 32, 64 }, { 8, 8, 16, 32 } };

static void mirror_cells(u32 bank)
{
    u32 n = HW(bank), stride = HW(bank + 2) & 1 ? 16 : 8;
    u32 cells = REG(bank + 4), i, k;
    for (i = 0; i < n; i++) {
        u32 cell = cells + i * stride;
        volatile u16 *oam = (volatile u16 *)REG(cell + 4);
        for (k = 0; k < HW(cell); k++, oam += 3) {
            u32 shape = oam[0] >> 14, w;
            int x;
            if (oam[0] & OAM_AFFINE || shape > 2)
                continue;
            w = obj_width[shape][oam[1] >> 14];
            x = oam[1] & 0x1ff;
            if (x & 0x100)
                x -= 0x200;
            x = -x - (int)w - (i == 0 ? CELL0_SHIFT : 0);
            oam[1] = (u16)((oam[1] & ~0x1ffu) ^ OAM_HFLIP) | (x & 0x1ff);
        }
    }
}

void vm_bustup(u32 hud)
{
    volatile u32 *from_right = (volatile u32 *)(hud + 0x14);
    if (vm_state != VM_DUEL || *from_right || left_art_exists(REG(hud + 0x80))) {
        BUSTUP_LOAD(hud);
        return;
    }
    *from_right = 1;
    BUSTUP_LOAD(hud);
    *from_right = 0;
    REG(hud + 0x1c) = BUSTUP_LEFT_X;
    mirror_cells(REG(hud));
}

void vm_result_panel(u32 side)
{
    if (vm_state != VM_DUEL)
        RESULT_PANEL(side);
}

static int vm_back(void)
{
    BRIGHT_MAIN = BRIGHT_BLACK;
    BRIGHT_SUB = BRIGHT_BLACK;
    MASTER_BRIGHT_MAIN = MASTER_BLACK;
    MASTER_BRIGHT_SUB = MASTER_BLACK;
    return 1;
}

int vm_exit(void)
{
    int r = ((int (*)(void))vm_next_exit)();
    if (CALLBACK == DUEL_LAUNCH) {
        in_duel = 0;
        story_finish();
    }
    if (vm_state == VM_DUEL && CALLBACK == DUEL_LAUNCH) {
        if (dp_saved)
            DP = dp_start;
        vm_state = VM_OFF;
        jk_wait = 0;
        TIME_UP = 0;
        if (story_spectate) {
            story_spectate = 0;
            return r;
        }
        MENU_RETURN = 1;
        SET_CALLBACK((u32)vm_back);
    }
    return r;
}

void vm_bright(volatile u16 *reg, int v)
{
    if (v > 0 && !in_duel)
        v = v >= 8 ? -16 : -2 * v;
    if (v > 0)
        *reg = (u16)v | 0x4000;
    else if (v < 0)
        *reg = (u16)-v | 0x8000;
    else
        *reg = 0;
}

int vm_janken_pick(u32 scene)
{
    volatile u32 *control;
    u32 saved;
    u16 held, pressed, repeat;
    if (!jk_wait || vm_state != VM_DUEL)
        return JANKEN_PICK(scene);
    control = &CFG_CONTROL[CFG_SIDE & 1];
    saved = *control;
    held = PAD_HELD;
    pressed = PAD_NEW[0];
    repeat = PAD_NEW[1];
    *control = 0;
    PAD_HELD = held | KEY_HAND_LOCK;
    PAD_NEW[0] = pressed & ~KEY_A;
    PAD_NEW[1] = repeat & ~KEY_HAND_MOVE;
    JANKEN_PICK(scene);
    *control = saved;
    PAD_HELD = held;
    PAD_NEW[0] = pressed;
    PAD_NEW[1] = repeat;
    if (!(pressed & (KEY_A | KEY_START)))
        return 0;
    jk_wait = 0;
    return JANKEN_PICK(scene);
}
