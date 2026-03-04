"""End-to-end bridge test via TCP port 5000:
1. Send a bridge DAP_Info command via TCP → ESP32 → UART → MCU
2. MCU executes DAP_Info and replies via UART → ESP32 → TCP
3. Check if reply comes back

This tests the full round-trip through the bridge."""
import socket
import struct
import time

def build_frame(sof0, ch, data_bytes):
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    return bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])

# Test 1: Bridge DAP command via TCP port 5000
print("=" * 60)
print("Test 1: Bridge DAP_Info via TCP port 5000")
print("=" * 60)
try:
    s = socket.socket()
    s.settimeout(3)
    s.connect(('192.168.227.100', 5000))
    
    # Bridge frame: CH=0xD0 (DAP), DATA = [0x00, 0x01] (DAP_Info, vendor)
    dap_info_cmd = build_frame(0xAA, 0xD0, bytes([0x00, 0x01]))
    print(f"  Sending bridge frame: {dap_info_cmd.hex()}")
    s.send(dap_info_cmd)
    
    time.sleep(2)
    try:
        resp = s.recv(4096)
        print(f"  Response ({len(resp)} bytes): {resp.hex()}")
    except socket.timeout:
        print(f"  TIMEOUT - no response")
    
    s.close()
except Exception as e:
    print(f"  Error: {e}")

# Test 2: elaphureLink DAP test via port 3240
print()
print("=" * 60)
print("Test 2: elaphureLink DAP_Info via port 3240")
print("=" * 60)
try:
    s = socket.socket()
    s.settimeout(5)
    s.connect(('192.168.227.100', 3240))
    
    # Handshake
    handshake = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
    s.send(handshake)
    resp = s.recv(256)
    print(f"  Handshake OK: {resp.hex()}")
    
    # DAP_Info vendor
    s.send(bytes([0x00, 0x01]))
    time.sleep(2)
    try:
        resp = s.recv(256)
        print(f"  DAP_Info response ({len(resp)} bytes): {resp[:32].hex()}")
        # Parse response: first byte = 0x00 (DAP_Info), second = length, then string
        if resp[0] == 0x00 and len(resp) > 2:
            str_len = resp[1]
            vendor = resp[2:2+str_len].decode('ascii', errors='replace')
            print(f"  Vendor: '{vendor}'")
    except socket.timeout:
        print(f"  TIMEOUT - no DAP_Info response!")
    
    s.close()
except Exception as e:
    print(f"  Error: {e}")

# Test 3: Check ESP32 counters after
print()
print("=" * 60)
print("Test 3: ESP32 counters after test")
print("=" * 60)
try:
    s = socket.socket()
    s.settimeout(3)
    s.connect(('192.168.227.100', 5000))
    s.send(build_frame(0xAA, 0xE0, bytes([0xF0])))
    time.sleep(0.3)
    data = s.recv(4096)
    s.close()
    if len(data) > 5 and data[0] == 0xBB and data[2] == 0xE0:
        payload = data[5:5+((data[3]<<8)|data[4])]
        if payload[0] == 0xF0:
            pos = 1
            names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout',
                     'uartBytesRx','uartFramesRx']
            for name in names:
                if pos + 4 <= len(payload):
                    val = struct.unpack('<I', payload[pos:pos+4])[0]
                    print(f"  {name} = {val}")
                    pos += 4
            pos += 2 + 8 + 2 + 16 + 2
            for name in ['serialAvail', 'baudRate', 'serialAvailMax', 'loopUartBytes']:
                if pos + 4 <= len(payload):
                    val = struct.unpack('<I', payload[pos:pos+4])[0]
                    print(f"  {name} = {val}")
                    pos += 4
except Exception as e:
    print(f"  Error: {e}")
