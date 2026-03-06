#!/usr/bin/env python3
"""Quick DAP test - write results to file."""
import socket, sys, time

host = "ehub.local"
port = 3240
out = open("test_result.txt", "w")

def log(msg):
    out.write(msg + "\n")
    out.flush()

log(f"Connecting to {host}:{port}...")
try:
    s = socket.socket()
    s.settimeout(5)
    s.connect((host, port))
except Exception as e:
    log(f"CONNECT FAILED: {e}")
    out.close()
    sys.exit(1)

# elaphureLink handshake
s.send(bytes(12))
r = s.recv(64)
log(f"Handshake: {r.hex()}")

ok = 0
fail = 0
for i in range(10):
    # DAP_Info(0x00) = Vendor Name
    cmd = bytes([0x00, 0x04, 0x00, 0x00]) + bytes([0x00, 0x00])
    s.send(cmd)
    try:
        r = s.recv(512)
        log(f"  Cmd {i+1}: OK ({len(r)} bytes) {r[:20].hex()}")
        ok += 1
    except socket.timeout:
        log(f"  Cmd {i+1}: TIMEOUT")
        fail += 1
        # Reconnect
        s.close()
        time.sleep(0.5)
        s = socket.socket()
        s.settimeout(5)
        try:
            s.connect((host, port))
            s.send(bytes(12))
            s.recv(64)
            log(f"    Reconnected")
        except Exception as e:
            log(f"    Reconnect failed: {e}")

s.close()
log(f"\nResult: {ok}/10 OK, {fail}/10 FAIL")
out.close()
