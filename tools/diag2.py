#!/usr/bin/env python3
"""Quick connectivity and DAP test."""
import socket, time, sys

out = open("C:/Users/MC/Desktop/diag2.txt", "w")
def log(msg):
    out.write(msg + "\n")
    out.flush()

host = "192.168.227.100"

# Test port 5000 (bridge TCP)
log("=== Port 5000 test ===")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, 5000))
    log(f"Port 5000: CONNECTED")
    sk.close()
except Exception as e:
    log(f"Port 5000: FAILED ({e})")

# Test port 3240 (elaphureLink)
log("=== Port 3240 test ===")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, 3240))
    log(f"Port 3240: CONNECTED")
    # Try handshake
    sk.send(bytes(12))
    r = sk.recv(64)
    log(f"Handshake: {r.hex() if r else 'EMPTY'}")
    # Try DAP command
    cmd = bytes([0x00, 0x04, 0x00, 0x00]) + bytes([0x00, 0x00])
    sk.send(cmd)
    time.sleep(1)
    try:
        r = sk.recv(512)
        log(f"DAP response: {len(r)} bytes: {r.hex()}")
    except socket.timeout:
        log("DAP response: TIMEOUT")
    sk.close()
except Exception as e:
    log(f"Port 3240: FAILED ({e})")

# Test port 6000 (OpenOCD DAP)
log("=== Port 6000 test ===")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect((host, 6000))
    log(f"Port 6000: CONNECTED")
    sk.close()
except Exception as e:
    log(f"Port 6000: FAILED ({e})")

out.close()
print("DONE2")
