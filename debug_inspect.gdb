set pagination off
set confirm off
target extended-remote :3333
file C:/Users/MC/Desktop/VSProject/EHUB4_3/EHUB/build/Debug/EHUB.elf
monitor halt
echo \n=== FreeRTOS scheduler ===\n
print xSchedulerRunning
echo \n=== bridge_cmd_queue / bridge_rx_queue ===\n
print bridge_cmd_queue
print bridge_rx_queue
echo \n=== huart1 state ===\n
print huart1.gState
print huart1.RxState
print huart1.ErrorCode
echo \n=== huart1 DMA tx/rx ===\n
print huart1.hdmatx
print huart1.hdmarx
echo \n=== USART1 SR (0x40011000) ===\n
x/1xw 0x40011000
echo \n=== DMA2_Stream7 CR (USART1 TX, 0x40026BE0+0) ===\n
x/4xw 0x40026BE0
echo \n=== DMA2_Stream2 CR (USART1 RX, 0x40026430+0) ===\n
x/4xw 0x40026430
echo \n=== usart1_rx_buf (first 16 bytes) ===\n
x/16xb Bridge_USART1_RxBuf()
echo \n=== bridge_cmd_queue internals ===\n
print *(StaticQueue_t*)bridge_cmd_queue
echo \n=== 所有任务 ===\n
info threads
monitor resume
quit
