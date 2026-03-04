"""
Test ESP32 UART RX during active DAP session.
1. Connect to elaphureLink (3240) to create DAP session
2. Send DAP command (triggers 2s tight loop with uartBytesRx counting)
3. Meanwhile send known data via COM18 → ESP32 GPIO3
4. Check if uartBytesRx increased
"""
import socket, serial, struct, time, threading

HOST = '192.168.227.100'

def build_bridge_frame(sof0, ch, data):
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data: crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])

def query_esp32_counters():
    s = socket.socket()
    s.settimeout(3)
    s.connect((HOST, 5000))
    frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF0]))
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

# Step 1: Get baseline counters
print("Step 1: Baseline ESP32 counters")
before = query_esp32_counters()
if not before:
    print("  ERROR: Cannot get counters"); exit(1)
print(f"  uartBytesRx={before['uartBytesRx']}  dapTimeout={before['dapTimeout']}")

# Step 2: Open COM18 for sending
print("\nStep 2: Open COM18")
ser = serial.Serial('COM18', 1000000, timeout=1)
time.sleep(0.05)
ser.reset_input_buffer()

# Step 3: Start a thread that sends data via COM18 after a short delay
def send_via_com18():
    """Send data via COM18 while DAP tight loop is running"""
    time.sleep(0.3)  # Give time for DAP session to start
    for i in range(5):
        # Send a valid bridge frame (heartbeat-like)
        data = build_bridge_frame(0xBB, 0xD0, bytes([0x00, 0x0A]) + b'TESTDATA!!')
        ser.write(data)
        ser.flush()
        time.sleep(0.1)
    print("  COM18: sent 5 bridge frames during DAP tight loop")

sender = threading.Thread(target=send_via_com18)
sender.start()

# Step 4: Create DAP session and send command (triggers tight loop)
print("\nStep 3: Connect to elaphureLink and send DAP command")
s = socket.socket()
s.settimeout(5)
s.connect((HOST, 3240))

# Handshake
hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x01])
s.send(hs)
resp = s.recv(256)
print(f"  Handshake: {resp.hex()}")

# Send DAP_Info (triggers tight loop for up to 2s)
print("  Sending DAP_Info...")
s.send(bytes([0x00, 0x01]))

# Wait for response or timeout
try:
    s.settimeout(3)
    resp = s.recv(256)
    print(f"  DAP_Info response: {resp[:32].hex()}")
except socket.timeout:
    print("  DAP_Info TIMEOUT (expected)")

s.close()
sender.join()
ser.close()

# Step 5: Check counters after
time.sleep(0.5)
print("\nStep 4: Check ESP32 counters AFTER")
after = query_esp32_counters()
if not after:
    print("  ERROR: Cannot get counters"); exit(1)

bytes_delta = after['uartBytesRx'] - before['uartBytesRx']
timeout_delta = after['dapTimeout'] - before['dapTimeout']
print(f"  uartBytesRx delta = {bytes_delta}")
print(f"  dapTimeout  delta = {timeout_delta}")
print(f"  uartFramesRx      = {after['uartFramesRx']}")

if bytes_delta > 0:
    print(f"\n  >>> ESP32 RX WORKS! Received {bytes_delta} bytes during DAP tight loop")
else:
    print(f"\n  >>> ESP32 RX receives 0 bytes even during DAP tight loop!")
    print(f"  >>> Serial.available() never returns > 0")
    print(f"  >>> Possible: Serial.begin() RX not configured, or GPIO3 issue")
