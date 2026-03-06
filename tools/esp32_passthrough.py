#!/usr/bin/env python3
"""
Enter ESP32 CDC↔USART2 passthrough mode.

Send a bridge command to the MCU, which will:
  1. Put ESP32 into bootloader (BOOT/EN sequence)
  2. Reinit USART2 at 115200
  3. Enter transparent CDC↔USART2 passthrough

After this, COM19 behaves as a direct USB-UART bridge to ESP32.
esptool/PlatformIO can flash ESP32 through COM19 — no CH340 needed.

Usage:
    python esp32_passthrough.py --port COM19

Then flash ESP32:
    cd ESP32_wifi && pio run -t upload --upload-port COM19
  or:
    esptool.py --port COM19 --baud 460800 write_flash 0x0 firmware.bin

Reset MCU (power cycle or OpenOCD reflash) to restore normal bridge mode.
"""
import serial
import sys
import argparse
import time


def build_frame(sof0, ch, data):
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data:
        crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])


def main():
    parser = argparse.ArgumentParser(
        description='Enter ESP32 CDC↔USART2 passthrough mode')
    parser.add_argument('--port', default='COM19',
                        help='MCU CDC port (default: COM19)')
    args = parser.parse_args()

    print(f"[*] Opening {args.port}...")
    ser = serial.Serial(args.port, 115200, timeout=2)
    time.sleep(0.1)

    # Send WIFI_SUBCMD_ESP_PASSTHROUGH (0x06) on channel 0xE0
    frame = build_frame(0xAA, 0xE0, bytes([0x06]))
    print(f"[*] Sending passthrough command...")
    ser.write(frame)
    time.sleep(1.0)  # wait for MCU to enter bootloader + passthrough

    # Read confirmation
    resp = ser.read(256)
    if resp:
        # Parse bridge frame reply
        if len(resp) >= 7 and resp[0] == 0xBB and resp[2] == 0xE0:
            plen = (resp[3] << 8) | resp[4]
            payload = resp[5:5 + plen]
            if len(payload) >= 2 and payload[0] == 0x06 and payload[1] == 0x00:
                print(f"[OK] Passthrough mode active!")
                print(f"     {args.port} is now a transparent USB-UART bridge to ESP32.")
                print(f"")
                print(f"     Flash ESP32:")
                print(f"       cd ESP32_wifi && pio run -t upload --upload-port {args.port}")
                print(f"     or:")
                print(f"       esptool.py --port {args.port} --baud 460800 \\")
                print(f"         write_flash 0x0 firmware.bin")
                print(f"")
                print(f"     Reset MCU to restore normal bridge mode.")
                ser.close()
                return 0

    print(f"[FAIL] No valid confirmation received.")
    print(f"       Raw response: {resp.hex() if resp else '(empty)'}")
    ser.close()
    return 1


if __name__ == '__main__':
    sys.exit(main())
