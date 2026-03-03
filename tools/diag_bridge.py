"""Test if UART bridge to MCU works by sending a raw bridge frame via TCP port 5000"""
import socket, struct, time

HOST = "ehub.local"

def calc_crc(ch, length, data):
    crc = ch
    crc ^= (length >> 8) & 0xFF
    crc ^= length & 0xFF
    for b in data:
        crc ^= b
    return crc & 0xFF

def build_bridge_frame(ch, data):
    """Build bridge frame: [SOF0=0xAA][SOF1=0x55][CH][LEN_H][LEN_L][DATA][CRC]"""
    length = len(data)
    frame = bytearray()
    frame.append(0xAA)  # SOF0_CMD
    frame.append(0x55)  # SOF1
    frame.append(ch)
    frame.append((length >> 8) & 0xFF)
    frame.append(length & 0xFF)
    frame.extend(data)
    frame.append(calc_crc(ch, length, data))
    return bytes(frame)

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data) if data else "(none)"

# Test 1: TCP bridge port 5000 — send a heartbeat (WiFi ctrl 0x10)
print("=== Test 1: Bridge TCP (port 5000) heartbeat ===")
try:
    sock = socket.create_connection((HOST, 5000), timeout=5)
    print("  Connected to port 5000")
    
    # Send WiFi control heartbeat: CH=0xE0, subcmd=0x10, counter=0x01020304
    heartbeat_data = bytes([0x10, 0x01, 0x02, 0x03, 0x04])
    frame = build_bridge_frame(0xE0, heartbeat_data)
    print(f"  TX bridge frame: {hexdump(frame)}")
    sock.sendall(frame)
    
    sock.settimeout(3)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print("  RX: TIMEOUT (heartbeat not echoed)")
    
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")

# Test 2: TCP bridge port 5000 — send a DAP command (CH=0xD0)
print("\n=== Test 2: Bridge TCP (port 5000) DAP via bridge ===")
try:
    sock = socket.create_connection((HOST, 5000), timeout=5)
    print("  Connected to port 5000")
    
    # Send DAP_Info(PacketCount): CH=0xD0, data=[0x00, 0xFE]
    dap_cmd = bytes([0x00, 0xFE])
    frame = build_bridge_frame(0xD0, dap_cmd)
    print(f"  TX bridge frame: {hexdump(frame)}")
    sock.sendall(frame)
    
    sock.settimeout(5)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print("  RX: TIMEOUT (MCU didn't respond to DAP via bridge TCP)")

    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")

# Test 3: DAP TCP port 6000
print("\n=== Test 3: DAP TCP (port 6000) ===")
try:
    sock = socket.create_connection((HOST, 6000), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("  Connected to port 6000")
    
    # DAP_Info(PacketCount) with 8-byte header
    cmd = bytes([0x00, 0xFE])
    header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
    print(f"  TX: {hexdump(header + cmd)}")
    sock.sendall(header + cmd)
    
    sock.settimeout(5)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print("  RX: TIMEOUT")
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")

# Test 4: WiFi status query
print("\n=== Test 4: Bridge TCP (port 5000) WiFi Status ===")
try:
    sock = socket.create_connection((HOST, 5000), timeout=5)
    print("  Connected to port 5000")
    
    # WiFi status query: CH=0xE0, subcmd=0x01
    status_data = bytes([0x01])
    frame = build_bridge_frame(0xE0, status_data)
    print(f"  TX: {hexdump(frame)}")
    sock.sendall(frame)
    
    sock.settimeout(3)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print("  RX: TIMEOUT")
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")
