"""PING 诊断脚本 — 直接对指定 COM 口发送 PING 并打印原始回复"""
import serial, time

SOF0_CMD, SOF1 = 0xAA, 0x55
CH_CONFIG = 0xF0

def crc8(ch_byte, data):
    crc = ch_byte ^ ((len(data) >> 8) & 0xFF) ^ (len(data) & 0xFF)
    for b in data:
        crc ^= b
    return crc & 0xFF

def build_frame(ch, data):
    hdr = bytes([SOF0_CMD, SOF1, ch, (len(data) >> 8) & 0xFF, len(data) & 0xFF])
    return hdr + data + bytes([crc8(ch, data)])

ping = build_frame(CH_CONFIG, bytes([0xF0, 0x00, 0, 0, 0, 0]))
print("PING frame:", " ".join(f"{b:02X}" for b in ping))

PORT = "COM19"
BAUD = 115200

def test_ping(port, baud, dtr, label):
    print(f"\n{'='*50}")
    print(f"Test: {label}  (DTR={'ON' if dtr else 'OFF'})")
    try:
        with serial.Serial(port, baud, timeout=0.1,
                           dsrdtr=dtr, rtscts=False,
                           write_timeout=2) as s:
            if dtr:
                s.dtr = True
            print(f"  Port opened. Waiting 300ms ...")
            time.sleep(0.3)
            s.reset_input_buffer()
            for attempt in range(3):
                s.write(ping)
                s.flush()
                print(f"  PING #{attempt+1} sent: {' '.join(f'{b:02X}' for b in ping)}")
                time.sleep(0.15)

            print("  Listening 2s ...")
            buf = bytearray()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                chunk = s.read(128)
                if chunk:
                    buf.extend(chunk)
                    print("  RX:", " ".join(f"{b:02X}" for b in buf))
                else:
                    time.sleep(0.05)

            print(f"  Total: {len(buf)} bytes")
            print(f"  BB55F0: {bytes([0xBB,0x55,0xF0]) in buf}  EHUB: {b'EHUB' in buf}")
            return len(buf) > 0
    except serial.SerialException as e:
        print(f"  SerialException: {e}")
        return False

test_ping(PORT, BAUD, dtr=False, label="DTR OFF (no hw handshake)")
test_ping(PORT, BAUD, dtr=True,  label="DTR ON  (assert host ready)")
print("\nDone.")
