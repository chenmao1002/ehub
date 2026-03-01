set pagination off
target remote localhost:3333

hbreak Bridge_SendToCDC
commands 1
  output $r0
  output $r2
  printf "BRIDGE_SEND ch=%d len=%d dev=%d\n", $r0, $r2, hUsbDeviceFS.dev_state
  continue
end

hbreak CDC_Transmit_FS
commands 2
  printf "CDC_TX_FS len=%d busy=%d dev=%d\n", $r1, cdc_tx_busy, hUsbDeviceFS.dev_state
  continue
end

printf "BPs set. Running...\n"
continue
