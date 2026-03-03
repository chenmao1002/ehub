#!/usr/bin/env python3
"""
Combined UART Bridge Diagnostic — reads both MCU and ESP32 debug counters.

Queries:
  - MCU  via CDC (COM19):  0xE0 subcmd 0xF1  → USART2 DMA counters + register snapshots
  - ESP32 via WiFi TCP:5000: 0xE0 subcmd 0xF0 → UART counters + GPIO states + baud rate

Usage:
    python diag_full.py [--port COM19] [--esp-ip 192.168.227.100]
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
    """Yield (sof0, ch, data) from raw bytes."""
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


def read_mcu_counters(ser: serial.Serial) -> dict:
    """Send 0xF1 subcmd to MCU via CDC and parse response."""
    frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF1]))
    ser.reset_input_buffer()
    ser.write(frame)
    time.sleep(0.3)
    raw = ser.read(ser.in_waiting or 256)
    for sof0, ch, data in parse_bridge_frames(raw):
        if ch == 0xE0 and len(data) >= 25 and data[0] == 0xF1:
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
                return dict(zip(['TX_OK','TX_FAIL','RX_EVENT','RX_BYTES','ERROR','FRAMES'], vals))
    return None


def read_esp32_counters(ip: str, port: int = 5000) -> dict:
    """Send 0xF0 subcmd to ESP32 via bridge TCP and parse response."""
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
                result = {}
                pos = 1
                if pos + 28 <= len(data):
                    vals = struct.unpack_from('<7I', data, pos)
                    result['dapTcpRead'] = vals[0]
                    result['dapUartTx'] = vals[1]
                    result['dapUartRx'] = vals[2]
                    result['dapTcpSend'] = vals[3]
                    result['dapTimeout'] = vals[4]
                    result['uartBytesRx'] = vals[5]
                    result['uartFramesRx'] = vals[6]
                    pos += 28

                if pos + 2 <= len(data):
                    result['lastDapCmdLen'] = struct.unpack_from('<H', data, pos)[0]
                    pos += 2
                if pos + 8 <= len(data):
                    result['lastDapCmd'] = data[pos:pos+8].hex()
                    pos += 8
                if pos + 2 <= len(data):
                    result['lastBridgeTxLen'] = struct.unpack_from('<H', data, pos)[0]
                    pos += 2
                if pos + 16 <= len(data):
                    result['lastBridgeTx'] = data[pos:pos+16].hex()
                    pos += 16

                # Extended GPIO diagnostics (new fields)
                if pos + 2 <= len(data):
                    result['GPIO1_state'] = data[pos]
                    result['GPIO3_state'] = data[pos+1]
                    pos += 2
                if pos + 4 <= len(data):
                    result['SerialAvailable'] = struct.unpack_from('<I', data, pos)[0]
                    pos += 4
                if pos + 4 <= len(data):
                    result['SerialBaudRate'] = struct.unpack_from('<I', data, pos)[0]
                    pos += 4

                return result
        return None
    except Exception as e:
        print(f"  ESP32 TCP connect failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM19', help='MCU CDC serial port')
    parser.add_argument('--esp-ip', default='192.168.227.100', help='ESP32 IP')
    args = parser.parse_args()

    ser = serial.Serial(args.port, 115200, timeout=1)
    time.sleep(0.5)

    print("=" * 60)
    print("EHUB Full UART Bridge Diagnostic")
    print("=" * 60)

    # ── MCU side ──
    print("\n[MCU] USART2 Counters:")
    mcu = read_mcu_counters(ser)
    if mcu:
        for k, v in mcu.items():
            if k in ('USART2_SR', 'DMA_CR'):
                print(f"  {k:14s} = 0x{v:08X}")
            else:
                print(f"  {k:14s} = {v}")

        sr = mcu.get('USART2_SR', 0)
        flags = []
        if sr & (1<<5): flags.append('RXNE')
        if sr & (1<<4): flags.append('IDLE')
        if sr & (1<<3): flags.append('ORE')
        if sr & (1<<2): flags.append('NF')
        if sr & (1<<1): flags.append('FE')
        if sr & (1<<0): flags.append('PE')
        if sr & (1<<6): flags.append('TC')
        if sr & (1<<7): flags.append('TXE')
        print(f"  SR flags: [{', '.join(flags) if flags else 'clean'}]")

        dma_en = 'ENABLED' if (mcu.get('DMA_CR', 0) & 1) else 'DISABLED'
        print(f"  DMA RX Stream: {dma_en}")
    else:
        print("  *** FAILED to read MCU counters")

    # ── ESP32 side ──
    print(f"\n[ESP32] Counters (via TCP {args.esp_ip}:5000):")
    esp = read_esp32_counters(args.esp_ip)
    if esp:
        for k, v in esp.items():
            if k in ('lastDapCmd', 'lastBridgeTx'):
                print(f"  {k:18s} = {v}")
            else:
                print(f"  {k:18s} = {v}")
    else:
        print("  *** FAILED to read ESP32 counters")

    # ── Analysis ──
    print("\n" + "=" * 60)
    print("ANALYSIS:")
    if mcu:
        if mcu['TX_OK'] > 0:
            print(f"  MCU → USART2: TX_OK={mcu['TX_OK']} (DMA TX works)")
        if mcu.get('DMA_NDTR', 0) == 1024:
            print("  MCU ← USART2: DMA NDTR=1024 (never received a single byte)")

    if esp:
        if 'GPIO1_state' in esp:
            g1, g3 = esp['GPIO1_state'], esp['GPIO3_state']
            print(f"  ESP32 GPIO1 (TX): {'HIGH' if g1 else 'LOW'}")
            print(f"  ESP32 GPIO3 (RX): {'HIGH' if g3 else 'LOW'}")
            if g3 == 0:
                print("  [!!] GPIO3 is LOW — MCU PA2 not driving it high (idle)")
                print("       → Possible: PA2 not connected to GPIO3!")
            elif g3 == 1:
                print("  [OK] GPIO3 is HIGH (idle UART state)")

        if 'SerialBaudRate' in esp:
            print(f"  ESP32 Serial baud: {esp['SerialBaudRate']}")

        if 'uartBytesRx' in esp:
            print(f"  ESP32 UART bytes RX: {esp['uartBytesRx']}")
            if esp['uartBytesRx'] == 0:
                print("  [!!] ESP32 received ZERO bytes from MCU USART2")

        if 'SerialAvailable' in esp:
            print(f"  ESP32 Serial.available(): {esp['SerialAvailable']}")

    print("=" * 60)
    ser.close()


if __name__ == '__main__':
    main()
