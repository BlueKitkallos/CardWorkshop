#include "w11packsfx.h"
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define W(a) (*(volatile u32 *)(a))
#define H(a) (*(volatile u16 *)(a))
#define B(a) (*(volatile u8 *)(a))
#define CTX 0x02159f48u
#define UI 0x02159e44u
#define CALL0(a) ((void(*)(void))((a)|1))()
#define CALL1(a,x) ((void(*)(u32))((a)|1))((u32)(x))
#define CALL2(a,x,y) ((void(*)(u32,u32))((a)|1))((u32)(x),(u32)(y))
extern u32 w11pk_rarity(u32,u32),w11_visual_frame(u32);
extern void *w11_frame128(u32);
extern void w11_audio_debug_start(void) __attribute__((weak));
extern void w11_audio_debug_event(u32,u32,u32) __attribute__((weak));
extern void w11_audio_debug_tick(u32) __attribute__((weak));
static struct {u32 active,tick,scene,env,motion,stop_pc,disp,subdisp,mode,power,model_heap;u8 banks[10];u16 bank_state[16],bg[28],palette[256],blend[3];u8 *bank_f;u8 *saved,*data;char paths[6][24];u32 rarity,retry_id,retry_at,retry_count;} *reveal;
static u32 heap_saved[3],heap_active;
static void *load(const char *s){return ((void *(*)(const char *,u32,u32))0x020168e9)(s,4,0);}
static void *alloc(u32 n){return ((void *(*)(u32,u32,u32))0x02016469)(n,4,0);}
static void release(void *p){CALL1(0x020164dc,p);}
static void copy(void *d,const void *s,u32 n){u8 *a=d;const u8 *b=s;while(n--)*a++=*b++;}
static void fastcopy(void *d,const void *s,u32 n){((void(*)(const void *,void *,u32))0x02089558)(s,d,n);}
static void copyv(u32 d,const void *s,u32 n){volatile u16 *a=(volatile u16 *)d;const u16 *b=s;while(n){*a++=*b++;n-=2;}}
static u8 *block(void *p,u32 t){return ((u8 *(*)(void *,u32))0x0201b515)(p,t);}
static u32 sound(u32 id)
{
 u32 token=((u32(*)(u32,int,u32,u32))0x02034b80)(id,-1,0,1);
 if(w11_audio_debug_event)w11_audio_debug_event(id,token,reveal?reveal->tick:0);
 if(id==W11_PACK_FLIP||id==W11_PACK_FLIP1||id==W11_PACK_FLIP2||id==W11_PACK_FLIP3||id==W11_PACK_FLIP4){
  if(token)reveal->retry_count=0;
  else if(!reveal->retry_count){reveal->retry_id=id;reveal->retry_at=reveal->tick+1;reveal->retry_count=1;}
 }
 return token;
}
/* Must run before the scene VM clears the shared transfer queue, or the 2D backdrop's callbacks are lost. */
static void drain_transfers(void)
{
 while(H(0x021219da)!=H(0x021219d8))CALL1(0x02025ab4,0);
}
static void setvar(u32 n,u32 v){CALL2(0x02025234,n,v);}
static u32 getvar(u32 n){return ((u32(*)(u32))0x02025245)(n);}

static u32 distance(u16 a,u16 b){int r=(a&31)-(b&31),g=((a>>5)&31)-((b>>5)&31),v=((a>>10)&31)-((b>>10)&31);return r*r+g*g+v*v;}
void *w11open_texture(u32 id)
{
 if(!reveal)return 0;
 if(!id)return load("/bin2/opening10_back.bin");
 void *art=((void *(*)(u32))0x0202b425)(id),*frame=w11_frame128(w11_visual_frame(id));
 u8 *a=block(art,0x42474454),*f=block(frame,0x42474454);
 const u16 *am=(const u16 *)(a+28),*fm=(const u16 *)(f+28);
 const u8 *ap=a+28+W((u32)a+12),*fp=f+28+W((u32)f+12);
 u16 colors[256];copy(colors,block(art,0x50414c54)+12,512);copy(colors+240,block(frame,0x50414c54)+12+480,32);
 u16 *image=(u16 *)0x02254000;for(u32 i=0;i<128*128;i++)image[i]=0;
 for(u32 y=0;y<128;y++)for(u32 x=4;x<92;x++){
  u32 sy=y*136/128,e=fm[(sy/8)*12+x/8],tx=x&7,ty=sy&7;
  if(e&0x400){tx=7-tx;}if(e&0x800){ty=7-ty;}
  u32 c=fp[(e&1023)*64+ty*8+tx],opaque=c!=0;
  if(x>=16&&x<80&&sy>=32&&sy<96){u32 xx=x-16,yy=sy-32;e=am[(yy/8)*8+xx/8];tx=xx&7;ty=yy&7;if(e&0x400){tx=7-tx;}if(e&0x800){ty=7-ty;}c=((ap[(e&1023)*32+ty*4+tx/2]>>((tx&1)*4))&15)+(e>>12)*16;opaque=1;}
  image[y*128+x+16]=c|(opaque?256:0);
 }
 u8 *out=alloc(16+8+4+0x1500+8+12+6144);if(!out){release(frame);release(art);return load("/bin2/opening10_back.bin");}u16 *pal=(u16 *)(out+28);u32 n=0;u32 *tex=(u32 *)0x0225c000;u16 *index=(u16 *)((u8 *)tex+4096);volatile u16 *lookup=(volatile u16 *)0x0225d800;for(u32 k=0;k<1024;k++)lookup[k]=0xffff;
 for(u32 by=0;by<32;by++)for(u32 bx=0;bx<32;bx++){
  u16 px[16],unique[16],q[4];u8 counts[16];u32 transparent=0,uniform=1,distinct=0;((void(*)(u32,void *,u32))0x020894c8)(0,q,sizeof(q));((void(*)(u32,void *,u32))0x020894c8)(0,counts,sizeof(counts));
  for(u32 k=0;k<16;k++){px[k]=image[(by*4+k/4)*128+bx*4+k%4];if(!(px[k]&256))transparent=1;if(px[k]!=px[0])uniform=0;}
  u32 nc=transparent?3:4;
  if(uniform)q[0]=colors[px[0]&255];
  else {
   for(u32 k=0;k<16;k++)if(px[k]&256){u32 j=0;while(j<distinct&&unique[j]!=px[k])j++;if(j==distinct){unique[j]=px[k];distinct++;}counts[j]++;}
   for(u32 j=0;j<nc;j++){u32 best=0;for(u32 k=1;k<distinct;k++)if(counts[k]>counts[best])best=k;if(counts[best]){q[j]=colors[unique[best]&255];counts[best]=0;}}
  }
  u32 hash=(q[0]*3u^q[1]*5u^q[2]*7u^q[3]*11u)&1023,pi;
  while((pi=lookup[hash])!=0xffff){if(pal[pi]==q[0]&&pal[pi+1]==q[1]&&pal[pi+2]==q[2]&&pal[pi+3]==q[3])break;hash=(hash+1)&1023;}
  if(pi==0xffff){pi=0;if(n<0xa80){pi=n;lookup[hash]=pi;for(u32 j=0;j<4;j++)pal[n++]=q[j];}}
  u32 bits=uniform?(transparent?~0u:0):0;
  if(!uniform)for(u32 k=0;k<16;k++){u32 best=3,err=~0u;if(px[k]&256)for(u32 j=0;j<nc;j++){u16 c=colors[px[k]&255];if(c==pal[pi+j]){best=j;break;}u32 d=distance(c,pal[pi+j]);if(d<err){err=d;best=j;}}bits|=best<<(k*2);}
  u32 at=by*32+bx;tex[at]=bits;index[at]=(pi/2)|(transparent?0:0x8000);
 }
 copy(out,"NTTX\xff\xfe\0\1",8);W((u32)out+8)=16+8+4+n*2+8+12+6144;H((u32)out+12)=16;H((u32)out+14)=2;
 copy(out+16,"PALT",4);W((u32)out+20)=12+n*2;W((u32)out+24)=n;
 u8 *im=out+28+n*2;copy(im,"IMGE",4);W((u32)im+4)=20+6144;W((u32)im+8)=0x00040405;H((u32)im+12)=128;H((u32)im+14)=128;W((u32)im+16)=6144;copy(im+20,tex,6144);
 release(frame);release(art);return out;
}
/* Fixed RAM 0x02200000..0x0225e000 and 0x02260000..0x022c5000 is free only while the shop (ov10) is loaded. */
static void snapshot(void)
{
 reveal->saved=(u8 *)0x02200000;reveal->bank_f=(u8 *)0x02250000;
 fastcopy(reveal->saved,(void *)0x06800000,0x40000);
 fastcopy(reveal->saved+0x40000,(void *)0x06880000,0x10000);
}
static void restore(void)
{
 fastcopy((void *)0x06800000,reveal->saved,0x40000);
 fastcopy((void *)0x06880000,reveal->saved+0x40000,0x10000);
 fastcopy((void *)0x06890000,reveal->bank_f,0x4000);
}
static void model_heap_restore(void)
{
 W(0x020b99c0)=heap_saved[0];W(0x020b99a8)=heap_saved[1];W(0x020b99ac)=heap_saved[2];heap_active=0;
}
static void model_heap_begin(void)
{
 heap_saved[0]=W(0x020b99c0);heap_saved[1]=W(0x020b99a8);heap_saved[2]=W(0x020b99ac);heap_active=1;
 reveal->model_heap=((u32(*)(u32,u32,u32))0x0207c3fd)(0x02260000,0x65000,0);
 W(0x020b99c0)=reveal->model_heap;W(0x020b99a8)=1;W(0x020b99ac)=0;
}
static void model_heap_end(void)
{
 u32 left=0;for(u32 p=W(reveal->model_heap+0x2c);p;p=W(p+12))left++;
 W(0x020b9998)-=left;CALL1(0x0207c0ac,reveal->model_heap);
 model_heap_restore();
}
/* A new shop scene has a new heap: a leftover reveal pointer is dangling and must not be read. */
void w11open_scene_reset(void)
{
 if(heap_active)model_heap_restore();
 reveal=0;
}
void w11open_finish(void)
{
 if(!reveal)return;
 ((void(*)(void))0x02052f50)();W(0x04000000)&=~0x1f00u;
 if(reveal->active){drain_transfers();CALL0(0x020247b0);((void(*)(void))0x01ffa498)();model_heap_end();}
 CALL1(0x020842c8,0x33);
 restore();copyv(0x05000000,reveal->palette,512);copyv(0x04000008,reveal->bg,sizeof(reveal->bg));copyv(0x04000050,reveal->blend,sizeof(reveal->blend));
 copy((void *)0x0213e264,reveal->bank_state,sizeof(reveal->bank_state));
 for(u32 i=0;i<10;i++)if(i!=7)B(0x04000240+i)=reveal->banks[i];
 W(0x04000000)=reveal->disp;W(0x04001000)=reveal->subdisp;W(0x020b99bc)=reveal->mode;H(0x04000304)=reveal->power;
 W(UI+0x28)=~0u;release(reveal->data);release(reveal);reveal=0;
}
void w11open_start(u32 ui)
{
 (void)ui;if(reveal)w11open_finish();reveal=alloc(sizeof(*reveal));if(!reveal){H(CTX+0xcc18)=1;return;}reveal->active=0;reveal->tick=0;reveal->retry_id=0;reveal->retry_at=0;reveal->retry_count=0;
 reveal->data=load("/bin2/opening10_scene.bin");if(!reveal->data){release(reveal);reveal=0;H(CTX+0xcc18)=1;return;}u32 *header=(u32 *)reveal->data;u32 *rel=header+4;u8 *data=(u8 *)(rel+header[1]);
 for(u32 i=0;i<header[1];i++)W((u32)data+rel[i])+=(u32)data;
 drain_transfers();
 reveal->mode=W(0x020b99bc);reveal->power=H(0x04000304);H(0x04000304)|=0xc;W(0x020b99bc)=2;reveal->disp=W(0x04000000);reveal->subdisp=W(0x04001000);for(u32 i=0;i<10;i++)reveal->banks[i]=B(0x04000240+i);
 copy(reveal->bank_state,(void *)0x0213e264,sizeof(reveal->bank_state));copy(reveal->bg,(void *)0x04000008,sizeof(reveal->bg));copy(reveal->palette,(void *)0x05000000,512);copy(reveal->blend,(void *)0x04000050,sizeof(reveal->blend));
 void *grid=load("/Getpack/bg_ue.LZ5bg");u8 *gb=block(grid,0x42474454);u16 *gp=(u16 *)(block(grid,0x50414c54)+12);
 ((void(*)(void))0x02052f50)();W(0x04000000)&=~0x1f00u;H(0x05000000)=gp[13];
 reveal->bank_f=(u8 *)0x02250000;CALL1(0x020842c8,0x20);fastcopy(reveal->bank_f,(void *)0x06890000,0x4000);
 CALL1(0x02083d54,0x20);
 copyv(0x06000000,gb+28+W((u32)gb+12),W((u32)gb+24));copyv(0x06001000,gb+28,W((u32)gb+12));copyv(0x05000000,gp,512);release(grid);H(0x0400000a)=0x0283;
 /* Extended BG palettes off before VRAM E is borrowed, or the grid reads an unmapped bank. */
 W(0x04000000)=(W(0x04000000)&~0xc0001f07u)|0x10200u;
 CALL1(0x020842c8,0x13);snapshot();
 CALL1(0x02083ea4,0);CALL1(0x02083f5c,0);CALL1(0x02083ff8,0);CALL1(0x02084064,3);CALL1(0x02084160,0x10);
 model_heap_begin();((void(*)(u32))0x01ffa3fc)(8);
 ((void(*)(u32,u32,u32,u32,u32))0x02000cf1)(3,0x10,0x18000,0,0x3000);
 CALL0(0x02024778);CALL2(0x02024850,3,8);
 reveal->env=((u32(*)(void *))0x02024861)(data+header[2]);CALL1(0x02024a0c,reveal->env);
 reveal->scene=((u32(*)(void *))0x02024861)(data+header[3]);CALL1(0x02024a0c,reveal->scene);
 const char *back="/card128/0000.5tx";for(u32 i=1;i<=6;i++)CALL2(0x02025268,i,back);
 for(u32 i=0;i<5;i++){u32 id=W(UI+0x14+i*4);char *p=reveal->paths[i];copy(p,back,18);for(u32 j=0;j<4;j++){p[12-j]='0'+id%10;id/=10;}CALL2(0x02025268,i+2,p);}
 u32 obj=((u32(*)(u32,u32,u32))0x02024b49)(reveal->scene,3,0);reveal->motion=obj;reveal->stop_pc=(u32)data+0x02164fc0-0x02164850;((void(*)(u32,u32,u32))0x02025251)(obj,2,1);
 u32 pack_index=((u32(*)(u32,u32))0x02155d60)(CTX,H(CTX+0xcc12)+H(CTX+0xcc16));u32 pack=H(0x02158d40+pack_index*0x34);
 u32 rarity=w11pk_rarity(W(UI+0x24),pack);reveal->rarity=rarity==4?1:rarity==3?2:rarity==2?3:0;setvar(2,reveal->rarity);
 if(!reveal->rarity){u32 effect=((u32(*)(u32,u32,u32))0x02024b49)(reveal->scene,3,1);W(effect)=(u32)data+0x02164c7c-0x02164850;}
 H(CTX+0xcc18)=reveal->rarity==1?415:475;W(CTX+0xcd2c)=1;reveal->active=1;W(0x04000000)=(W(0x04000000)&~0x1f07u)|0x10208u;H(0x04000008)=0;
 if(w11_audio_debug_start)w11_audio_debug_start();
 sound(W11_PACK_FLIP);
}
void w11open_camera_display(u32 base,u32 reg,u32 layers)
{
 u32 display=base|layers;
 if(reveal&&reveal->tick<2)display&=~0x100u;
 W(reg)=display;
}
u32 w11open_camera_visibility(u32 camera)
{
 if(reveal&&reveal->tick<2){W(0x04000000)&=~0x100u;return 1;}
 return ((u32(*)(u32))0x020266b9)(camera);
}
void w11open_tick(u32 ui)
{
 (void)ui;if(!reveal||!reveal->active)return;
 if(reveal->tick==1){((void(*)(void))0x02052f50)();}
 reveal->tick++;
 if(reveal->retry_id&&reveal->tick>=reveal->retry_at){u32 id=reveal->retry_id;reveal->retry_id=0;sound(id);}
 u32 tick=reveal->tick;
 if(tick==64)sound(W11_PACK_FLIP1);
 if(tick==115)sound(W11_PACK_FLIP2);
 if(tick==167)sound(W11_PACK_FLIP3);
 if(tick==219)sound(W11_PACK_FLIP4);
 if(reveal->tick==271)sound(reveal->rarity==3?W11_PACK_ULTRA:reveal->rarity==2?W11_PACK_SUPER:reveal->rarity==1?W11_PACK_RARE:W11_PACK_FLIP);
 CALL1(0x02024b88,0x0211a79c);((void(*)(void))0x01ffd780)();CALL1(0x02024d0c,0x0211a79c);((void(*)(void))0x01ffe5e8)();W(0x04000540)=1;
 if(reveal->tick==1)setvar(0,getvar(0)|2);
 if(reveal->tick==2)W(0x04000000)|=0x100;
 u32 remaining=H(CTX+0xcc18);
 if(remaining&&W(reveal->motion)==reveal->stop_pc)H(CTX+0xcc18)=remaining>45?45:1;
 if(w11_audio_debug_tick)w11_audio_debug_tick(reveal->tick);
}

