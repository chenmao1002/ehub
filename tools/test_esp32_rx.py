"""
Test ESP32 UART RX by sending data via COM18 (CH340 TX → ESP32 GPIO3 RX).
1. Query ESP32 counters BEFORE
2. Send known bridge frame via COM18
3. Query ESP32 counters AFTER
4. Compare uartBytesRx
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

def query_esp32_counters():
    """Query ESP32 debug counters via TCP port 5000"""
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
        if payload[0] == 0xF0 and len(payload) >= 29:
            pos = 1
            counters = {}
            names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout',
                     'uartBytesRx','uartFramesRx']
            for name in names:
                if pos + 4 <= len(payload):
                    counters[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                    pos += 4
            return counters
    return None

# Step 1: Query counters BEFORE
print("Step 1: Query ESP32 counters BEFORE sending via COM18")
before = query_esp32_counters()
if not before:
    print("  ERROR: Cannot query ESP32 counters!")
    exit(1)
print(f"  uartBytesRx  = {before['uartBytesRx']}")
print(f"  uartFramesRx = {before['uartFramesRx']}")

# Step 2: Send bridge frame via COM18
print("\nStep 2: Send test data via COM18 → ESP32 GPIO3 (RX)")
# Build a valid bridge frame: WIFI_CTRL heartbeat
test_frame = build_frame(0xAA, 0xE0, bytes([0x10, 0x00, 0x00, 0x00, 0x01]))
print(f"  Sending {len(test_frame)}B: {test_frame.hex()}")

ser = serial.Serial('COM18', 1000000, timeout=1)
time.sleep(0.05)
ser.reset_input_buffer()
ser.write(test_frame)
ser.flush()
time.sleep(0.2)

# Also send some raw bytes to be sure
raw_test = b'\xAA\x55\xE0\x00\x01\x01\xE1'  # WIFI_STATUS query
print(f"  Sending {len(raw_test)}B: {raw_test.hex()}")
ser.write(raw_test)
ser.flush()
ser.close()

# Step 3: Wait and query AFTER
time.sleep(1)
print("\nStep 3: Query ESP32 counters AFTER")
after = query_esp32_counters()
if not after:
    print("  ERROR: Cannot query ESP32 counters!")
    exit(1)
print(f"  uartBytesRx  = {after['uartBytesRx']}")
print(f"  uartFramesRx = {after['uartFramesRx']}")

# Step 4: Compare
print("\nResult:")
bytes_delta = after['uartBytesRx'] - before['uartBytesRx']
frames_delta = after['uartFramesRx'] - before['uartFramesRx']
print(f"  uartBytesRx  delta = {bytes_delta}")
print(f"  uartFramesRx delta = {frames_delta}")
if bytes_delta > 0:
    print(f"  >>> ESP32 RX WORKS! Received {bytes_delta} bytes via COM18 (CH340)")
    if frames_delta > 0:
        print(f"  >>> Parsed {frames_delta} valid frames!")
    else:
        print(f"  >>> Bytes received but no frames parsed (parser issue?)")
else:
    print(f"  >>> ESP32 RX NOT receiving data from COM18!")
    print(f"  >>> Hardware issue: CH340 TX not reaching ESP32 GPIO3?")
