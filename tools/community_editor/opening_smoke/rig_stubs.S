    .syntax unified
    .global scene_change
    .thumb_set scene_change, 0x02016cf5
    .global pad_read
    .thumb_set pad_read, 0x02014efd
    .global shop_draw
    .type shop_draw, %function
    .set shop_draw, 0x02155a68

    .global shop_filter
    .type shop_filter, %function
    .set shop_filter, 0x02155934
