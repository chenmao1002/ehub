"""Poll ESP32 counters every 2 seconds to see if serialAvailMax changes
(indicating MCU heartbeat data is arriving)"""
import socket, struct, time

def build_frame(sof0, ch, data_bytes):
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    return bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])

def query():
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

print("Polling ESP32 counters (5 rounds, 2s apart)...")
for i in range(5):
    r = query()
    if r:
        print(f"[{i}] serialAvailMax={r.get('serialAvailMax','-')}, "
              f"loopUartBytes={r.get('loopUartBytes','-')}, "
              f"uartBytesRx={r.get('uartBytesRx','-')}, "
              f"uartFramesRx={r.get('uartFramesRx','-')}")
    else:
        print(f"[{i}] Query failed")
    if i < 4:
        time.sleep(2)

print("\nDone. If serialAvailMax didn't change, MCU data is NOT reaching ESP32 GPIO3.")
