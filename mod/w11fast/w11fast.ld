SECTIONS
{
    . = CODE_BASE;
    .text : { *(.text*) *(.rodata*) }
    .data : { *(.data*) *(.bss*) *(COMMON) }
    /DISCARD/ : { *(.ARM.*) *(.comment) }
}
