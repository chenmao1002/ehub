"""Quick test - new 8-byte header only, fresh connection"""
import socket, struct, time

HOST = "ehub.local"
PORT = 6000

# Fresh connection
sock = socket.create_connection((HOST, PORT), timeout=5)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
print(f"Connected to {HOST}:{PORT}")

# DAP_Info: Get Packet Count (0x00, 0xFE)
cmd = bytes([0x00, 0xFE])
# 8-byte header: signature(4) + length(2) + type(1) + reserved(1)
header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
payload = header + cmd
print(f"TX ({len(payload)} bytes): {payload.hex()}")
sock.sendall(payload)

# Wait a bit then try to receive
time.sleep(2)
sock.settimeout(3)
try:
    data = sock.recv(512)
    print(f"RX ({len(data)} bytes): {data.hex()}")
except socket.timeout:
    print("RX: TIMEOUT - no response")

# Try raw read to see if anything comes later
time.sleep(1)
try:
    data = sock.recv(512)
    print(f"RX2 ({len(data)} bytes): {data.hex()}")
except socket.timeout:
    print("RX2: TIMEOUT")

sock.close()

# Also test port 3240 for elaphureLink
print(f"\n--- Testing port 3240 (elaphureLink) ---")
try:
    sock2 = socket.create_connection((HOST, 3240), timeout=5)
    print(f"Connected to {HOST}:3240")
    # Send elaphureLink handshake
    hs = bytes([0x8a, 0x65, 0x6c, 0x61, 0x70, 0x68, 0x75, 0x72, 0x00, 0x00, 0x00, 0x00])
    print(f"TX handshake: {hs.hex()}")
    sock2.sendall(hs)
    sock2.settimeout(3)
    try:
        data = sock2.recv(256)
        print(f"RX ({len(data)} bytes): {data.hex()}")
    except socket.timeout:
        print("RX: TIMEOUT")
    sock2.close()
except Exception as e:
    print(f"Connection failed: {e}")

# Also try port 5000 (bridge TCP) to verify ESP32 is up
print(f"\n--- Testing port 5000 (bridge TCP) ---")
try:
    sock3 = socket.create_connection((HOST, 5000), timeout=5)
    print(f"Connected to {HOST}:5000 - ESP32 bridge is alive")
    sock3.close()
except Exception as e:
    print(f"Connection failed: {e}")
