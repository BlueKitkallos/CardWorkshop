OUTPUT_ARCH(arm)
ENTRY(CODE_BASE)
INCLUDE engine.ld
INCLUDE bss_mem.ld
INCLUDE spans_mem.ld
SECTIONS
{
  INCLUDE menu.ld
  INCLUDE spans.ld
  INCLUDE banks.ld
  . = CODE_BASE;
  .text : { KEEP(*(.text.keep*)) *(.text*) *(.rodata*) *(.glue_7*) *(.vfp11_veneer) *(.v4_bx) }
  .data : { *(.data*) }
  . = ALIGN(4);
  INCLUDE bss.ld
  .fxfile 0x08000000 : { KEEP(*(.fxfile)) }
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
}
