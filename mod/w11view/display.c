typedef unsigned int u32;

#define PALETTE_QUEUE 0x020b916c
#define QUEUE_FIRST 3
#define QUEUE_END 51
#define QUEUE_OBJ_EXT_PALETTE 3
#define SPRITE_DRAW ((void (*)(u32, u32, u32, u32, u32, u32, u32, u32, u32))0x021684e0)

static u32 obj_palette_pending(u32 slot)
{
    for (u32 i = QUEUE_FIRST; i < QUEUE_END; i++) {
        u32 *q = (u32 *)(PALETTE_QUEUE + i * 0x24);
        if (q[0] == QUEUE_OBJ_EXT_PALETTE && q[1] && q[4] == slot << 9)
            return 1;
    }
    return 0;
}

void material_draw(u32 a, u32 b, u32 c, u32 slot, u32 x, u32 y, u32 p7, u32 p8, u32 p9)
{
    if (obj_palette_pending(slot))
        return;
    SPRITE_DRAW(a, b, c, slot, x, y, p7, p8, p9);
}

#define JOB_HEAD (*(volatile unsigned short *)0x021219da)
#define JOB_TAIL (*(volatile unsigned short *)0x021219d8)
#define JOBS 0x0211f818
#define JOB_SIZE 0x3c
#define JOB_RING 0x90
#define JOB_UPLOAD 3
#define FREE ((void (*)(u32))0x02016aa9)
#define GFX_LOAD ((void (*)(u32 *))0x0201c03d)
#define JOB_FREE ((void (*)(u32))0x020202a5)

static u32 panel_frame[10];
static u32 panel_frame_held, panel_job;
void panel_job_done(u32 arg);

static u32 panel_job_pending(void)
{
    u32 head = JOB_HEAD, tail = JOB_TAIL;
    u32 *job = (u32 *)(JOBS + panel_job * JOB_SIZE);
    return (panel_job + JOB_RING - head) % JOB_RING < (tail + JOB_RING - head) % JOB_RING &&
           job[0] == JOB_UPLOAD && job[12] == (u32)panel_job_done;
}

void panel_frame_hold(u32 *request)
{
    if (panel_frame_held && panel_job_pending())
        FREE(panel_frame[0]);
    for (u32 i = 0; i < 10; i++)
        panel_frame[i] = request[i];
    panel_frame_held = 1;
    panel_job = JOB_TAIL;
}

void panel_frame_free(u32 data)
{
    if (panel_frame_held && data == panel_frame[0])
        return;
    FREE(data);
}

static void panel_frame_load(void)
{
    if (!panel_frame_held)
        return;
    panel_frame_held = 0;
    GFX_LOAD(panel_frame);
    FREE(panel_frame[0]);
}

void panel_job_upload(u32 *request)
{
    u32 *job = (u32 *)(JOBS + JOB_HEAD * JOB_SIZE);
    if (job[12] == (u32)panel_job_done)
        panel_frame_load();
    GFX_LOAD(request);
}

void panel_job_done(u32 arg)
{
    panel_frame_load();
    JOB_FREE(arg);
}
