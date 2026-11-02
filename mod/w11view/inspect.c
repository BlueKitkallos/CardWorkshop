/* Read-only spectator inspection uses the stock field cursor and card details.
 * The simulation is frozen; CPU controllers remain CPU so their private cards
 * retain the stock opponent privacy checks as well as View Mode's backs. */
typedef unsigned int u32;
typedef unsigned short u16;
#define REG(a) (*(volatile u32 *)(a))
#define HW(a) (*(volatile u16 *)(a))
extern u32 vm_state, story_spectate;
u32 inspect_next_step;
u32 inspect_paused;
static u32 requested, saved_select, saved_view;
void inspect_reset(void) { requested = inspect_paused = 0; }
#define SELECT REG(0x02297328)
#define FIELD ((volatile u32 *)0x022963f8)
#define PAD HW(0x020b87de)
#define NEW HW(0x020b87e0)
#define REPEAT HW(0x020b87e4)
#define VIEW ((u32 (*)(void))0x021466d8)
#define SET_VIEW ((int (*)(u32))0x0214656c)
#define FIELD_IDLE ((int (*)(u32))0x0216b39c)
#define FIELD_TICK ((void (*)(u32))0x0216d624)

void inspect_input(void)
{
    if (vm_state != 3) { requested = inspect_paused = 0; return; }
    if (NEW & 2) {
        NEW &= ~2u;
        PAD &= ~2u;
        if (inspect_paused) {
            inspect_paused = 0;
            SELECT = saved_select;
            SET_VIEW(saved_view);
        } else requested ^= 1;
    }
    if (requested && !inspect_paused && !REG(0x0229451c) &&
        !FIELD_IDLE((u32)FIELD) && VIEW() < 7) {
        saved_select = SELECT;
        saved_view = VIEW();
        SELECT = 0;
        inspect_paused = 1;
        requested = 0;
        SET_VIEW(4);
    }
}

int inspect_step(void)
{
    if (inspect_paused) return 0;
    return ((int (*)(void))inspect_next_step)();
}

void inspect_field(u32 field)
{
    u32 masks[2], i;
    u16 held, pressed, previous;
    if (!inspect_paused) { FIELD_TICK(field); return; }
    /* No action can be selected, including the release-of-A path. */
    held = PAD; pressed = NEW; previous = HW(0x020b87dc);
    PAD &= ~1u; NEW &= ~1u; HW(0x020b87dc) &= ~1u;
    for (i = 0; i < 2; i++) {
        masks[i] = REG(field + 0x8b0 + 4 * i);
        REG(field + 0x8b0 + 4 * i) = 0;
    }
    FIELD_TICK(field);
    for (i = 0; i < 2; i++) REG(field + 0x8b0 + 4 * i) = masks[i];
    PAD = held; NEW = pressed; HW(0x020b87dc) = previous;
}
