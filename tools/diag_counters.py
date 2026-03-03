"""
Diagnostic: send DAP command via port 6000, then query debug counters via port 5000.
Shows exactly where the data path breaks.
"""
import socket, struct, time

HOST = "ehub.local"

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data) if data else "(none)"

def calc_crc(ch, length, data):
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data: crc ^= b
    return crc & 0xFF

def build_frame(ch, data):
    length = len(data)
    frame = bytearray([0xAA, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF])
    frame.extend(data)
    frame.append(calc_crc(ch, length, data))
    return bytes(frame)

def query_debug_counters():
    """Send subcmd 0xF0 to WiFi ctrl via bridge TCP and parse response"""
    sock = socket.create_connection((HOST, 5000), timeout=5)
    frame = build_frame(0xE0, bytes([0xF0]))
    sock.sendall(frame)
    sock.settimeout(3)
    try:
        resp = sock.recv(512)
        # Parse bridge frame response: [BB 55 E0 LEN_H LEN_L DATA CRC]
        if len(resp) > 6 and resp[0] == 0xBB and resp[1] == 0x55 and resp[2] == 0xE0:
            data_len = (resp[3] << 8) | resp[4]
            data = resp[5:5+data_len]
            if data[0] == 0xF0 and len(data) >= 49:
                pos = 1
                dap_tcp_read   = struct.unpack_from('<I', data, pos)[0]; pos += 4
                dap_uart_tx    = struct.unpack_from('<I', data, pos)[0]; pos += 4
                dap_uart_rx    = struct.unpack_from('<I', data, pos)[0]; pos += 4
                dap_tcp_send   = struct.unpack_from('<I', data, pos)[0]; pos += 4
                dap_timeout    = struct.unpack_from('<I', data, pos)[0]; pos += 4
                uart_bytes_rx  = struct.unpack_from('<I', data, pos)[0]; pos += 4
                uart_frames_rx = struct.unpack_from('<I', data, pos)[0]; pos += 4
                last_cmd_len   = struct.unpack_from('<H', data, pos)[0]; pos += 2
                last_cmd        = data[pos:pos+8]; pos += 8
                last_bridge_len = struct.unpack_from('<H', data, pos)[0]; pos += 2
                last_bridge     = data[pos:pos+16]; pos += 16
                
                print(f"  --- Debug Counters ---")
                print(f"  DAP TCP Read:    {dap_tcp_read}")
                print(f"  DAP UART TX:     {dap_uart_tx}")
                print(f"  DAP UART RX:     {dap_uart_rx}")
                print(f"  DAP TCP Send:    {dap_tcp_send}")
                print(f"  DAP Timeouts:    {dap_timeout}")
                print(f"  UART Bytes RX:   {uart_bytes_rx}")
                print(f"  UART Frames RX:  {uart_frames_rx}")
                print(f"  Last DAP cmd ({last_cmd_len}B): {hexdump(last_cmd[:last_cmd_len] if last_cmd_len <= 8 else last_cmd)}")
                print(f"  Last Bridge TX ({last_bridge_len}B): {hexdump(last_bridge[:min(last_bridge_len, 16)])}")
                return True
            else:
                print(f"  Unexpected response: {hexdump(data)}")
        else:
            print(f"  Raw response: {hexdump(resp)}")
    except socket.timeout:
        print(f"  Debug query TIMEOUT — subcmd 0xF0 not supported?")
    finally:
        sock.close()
    return False

# Step 1: Query initial counters
print("=== Step 1: Initial counters ===")
time.sleep(5)  # Wait for ESP32 boot
query_debug_counters()

# Step 2: Send one DAP command via port 6000
print(f"\n=== Step 2: Send DAP_Info(PacketCount) via port 6000 ===")
try:
    sock = socket.create_connection((HOST, 6000), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"  Connected to port 6000")
    
    cmd = bytes([0x00, 0xFE])
    header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
    print(f"  TX: {hexdump(header + cmd)}")
    sock.sendall(header + cmd)
    
    sock.settimeout(5)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print(f"  RX: TIMEOUT")
    
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")

# Step 3: Query counters after DAP command
print(f"\n=== Step 3: Counters after DAP command ===")
time.sleep(0.5)
query_debug_counters()

# Step 4: Try elaphureLink path
print(f"\n=== Step 4: Send DAP via elaphureLink (port 3240) ===")
try:
    sock = socket.create_connection((HOST, 3240), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("  Connected to port 3240")
    
    # Handshake
    req_hs = struct.pack('>III', 0x8a656c70, 0x00000000, 0x00000001)
    sock.sendall(req_hs)
    sock.settimeout(3)
    try:
        resp = sock.recv(256)
        print(f"  Handshake RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print(f"  Handshake TIMEOUT")
        sock.close()
        raise SystemExit(1)
    
    time.sleep(0.1)
    
    # DAP_Info(PacketCount) raw
    cmd = bytes([0x00, 0xFE])
    print(f"  TX DAP: {hexdump(cmd)}")
    sock.sendall(cmd)
    
    sock.settimeout(5)
    try:
        resp = sock.recv(512)
        print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print(f"  RX: TIMEOUT")
    
    sock.close()
except Exception as e:
    print(f"  ERROR: {e}")

# Step 5: Final counters
print(f"\n=== Step 5: Final counters ===")
time.sleep(0.5)
query_debug_counters()
