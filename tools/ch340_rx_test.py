"""Test if ESP32 can receive data sent via CH340 (COM18).
1. Send known bytes to COM18 at 1Mbaud
2. Wait briefly 
3. Query ESP32 counters via TCP to check serialAvailMax
"""
import serial
import socket
import struct
import time

def build_frame(sof0, ch, data_bytes):
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    return bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])

def query_esp32_counters():
    s = socket.socket()
    s.settimeout(3)
    s.connect(('192.168.227.100', 5000))
    frame = build_frame(0xAA, 0xE0, bytes([0xF0]))
    s.send(frame)
    time.sleep(0.5)
    data = s.recv(4096)
    s.close()
    
    if len(data) > 5 and data[0] == 0xBB and data[2] == 0xE0:
        payload = data[5:5+((data[3]<<8)|data[4])]
        if len(payload) > 0 and payload[0] == 0xF0:
            pos = 1
            results = {}
            names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout',
                     'uartBytesRx','uartFramesRx']
            for name in names:
                if pos + 4 <= len(payload):
                    results[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                    pos += 4
            pos += 2 + 8 + 2 + 16 + 2  # skip lastDapCmd, lastBridgeTx, GPIO
            for name in ['serialAvail', 'baudRate', 'serialAvailMax', 'loopUartBytes']:
                if pos + 4 <= len(payload):
                    results[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                    pos += 4
            return results
    return None

# Step 1: Query baseline counters
print("=== Baseline counters ===")
baseline = query_esp32_counters()
if baseline:
    for k, v in baseline.items():
        print(f"  {k} = {v}")
else:
    print("  Failed to query!")

# Step 2: Send data via COM18 
print("\n=== Sending data via COM18 (CH340) at 1Mbaud ===")
try:
    ser = serial.Serial('COM18', 1000000, timeout=0.1)
    time.sleep(0.1)
    
    # Send a valid bridge frame and some raw bytes
    test_frame = build_frame(0xAA, 0xE0, bytes([0x10]))  # heartbeat-like
    print(f"  Sending frame: {test_frame.hex()}")
    ser.write(test_frame)
    ser.write(b'\xAA\x55\xAA\x55\xAA\x55')  # Extra garbage to trigger available()
    ser.flush()
    
    # Also read any incoming data (MCU heartbeats)
    time.sleep(0.3)
    incoming = ser.read(1024)
    print(f"  Read {len(incoming)} bytes from COM18")
    if incoming:
        print(f"  First 32 bytes: {incoming[:32].hex()}")
    
    ser.close()
except Exception as e:
    print(f"  COM18 error: {e}")

# Step 3: Wait and query counters again
time.sleep(0.5)
print("\n=== Post-send counters ===")
after = query_esp32_counters()
if after:
    for k, v in after.items():
        changed = " *** CHANGED ***" if baseline and baseline.get(k) != v else ""
        print(f"  {k} = {v}{changed}")
else:
    print("  Failed to query!")
