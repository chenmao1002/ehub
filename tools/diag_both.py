"""Quick diagnostic: test both OpenOCD (port 6000) and elaphureLink (port 3240) DAP paths"""
import socket, struct, time

HOST = "ehub.local"

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data) if data else "(none)"

# ─── Test 1: OpenOCD path (port 6000) ───
print("=== Test OpenOCD path (port 6000) ===")
try:
    sock = socket.create_connection((HOST, 6000), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("  Connected!")
    
    # DAP_Info(PacketCount) with 8-byte header
    cmd = bytes([0x00, 0xFE])
    header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
    print(f"  TX: {hexdump(header + cmd)}")
    sock.sendall(header + cmd)
    
    sock.settimeout(3)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
        if len(resp) >= 8:
            sig, plen, ptype = struct.unpack_from('<IHBx', resp, 0)
            print(f"  Header: sig=0x{sig:08x} len={plen} type=0x{ptype:02x}")
            if len(resp) > 8:
                print(f"  DAP Response: {hexdump(resp[8:])}")
    except socket.timeout:
        print("  RX: TIMEOUT")
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")

print()

# ─── Test 2: elaphureLink path (port 3240) ───
print("=== Test elaphureLink path (port 3240) ===")
try:
    sock = socket.create_connection((HOST, 3240), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("  Connected!")
    
    # Handshake
    req_hs = struct.pack('>III', 0x8a656c70, 0x00000000, 0x00000001)
    print(f"  TX Handshake: {hexdump(req_hs)}")
    sock.sendall(req_hs)
    
    sock.settimeout(3)
    try:
        resp = sock.recv(256)
        print(f"  RX Handshake ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print("  RX Handshake: TIMEOUT")
        sock.close()
        raise SystemExit(1)
    
    # Wait a moment for ESP32 to be ready
    time.sleep(0.1)
    
    # DAP_Info(PacketCount) — raw, no header
    cmd = bytes([0x00, 0xFE])
    print(f"  TX DAP_Info(PacketCount): {hexdump(cmd)}")
    sock.sendall(cmd)
    
    sock.settimeout(5)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print("  RX: TIMEOUT ← DAP command not forwarded or response lost!")
        
        # Check if connection is still alive
        try:
            sock.sendall(bytes([0x00, 0x01]))  # DAP_Info(Vendor) as keepalive check
            time.sleep(0.5)
            resp2 = sock.recv(512)
            print(f"  Second attempt RX ({len(resp2)}B): {hexdump(resp2)}")
        except:
            print("  Connection appears dead")
    
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")
