#!/usr/bin/env python3
"""Query ESP32 counters via port 5000 and test DAP ports."""
import socket, time, struct

out = open("C:/Users/MC/Desktop/diag3.txt", "w")
def log(msg):
    out.write(msg + "\n")
    out.flush()

host = "192.168.227.100"

# === Query ESP32 counters via port 5000 ===
log("=== ESP32 counters via port 5000 ===")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, 5000))
    log("Connected to 5000")
    
    # Send bridge frame: [AA 55 E0 00 01 F0] + CRC
    data = bytes([0xF0])
    frame = bytearray([0xAA, 0x55, 0xE0, 0x00, len(data)])
    crc = 0xE0 ^ 0x00 ^ len(data)
    for b in data:
        frame.append(b)
        crc ^= b
    frame.append(crc)
    
    sk.send(bytes(frame))
    time.sleep(1)
    r = sk.recv(1024)
    log(f"Response: {len(r)} bytes: {r.hex()}")
    sk.close()
except Exception as e:
    log(f"Port 5000 error: {e}")

# === Test port 3240 with delays ===
log("\n=== Port 3240 with delays ===")
try:
    sk = socket.socket()
    sk.settimeout(10)  # longer timeout
    log("Connecting to 3240...")
    sk.connect((host, 3240))
    log("Connected!")
    time.sleep(1)  # wait before sending
    
    # Send handshake
    hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
    sk.send(hs)
    log(f"Sent handshake: {hs.hex()}")
    
    # Wait for response
    try:
        r = sk.recv(64)
        log(f"Handshake response: {len(r)} bytes: {r.hex()}")
    except socket.timeout:
        log("Handshake response: TIMEOUT (10s)")
    
    sk.close()
except Exception as e:
    log(f"Port 3240 error: {e}")

# === Test port 6000 with OpenOCD protocol ===
log("\n=== Port 6000 OpenOCD test ===")
try:
    sk = socket.socket()
    sk.settimeout(10)
    sk.connect((host, 6000))
    log("Connected to 6000")
    
    # Send OpenOCD DAP header + DAP_Info(0x00)
    # Header: [sig4][len2][type1][rsv1] = 8 bytes
    # sig = 0x00000001 (little-endian), len = 2, type = 1 (REQ), rsv = 0
    dap_cmd = bytes([0x00, 0x00])  # DAP_Info(Vendor)
    hdr = struct.pack('<IHBx', 1, len(dap_cmd), 1)
    sk.send(hdr + dap_cmd)
    log(f"Sent OpenOCD DAP_Info")
    
    try:
        r = sk.recv(512)
        log(f"Response: {len(r)} bytes: {r.hex()}")
    except socket.timeout:
        log("Response: TIMEOUT (10s)")
    
    sk.close()
except Exception as e:
    log(f"Port 6000 error: {e}")

out.close()
print("DONE3")
