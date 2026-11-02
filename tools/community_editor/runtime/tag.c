typedef unsigned short u16;
typedef unsigned int u32;

struct team { u16 team, flags, first, second, text, pad; };
extern const struct team w11tag_teams[];
extern const u32 w11tag_teams_n;

#define STOCK_TEAMS ((const u32 *)0x0209b760)
#define STOCK_TEAM_N 49
#define LIST ((volatile unsigned char *)0x021610a0)
#define LIST_COUNT (*(volatile u16 *)(LIST + 0xeeae))
#define LIST_INDEX ((volatile u16 *)(LIST + 0xf320))
#define LIST_CAP 256
#define MODE (*(volatile u32 *)0x020b8f3c)
#define MODE_TURBO_TAG 0x2004

u32 w11tag_team(u32 team)
{
    u32 i;
    if (team < STOCK_TEAM_N)
        return STOCK_TEAMS[team];
    for (i = 0; i < w11tag_teams_n; i++)
        if (w11tag_teams[i].team == team)
            return w11tag_teams[i].first | (u32)w11tag_teams[i].second << 16;
    return 0;
}

int w11tag_text(u32 team)
{
    u32 i;
    for (i = 0; i < w11tag_teams_n; i++)
        if (w11tag_teams[i].team == team)
            return w11tag_teams[i].text;
    return -1;
}

void w11tag_append(void)
{
    u32 i;
    for (i = 0; i < w11tag_teams_n && LIST_COUNT < LIST_CAP; i++) {
        if ((w11tag_teams[i].flags >> 15) != (MODE == MODE_TURBO_TAG))
            continue;
        LIST_INDEX[LIST_COUNT] = w11tag_teams[i].team;
        LIST_COUNT = LIST_COUNT + 1;
    }
}
