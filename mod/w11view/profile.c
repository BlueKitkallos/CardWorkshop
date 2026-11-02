typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define REG(a) (*(volatile u32 *)(a))
#define HW(a) (*(volatile u16 *)(a))

#define SCENE ((void (*)(u32, u32, u32))0x02016cf5)
#define SET_CALLBACK ((void (*)(u32))0x02014ff1)
#define LOAD_TEXT ((void (*)(u32))0x020297c5)
#define MENU_ID REG(0x020b8f3c)
#define MENU_RETURN REG(0x020b8f38)
#define USER_SETTINGS_ID 0x4001u

#define LANG_WORD REG(0x021264a4)
#define LANG_BITS 0x700u
#define TAG_WORD REG(0x021264a8)
#define TAG_LANG_BITS 0x38000000u
#define TAG_NAME ((volatile u8 *)0x021264b4)
#define TAG_NAME_SIZE 0x30
#define AVATAR REG(0x021240c0)
#define AVATAR_HAIR_GENDER 0x10001fu
#define HAIR_COLOR HW(0x021240c4)
#define WEAR_COLOR HW(0x021240c6)
#define HAIR_PRESET ((u32 (*)(u32, u32))0x02019c65)
#define WEAR_PRESET ((u32 (*)(u32, u32))0x02019c85)
#define FIXED_TEXT ((volatile u8 *)0x021240c8)
#define FIXED_TEXT_SIZE 29
#define FIXED_MALE 6u
#define FIXED_FEMALE 0x44u

#define CM_ENTRY 0x0214cef4u
#define CM_INIT ((int (*)(void))0x0214cadc)
#define CM_SETUP ((int (*)(void))0x0214cc30)
#define CM_CONFIRM ((int (*)(void))0x0214cd20)
#define CM_GENDER_EXIT ((int (*)(void))0x0214ea58)
#define CM_STEP REG(0x02154104)
#define CM_GENDER HW(0x02154130)
#define CM_COUNTRY HW(0x02154134)
#define CM_NOTICE REG(0x02154138)
#define CM_SUMMARY_STEP 5u

u32 pe_items[7 * 5];
static u32 editing, lang0, tag0, avatar0;
static u16 hair0, wear0;
static u8 tag_name0[TAG_NAME_SIZE];

static void copy(volatile u8 *to, const volatile u8 *from, int n)
{
    while (n--)
        *to++ = *from++;
}

void pe_menu_go(void)
{
    editing = 1;
    lang0 = LANG_WORD & LANG_BITS;
    tag0 = TAG_WORD & TAG_LANG_BITS;
    avatar0 = AVATAR;
    hair0 = HAIR_COLOR;
    wear0 = WEAR_COLOR;
    copy(tag_name0, TAG_NAME, TAG_NAME_SIZE);
    SCENE(7, 0xd, CM_ENTRY);
}

int pe_init(void)
{
    int r = CM_INIT();
    if (editing) {
        CM_GENDER = AVATAR >> 20 & 1;
        CM_COUNTRY = AVATAR >> 21 & 0x3f;
        CM_NOTICE = 0;
        CM_STEP = CM_SUMMARY_STEP - 1;
    }
    return r;
}

int pe_setup(void)
{
    if (editing && (LANG_WORD & LANG_BITS) != lang0) {
        LANG_WORD = (LANG_WORD & ~LANG_BITS) | lang0;
        LOAD_TEXT(lang0 >> 8);
    }
    return CM_SETUP();
}

int pe_confirm(void)
{
    int r = CM_CONFIRM();
    if (editing) {
        TAG_WORD = (TAG_WORD & ~TAG_LANG_BITS) | tag0;
        copy(TAG_NAME, tag_name0, TAG_NAME_SIZE);
    }
    return r;
}

int pe_gender_exit(void)
{
    u32 g0 = CM_GENDER, g1, old, now;
    u16 hair = HAIR_COLOR, wear = WEAR_COLOR;
    u8 text[FIXED_TEXT_SIZE];
    int r, i;
    copy(text, FIXED_TEXT, FIXED_TEXT_SIZE);
    r = CM_GENDER_EXIT();
    if (!editing)
        return r;
    g1 = CM_GENDER;
    if (g1 == g0) {
        HAIR_COLOR = hair;
        WEAR_COLOR = wear;
    } else if (g1 == (avatar0 >> 20 & 1)) {
        WEAR_COLOR = wear0;
    }
    old = g0 == 1 ? FIXED_FEMALE : FIXED_MALE;
    now = g1 == 1 ? FIXED_FEMALE : FIXED_MALE;
    for (i = 0; i < FIXED_TEXT_SIZE; i++)
        FIXED_TEXT[i] = text[i] == old ? now : text[i];
    return r;
}

u32 pe_hair_color(const u16 *cm)
{
    u32 style = *(const u32 *)(cm + 6);
    if (!style)
        style = cm[0] & 0xff;
    style &= 0xffff;
    if (editing && CM_GENDER == (avatar0 >> 20 & 1) && style == (avatar0 & 0x1f))
        return hair0;
    return HAIR_PRESET(CM_GENDER, style);
}

u32 pe_wear_color(const u16 *cm)
{
    if (editing)
        return WEAR_COLOR;
    return WEAR_PRESET(CM_GENDER, cm[1] & 0xff);
}

static int pe_back(void)
{
    return 1;
}

int pe_done(void)
{
    if (!editing) {
        SCENE(7, 0x12, 0x0214e104);
        return 0;
    }
    editing = 0;
    if (((AVATAR ^ avatar0) & AVATAR_HAIR_GENDER) == 0)
        HAIR_COLOR = hair0;
    MENU_ID = USER_SETTINGS_ID;
    MENU_RETURN = 1;
    SET_CALLBACK((u32)pe_back);
    return 0;
}
