#!/usr/bin/env python3
"""Complete DAP test via elaphureLink port 3240."""
import socket, time

out = open("C:/Users/MC/Desktop/dap_test.txt", "w")
def log(msg):
    out.write(msg + "\n")
    out.flush()

host = "192.168.227.100"
port = 3240

log("=== DAP Test via elaphureLink ===")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, port))
    log("Connected")
    
    # Handshake
    hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
    sk.send(hs)
    r = sk.recv(64)
    log(f"Handshake: {r.hex()}")
    
    # Send DAP commands
    ok = 0
    fail = 0
    for i in range(20):
        # elaphureLink: 4-byte header [00 LenH LenL 00] + DAP command
        # DAP_Info(0x00) = Vendor
        dap_cmd = bytes([0x00, 0x00])  # DAP_Info(Vendor)
        # elaphureLink raw mode: just send the DAP command directly
        el_frame = bytes([0x00, 0x00, len(dap_cmd), 0x00]) + dap_cmd
        sk.send(el_frame)
        
        try:
            r = sk.recv(512)
            if len(r) > 0:
                log(f"  Cmd {i+1}: OK ({len(r)} bytes)")
                ok += 1
            else:
                log(f"  Cmd {i+1}: EMPTY")
                fail += 1
        except socket.timeout:
            log(f"  Cmd {i+1}: TIMEOUT")
            fail += 1
    
    sk.close()
    log(f"\nResult: {ok}/20 OK, {fail}/20 FAIL")

except Exception as e:
    log(f"Error: {e}")

# Query ESP32 counters
log("\n=== ESP32 counters ===")
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
    
    # Parse counter data from bridge frame
    if len(r) >= 30 and r[0] == 0xBB:
        flen = (r[3] << 8) | r[4]
        data = r[5:5+flen]
        if data[0] == 0xF0:
            import struct
            names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout','uartBytesRx','uartFramesRx']
            for idx, name in enumerate(names):
                v = struct.unpack_from('<I', data, 1 + idx*4)[0]
                log(f"  {name:20s} = {v}")
    sk.close()
except Exception as e:
    log(f"Counter error: {e}")

out.close()
print("DONE_DAP")
