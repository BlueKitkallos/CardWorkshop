 .include "w11npc_gen.asm"
.open "arm9.bin", 0x02000000
.thumb
.org 0x02018104
    .word W11NPC_STORY_COUNT
.org 0x02019ca6
    bl w11npc_story_hook
.org 0x0201a42a
    bl w11npc_deck_hook
.org 0x020181a2
    bl w11npc_deckname_hook
.org 0x0201810a
    bl w11npc_lim_file
.org 0x02018516
    bl w11npc_lim_name
.org 0x020189be
    bl w11npc_lim_load
.org 0x020189f2
    bl w11npc_lim_word
.org 0x02019ad8
    bl w11npc_charname_hook
.close
.include "free_duel.asm"
