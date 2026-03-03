#!/usr/bin/env python3
"""
Diagnostic: USART2 register dump + polling TX test (0xF3)
Then query ESP32 counters (0xF0) to check if polling TX was received.

Usage:  python tools/diag_reg_tx.py --port COM19 [--esp-ip 192.168.227.100]
"""
import argparse, serial, struct, socket, time


def crc8_xor(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c


def build_bridge_frame(sof0: int, ch: int, data: bytes) -> bytes:
    length = len(data)
    hdr = bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF])
    payload = hdr + data
    crc = crc8_xor(payload[2:])   # CRC covers ch + len_h + len_l + data
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


def read_cdc_responses(ser, timeout=1.0):
    """Read all bridge frames from CDC within timeout."""
    results = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.1)
        n = ser.in_waiting
        if n > 0:
            raw = ser.read(n)
            for sof0, ch, data in parse_bridge_frames(raw):
                results.append((ch, data))
    return results


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
                # skip lastDapCmd/lastBridgeTx
                if pos + 2 <= len(data):
                    pos += 2  # lastDapCmdLen
                if pos + 8 <= len(data):
                    pos += 8  # lastDapCmd
                if pos + 2 <= len(data):
                    pos += 2  # lastBridgeTxLen
                if pos + 16 <= len(data):
                    pos += 16  # lastBridgeTx
                # Extended GPIO diagnostics
                if pos + 2 <= len(data):
                    result['GPIO1_state'] = data[pos]
                    result['GPIO3_state'] = data[pos+1]
                    pos += 2
                if pos + 4 <= len(data):
                    result['Serial_available'] = struct.unpack_from('<I', data, pos)[0]
                    pos += 4
                if pos + 4 <= len(data):
                    result['Serial_baudRate'] = struct.unpack_from('<I', data, pos)[0]
                    pos += 4
                return result
    except Exception as e:
        print(f"  ESP32 TCP error: {e}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='COM19')
    ap.add_argument('--esp-ip', default='192.168.227.100')
    args = ap.parse_args()

    ser = serial.Serial(args.port, 115200, timeout=2)
    time.sleep(0.5)
    ser.reset_input_buffer()

    # ----------------------------------------------------------------
    print("=== Step 1: ESP32 counters BEFORE test ===")
    esp_before = read_esp32_counters(args.esp_ip)
    if esp_before:
        for k, v in esp_before.items():
            print(f"    {k:20s} = {v}")
    else:
        print("  (no ESP32 response)")

    # ----------------------------------------------------------------
    print("\n=== Step 2: USART2 register dump + polling TX (0xF3) ===")
    ser.reset_input_buffer()
    frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF3]))
    ser.write(frame)
    responses = read_cdc_responses(ser, timeout=2.0)

    reg_data = None
    for ch, data in responses:
        if ch == 0xE0 and len(data) >= 1 and data[0] == 0xF3:
            reg_data = data
            print(f"  MCU register response ({len(data)} bytes): {data.hex()}")
        else:
            print(f"  Other CDC frame: ch=0x{ch:02X} len={len(data)} data={data[:16].hex()}")

    if reg_data and len(reg_data) >= 29:
        off = 1
        cr1  = struct.unpack_from('<I', reg_data, off)[0]; off += 4
        cr3  = struct.unpack_from('<I', reg_data, off)[0]; off += 4
        brr  = struct.unpack_from('<I', reg_data, off)[0]; off += 4
        sr   = struct.unpack_from('<I', reg_data, off)[0]; off += 4
        tx_dma_cr   = struct.unpack_from('<I', reg_data, off)[0]; off += 4
        tx_dma_ndtr = struct.unpack_from('<I', reg_data, off)[0]; off += 4
        poll_tx_rc  = struct.unpack_from('<I', reg_data, off)[0]; off += 4

        print(f"\n  USART2->CR1  = 0x{cr1:08X}")
        print(f"    UE  (bit13) = {(cr1>>13)&1}  (USART Enable)")
        print(f"    TE  (bit 3) = {(cr1>>3)&1}  (Transmitter Enable)")
        print(f"    RE  (bit 2) = {(cr1>>2)&1}  (Receiver Enable)")
        print(f"    IDLEIE(bit4)= {(cr1>>4)&1}  (IDLE interrupt)")
        print(f"    TCIE (bit6) = {(cr1>>6)&1}  (TC interrupt)")
        print(f"    OVER8(bit15)= {(cr1>>15)&1}  (Oversampling)")

        print(f"\n  USART2->CR3  = 0x{cr3:08X}")
        print(f"    DMAT (bit 7)= {(cr3>>7)&1}  (DMA Transmit enable)")
        print(f"    DMAR (bit 6)= {(cr3>>6)&1}  (DMA Receive enable)")

        print(f"\n  USART2->BRR  = 0x{brr:04X}")
        over8 = (cr1 >> 15) & 1
        if over8:
            mantissa = (brr >> 4)
            fraction = brr & 0x07
            usartdiv = mantissa + fraction / 8.0
        else:
            mantissa = (brr >> 4)
            fraction = brr & 0x0F
            usartdiv = mantissa + fraction / 16.0
        if usartdiv > 0:
            actual_baud = 30_000_000 / usartdiv
            print(f"    USARTDIV   = {usartdiv:.4f}")
            print(f"    Actual baud= {actual_baud:.0f} (PCLK1=30MHz)")
        else:
            print(f"    WARNING: USARTDIV=0!")

        print(f"\n  USART2->SR   = 0x{sr:04X}")
        print(f"    TXE (bit7)  = {(sr>>7)&1}  (TX empty)")
        print(f"    TC  (bit6)  = {(sr>>6)&1}  (TX complete)")
        print(f"    RXNE(bit5)  = {(sr>>5)&1}  (RX not empty)")
        print(f"    ORE (bit3)  = {(sr>>3)&1}  (Overrun)")
        print(f"    FE  (bit1)  = {(sr>>1)&1}  (Framing error)")

        print(f"\n  TX DMA CR    = 0x{tx_dma_cr:08X}")
        print(f"    EN  (bit 0) = {tx_dma_cr & 1}")
        print(f"  TX DMA NDTR  = {tx_dma_ndtr}")

        rc_map = {0: 'HAL_OK', 1: 'HAL_ERROR', 2: 'HAL_BUSY', 3: 'HAL_TIMEOUT'}
        print(f"\n  Polling TX result = {rc_map.get(poll_tx_rc, f'UNKNOWN({poll_tx_rc})')}")
        if poll_tx_rc == 0:
            print("    => HAL_UART_Transmit sent 'HELLO_FROM_MCU\\n' (15 bytes) OK")
        elif poll_tx_rc == 2:
            print("    => HAL_BUSY — UART TX locked by DMA?")
        elif poll_tx_rc == 3:
            print("    => HAL_TIMEOUT — TX shift register stuck?")
    else:
        print("  WARNING: No or short F3 response")

    # ----------------------------------------------------------------
    print("\n=== Step 3: ESP32 counters AFTER test (wait 2s) ===")
    time.sleep(2.0)
    esp_after = read_esp32_counters(args.esp_ip)
    if esp_after:
        for k, v in esp_after.items():
            print(f"    {k:20s} = {v}")
    else:
        print("  (no ESP32 response)")

    # Compare
    if esp_before and esp_after:
        rx_delta = esp_after.get('uartBytesRx', 0) - esp_before.get('uartBytesRx', 0)
        print(f"\n  >>> ESP32 uartBytesRx delta = {rx_delta}")
        if rx_delta > 0:
            print("  >>> SUCCESS: ESP32 received bytes from MCU!")
        else:
            print("  >>> FAIL: ESP32 still received nothing from MCU")

    # ----------------------------------------------------------------
    print("\n=== Step 4: MCU-side UART2 counters (0xF1) ===")
    ser.reset_input_buffer()
    frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF1]))
    ser.write(frame)
    responses = read_cdc_responses(ser, timeout=1.5)
    for ch, data in responses:
        if ch == 0xE0 and len(data) >= 41 and data[0] == 0xF1:
            vals = struct.unpack_from('<10I', data, 1)
            names = ['TX_OK', 'TX_FAIL', 'RX_EVENT', 'RX_BYTES',
                     'ERROR', 'FRAMES', 'DMA_INIT_RC',
                     'USART2_SR', 'DMA_RX_CR', 'DMA_RX_NDTR']
            for name, val in zip(names, vals):
                if 'SR' in name or 'CR' in name:
                    print(f"    {name:15s} = 0x{val:08X}")
                else:
                    print(f"    {name:15s} = {val}")

    ser.close()
    print("\n=== DONE ===")


if __name__ == '__main__':
    main()
