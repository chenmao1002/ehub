"""Direct test: open COM18 briefly to verify MCU is transmitting,
then close it and immediately poll ESP32 counters to see if
serialAvailMax changed while COM18 was closed."""
import socket
import struct
import time

def build_frame(sof0, ch, data_bytes):
    length = len(data_bytes)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data_bytes:
        crc ^= b
    return bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data_bytes + bytes([crc & 0xFF])

def query_esp32():
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
            pos += 2 + 8 + 2 + 16 + 2
            for name in ['serialAvail', 'baudRate', 'serialAvailMax', 'loopUartBytes']:
                if pos + 4 <= len(payload):
                    results[name] = struct.unpack('<I', payload[pos:pos+4])[0]
                    pos += 4
            return results
    return None

# Poll every second for 10 seconds — see if serialAvailMax grows
# This tests whether MCU heartbeats are arriving at ESP32 UART without
# any COM port being open
print("Polling ESP32 counters for 10 seconds (COM18 closed)...")
print("MCU should be sending battery/heartbeat via Bridge_SendToAll every few seconds")
for i in range(10):
    r = query_esp32()
    if r:
        print(f"[{i:2d}s] serialAvailMax={r['serialAvailMax']:5d}  "
              f"loopUartBytes={r['loopUartBytes']:5d}  "
              f"serialAvail={r['serialAvail']:3d}  "
              f"uartFramesRx={r['uartFramesRx']:3d}")
    else:
        print(f"[{i:2d}s] query failed")
    time.sleep(1)
