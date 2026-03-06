"""
Definitive PA2→GPIO3 connectivity test.
1. Record ESP32 Serial.available() baseline
2. MCU: F2 action=0 → PA2=LOW (break signal on ESP32 UART RX)
3. Wait, then check ESP32 Serial.available() via WiFi
4. MCU: F2 action=2 → Restore USART2

If PA2 is connected to ESP32 GPIO3 (UART RX), holding LOW generates
break/framing errors and the ESP32 UART hardware will queue bytes.
"""
import socket, serial, struct, time

HOST = '192.168.227.100'

def build_frame(sof0, ch, data):
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data: crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])

def query_esp32_serial_avail():
    """Query ESP32 F0 debug and extract Serial.available() and baudRate"""
    s = socket.socket()
    s.settimeout(3)
    s.connect((HOST, 5000))
    frame = build_frame(0xAA, 0xE0, bytes([0xF0]))
    s.send(frame)
    time.sleep(0.5)
    resp = s.recv(4096)
    s.close()
    if len(resp) > 5 and resp[0] == 0xBB and resp[2] == 0xE0:
        plen = (resp[3] << 8) | resp[4]
        payload = resp[5:5+plen]
        if payload[0] == 0xF0 and len(payload) >= 67:
            # Layout: subcmd(1) + 7*uint32(28) + uint16(2) + 8bytes + uint16(2) + 16bytes + 2bytes + uint32 + uint32
            # Offset to Serial.available(): 1 + 28 + 2 + 8 + 2 + 16 + 2 = 59
            offset = 59
            serial_avail = struct.unpack('<I', payload[offset:offset+4])[0]
            baud_rate = struct.unpack('<I', payload[offset+4:offset+8])[0]
            return serial_avail, baud_rate
    return None, None

def send_f2_command(ser, action):
    """Send F2 GPIO test command via CDC"""
    frame = build_frame(0xAA, 0xE0, bytes([0xF2, action]))
    ser.write(frame)
    time.sleep(0.3)
    resp = ser.read(256)
    # Parse response
    for i in range(len(resp) - 5):
        if resp[i] == 0xBB and resp[i+1] == 0x55 and resp[i+2] == 0xE0:
            plen = (resp[i+3] << 8) | resp[i+4]
            if i + 5 + plen <= len(resp):
                return resp[i+5:i+5+plen]
    return None

# ─── Step 1: Baseline ───
print("Step 1: ESP32 Serial.available() baseline")
avail0, baud = query_esp32_serial_avail()
print(f"  Serial.available() = {avail0}, baudRate = {baud}")

# ─── Step 2: PA2 = LOW ───
print("\nStep 2: MCU F2 → PA2 = LOW (USART2 deinitialized)")
cdc = serial.Serial('COM19', 115200, timeout=2)
time.sleep(0.1)
cdc.reset_input_buffer()
resp = send_f2_command(cdc, 0)
if resp:
    print(f"  F2 resp: action={resp[1]}, PA3={resp[2]}")
print("  PA2 is now LOW — waiting 500ms to let ESP32 see break...")

time.sleep(0.5)

# ─── Step 3: Check ESP32 ───
print("\nStep 3: ESP32 Serial.available() with PA2=LOW")
avail1, _ = query_esp32_serial_avail()
print(f"  Serial.available() = {avail1}")

# ─── Step 3b: PA2 = HIGH ───
print("\nStep 3b: MCU F2 → PA2 = HIGH")
cdc.reset_input_buffer()
resp = send_f2_command(cdc, 1)
if resp:
    print(f"  F2 resp: action={resp[1]}, PA3={resp[2]}")
time.sleep(0.5)

avail2, _ = query_esp32_serial_avail()
print(f"  Serial.available() = {avail2}")

# ─── Step 4: Restore USART2 ───
print("\nStep 4: Restore USART2")
cdc.reset_input_buffer()
resp = send_f2_command(cdc, 2)
if resp:
    print(f"  F2 resp: action={resp[1]}")
cdc.close()

# ─── Summary ───
print("\n" + "=" * 60)
print("Summary:")
print(f"  Baseline Serial.available() = {avail0}")
print(f"  After PA2=LOW               = {avail1}")
print(f"  After PA2=HIGH              = {avail2}")
if avail1 is not None and avail1 > (avail0 or 0):
    print(f"\n  >>> PA2 → GPIO3 CONNECTED! ESP32 RX sees break when PA2=LOW")
    print(f"  >>> MCU TX hardware is OK. The problem is in the UART data path.")
elif avail1 == 0 and avail0 == 0:
    print(f"\n  >>> PA2 → GPIO3 NOT CONNECTED (or ESP32 RX doesn't detect break)")
    print(f"  >>> Hardware wiring issue: PA2 output not reaching ESP32 GPIO3")
