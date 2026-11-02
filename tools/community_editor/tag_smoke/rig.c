typedef unsigned int u32;
#define W(a) (*(volatile u32 *)(a))
#define MODE 0x020b8f3cu
#define TEAM_BITS 0x021268b4u
#define RECORDS 0x021247c8u
#define LIST_SCENE 0x02157000u
extern void body_init(void);
extern void scene_change(u32, u32, u32);
u32 tag_rig_call(u32 (*fn)(u32, u32), u32 a, u32 b)
{
    return fn(a, b);
}

volatile u32 tag_rig[5] = {0, 0x2003, 0x27, 0x63636363, (u32)tag_rig_call};

int tag_rig_start(void)
{
    if (tag_rig[0]) return 0;
    tag_rig[0] = 1;
    W(0x021264a4) = (W(0x021264a4) & ~0x700u) | 0x100u;
    body_init();
    W(MODE) = tag_rig[1];
    W(TEAM_BITS) = tag_rig[2];
    W(RECORDS) = 0x00010203;
    W(RECORDS + 4 * 20) = 0x00040506;
    W(RECORDS + 4 * 49) = tag_rig[3];
    W(RECORDS + 4 * 50) = tag_rig[3];
    scene_change(7, 5, LIST_SCENE);
    return 0;
}
