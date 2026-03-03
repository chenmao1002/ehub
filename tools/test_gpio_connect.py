#!/usr/bin/env python3
"""
GPIO Connectivity Test — definitive test for PA2↔GPIO3 physical connection.

Sequence:
  1. MCU deinits USART2, sets PA2 = LOW  (GPIO output)
  2. Query ESP32 GPIO3 state → expect LOW if connected
  3. MCU sets PA2 = HIGH
  4. Query ESP32 GPIO3 state → expect HIGH if connected
  5. MCU restores USART2

Usage:
    python test_gpio_connect.py [--port COM19] [--esp-ip 192.168.227.100]
"""

import serial
import struct
import socket
import time
import argparse


def crc8_xor(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c


def build_bridge_frame(sof0: int, ch: int, data: bytes) -> bytes:
    length = len(data)
    hdr = bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF])
    payload = hdr + data
    crc = crc8_xor(payload[2:])
    return payload + bytes([crc])


def parse_bridge_frames(raw: bytes):
    i = 0
    while i < len(raw) - 5:
        if raw[i] in (0xAA, 0xBB) and raw[i+1] == 0x55:
            sof0 = raw[i]
            ch = raw[i+2]
            length = (raw[i+3] << 8) | raw[i+4]
            if length == 0 or i + 5 + length + 1 > len(raw):
                i += 1
                continue
            data = raw[i+5 : i+5+length]
            crc = raw[i+5+length]
            expected = crc8_xor(raw[i+2 : i+5+length])
            if crc == expected:
                yield (sof0, ch, data)
                i += 5 + length + 1
                continue
        i += 1


def send_f2_cmd(ser: serial.Serial, action: int) -> bytes:
    """Send 0xF2 GPIO test command. action: 0=PA2 LOW, 1=PA2 HIGH, 2=restore USART2"""
    frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF2, action]))
    ser.reset_input_buffer()
    ser.write(frame)
    time.sleep(0.3)
    raw = ser.read(ser.in_waiting or 256)
    for sof0, ch, data in parse_bridge_frames(raw):
        if ch == 0xE0 and len(data) >= 2 and data[0] == 0xF2:
            return data
    return None


def read_esp32_gpio(ip: str, port: int = 5000) -> dict:
    """Query ESP32 GPIO states via 0xF0 subcmd."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((ip, port))
        frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF0]))
        s.sendall(frame)
        time.sleep(0.5)
        raw = s.recv(4096)
        s.close()

        for sof0, ch, data in parse_bridge_frames(raw):
            if ch == 0xE0 and len(data) >= 1 and data[0] == 0xF0:
                # GPIO states are at fixed offset: pos=1+28+2+8+2+16 = 57
                pos = 57
                result = {}
                if pos + 2 <= len(data):
                    result['GPIO1'] = data[pos]
                    result['GPIO3'] = data[pos+1]
                return result
        return None
    except Exception as e:
        print(f"  ESP32 error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM19', help='MCU CDC serial port')
    parser.add_argument('--esp-ip', default='192.168.227.100', help='ESP32 IP')
    args = parser.parse_args()

    ser = serial.Serial(args.port, 115200, timeout=1)
    time.sleep(0.5)

    print("=" * 60)
    print("GPIO Connectivity Test: MCU PA2 ↔ ESP32 GPIO3")
    print("=" * 60)

    # Step 0: Baseline GPIO3 state
    print("\n[0] Baseline: Reading ESP32 GPIO3...")
    g0 = read_esp32_gpio(args.esp_ip)
    if g0:
        print(f"    GPIO1={g0.get('GPIO1','?')}  GPIO3={g0.get('GPIO3','?')}")
    else:
        print("    *** Failed to read ESP32 GPIO")

    # Step 1: Set PA2 = LOW
    print("\n[1] Setting MCU PA2 = LOW (deinit USART2)...")
    r1 = send_f2_cmd(ser, 0)
    if r1:
        pa3_read = r1[2] if len(r1) >= 3 else '?'
        print(f"    MCU response: OK  (PA3 read = {pa3_read})")
    else:
        print("    *** No response from MCU!")
        ser.close()
        return

    time.sleep(0.3)

    # Step 2: Read ESP32 GPIO3 (should be LOW if connected)
    print("\n[2] Reading ESP32 GPIO3 (expect LOW if connected)...")
    g1 = read_esp32_gpio(args.esp_ip)
    if g1:
        gpio3_low = g1.get('GPIO3', None)
        print(f"    GPIO1={g1.get('GPIO1','?')}  GPIO3={gpio3_low}")
    else:
        print("    *** Failed")
        gpio3_low = None

    # Step 3: Set PA2 = HIGH
    print("\n[3] Setting MCU PA2 = HIGH...")
    r2 = send_f2_cmd(ser, 1)
    if r2:
        pa3_read = r2[2] if len(r2) >= 3 else '?'
        print(f"    MCU response: OK  (PA3 read = {pa3_read})")
    else:
        print("    *** No response from MCU!")

    time.sleep(0.3)

    # Step 4: Read ESP32 GPIO3 (should be HIGH if connected)
    print("\n[4] Reading ESP32 GPIO3 (expect HIGH if connected)...")
    g2 = read_esp32_gpio(args.esp_ip)
    if g2:
        gpio3_high = g2.get('GPIO3', None)
        print(f"    GPIO1={g2.get('GPIO1','?')}  GPIO3={gpio3_high}")
    else:
        print("    *** Failed")
        gpio3_high = None

    # Step 5: Restore USART2
    print("\n[5] Restoring USART2...")
    r3 = send_f2_cmd(ser, 2)
    if r3:
        print("    USART2 restored OK")
    else:
        print("    *** Failed to restore!")

    # Analysis
    print("\n" + "=" * 60)
    print("RESULT:")
    if gpio3_low is not None and gpio3_high is not None:
        if gpio3_low == 0 and gpio3_high == 1:
            print("  ✓ PA2 → GPIO3: CONNECTED! GPIO3 follows PA2.")
            print("    The physical wire is OK. Problem is likely baud rate or config.")
        elif gpio3_low == 1 and gpio3_high == 1:
            print("  ✗ PA2 → GPIO3: NOT CONNECTED (or CH340 holding GPIO3 HIGH)")
            print("    GPIO3 stays HIGH regardless of PA2 state.")
            print("    → Check: is CH340 still plugged in? Try unplugging.")
            print("    → Or: PA2 is not wired to GPIO3 at all.")
        elif gpio3_low == 0 and gpio3_high == 0:
            print("  ✗ GPIO3 stuck LOW — possible short to ground")
        else:
            print(f"  ✗ Unexpected: LOW→GPIO3={gpio3_low}, HIGH→GPIO3={gpio3_high}")
    else:
        print("  Could not determine — ESP32 query failed")

    # Also check PA3 (MCU RX) vs GPIO1 (ESP32 TX)
    if r1 and len(r1) >= 3 and r2 and len(r2) >= 3:
        pa3_when_pa2_low = r1[2]
        pa3_when_pa2_high = r2[2]
        print(f"\n  MCU PA3 (RX) state: when PA2=LOW→{pa3_when_pa2_low}, when PA2=HIGH→{pa3_when_pa2_high}")
        if pa3_when_pa2_low == 1 and pa3_when_pa2_high == 1:
            print("  PA3 stays HIGH — ESP32 GPIO1 (TX) is in idle state (or connected but idle)")

    print("=" * 60)
    ser.close()


if __name__ == '__main__':
    main()
