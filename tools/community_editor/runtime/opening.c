typedef unsigned int u32;
#define UI 0x02159e44u
extern u32 community_pack_rarity(u32, u32);
u32 w11pk_rarity(u32 id, u32 pack) { return community_pack_rarity(id, pack); }
u32 w11_visual_frame(u32 id) { return ((u32 (*)(u32))0x02022d71)(id); }
void *w11_frame128(u32 frame) { return ((void *(*)(u32))0x0202b531)(frame); }
void community_open_entry(void) {
    ((void (*)(u32,u32))0x02152854)(UI,1);
    ((void (*)(u32,u32))0x02152548)(UI,1);
}
