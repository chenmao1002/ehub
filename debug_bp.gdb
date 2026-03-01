set pagination off
target remote localhost:3333

# 用硬件断点，不影响 Flash
hbreak CDC_Receive_FS
hbreak Bridge_SendToCDC

printf "Breakpoints set, continuing MCU...\n"
continue
