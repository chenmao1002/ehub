#!/usr/bin/env python3
"""Simple reliability test: send N DAP_Info commands, count success/fail."""
import socket, struct, time, sys

HOST = '192.168.227.100'
PORT = 6000
SIG = 0x00504144
N = 50

def send_recv(s, cmd):
    s.sendall(struct.pack('<IHBb', SIG, len(cmd), 1, 0) + bytes(cmd))
    h = b''
    while len(h) < 8:
        h += s.recv(8 - len(h))
    _, L, _, _ = struct.unpack('<IHBb', h)
    d = b''
    while len(d) < L:
        d += s.recv(L - len(d))
    return d

s = socket.socket()
s.settimeout(3)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
s.connect((HOST, PORT))

ok = 0
fail = 0
times = []
consecutive_fails = 0

for i in range(N):
    time.sleep(0.05)
    # After a timeout, drain stale data and reconnect if needed
    if consecutive_fails >= 2:
        s.close()
        time.sleep(0.5)
        s = socket.socket()
        s.settimeout(3)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((HOST, PORT))
        consecutive_fails = 0
    else:
        # Drain stale data
        s.setblocking(False)
        try: s.recv(4096)
        except: pass
        s.setblocking(True)
        s.settimeout(3)
    
    try:
        t0 = time.perf_counter()
        r = send_recv(s, [0x00, 0x04])
        dt = (time.perf_counter() - t0) * 1000
        if r[0] == 0:
            ok += 1
            times.append(dt)
            consecutive_fails = 0
        else:
            fail += 1
            consecutive_fails += 1
            print(f"  Cmd {i}: bad response {r.hex()}")
    except Exception as e:
        fail += 1
        consecutive_fails += 1
        print(f"  Cmd {i}: {e}")

s.close()
avg_t = sum(times) / len(times) if times else 0
print(f"DAP_Info x{N}: OK={ok} FAIL={fail} rate={ok*100//(ok+fail)}% avg={avg_t:.0f}ms")
