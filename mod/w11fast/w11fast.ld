SECTIONS
{
    . = CODE_BASE;
    .think : { KEEP(*(.think)) }
    .text : { *(.text*) *(.rodata*) }
    .data : { *(.data*) *(.bss*) *(COMMON) }
    /DISCARD/ : { *(.ARM.*) *(.comment) }
}
