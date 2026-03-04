"""
Definitive bus contention test:
1. Normal state → read ESP32 GPIO3 level (should be HIGH = UART idle)
2. MCU F2 action=0 → PA2=LOW → read ESP32 GPIO3 level
3. MCU F2 action=1 → PA2=HIGH → read ESP32 GPIO3 level
4. Restore USART2

If GPIO3 stays HIGH when PA2=LOW, CH340 TX is overpowering MCU PA2 on the bus.
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

def query_esp32_gpio3():
    """Query ESP32 F0 debug, return (gpio1, gpio3, serial_avail, baud)"""
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
            # Layout: subcmd(1) + 7*uint32(28) + uint16(2) + 8bytes + uint16(2) + 16bytes = 57
            # Then: GPIO1(1) + GPIO3(1) + serial_avail(4) + baud(4)
            offset = 57
            gpio1 = payload[offset]
            gpio3 = payload[offset+1]
            serial_avail = struct.unpack('<I', payload[offset+2:offset+6])[0]
            baud = struct.unpack('<I', payload[offset+6:offset+10])[0]
            return gpio1, gpio3, serial_avail, baud
    return None, None, None, None

def send_f2(cdc, action):
    """Send F2 GPIO test command via CDC"""
    cdc.reset_input_buffer()
    frame = build_frame(0xAA, 0xE0, bytes([0xF2, action]))
    cdc.write(frame)
    time.sleep(0.3)
    resp = cdc.read(256)
    for i in range(len(resp) - 5):
        if resp[i] == 0xBB and resp[i+1] == 0x55 and resp[i+2] == 0xE0:
            plen = (resp[i+3] << 8) | resp[i+4]
            if i + 5 + plen <= len(resp):
                return resp[i+5:i+5+plen]
    return None

cdc = serial.Serial('COM19', 115200, timeout=2)
time.sleep(0.1)

# ── Step 1: Normal state ──
print("Step 1: Normal state (USART2 active, MCU TX idle = HIGH)")
g1, g3, avail, baud = query_esp32_gpio3()
print(f"  ESP32 GPIO1(TX)={g1}  GPIO3(RX)={g3}  Serial.available()={avail}  baud={baud}")

# ── Step 2: PA2 = LOW ──
print("\nStep 2: MCU F2 → PA2 = LOW (USART2 deinitialized)")
resp = send_f2(cdc, 0)
if resp and len(resp) >= 3:
    print(f"  MCU response: PA3_read={resp[2]}")
time.sleep(0.3)
g1, g3, avail, baud = query_esp32_gpio3()
print(f"  ESP32 GPIO1(TX)={g1}  GPIO3(RX)={g3}  Serial.available()={avail}")
if g3 == 1:
    print(f"  >>> GPIO3 still HIGH when PA2=LOW! Bus contention: CH340 TX overpowers MCU")
elif g3 == 0:
    print(f"  >>> GPIO3 went LOW! PA2 → GPIO3 signal path works")

# ── Step 3: PA2 = HIGH ──
print("\nStep 3: MCU F2 → PA2 = HIGH")
resp = send_f2(cdc, 1)
if resp and len(resp) >= 3:
    print(f"  MCU response: PA3_read={resp[2]}")
time.sleep(0.3)
g1, g3, avail, baud = query_esp32_gpio3()
print(f"  ESP32 GPIO1(TX)={g1}  GPIO3(RX)={g3}  Serial.available()={avail}")

# ── Step 4: Restore ──
print("\nStep 4: Restore USART2")
resp = send_f2(cdc, 2)
print(f"  USART2 restored")

cdc.close()

print("\n" + "=" * 60)
print("Analysis:")
print("  If GPIO3 stayed HIGH when PA2=LOW:")
print("    → CH340 TX is actively driving the bus HIGH")
print("    → MCU PA2 cannot pull the line LOW (bus contention)")
print("    → Need hardware fix: add series resistor on CH340 TX")
print("    → Or disable CH340 TX (cut trace / add switch)")
print("  If GPIO3 went LOW when PA2=LOW:")
print("    → Signal path works, issue may be timing or UART config")
