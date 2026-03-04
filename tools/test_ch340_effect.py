"""
Test if opening COM18 (CH340) affects MCU TX → ESP32 RX path.
Hypothesis: CH340 TX state differs when COM port is open vs closed.

Test A: COM18 closed → send DAP → check if ESP32 receives MCU response
Test B: COM18 open (idle) → send DAP → check if ESP32 receives MCU response
"""
import socket, serial, struct, time

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
            for name in ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout',
                         'uartBytesRx','uartFramesRx']:
                if pos + 4 <= len(payload):
                    counters[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                    pos += 4
            return counters
    return None

def send_dap_and_check():
    """Send DAP_Info via elaphureLink, return (got_response, bytes_delta)"""
    before = query_esp32_counters()
    if not before: return None, None
    
    s = socket.socket()
    s.settimeout(5)
    s.connect((HOST, 3240))
    # Handshake
    s.send(bytes([0x8a,0x65,0x6c,0x70, 0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x01]))
    s.recv(256)
    # DAP_Info
    s.send(bytes([0x00, 0x01]))
    got_resp = False
    resp_data = None
    try:
        s.settimeout(3)
        resp_data = s.recv(256)
        got_resp = True
    except socket.timeout:
        pass
    s.close()
    
    time.sleep(0.5)
    after = query_esp32_counters()
    if not after: return got_resp, None
    
    bytes_delta = after['uartBytesRx'] - before['uartBytesRx']
    return got_resp, bytes_delta, resp_data

# ─── Test A: COM18 closed ───
print("=" * 60)
print("Test A: COM18 CLOSED — send DAP_Info via elaphureLink")
print("=" * 60)
got, delta, resp = send_dap_and_check()
print(f"  Got response: {got}")
print(f"  uartBytesRx delta: {delta}")
if resp:
    print(f"  Response data: {resp[:32].hex()}")

# ─── Test B: COM18 open (idle, no data sent) ───
print()
print("=" * 60)
print("Test B: COM18 OPEN (idle) — send DAP_Info via elaphureLink")
print("=" * 60)
ser = serial.Serial('COM18', 1000000, timeout=1)
time.sleep(0.2)
ser.reset_input_buffer()
print("  COM18 opened, keeping idle...")

got2, delta2, resp2 = send_dap_and_check()
print(f"  Got response: {got2}")
print(f"  uartBytesRx delta: {delta2}")
if resp2:
    print(f"  Response data: {resp2[:32].hex()}")

ser.close()
print("  COM18 closed.")

# ─── Summary ───
print()
print("=" * 60)
print("Summary:")
print(f"  Test A (COM18 closed): response={got},  uartBytesRx delta={delta}")
print(f"  Test B (COM18 open):   response={got2}, uartBytesRx delta={delta2}")
if not got and got2:
    print("  >>> CH340 TX interferes when COM port is closed!")
    print("  >>> Opening COM18 puts CH340 TX in controlled state, fixing MCU TX path")
elif not got and not got2:
    print("  >>> MCU TX → ESP32 RX broken regardless of COM18 state")
    print("  >>> Hardware wiring issue between PA2 and GPIO3?")
elif got and got2:
    print("  >>> Both work! MCU TX → ESP32 RX is OK")
