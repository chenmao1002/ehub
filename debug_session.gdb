# GDB 自动化调试脚本 — 检查 CDC→USART1 通路
set pagination off
set confirm off

# 连接 OpenOCD GDB server
target extended-remote :3333

# 加载调试符号
file C:/Users/MC/Desktop/VSProject/EHUB4_3/EHUB/build/Debug/EHUB.elf

# 暂停目标
monitor halt

echo \n======== 1. 检查 FreeRTOS 内核是否已启动 ========\n
print xSchedulerRunning
print uxTopReadyPriority

echo \n======== 2. 检查 bridge_cmd_queue / bridge_rx_queue 是否非空 ========\n
print bridge_cmd_queue
print bridge_rx_queue

echo \n======== 3. USART1 DMA 状态 ========\n
print huart1.State
print huart1.gState
print huart1.ErrorCode
print huart1.hdmatx->State
print huart1.hdmarx->State

echo \n======== 4. DMA2 Stream7 (USART1_TX) 寄存器 ========\n
# DMA2_Stream7 base = 0x40026BE0
x/8xw 0x40026BE0

echo \n======== 5. USART1 SR 寄存器 ========\n
# USART1 base = 0x40011000
x/4xw 0x40011000

echo \n======== 6. 当前所有任务栈 ========\n
info threads

echo \n======== 7. 在 Bridge_Dispatch 设断点，发送一帧后检查 ========\n
# 在 USART1 发送处设断点
break usb_app.c:Bridge_Dispatch
echo 断点已设置，输入 continue 让目标继续运行\n
echo 然后通过 COM19 发送一帧，断点触发后检查 m->ch 和 m->len\n

# 让目标继续运行
continue
