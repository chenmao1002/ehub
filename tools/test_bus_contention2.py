"""
Extended bus contention test:
- Test with COM18 OPEN (CH340 TX may go tri-state) vs CLOSED
- Also test MCU PA2 with VERY_HIGH speed

New F2 action=3: PA2=LOW with VERY_HIGH speed
"""
import socket, serial, struct, time, sys

HOST = '192.168.227.100'

def build_frame(sof0, ch, data):
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data: crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])

def query_esp32_gpio3():
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
            offset = 57
            gpio1 = payload[offset]
            gpio3 = payload[offset+1]
            return gpio1, gpio3
    return None, None

def send_f2(cdc, action):
    cdc.reset_input_buffer()
    frame = build_frame(0xAA, 0xE0, bytes([0xF2, action]))
    cdc.write(frame)
    time.sleep(0.3)
    cdc.read(256)

cdc = serial.Serial('COM19', 115200, timeout=2)
time.sleep(0.1)

# ── Test A: COM18 closed, PA2=LOW ──
print("Test A: COM18 CLOSED, PA2=LOW")
send_f2(cdc, 0)  # PA2=LOW
time.sleep(0.2)
g1, g3 = query_esp32_gpio3()
print(f"  GPIO3(RX) = {g3}  {'<-- CONTENTION' if g3==1 else '<-- OK, LOW'}")
send_f2(cdc, 2)  # restore
time.sleep(1)

# ── Test B: COM18 open but idle, PA2=LOW ──
print("\nTest B: COM18 OPEN (idle), PA2=LOW")
ch340 = serial.Serial('COM18', 1000000, timeout=1)
time.sleep(0.3)
ch340.reset_input_buffer()

send_f2(cdc, 0)  # PA2=LOW
time.sleep(0.2)
g1, g3 = query_esp32_gpio3()
print(f"  GPIO3(RX) = {g3}  {'<-- CONTENTION' if g3==1 else '<-- OK, LOW'}")
send_f2(cdc, 2)  # restore
time.sleep(1)

# ── Test C: COM18 open, send break (CH340 TX=LOW), PA2=LOW ──
print("\nTest C: COM18 OPEN + send_break (CH340 TX=LOW), check GPIO3")
ch340.send_break(duration=0.5)
time.sleep(0.1)
g1, g3 = query_esp32_gpio3()
print(f"  GPIO3(RX) = {g3}  (during CH340 break, expect 0)")
time.sleep(0.5)

# restore
g1, g3 = query_esp32_gpio3()
print(f"  GPIO3(RX) = {g3}  (after CH340 break, expect 1)")

ch340.close()
cdc.close()

print("\n" + "=" * 60)
print("If Test B shows GPIO3=0 but Test A shows GPIO3=1:")
print("  → Opening COM18 puts CH340 TX in hi-Z or controlled state")
print("  → Solution: keep COM18 open, or add series resistor on CH340 TX")
