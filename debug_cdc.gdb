target remote localhost:3333

# 设置断点
break CDC_Receive_FS
break Bridge_SendToCDC

# 显示状态
printf "=== CDC debug ready ===\n"
printf "bridge_cmd_queue = %p\n", bridge_cmd_queue
printf "Breakpoints set. Send data from PC now.\n"
printf "Type 'continue' to run.\n"
