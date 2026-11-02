typedef unsigned int u32;
extern void body_save(void), body_init(void);
extern u32 body_load(u32 dst, int slot);
extern void w11pk_save(void), w11pk_load(void), w11pk_clear(void);
void community_save_body(void) { body_save(); w11pk_save(); }
u32 community_load_body(u32 dst, int slot) {
    u32 result = body_load(dst, slot);
    w11pk_load();
    return result;
}
void community_body_init(void) { w11pk_clear(); body_init(); }
