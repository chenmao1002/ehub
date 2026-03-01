set pagination off
set charset CP1252
target remote localhost:3333

# 断点1: Bridge_SendToCDC — 确认回复路径
hbreak Bridge_SendToCDC
commands 1
  printf "HIT Bridge_SendToCDC: ch=%d len=%d\n", $r0, $r2
  continue
end

# 断点2: osMessageQueuePut 的返回点 (CDC_Receive_FS 末尾)  
hbreak usb_app.c:227
commands 2
  printf "HIT queue put done, s_state=%d\n", s_state
  continue
end

printf "Breakpoints set, running...\n"
continue
