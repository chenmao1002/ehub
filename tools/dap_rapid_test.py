"""No-delay rapid DAP command test matching exact OpenOCD init sequence"""
import socket, struct, time

HOST = "ehub.local"
PORT = 6000
SIGNATURE = 0x00504144

def build_packet(data):
    hdr = struct.pack('<IHBx', SIGNATURE, len(data), 0x01)
    return hdr + data

def recv_exact(sock, n, timeout=8.0):
    data = b''
    t0 = time.time()
    while len(data) < n:
        if time.time() - t0 > timeout:
            return None
        try:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        except socket.timeout:
            return None
    return data

def send_recv(sock, data, label):
    pkt = build_packet(data)
    t0 = time.time()
    sock.sendall(pkt)
    
    hdr = recv_exact(sock, 8, timeout=8.0)
    t1 = time.time()
    if hdr is None:
        print(f"  {label}: TIMEOUT after {(t1-t0)*1000:.0f}ms")
        return None
    
    sig, length, ptype = struct.unpack_from('<IHB', hdr)
    if sig != SIGNATURE:
        print(f"  {label}: BAD SIGNATURE 0x{sig:08X}")
        return None
    
    payload = recv_exact(sock, length, timeout=8.0)
    t2 = time.time()
    if payload is None:
        print(f"  {label}: DATA TIMEOUT after {(t2-t1)*1000:.0f}ms (expected {length}B)")
        return None
    
    print(f"  {label}: OK ({(t2-t0)*1000:.0f}ms) len={length}")
    return payload

print("Connecting to", HOST, PORT)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(8)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.connect((HOST, PORT))
print("Connected!")

# Match EXACT OpenOCD init sequence (no delays!)
# 1. Flush read (150ms timeout) — we skip this, just connect
# 2. Caps
# 3. FW Version
# 4. Serial Number
# 5. SWD Connect
# 6. PKT_SZ  ← this one fails in OpenOCD!
# 7. PKT_CNT

commands = [
    (bytes([0x00, 0xF0]), "1.Caps(0xF0)"),
    (bytes([0x00, 0x04]), "2.FW_Ver(0x04)"),
    (bytes([0x00, 0x03]), "3.Serial(0x03)"),
    (bytes([0x02, 0x01]), "4.SWD_Connect"),
    (bytes([0x00, 0xFF]), "5.PKT_SZ(0xFF)"),   # <-- OpenOCD fails here
    (bytes([0x00, 0xFE]), "6.PKT_CNT(0xFE)"),
]

# Run 3 times to check reproducibility
for run in range(3):
    print(f"\n=== Run {run+1} (no delay) ===")
    
    # Reconnect for each run
    if run > 0:
        sock.close()
        time.sleep(0.5)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(8)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.connect((HOST, PORT))
    
    all_ok = True
    for cmd_data, label in commands:
        resp = send_recv(sock, cmd_data, label)
        if resp is None:
            all_ok = False
            break
        # NO DELAY between commands!
    
    if all_ok:
        print("  All OK!")
    else:
        print("  FAILED!")

sock.close()
print("\nDone!")
