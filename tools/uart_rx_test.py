#!/usr/bin/env python3
"""Test if ESP32 UART RX is working by sending a bridge frame via CH340 (COM18).
If ESP32 UART RX works, it should process the frame and we'd see counter changes."""
import serial, socket, struct, time

out = open("C:/Users/MC/Desktop/uart_rx_test.txt", "w")
def log(msg):
    out.write(msg + "\n")
    out.flush()

host = "192.168.227.100"

# 1. Get ESP32 baseline counters
log("=== Test ESP32 UART RX via CH340 ===")
log("\n[1] Baseline ESP32 counters:")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, 5000))
    frame = bytearray([0xAA, 0x55, 0xE0, 0x00, 0x01, 0xF0])
    crc = 0xE0 ^ 0x00 ^ 0x01 ^ 0xF0
    frame.append(crc)
    sk.send(bytes(frame))
    time.sleep(0.5)
    r = sk.recv(1024)
    if len(r) > 5 and r[0] == 0xBB:
        flen = (r[3] << 8) | r[4]
        data = r[5:5+flen]
        if data[0] == 0xF0:
            names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout','uartBytesRx','uartFramesRx']
            for idx, name in enumerate(names):
                v = struct.unpack_from('<I', data, 1 + idx*4)[0]
                log(f"  {name:20s} = {v}")
    sk.close()
except Exception as e:
    log(f"  Error: {e}")

# 2. Send a bridge frame via COM18 (CH340→ESP32 GPIO3)
log("\n[2] Sending bridge frame via COM18 at 1Mbaud...")
try:
    s = serial.Serial('COM18', 1000000, timeout=1)
    # Send a simple heartbeat-like frame: [AA 55 E0 00 01 F0 CRC]
    # This is a 0xF0 counter query, same as we send via TCP
    test_frame = bytearray([0xAA, 0x55, 0xE0, 0x00, 0x01, 0xF0])
    crc = 0xE0 ^ 0x00 ^ 0x01 ^ 0xF0
    test_frame.append(crc)
    
    s.write(bytes(test_frame))
    log(f"  Sent: {test_frame.hex()} ({len(test_frame)} bytes)")
    
    # Wait and check if we get any response back
    time.sleep(1)
    avail = s.in_waiting
    if avail > 0:
        resp = s.read(avail)
        log(f"  Response on COM18: {resp.hex()} ({len(resp)} bytes)")
    else:
        log(f"  No response on COM18 (expected since response goes to MCU)")
    s.close()
except Exception as e:
    log(f"  Error: {e}")

# 3. Check ESP32 counters after
log("\n[3] ESP32 counters after sending via COM18:")
time.sleep(1)
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, 5000))
    frame = bytearray([0xAA, 0x55, 0xE0, 0x00, 0x01, 0xF0])
    crc = 0xE0 ^ 0x00 ^ 0x01 ^ 0xF0
    frame.append(crc)
    sk.send(bytes(frame))
    time.sleep(0.5)
    r = sk.recv(1024)
    if len(r) > 5 and r[0] == 0xBB:
        flen = (r[3] << 8) | r[4]
        data = r[5:5+flen]
        if data[0] == 0xF0:
            names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout','uartBytesRx','uartFramesRx']
            for idx, name in enumerate(names):
                v = struct.unpack_from('<I', data, 1 + idx*4)[0]
                log(f"  {name:20s} = {v}")
    sk.close()
except Exception as e:
    log(f"  Error: {e}")

log("\n[4] If uartBytesRx increased, ESP32 UART RX works via CH340.")
log("    If not, ESP32 UART0 RX is not receiving despite signal being on the wire.")

out.close()
print("DONE_RX_TEST")
