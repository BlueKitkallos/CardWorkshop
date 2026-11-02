/* Palette entry 0 is also the screen backdrop; the stock logos keep magenta there. */
typedef unsigned int u32;
typedef unsigned short u16;
void w11boot_logo_transfer(u32 *request)
{
 u16 *palette=((u16 *(*)(u32))0x0201b5d1)(request[0]);
 palette[0]=0;
 ((void(*)(u32 *))0x0201c03d)(request);
}
