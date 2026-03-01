set pagination off
set charset CP1252
target remote localhost:3333

# 连接成功后 MCU 会被 halt，此处设断点不影响 USB
hbreak Bridge_SendToCDC
commands 1
  printf ">>> BRIDGE_SENDTOCDC CALLED! ch=0x%x len=%d\n", $r0, $r2
  printf "    dev_state=%d\n", hUsbDeviceFS.dev_state
  continue
end

hbreak CDC_Transmit_FS
commands 2
  printf ">>> CDC_Transmit_FS CALLED! len=%d busy=%d dev=%d\n", $r1, cdc_tx_busy, hUsbDeviceFS.dev_state
  continue
end

printf "BPs set. Resuming MCU...\n"
continue
