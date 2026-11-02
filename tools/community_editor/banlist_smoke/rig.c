/* Native list loading and 99-point status probe, after direct shop setup. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define W(a) (*(volatile u32 *)(a))
#define H(a) (*(volatile u16 *)(a))
extern void body_init(void),pad_read(void),scene_change(u32,u32,u32);
extern u32 community_probe_icon(u32);
struct {u32 magic,state,frame,classic_status,point_status,src,index;} banlist_smoke={0x424c5354u};
int smoke_start(void){if(banlist_smoke.state)return 0;banlist_smoke.state=1;W(0x021264a4)=(W(0x021264a4)&~0x700u)|0x100u;body_init();scene_change(7,10,0x0214d6f4);return 0;}
void smoke_frame(void){
 pad_read();
 if(banlist_smoke.state==1&&W(0x02159de8)&&H(0x02159db4)){banlist_smoke.state=2;banlist_smoke.frame=W(0x020b7cc4);}
 else if(banlist_smoke.state==2&&W(0x020b7cc4)-banlist_smoke.frame>60){
  W(0x02126460)&=~1u;
  *(volatile u8 *)0x02127305=3;
  ((void *(*)(u32,u32,u8 *))0x0202ac91)(0,3,0);
  banlist_smoke.classic_status=((u32(*)(u32))0x0202ad61)(4007);
  *(volatile u8 *)0x02127305=4;
  ((void *(*)(u32,u32,u8 *))0x0202ac91)(0,4,0);
  banlist_smoke.point_status=community_probe_icon(4007);
  banlist_smoke.src=H(0x02122114);banlist_smoke.index=H(0x02122116);
  banlist_smoke.state=3;
 }
}
