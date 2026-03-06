"""
Definitive GPIO3 pin level test — uses Serial.end() + digitalRead on ESP32.
1. Normal state: query GPIO3 via F4 (UART idle, expect HIGH)
2. MCU PA2=LOW: query GPIO3 via F4 (expect LOW if connected)
3. Restore
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

def query_gpio3_direct():
    """Send F4 command to ESP32 — stops UART, reads GPIO3 with digitalRead, restarts"""
    s = socket.socket()
    s.settimeout(5)
    s.connect((HOST, 5000))
    frame = build_frame(0xAA, 0xE0, bytes([0xF4]))
    s.send(frame)
    time.sleep(1)  # Need more time since Serial.end()/begin() takes time
    resp = s.recv(4096)
    s.close()
    if len(resp) > 5 and resp[0] == 0xBB and resp[2] == 0xE0:
        plen = (resp[3] << 8) | resp[4]
        payload = resp[5:5+plen]
        if payload[0] == 0xF4 and len(payload) >= 12:
            gpio1 = payload[1]
            readings = list(payload[2:12])
            return gpio1, readings
    return None, None

def send_f2(cdc, action):
    cdc.reset_input_buffer()
    frame = build_frame(0xAA, 0xE0, bytes([0xF2, action]))
    cdc.write(frame)
    time.sleep(0.3)
    cdc.read(256)

# ── Test 1: Normal state (USART2 active, MCU TX idle) ──
print("Test 1: Normal state — USART2 active, MCU TX idle (expect GPIO3=1)")
g1, readings = query_gpio3_direct()
print(f"  GPIO1(TX) = {g1}")
print(f"  GPIO3(RX) readings = {readings}")
avg = sum(readings)/len(readings) if readings else -1
print(f"  GPIO3 average = {avg:.1f} ({'HIGH' if avg > 0.5 else 'LOW'})")

time.sleep(1)

# ── Test 2: MCU PA2 = LOW ──
print("\nTest 2: MCU PA2 = LOW — expect GPIO3=0 if connected")
cdc = serial.Serial('COM19', 115200, timeout=2)
time.sleep(0.1)
send_f2(cdc, 0)  # PA2 = LOW
time.sleep(0.3)
print("  MCU PA2 set to LOW")

g1, readings = query_gpio3_direct()
print(f"  GPIO1(TX) = {g1}")
print(f"  GPIO3(RX) readings = {readings}")
avg = sum(readings)/len(readings) if readings else -1
print(f"  GPIO3 average = {avg:.1f} ({'HIGH' if avg > 0.5 else 'LOW'})")

# ── Test 3: MCU PA2 = HIGH ──
print("\nTest 3: MCU PA2 = HIGH — expect GPIO3=1")
send_f2(cdc, 1)  # PA2 = HIGH
time.sleep(0.3)

g1, readings = query_gpio3_direct()
print(f"  GPIO1(TX) = {g1}")
print(f"  GPIO3(RX) readings = {readings}")
avg = sum(readings)/len(readings) if readings else -1
print(f"  GPIO3 average = {avg:.1f} ({'HIGH' if avg > 0.5 else 'LOW'})")

# ── Restore ──
print("\nRestoring USART2...")
send_f2(cdc, 2)
cdc.close()

# ── Summary ──
print("\n" + "=" * 60)
print("If Test1=HIGH, Test2=LOW, Test3=HIGH:")
print("  → PA2 connected to GPIO3, signal path OK")
print("  → Problem is UART configuration or IO_MUX routing")
print("If Test2=HIGH (PA2=LOW but GPIO3 stays HIGH):")
print("  → Bus contention: another driver holds GPIO3 HIGH")
print("  → Or PA2 not reaching GPIO3 (broken trace, buffer issue)")
