"""Query MCU F1 counters via CDC (COM19) and ESP32 F0 counters via TCP,
then run a quick DAP test to see what happens during a session."""
import serial
import socket
import struct
import time

def build_frame(sof0, ch, data_bytes):
    """CRC = XOR(CH, LEN_H, LEN_L, DATA[0..N-1])"""
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    return bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])

def query_mcu_f1(port='COM19'):
    """Send F1 diag query to MCU via CDC, parse response."""
    frame = build_frame(0xAA, 0xE0, bytes([0xF1]))
    try:
        s = serial.Serial(port, 115200, timeout=2)
        s.reset_input_buffer()
        s.write(frame)
        s.flush()
        time.sleep(0.3)
        data = s.read(256)
        s.close()
        if not data:
            return None
        # Find response frame BB 55 E0 ...
        idx = data.find(b'\xBB\x55\xE0')
        if idx < 0:
            print(f"  MCU raw: {data.hex()}")
            return None
        data = data[idx:]
        if len(data) < 6:
            return None
        payload_len = (data[3] << 8) | data[4]
        payload = data[5:5+payload_len]
        if len(payload) < 1 or payload[0] != 0xF1:
            return None
        pos = 1
        names = ['tx_ok','tx_fail','rx_event','rx_bytes','error','frames',
                 'dma_init_rc','USART2_SR','BRR','gState']
        results = {}
        for name in names:
            if pos + 4 <= len(payload):
                results[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                pos += 4
        return results
    except Exception as e:
        print(f"  MCU query error: {e}")
        return None

def query_esp32_f0():
    """Query ESP32 debug counters via TCP port 5000."""
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
    except Exception as e:
        print(f"  ESP32 query error: {e}")
        return None

# ── Step 1: Query both sides ──
print("=" * 60)
print("Step 1: Query MCU F1 counters")
print("=" * 60)
mcu = query_mcu_f1()
if mcu:
    for k, v in mcu.items():
        flag = ""
        if k == 'rx_event' and v > 0:
            flag = " *** MCU received ESP32 data!"
        if k == 'tx_ok' and v > 0:
            flag = " *** MCU sent data to ESP32!"
        print(f"  {k} = {v}{flag}")
else:
    print("  Failed to query MCU!")

print()
print("=" * 60)
print("Step 2: Query ESP32 F0 counters")
print("=" * 60)
esp = query_esp32_f0()
if esp:
    for k, v in esp.items():
        print(f"  {k} = {v}")
else:
    print("  Failed to query ESP32!")

# ── Step 3: Quick DAP handshake test ──
print()
print("=" * 60)
print("Step 3: DAP handshake test (elaphureLink port 3240)")
print("=" * 60)
try:
    s = socket.socket()
    s.settimeout(5)
    s.connect(('192.168.227.100', 3240))
    # elaphureLink handshake
    handshake = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
    s.send(handshake)
    resp = s.recv(256)
    print(f"  Handshake response: {resp.hex()}")
    
    # Send DAP_Info (ID=0x00, subcommand=0x01 = vendor name)
    dap_cmd = bytes([0x00, 0x01])
    s.send(dap_cmd)
    time.sleep(0.5)
    resp = s.recv(256)
    print(f"  DAP_Info response ({len(resp)} bytes): {resp[:32].hex()}")
    
    # Send DAP_Connect (ID=0x02, port=1=SWD)
    dap_cmd2 = bytes([0x02, 0x01])
    s.send(dap_cmd2)
    time.sleep(0.5)
    resp2 = s.recv(256)
    print(f"  DAP_Connect response ({len(resp2)} bytes): {resp2[:16].hex()}")
    
    s.close()
    print("  DAP session OK!")
except Exception as e:
    print(f"  DAP test error: {e}")

# ── Step 4: Re-query counters after DAP test ──
print()
print("=" * 60)
print("Step 4: Re-query counters after DAP test")
print("=" * 60)
time.sleep(1)

print("MCU F1:")
mcu2 = query_mcu_f1()
if mcu2:
    for k, v in mcu2.items():
        changed = ""
        if mcu and mcu.get(k) != v:
            changed = f" (was {mcu.get(k)}) *** CHANGED"
        print(f"  {k} = {v}{changed}")

print("\nESP32 F0:")
esp2 = query_esp32_f0()
if esp2:
    for k, v in esp2.items():
        changed = ""
        if esp and esp.get(k) != v:
            changed = f" (was {esp.get(k)}) *** CHANGED"
        print(f"  {k} = {v}{changed}")
