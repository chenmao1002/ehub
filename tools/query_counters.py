import socket, struct, time

def build_frame(sof0, ch, data_bytes):
    """Build bridge frame: [SOF0][0x55][CH][LEN_H][LEN_L][DATA...][CRC]
    CRC = XOR(CH, LEN_H, LEN_L, DATA[0..N-1])"""
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    frame = bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])
    return frame

def query_esp32():
    s = socket.socket()
    s.settimeout(3)
    s.connect(('192.168.227.100', 5000))
    # Send WiFi control frame with subcmd 0xF0 (DEBUG_DIAG)
    # CH=0xE0 (BRIDGE_CH_WIFI_CTRL), DATA=[0xF0]
    frame = build_frame(0xAA, 0xE0, bytes([0xF0]))
    s.send(frame)
    time.sleep(0.5)
    data = s.recv(4096)
    s.close()
    return data

print('=== Query ESP32 counters ===')
data = query_esp32()
print(f'Raw hex: {data.hex()}')
print(f'Raw len: {len(data)}')

# Parse counter frame: BB 55 E0 LEN_H LEN_L [data] CRC
# data[0] = subcmd echo 0xF0, then counters
if len(data) > 5 and data[0] == 0xBB and data[2] == 0xE0:
    payload_len = (data[3] << 8) | data[4]
    payload = data[5:5+payload_len]
    print(f'Payload len: {payload_len}, payload hex: {payload.hex()}')
    
    if payload[0] == 0xF0:
        pos = 1  # skip subcmd echo
        # 7 x uint32 counters
        counter_names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout',
                         'uartBytesRx','uartFramesRx']
        for i, name in enumerate(counter_names):
            if pos + 4 <= len(payload):
                val = struct.unpack('<I', payload[pos:pos+4])[0]
                print(f'  {name} = {val}')
                pos += 4
        
        # 2 bytes: lastDapCmdLen
        if pos + 2 <= len(payload):
            lastDapCmdLen = struct.unpack('<H', payload[pos:pos+2])[0]
            pos += 2
            print(f'  lastDapCmdLen = {lastDapCmdLen}')
        # 8 bytes: lastDapCmd
        if pos + 8 <= len(payload):
            print(f'  lastDapCmd = {payload[pos:pos+8].hex()}')
            pos += 8
        # 2 bytes: lastBridgeTxLen
        if pos + 2 <= len(payload):
            lastBridgeTxLen = struct.unpack('<H', payload[pos:pos+2])[0]
            pos += 2
            print(f'  lastBridgeTxLen = {lastBridgeTxLen}')
        # 16 bytes: lastBridgeTx
        if pos + 16 <= len(payload):
            print(f'  lastBridgeTx = {payload[pos:pos+16].hex()}')
            pos += 16
        # 2 bytes: GPIO placeholders
        if pos + 2 <= len(payload):
            print(f'  gpio1={payload[pos]:02x} gpio3={payload[pos+1]:02x}')
            pos += 2
        # Serial.available() snapshot
        if pos + 4 <= len(payload):
            val = struct.unpack('<I', payload[pos:pos+4])[0]
            print(f'  serialAvail = {val}')
            pos += 4
        # baudRate
        if pos + 4 <= len(payload):
            val = struct.unpack('<I', payload[pos:pos+4])[0]
            print(f'  baudRate = {val}')
            pos += 4
        # serialAvailMax
        if pos + 4 <= len(payload):
            val = struct.unpack('<I', payload[pos:pos+4])[0]
            print(f'  serialAvailMax = {val}')
            pos += 4
        # loopUartBytes
        if pos + 4 <= len(payload):
            val = struct.unpack('<I', payload[pos:pos+4])[0]
            print(f'  loopUartBytes = {val}')
            pos += 4
    else:
        print(f'Unexpected subcmd: 0x{payload[0]:02x}')
else:
    print('Unexpected response format')
    print(f'First bytes: {data[:10].hex() if len(data) >= 10 else data.hex()}')
