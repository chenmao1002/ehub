#!/usr/bin/env python3
"""Direct DAP TCP protocol test — bypasses OpenOCD to debug bridge."""
import socket, struct, time

HOST = '192.168.227.100'
PORT = 6000
SIG = 0x00504144  # DAP TCP signature 'DAP\0' little-endian

def send_dap_tcp(s, cmd):
    """Send one DAP command over OpenOCD TCP protocol, return response bytes."""
    hdr = struct.pack('<IHBb', SIG, len(cmd), 1, 0)  # type=1=REQ
    s.sendall(hdr + bytes(cmd))
    # Read 8-byte response header
    h = b''
    while len(h) < 8:
        chunk = s.recv(8 - len(h))
        if not chunk:
            raise ConnectionError("TCP closed during header read")
        h += chunk
    sig, length, ptype, _ = struct.unpack('<IHBb', h)
    if sig != SIG:
        print(f"  !! Bad sig: 0x{sig:08X}")
    # Read response data
    d = b''
    while len(d) < length:
        chunk = s.recv(length - len(d))
        if not chunk:
            raise ConnectionError("TCP closed during data read")
        d += chunk
    return d

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.connect((HOST, PORT))
    print(f"Connected to {HOST}:{PORT}")

    tests = [
        ("DAP_Info(FW)",     [0x00, 0x04]),
        ("DAP_Info(Caps)",   [0x00, 0xF0]),
        ("DAP_Info(PktSz)",  [0x00, 0xFF]),
        ("DAP_Info(PktCnt)", [0x00, 0xFE]),
        ("DAP_Connect(SWD)", [0x02, 0x01]),
        ("DAP_SWJ_Clock(1M)", [0x11, 0x40, 0x42, 0x0F, 0x00]),
        ("DAP_SWD_Config",   [0x13, 0x00]),
        ("DAP_SWJ_Seq(51)",  [0x12, 51, 0xFF,0xFF,0xFF,0xFF,0xFF,0xFF, 0x03]),
        ("DAP_SWJ_Seq(16)",  [0x12, 16, 0x9E, 0xE7]),
        ("DAP_SWJ_Seq(51)",  [0x12, 51, 0xFF,0xFF,0xFF,0xFF,0xFF,0xFF, 0x03]),
        ("DAP_SWJ_Seq(8)",   [0x12, 8, 0x00]),
        ("DAP_Transfer(DPIDR)", [0x05, 0x00, 0x01, 0x02]),
        ("DAP_Disconnect",   [0x03]),
    ]

    for name, cmd in tests:
        time.sleep(0.05)  # Small gap between commands
        try:
            # Drain any stale data first
            s.setblocking(False)
            try:
                stale = s.recv(4096)
                if stale:
                    print(f"  !! STALE DATA ({len(stale)}B): {stale[:32].hex()}")
            except BlockingIOError:
                pass
            s.setblocking(True)
            s.settimeout(10.0)
            
            t0 = time.perf_counter()
            r = send_dap_tcp(s, cmd)
            dt = (time.perf_counter() - t0) * 1000
            # Interpret
            detail = ""
            if cmd[0] == 0x05 and len(r) >= 7 and r[2] == 0x01:
                val = struct.unpack_from('<I', r, 3)[0]
                detail = f" → 0x{val:08X}"
            elif cmd[0] == 0x00 and len(r) >= 2:
                info_len = r[1]
                if info_len > 0 and len(r) >= 2 + info_len:
                    detail = f" → {r[2:2+info_len]}"
            print(f"  {name:25s}: [{r.hex()}] {dt:6.1f}ms{detail}")
        except Exception as e:
            print(f"  {name:25s}: ERROR {e}")

    s.close()
    print("Done")

if __name__ == '__main__':
    main()
