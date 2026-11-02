typedef unsigned short u16;
typedef unsigned int u32;

extern const u16 w11npc_free[];
extern const u32 w11npc_free_n;

#define LIST ((volatile unsigned char *)0x021610a0)
#define LIST_COUNT (*(volatile u16 *)(LIST + 0xeeae))
#define LIST_CHARS ((volatile u16 *)(LIST + 0xf120))
#define LIST_INDEX ((volatile u16 *)(LIST + 0xf320))
#define LIST_CAP 256
#define MODE (*(volatile u32 *)0x020b8f3c)
#define MODE_TURBO 0x2002
#define LIST_DONE ((void (*)(void))(0x0202cfb0 | 1))
#define CHAR_DECK ((int (*)(u32))(0x0201a428 | 1))
#define NEW_DECKS 0x12d
#define RECORD_NONE 0x115

void w11free_append(void)
{
    u32 i;
    LIST_DONE();
    for (i = 0; i < w11npc_free_n && LIST_COUNT < LIST_CAP; i++) {
        u16 flags = w11npc_free[2 * i + 1];
        if ((flags >> 15) != (MODE == MODE_TURBO))
            continue;
        LIST_CHARS[LIST_COUNT] = w11npc_free[2 * i];
        LIST_INDEX[LIST_COUNT] = flags & 0x7fff;
        LIST_COUNT = LIST_COUNT + 1;
    }
}

int w11free_record_deck(u32 chara)
{
    int deck = CHAR_DECK(chara);
    return deck >= NEW_DECKS ? RECORD_NONE : deck;
}
