SECTIONS
{
    . = CODE_BASE;
    .text : { *(.vmhead) *(.text*) *(.rodata*) }
    .data : { *(.data*) *(.bss*) *(COMMON) }
    /DISCARD/ : { *(.ARM.*) *(.comment) }
}
