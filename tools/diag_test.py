#!/usr/bin/env python3
"""
Diagnose UART bridge reliability by checking ESP32 debug counters.
Uses TCP bridge port 5000 with subcommand 0xF0 to read ESP32 debug stats.
"""
import socket, struct, time

ESP32_HOST = '192.168.227.100'
DAP_PORT = 6000
BRIDGE_PORT = 5000
SIG = 0x00504144

# Bridge protocol constants
SOF0_CMD = 0xAA
SOF0_RPY = 0xBB
SOF1     = 0x55
CH_WIFI_CTRL = 0xE0

def build_bridge_frame(sof0, ch, data):
    """Build a bridge protocol frame."""
    crc = ch ^ (len(data) >> 8) ^ (len(data) & 0xFF)
    for b in data:
        crc ^= b
    return bytes([sof0, SOF1, ch, len(data) >> 8, len(data) & 0xFF]) + bytes(data) + bytes([crc & 0xFF])

def parse_bridge_frames(raw):
    """Parse bridge frames from raw bytes, return list of (ch, data)."""
    frames = []
    i = 0
    while i < len(raw) - 5:
        if raw[i] in (SOF0_CMD, SOF0_RPY) and raw[i+1] == SOF1:
            ch = raw[i+2]
            length = (raw[i+3] << 8) | raw[i+4]
            if i + 5 + length + 1 <= len(raw):
                data = raw[i+5:i+5+length]
                crc_expect = ch ^ raw[i+3] ^ raw[i+4]
                for b in data:
                    crc_expect ^= b
                crc_actual = raw[i+5+length]
                if (crc_expect & 0xFF) == crc_actual:
                    frames.append((ch, data))
                    i += 5 + length + 1
                    continue
        i += 1
    return frames

def send_dap_tcp(s, cmd):
    """Send DAP command over TCP protocol, return response or None on timeout."""
    hdr = struct.pack('<IHBb', SIG, len(cmd), 1, 0)
    s.sendall(hdr + bytes(cmd))
    h = b''
    while len(h) < 8:
        chunk = s.recv(8 - len(h))
        if not chunk: return None
        h += chunk
    _, L, _, _ = struct.unpack('<IHBb', h)
    d = b''
    while len(d) < L:
        chunk = s.recv(L - len(d))
        if not chunk: return None
        d += chunk
    return d

def get_esp32_diag(bridge_sock):
    """Query ESP32 debug counters via bridge port 5000."""
    frame = build_bridge_frame(SOF0_CMD, CH_WIFI_CTRL, [0xF0])
    bridge_sock.sendall(frame)
    time.sleep(0.3)
    raw = b''
    try:
        while True:
            chunk = bridge_sock.recv(4096)
            if not chunk: break
            raw += chunk
    except: pass
    
    frames = parse_bridge_frames(raw)
    for ch, data in frames:
        if ch == CH_WIFI_CTRL and len(data) >= 31 and data[0] == 0xF0:
            pos = 1
            counters = {}
            names = ['dapTcpRead', 'dapUartTx', 'dapUartRx', 'dapTcpSend', 
                     'dapTimeout', 'uartBytesRx', 'uartFramesRx']
            for name in names:
                counters[name] = struct.unpack_from('<I', data, pos)[0]
                pos += 4
            return counters
    return None

def main():
    # 1. Connect bridge port for diagnostics
    bs = socket.socket()
    bs.settimeout(2)
    bs.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    bs.connect((ESP32_HOST, BRIDGE_PORT))
    
    # 2. Get initial counters
    print("=== ESP32 Debug Counters (before test) ===")
    c_before = get_esp32_diag(bs)
    if c_before:
        for k, v in c_before.items():
            print(f"  {k:15s}: {v}")
    else:
        print("  Failed to read counters")
    
    bs.close()
    time.sleep(0.5)
    
    # 3. Run DAP test
    print(f"\n=== Sending 30 DAP_Info commands ===")
    ds = socket.socket()
    ds.settimeout(3)
    ds.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    ds.connect((ESP32_HOST, DAP_PORT))
    
    ok = 0
    fail = 0
    for i in range(30):
        time.sleep(0.05)
        ds.setblocking(False)
        try: ds.recv(4096)
        except: pass
        ds.setblocking(True)
        ds.settimeout(3)
        try:
            r = send_dap_tcp(ds, [0x00, 0x04])
            if r and r[0] == 0:
                ok += 1
            else:
                fail += 1
                print(f"  Cmd {i}: bad {r.hex() if r else 'None'}")
        except Exception as e:
            fail += 1
            print(f"  Cmd {i}: {e}")
    
    ds.close()
    print(f"  Result: OK={ok} FAIL={fail}")
    
    # 4. Get final counters
    time.sleep(1)
    bs2 = socket.socket()
    bs2.settimeout(2)
    bs2.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    bs2.connect((ESP32_HOST, BRIDGE_PORT))
    
    print(f"\n=== ESP32 Debug Counters (after test) ===")
    c_after = get_esp32_diag(bs2)
    if c_after:
        for k, v in c_after.items():
            print(f"  {k:15s}: {v}")
        if c_before:
            print(f"\n=== Delta ===")
            for k in c_before:
                delta = c_after.get(k, 0) - c_before.get(k, 0)
                print(f"  {k:15s}: +{delta}")
            print(f"\n  Expected: dapTcpRead=+30, dapUartTx=+30, dapUartRx=+{ok}, dapTcpSend=+{ok}, dapTimeout=+{fail}")
    else:
        print("  Failed to read counters")
    
    bs2.close()

if __name__ == '__main__':
    main()
