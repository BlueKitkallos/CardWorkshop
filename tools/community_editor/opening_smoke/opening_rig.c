#include "w11packsfx.h"
typedef unsigned int u32;
typedef unsigned short u16;
#define W(a) (*(volatile u32 *)(a))
#define H(a) (*(volatile u16 *)(a))
#define CTX 0x02159f48u
#define STORE 0x02158d10u
extern void body_init(void), scene_change(u32,u32,u32),pad_read(void);
extern int pack_card_list(u32,u32*,u32);
extern int shop_filter(u32,u32,u32*,u32);
extern void shop_draw(u32,volatile u16*,u32);
volatile u32 opening_skip;
/* Frame-analysis runner holds immediately before the single opening action. */
volatile u32 opening_hold;
volatile u32 opening_input;
volatile u32 opening_kind=3;
struct {u32 magic,state,frame;u16 cards[6];u32 flags[4];u32 soundmask;u32 first_sound[4];u32 regs[16];u16 map[1024];} opening_rig={0x4f50454e};
int shop_rig_start(void){if(opening_rig.state)return 0;opening_rig.state=1;W(0x021264a4)=(W(0x021264a4)&~0x700u)|0x100;body_init();scene_change(7,10,0x0214d6f4);return 0;}
void shop_rig_frame(void){
 pad_read();
 if(opening_rig.state==4){
  for(u32 k=0;k<0x1c;k++){
   u32 id=W(0x021278a0+k*0x6c+0x28)&0xffff;
   u32 flip=id==W11_PACK_FLIP||id==W11_PACK_FLIP1||id==W11_PACK_FLIP2||id==W11_PACK_FLIP3||id==W11_PACK_FLIP4;
   u32 bit=flip?1:id==W11_PACK_RARE?2:id==W11_PACK_SUPER?4:id==W11_PACK_ULTRA?8:0;
   if(bit && !(opening_rig.soundmask&bit)){
    opening_rig.first_sound[bit==1?0:bit==2?1:bit==4?2:3]=H(CTX+0xcc18);
    opening_rig.soundmask|=bit;
   }
  }
 }
 if(opening_rig.state==1 && W(STORE+0x10d8)&&H(STORE+0x10a4)){opening_rig.state=2;opening_rig.frame=W(0x020b7cc4);}
 if(opening_rig.state==2 && W(0x020b7cc4)-opening_rig.frame>90){
  u32 i;for(i=0;i<H(STORE+0x10a4);i++)if(H(STORE+0x30+i*0x34)==1)break;
  W(STORE+0x40+i*0x34)|=1;
  H(CTX+0xcc10)=1;pack_card_list(1,(u32*)(CTX+0x88bc),0x10d2);shop_draw(CTX,opening_rig.cards,0);
  static u32 pool[4306];for(u32 k=0;k<4;k++){shop_filter(CTX,i,pool,1u<<k);opening_rig.cards[k]=pool[0];}
  opening_rig.cards[4]=opening_rig.cards[opening_kind&3];for(u32 k=1;k<4;k++)opening_rig.cards[k]=opening_rig.cards[0];
  W(CTX+4)=(u32)opening_rig.cards;W(CTX+8)=(u32)&opening_rig.flags[0];W(CTX+12)=(u32)&opening_rig.flags[2];
  W(0x02159dd0)=4;
  ((void(*)(u32,int))0x02151df4)(0x02159e44,0);
  ((int(*)(u32))0x02153018)(CTX);
  opening_rig.state=3;opening_rig.frame=W(0x020b7cc4);
 }
 if(opening_rig.state==3 && !opening_hold && W(0x020b7cc4)-opening_rig.frame>90){
  if(opening_input){
   /* One A edge through the native purchased-pack input handler. */
   W(0x020b87e0)|=1;
   ((u32(*)(u32,u32,u32,u32))0x02153ec8)(CTX,0,0,0);
  }else{
   ((void(*)(u32,u32))0x02157c4c)(CTX,0);
   ((void(*)(u32))0x02157e04)(CTX);
  }
  opening_rig.state=4;opening_rig.frame=W(0x020b7cc4);
 }
 if(opening_rig.state==4 && opening_skip==1 && W(0x020b7cc4)-opening_rig.frame>15){W(0x020b87e0)|=2;opening_skip=2;}
 if(opening_rig.state==4 && W(0x020b7cc4)-opening_rig.frame==40){u32 i;for(i=0;i<16;i++)opening_rig.regs[i]=W(0x04000000+i*4);for(i=0;i<1024;i++)opening_rig.map[i]=H(0x06002800+i*2);}
}

