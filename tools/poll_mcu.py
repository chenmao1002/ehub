"""Poll MCU F1 counters to see if tx_ok is still growing,
proving MCU is actively transmitting."""
import serial
import struct
import time

def build_frame(sof0, ch, data_bytes):
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    return bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])

def query_mcu():
    frame = build_frame(0xAA, 0xE0, bytes([0xF1]))
    try:
        s = serial.Serial('COM19', 115200, timeout=1)
        s.reset_input_buffer()
        s.write(frame)
        s.flush()
        time.sleep(0.3)
        data = s.read(256)
        s.close()
        if not data:
            return None
        idx = data.find(b'\xBB\x55\xE0')
        if idx < 0:
            return None
        data = data[idx:]
        if len(data) < 6:
            return None
        payload_len = (data[3] << 8) | data[4]
        payload = data[5:5+payload_len]
        if len(payload) < 1 or payload[0] != 0xF1:
            return None
        pos = 1
        names = ['tx_ok','tx_fail','rx_event','rx_bytes','error','frames',
                 'dma_init_rc','USART2_SR','BRR','gState']
        results = {}
        for name in names:
            if pos + 4 <= len(payload):
                results[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                pos += 4
        return results
    except Exception as e:
        return None

print("Polling MCU F1 counters for 15 seconds...")
for i in range(5):
    r = query_mcu()
    if r:
        print(f"[{i*3:2d}s] tx_ok={r['tx_ok']:4d}  tx_fail={r['tx_fail']}  "
              f"rx_event={r['rx_event']:3d}  rx_bytes={r['rx_bytes']:5d}  "
              f"frames={r['frames']:3d}  error={r['error']}")
    else:
        print(f"[{i*3:2d}s] query failed")
    time.sleep(3)
