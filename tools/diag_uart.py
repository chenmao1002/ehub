#!/usr/bin/env python3
"""
UART Bridge Diagnostic — reads MCU-side USART2 debug counters via CDC (COM19).

Sends bridge-protocol command:  CH=0xE0, subcmd=0xF1  → MCU returns USART2 stats.
Also sends a DAP INFO cmd via WiFi (port 6000) to generate UART traffic,
then re-reads counters.

Usage:
    python diag_uart.py [--port COM19] [--esp-ip 192.168.4.1]
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
    crc = crc8_xor(payload[2:])  # CRC over ch + len_h + len_l + data
    return payload + bytes([crc])


def parse_bridge_frames(raw: bytes):
    """Yield (sof0, ch, data) from raw bytes."""
    i = 0
    while i < len(raw) - 5:
        if raw[i] in (0xAA, 0xBB) and raw[i+1] == 0x55:
            sof0 = raw[i]
            ch   = raw[i+2]
            length = (raw[i+3] << 8) | raw[i+4]
            if length == 0 or i + 5 + length + 1 > len(raw):
                i += 1
                continue
            data = raw[i+5 : i+5+length]
            crc  = raw[i+5+length]
            expected = crc8_xor(raw[i+2 : i+5+length])
            if crc == expected:
                yield (sof0, ch, data)
                i += 5 + length + 1
                continue
        i += 1


def read_mcu_counters(ser: serial.Serial) -> dict:
    """Send 0xF1 subcmd on BRIDGE_CH_WIFI_CTRL and parse response."""
    # Build: AA 55 E0 00 01 F1 CRC
    frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF1]))
    ser.reset_input_buffer()
    ser.write(frame)
    time.sleep(0.3)

    raw = ser.read(ser.in_waiting or 256)
    for sof0, ch, data in parse_bridge_frames(raw):
        if ch == 0xE0 and len(data) >= 25 and data[0] == 0xF1:
            # Support both 6-field (25 bytes) and 10-field (41 bytes) responses
            if len(data) >= 41:
                vals = struct.unpack_from('<10I', data, 1)
                return {
                    'TX_OK':       vals[0],
                    'TX_FAIL':     vals[1],
                    'RX_EVENT':    vals[2],
                    'RX_BYTES':    vals[3],
                    'ERROR':       vals[4],
                    'FRAMES':      vals[5],
                    'DMA_INIT_RC': vals[6],
                    'USART2_SR':   vals[7],
                    'DMA_CR':      vals[8],
                    'DMA_NDTR':    vals[9],
                }
            else:
                vals = struct.unpack_from('<6I', data, 1)
                return {
                    'TX_OK':     vals[0],
                    'TX_FAIL':   vals[1],
                    'RX_EVENT':  vals[2],
                    'RX_BYTES':  vals[3],
                    'ERROR':     vals[4],
                    'FRAMES':    vals[5],
                }
    return None


def trigger_wifi_dap(ip: str, port: int = 6000):
    """Send a DAP_INFO command via OpenOCD TCP to generate UART traffic."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((ip, port))

        # OpenOCD header: 4-byte proto (0x00000001) + 4-byte length
        dap_cmd = bytes([0x00, 0xFE])  # DAP_Info: Get Vendor Name
        header = struct.pack('>II', 1, len(dap_cmd))
        s.sendall(header + dap_cmd)
        time.sleep(1)
        try:
            resp = s.recv(1024)
            print(f"  WiFi DAP response: {resp.hex()}")
        except socket.timeout:
            print("  WiFi DAP response: TIMEOUT")
        s.close()
        return True
    except Exception as e:
        print(f"  WiFi DAP connect failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM19', help='MCU CDC serial port')
    parser.add_argument('--esp-ip', default='192.168.4.1', help='ESP32 IP')
    args = parser.parse_args()

    ser = serial.Serial(args.port, 115200, timeout=1)
    time.sleep(0.5)

    print("=" * 60)
    print("EHUB UART Bridge Diagnostic")
    print("=" * 60)

    # Step 1: Read initial MCU counters
    print("\n[1] Reading MCU USART2 counters (initial)...")
    c1 = read_mcu_counters(ser)
    if c1 is None:
        print("  *** FAILED to read MCU counters! MCU may not have 0xF1 handler.")
        ser.close()
        return
    for k, v in c1.items():
        print(f"  {k:12s} = {v}")

    # Step 2: Wait a few seconds for battery frames to accumulate TX stats
    print("\n[2] Waiting 3s for battery frame TX activity...")
    time.sleep(3)

    c2 = read_mcu_counters(ser)
    if c2:
        print("  After 3s:")
        for k, v in c2.items():
            delta = v - c1.get(k, 0)
            print(f"  {k:12s} = {v}  (delta: +{delta})")
    else:
        print("  *** FAILED to read counters")

    # Step 3: Send DAP command via WiFi to test ESP32→MCU direction
    print(f"\n[3] Sending DAP_Info via WiFi TCP ({args.esp_ip}:6000)...")
    trigger_wifi_dap(args.esp_ip)

    time.sleep(2)

    c3 = read_mcu_counters(ser)
    if c3:
        print("  After WiFi DAP:")
        for k, v in c3.items():
            delta = v - c2.get(k, 0)
            print(f"  {k:12s} = {v}  (delta: +{delta})")
    else:
        print("  *** FAILED to read counters")

    # Step 4: Analysis
    print("\n" + "=" * 60)
    print("ANALYSIS:")
    if c3:
        if c3['TX_OK'] > 0 and c3['TX_FAIL'] == 0:
            print("  [OK] MCU USART2 DMA TX is working (battery frames sent)")
        elif c3['TX_FAIL'] > 0:
            print("  [!!] MCU USART2 DMA TX FAILING — HAL_UART_Transmit_DMA returns error")
        else:
            print("  [??] Zero TX — WiFi_Bridge_Send might not be called at all")

        if c3['RX_BYTES'] > 0:
            print(f"  [OK] MCU received {c3['RX_BYTES']} bytes from ESP32")
        else:
            print("  [!!] MCU received ZERO bytes from ESP32 — UART RX dead!")

        if c3['ERROR'] > 0:
            print(f"  [!!] USART2 errors: {c3['ERROR']} — may indicate baud mismatch or noise")
        else:
            print("  [OK] No USART2 errors")

        if c3['RX_EVENT'] > 0:
            print(f"  [OK] {c3['RX_EVENT']} DMA RxEvent callbacks fired")
        else:
            print("  [!!] Zero RxEvent callbacks — DMA receive not armed or not triggered")

        if c3['FRAMES'] > 0:
            print(f"  [OK] {c3['FRAMES']} complete bridge frames parsed from ESP32")
        else:
            print("  [!!] Zero frames parsed — either no data or framing issue")

        # Extended diagnostics
        if 'DMA_INIT_RC' in c3:
            rc = c3['DMA_INIT_RC']
            rc_str = {0: 'HAL_OK', 1: 'HAL_ERROR', 2: 'HAL_BUSY', 3: 'HAL_TIMEOUT'}.get(rc, f'UNKNOWN({rc})')
            print(f"\n  DMA Init Return: {rc_str}")

            sr = c3.get('USART2_SR', 0)
            print(f"  USART2_SR: 0x{sr:08X}", end='  ')
            flags = []
            if sr & (1<<5): flags.append('RXNE')
            if sr & (1<<4): flags.append('IDLE')
            if sr & (1<<3): flags.append('ORE')
            if sr & (1<<2): flags.append('NF')
            if sr & (1<<1): flags.append('FE')
            if sr & (1<<0): flags.append('PE')
            if sr & (1<<6): flags.append('TC')
            if sr & (1<<7): flags.append('TXE')
            print(f"  [{', '.join(flags) if flags else 'clean'}]")

            cr = c3.get('DMA_CR', 0)
            en = 'ENABLED' if (cr & 1) else 'DISABLED'
            print(f"  DMA_CR: 0x{cr:08X}  [Stream {en}]")

            ndtr = c3.get('DMA_NDTR', 0)
            print(f"  DMA_NDTR: {ndtr}  (bytes remaining)")
            
            if not (cr & 1):
                print("  [!!] DMA Stream DISABLED — receive won't work!")
    print("=" * 60)
    ser.close()


if __name__ == '__main__':
    main()
