typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define LANG ((*(volatile u32 *)0x021264a4) >> 8 & 7)
#define GAME_TEXT ((const u8 *(*)(u32))0x0202b64d)
#define TEXT_FIRST 0x7f00u
#define TEXTS 2
#define LANGS 7
#define NO_TEXT 0xffffu

u16 pe_text_fallback[TEXTS] = { 0 };
u16 pe_text_offs[TEXTS][LANGS] = { { 0 } };
u8 pe_text_data[384] = { 0 };

const u8 *pe_text(u32 id)
{
    u32 k = id - TEXT_FIRST, l = LANG;
    if (l < LANGS && pe_text_offs[k][l] != NO_TEXT)
        return pe_text_data + pe_text_offs[k][l];
    return GAME_TEXT(pe_text_fallback[k]);
}
