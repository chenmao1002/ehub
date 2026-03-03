"""
Focused diagnostic: test DAP TCP path with timing info.
Connect to port 6000, send one DAP command, measure response time.
"""
import socket, struct, time, sys

HOST = "ehub.local"

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data) if data else "(none)"

def test_openocd_dap():
    """Send one DAP_Info command via port 6000 with detailed timing"""
    print(f"=== OpenOCD DAP Test (port 6000) ===")
    
    sock = socket.create_connection((HOST, 6000), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"  Connected! Local port: {sock.getsockname()[1]}")
    
    # Wait a bit for ESP32 to process the new connection
    time.sleep(0.5)
    
    # Check if there's any initial data from ESP32
    sock.settimeout(0.5)
    try:
        init_data = sock.recv(512)
        print(f"  Initial data: {hexdump(init_data)}")
    except socket.timeout:
        print(f"  No initial data (expected)")
    
    # Send DAP_Info(PacketCount) with OpenOCD 8-byte header
    cmd = bytes([0x00, 0xFE])
    header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
    payload = header + cmd
    
    print(f"  TX: {hexdump(payload)}")
    t0 = time.time()
    sock.sendall(payload)
    
    # Try to read response with increasing timeouts
    for timeout in [0.5, 1.0, 2.0, 5.0]:
        sock.settimeout(timeout)
        try:
            resp = sock.recv(512)
            elapsed = time.time() - t0
            print(f"  RX ({len(resp)}B, {elapsed*1000:.0f}ms): {hexdump(resp)}")
            
            if len(resp) >= 8:
                sig, plen, ptype = struct.unpack_from('<IHBx', resp, 0)
                print(f"  Header: sig=0x{sig:08x} len={plen} type=0x{ptype:02x}")
                if len(resp) > 8:
                    dap_resp = resp[8:]
                    print(f"  DAP: {hexdump(dap_resp)}")
                    if len(dap_resp) >= 3 and dap_resp[0] == 0x00:
                        print(f"  → PacketCount: {dap_resp[2]}")
            sock.close()
            return True
        except socket.timeout:
            elapsed = time.time() - t0
            print(f"  ... no response after {elapsed*1000:.0f}ms")
    
    # Final attempt: just read any bytes
    print(f"  Sending another command...")
    cmd2 = bytes([0x00, 0x01])  # DAP_Info(Vendor)
    header2 = struct.pack('<IHBx', 0x00504144, len(cmd2), 0x01)
    sock.sendall(header2 + cmd2)
    
    sock.settimeout(5)
    try:
        resp = sock.recv(512)
        print(f"  RX2 ({len(resp)}B): {hexdump(resp)}")
    except socket.timeout:
        print(f"  RX2: TIMEOUT")
    
    sock.close()
    return False

def test_raw_uart_loopback():
    """Send a WiFi status query via bridge TCP — this is handled by ESP32 locally"""
    print(f"\n=== WiFi Status (ESP32-local, port 5000) ===")
    
    sock = socket.create_connection((HOST, 5000), timeout=5)
    print(f"  Connected to port 5000")
    
    # WiFi status: CH=0xE0, subcmd=0x01
    ch = 0xE0
    data = bytes([0x01])
    length = len(data)
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data: crc ^= b
    frame = bytes([0xAA, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF]) + data + bytes([crc & 0xFF])
    
    print(f"  TX: {hexdump(frame)}")
    t0 = time.time()
    sock.sendall(frame)
    
    sock.settimeout(3)
    try:
        resp = sock.recv(512)
        elapsed = time.time() - t0
        print(f"  RX ({len(resp)}B, {elapsed*1000:.0f}ms): {hexdump(resp)}")
        # Parse: SOF0=BB, SOF1=55, CH=E0, LEN_H, LEN_L, DATA, CRC
        if len(resp) > 6 and resp[0] == 0xBB and resp[1] == 0x55:
            ch_rx = resp[2]
            data_len = (resp[3] << 8) | resp[4]
            print(f"  CH=0x{ch_rx:02x}, data_len={data_len}")
            if data_len >= 7 and resp[5] == 0x01:
                status = resp[6]
                rssi = resp[7] if resp[7] < 128 else resp[7] - 256
                ip = f"{resp[8]}.{resp[9]}.{resp[10]}.{resp[11]}"
                print(f"  WiFi status={status}, RSSI={rssi}dBm, IP={ip}")
    except socket.timeout:
        print(f"  RX: TIMEOUT")
    
    sock.close()

if __name__ == "__main__":
    test_raw_uart_loopback()
    print()
    test_openocd_dap()
