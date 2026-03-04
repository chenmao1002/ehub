#!/usr/bin/env python3
"""Quick DAP test - send a few commands and print results."""
import socket, sys, time

host = "ehub.local"
port = 3240

print(f"Connecting to {host}:{port}...", flush=True)
s = socket.socket()
s.settimeout(5)
s.connect((host, port))

# elaphureLink handshake
s.send(bytes(12))
r = s.recv(64)
print(f"Handshake: {r.hex()}", flush=True)

ok = 0
fail = 0
for i in range(10):
    # DAP_Info(0x00) = Vendor Name
    cmd = bytes([0x00, 0x04, 0x00, 0x00]) + bytes([0x00, 0x00])
    s.send(cmd)
    try:
        r = s.recv(512)
        print(f"  Cmd {i+1}: OK ({len(r)} bytes)", flush=True)
        ok += 1
    except socket.timeout:
        print(f"  Cmd {i+1}: TIMEOUT", flush=True)
        fail += 1
        # Reconnect
        s.close()
        s = socket.socket()
        s.settimeout(5)
        s.connect((host, port))
        s.send(bytes(12))
        s.recv(64)

s.close()
print(f"\nResult: {ok}/10 OK, {fail}/10 FAIL", flush=True)
