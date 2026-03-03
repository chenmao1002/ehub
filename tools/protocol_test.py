"""Quick protocol test - try both old and new header formats"""
import socket, struct

HOST = "ehub.local"
PORT = 6000

sock = socket.create_connection((HOST, PORT), timeout=5)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
print(f"Connected to {HOST}:{PORT}")

# Test 1: OLD 4-byte LE length header
cmd = bytes([0x00, 0xFE])  # DAP_Info: Get Packet Count
header_old = struct.pack('<I', len(cmd))
sock.sendall(header_old + cmd)
print(f"\nTest 1 - Old 4-byte header: {(header_old+cmd).hex()}")
sock.settimeout(3)
try:
    data = sock.recv(256)
    print(f"  Response ({len(data)} bytes): {data[:20].hex()}...")
    print(f"  >>> OLD protocol works!")
except socket.timeout:
    print(f"  No response (old protocol not active)")

# Test 2: NEW 8-byte header (signature + length + type)
cmd2 = bytes([0x00, 0xFE])
header_new = struct.pack('<IHBx', 0x00504144, len(cmd2), 0x01)
sock.sendall(header_new + cmd2)
print(f"\nTest 2 - New 8-byte header: {(header_new+cmd2).hex()}")
sock.settimeout(3)
try:
    data = sock.recv(256)
    print(f"  Response ({len(data)} bytes): {data[:20].hex()}...")
    print(f"  >>> NEW protocol works!")
except socket.timeout:
    print(f"  No response (new protocol not active)")

sock.close()
print("\nDone.")
