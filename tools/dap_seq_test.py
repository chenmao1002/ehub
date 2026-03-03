"""Detailed sequential DAP command test with timing"""
import socket, struct, time, sys

HOST = "ehub.local"
PORT = 6000
SIGNATURE = 0x00504144

def build_packet(data: bytes) -> bytes:
    hdr = struct.pack('<IHBx', SIGNATURE, len(data), 0x01)
    return hdr + data

def recv_exact(sock, n, timeout=5.0):
    """Receive exactly n bytes with timeout"""
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

def send_recv(sock, data: bytes, label: str):
    pkt = build_packet(data)
    t0 = time.time()
    print(f"\n[{time.time():.3f}] === {label} ===")
    print(f"  TX ({len(pkt)}B): {pkt.hex()}")
    sock.sendall(pkt)
    t_sent = time.time()
    print(f"  Sent in {(t_sent-t0)*1000:.1f}ms")
    
    # Read 8-byte header
    hdr = recv_exact(sock, 8, timeout=5.0)
    t_hdr = time.time()
    if hdr is None:
        print(f"  TIMEOUT reading header after {(t_hdr-t_sent)*1000:.0f}ms")
        # Try to read whatever is available
        sock.setblocking(False)
        try:
            leftover = sock.recv(256)
            print(f"  Leftover data: {leftover.hex() if leftover else 'none'}")
        except:
            print(f"  No leftover data")
        sock.setblocking(True)
        sock.settimeout(5)
        return None
    
    print(f"  RX hdr ({(t_hdr-t_sent)*1000:.1f}ms): {hdr.hex()}")
    
    sig, length, ptype = struct.unpack_from('<IHB', hdr)
    if sig != SIGNATURE:
        print(f"  ERROR: Bad signature 0x{sig:08X}")
        return None
    
    print(f"    sig=0x{sig:08X} len={length} type=0x{ptype:02X}")
    
    # Read payload
    payload = recv_exact(sock, length, timeout=5.0)
    t_data = time.time()
    if payload is None:
        print(f"  TIMEOUT reading {length}B payload after {(t_data-t_hdr)*1000:.0f}ms")
        return None
    
    print(f"  RX data ({(t_data-t_hdr)*1000:.1f}ms, {length}B): {payload[:20].hex()}{'...' if length>20 else ''}")
    print(f"  Total round-trip: {(t_data-t0)*1000:.1f}ms")
    return payload

# Connect
print(f"Connecting to {HOST}:{PORT}...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.connect((HOST, PORT))
print(f"Connected!")

# Test sequence matching OpenOCD init
commands = [
    (bytes([0x00, 0xF0]), "1. DAP_Info Capabilities"),
    (bytes([0x00, 0x04]), "2. DAP_Info FW Version"),
    (bytes([0x00, 0x03]), "3. DAP_Info Serial Number"),
    (bytes([0x00, 0xFF]), "4. DAP_Info Packet Size"),
    (bytes([0x00, 0xFE]), "5. DAP_Info Packet Count"),
    (bytes([0x02, 0x01]), "6. DAP_Connect SWD"),
]

for cmd_data, label in commands:
    resp = send_recv(sock, cmd_data, label)
    if resp is None:
        print(f"\n*** FAILED at: {label} ***")
        break
    # Small delay between commands (like OpenOCD would have)
    time.sleep(0.01)

sock.close()
print(f"\n[{time.time():.3f}] Done!")
