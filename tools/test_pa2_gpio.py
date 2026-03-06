"""
PA2 GPIO connectivity test via CDC (COM19).
1. F2 action=0: DeInit USART2, PA2=LOW (read PA3)
2. F2 action=1: PA2=HIGH (read PA3)
3. F2 action=2: Restore USART2

This tests if MCU PA2 can actually change state and if PA3 reads correctly.
To check if PA2 reaches ESP32 GPIO3, we'd need ESP32 to report its GPIO3 state.
"""
import serial, struct, time, sys

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM19'

def build_frame(sof0, ch, data):
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data: crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])

def parse_response(data):
    """Find bridge frame in data"""
    for i in range(len(data) - 5):
        if data[i] == 0xBB and data[i+1] == 0x55 and data[i+2] == 0xE0:
            plen = (data[i+3] << 8) | data[i+4]
            if i + 5 + plen <= len(data):
                return data[i+5:i+5+plen]
    return None

ser = serial.Serial(PORT, 115200, timeout=2)
time.sleep(0.1)
ser.reset_input_buffer()

# ─── Step 1: PA2 = LOW ───
print("Step 1: F2 action=0 → DeInit USART2, PA2=LOW")
frame = build_frame(0xAA, 0xE0, bytes([0xF2, 0x00]))
ser.write(frame)
time.sleep(0.5)
resp = ser.read(256)
payload = parse_response(resp)
if payload and payload[0] == 0xF2:
    print(f"  Response: action={payload[1]}, PA3_read={payload[2]}")
    print(f"  PA2=LOW set, PA3={'HIGH' if payload[2] else 'LOW'}")
else:
    print(f"  Raw: {resp.hex() if resp else '(empty)'}")

# Wait a moment
time.sleep(0.5)

# ─── Step 2: PA2 = HIGH ───
print("\nStep 2: F2 action=1 → PA2=HIGH")
ser.reset_input_buffer()
frame = build_frame(0xAA, 0xE0, bytes([0xF2, 0x01]))
ser.write(frame)
time.sleep(0.5)
resp = ser.read(256)
payload = parse_response(resp)
if payload and payload[0] == 0xF2:
    print(f"  Response: action={payload[1]}, PA3_read={payload[2]}")
    print(f"  PA2=HIGH set, PA3={'HIGH' if payload[2] else 'LOW'}")
else:
    print(f"  Raw: {resp.hex() if resp else '(empty)'}")

time.sleep(0.5)

# ─── Step 3: Restore USART2 ───
print("\nStep 3: F2 action=2 → Restore USART2")
ser.reset_input_buffer()
frame = build_frame(0xAA, 0xE0, bytes([0xF2, 0x02]))
ser.write(frame)
time.sleep(0.5)
resp = ser.read(256)
payload = parse_response(resp)
if payload and payload[0] == 0xF2:
    print(f"  Response: action={payload[1]} → USART2 restored")
else:
    print(f"  Raw: {resp.hex() if resp else '(empty)'}")

ser.close()
print("\nDone. If PA3 was always LOW regardless of PA2 state,")
print("it suggests PA2→ESP32 GPIO3 has no loopback path to PA3,")
print("which is expected since PA3 connects to ESP32 TX, not GPIO3 directly.")
print("\nNote: To truly test PA2→GPIO3, ESP32 would need to report GPIO3 level.")
