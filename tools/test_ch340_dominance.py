"""
CH340 TX dominance test — verify CH340 controls GPIO3, MCU PA2 does not.
1. Normal: both idle HIGH → expect GPIO3=HIGH
2. CH340 BREAK (TX=LOW): GPIO3 should go LOW if CH340 dominates
3. MCU PA2=LOW + CH340 idle: if GPIO3 stays HIGH → CH340 overpowers MCU
4. MCU PA2=LOW + CH340 BREAK: both LOW → should definitely be LOW
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
    time.sleep(1.5)
    resp = b''
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            resp += chunk
    except:
        pass
    s.close()
    if len(resp) > 5 and resp[0] == 0xBB and resp[2] == 0xE0:
        plen = (resp[3] << 8) | resp[4]
        payload = resp[5:5+plen]
        if payload[0] == 0xF4 and len(payload) >= 12:
            gpio1 = payload[1]
            readings = list(payload[2:12])
            return gpio1, readings
    print(f"  [RAW RESP: {resp.hex() if resp else 'empty'}]")
    return None, None

def send_f2(cdc, action):
    cdc.reset_input_buffer()
    frame = build_frame(0xAA, 0xE0, bytes([0xF2, action]))
    cdc.write(frame)
    time.sleep(0.3)
    cdc.read(256)

def show_result(label, g1, readings):
    if readings is None:
        print(f"  {label}: NO RESPONSE")
        return
    avg = sum(readings)/len(readings)
    print(f"  {label}: GPIO3 = {readings}  avg={avg:.1f} ({'HIGH' if avg > 0.5 else 'LOW'})")

print("=" * 70)
print("CH340 TX Dominance Test — F4 digitalRead(3) after Serial.end()")
print("=" * 70)

cdc = serial.Serial('COM19', 115200, timeout=2)
time.sleep(0.2)

# ── Test A: Both idle (MCU USART2 active TX=HIGH, CH340 idle TX=HIGH) ──
print("\nTest A: Both idle — MCU TX idle, CH340 idle → expect HIGH")
g1, readings = query_gpio3_direct()
show_result("A", g1, readings)

time.sleep(0.5)

# ── Test B: CH340 BREAK (TX=LOW), MCU idle ──
print("\nTest B: CH340 BREAK (TX=LOW), MCU USART2 active → expect LOW if CH340 dominates")
ch340 = serial.Serial('COM18', 1000000, timeout=1)
time.sleep(0.1)
ch340.break_condition = True  # Force TX=LOW
time.sleep(0.2)
g1, readings = query_gpio3_direct()
show_result("B", g1, readings)
ch340.break_condition = False
ch340.close()

time.sleep(0.5)

# ── Test C: MCU PA2=LOW, CH340 idle ──
print("\nTest C: MCU PA2=LOW (push-pull), CH340 idle → shows who wins")
send_f2(cdc, 0)  # PA2 = LOW
time.sleep(0.3)
g1, readings = query_gpio3_direct()
show_result("C", g1, readings)

time.sleep(0.5)

# ── Test D: MCU PA2=LOW + CH340 BREAK → both LOW ──
print("\nTest D: MCU PA2=LOW + CH340 BREAK → both LOW → must be LOW")
ch340 = serial.Serial('COM18', 1000000, timeout=1)
time.sleep(0.1)
ch340.break_condition = True
time.sleep(0.2)
g1, readings = query_gpio3_direct()
show_result("D", g1, readings)
ch340.break_condition = False
ch340.close()

# ── Restore ──
print("\nRestoring USART2...")
send_f2(cdc, 2)
cdc.close()

# ── Summary ──
print("\n" + "=" * 70)
print("Analysis:")
print("  A=HIGH, B=LOW  → CH340 controls GPIO3 (dominates)")
print("  A=HIGH, C=HIGH → MCU PA2 CANNOT pull GPIO3 LOW (overpowered)")
print("  D=LOW          → confirms both LOW state is detectable")
print("")
print("If B=LOW but C=HIGH: CH340 TX overpowers MCU PA2 on shared bus")
print("  → Hardware fix needed: series resistor on CH340 TX, or tristate buffer")
print("If C=LOW: MCU PA2 CAN control GPIO3, some other issue")
