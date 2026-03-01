set pagination off
set charset CP1252
target remote localhost:3333

hbreak Bridge_SendToCDC
commands 1
  printf ">>> Bridge_SendToCDC called! ch=0x%x len=%d\n", $r0, $r2
  printf "    dev_state=%d cdc_tx_busy=cdc_tx_busy\n", hUsbDeviceFS.dev_state
  continue
end

printf "BP set at Bridge_SendToCDC, continuing MCU...\n"
continue
