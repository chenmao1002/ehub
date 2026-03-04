"""
Layered DAP bridge test — isolates where the problem is.

Layer 1: TCP → ESP32 (local) — WIFI_STATUS on port 5000, no UART needed
Layer 2: TCP → ESP32 → UART → MCU → UART → ESP32 → TCP — DAP_Info via elaphureLink (3240)
Layer 3: TCP → ESP32 → UART → MCU → UART → ESP32 → TCP — DAP_Info via OpenOCD (6000)
"""
import socket, struct, time, sys

HOST = '192.168.227.100'

def build_bridge_frame(sof0, ch, data):
    """Build a bridge protocol frame"""
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data:
        crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])

def test_layer1_wifi_status():
    """Layer 1: WIFI_STATUS via port 5000 — handled locally by ESP32, no UART"""
    print("=" * 60)
    print("Layer 1: WIFI_STATUS via port 5000 (ESP32 local, no UART)")
    print("=" * 60)
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((HOST, 5000))
        # WIFI_CTRL (CH=0xE0), subcmd=0x01 (WIFI_STATUS)
        frame = build_bridge_frame(0xAA, 0xE0, bytes([0x01]))
        print(f"  TX: {frame.hex()}")
        s.send(frame)
        time.sleep(1)
        resp = s.recv(4096)
        print(f"  RX ({len(resp)}B): {resp.hex()}")
        # Parse: should be BB 55 E0 xx xx [01 status rssi ip0 ip1 ip2 ip3] CRC
        if len(resp) >= 6 and resp[0] == 0xBB and resp[2] == 0xE0:
            payload_len = (resp[3] << 8) | resp[4]
            payload = resp[5:5+payload_len]
            if payload[0] == 0x01:
                status_names = {0: 'IDLE', 1: 'CONNECTING', 2: 'CONNECTED', 3: 'AP_MODE', 4: 'ERROR'}
                st = payload[1]
                rssi = payload[2] if payload[2] < 128 else payload[2] - 256
                ip = f"{payload[3]}.{payload[4]}.{payload[5]}.{payload[6]}"
                print(f"  OK! Status={status_names.get(st, st)}, RSSI={rssi}dBm, IP={ip}")
                s.close()
                return True
        print(f"  UNEXPECTED response format")
        s.close()
        return False
    except socket.timeout:
        print("  TIMEOUT — ESP32 TCP port 5000 not responding")
        s.close()
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_layer1_counter():
    """Layer 1b: Query ESP32 debug counters (F0) via port 5000 — ESP32 local"""
    print()
    print("=" * 60)
    print("Layer 1b: ESP32 counters (F0) via port 5000 (ESP32 local)")
    print("=" * 60)
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((HOST, 5000))
        frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF0]))
        s.send(frame)
        time.sleep(0.5)
        resp = s.recv(4096)
        print(f"  RX ({len(resp)}B): {resp[:40].hex()}...")
        if len(resp) > 5 and resp[0] == 0xBB and resp[2] == 0xE0:
            payload_len = (resp[3] << 8) | resp[4]
            payload = resp[5:5+payload_len]
            if payload[0] == 0xF0 and len(payload) >= 29:
                pos = 1
                names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout',
                         'uartBytesRx','uartFramesRx']
                for name in names:
                    if pos + 4 <= len(payload):
                        val = struct.unpack('<I', payload[pos:pos+4])[0]
                        print(f"    {name:16s} = {val}")
                        pos += 4
                print(f"  OK! ESP32 counters retrieved")
                s.close()
                return True
        s.close()
        return False
    except socket.timeout:
        print("  TIMEOUT")
        s.close()
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_layer2_elaphurelink():
    """Layer 2: DAP_Info via elaphureLink port 3240 — requires full MCU round trip"""
    print()
    print("=" * 60)
    print("Layer 2: elaphureLink DAP_Info via port 3240 (MCU round trip)")
    print("=" * 60)
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((HOST, 3240))
        # Handshake
        hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x01])
        s.send(hs)
        resp = s.recv(256)
        print(f"  Handshake: {resp.hex()}")
        
        # Send DAP_Info(0x00) - Vendor ID (0x01)
        # Raw CMSIS-DAP: cmd_id=0x00, param=0x01
        s.send(bytes([0x00, 0x01]))
        
        # Wait for response with extended timeout
        s.settimeout(5)
        try:
            resp = s.recv(256)
            print(f"  DAP_Info resp ({len(resp)}B): {resp[:32].hex()}")
            if resp[0] == 0x00 and len(resp) > 2:
                slen = resp[1]
                if slen > 0:
                    vendor = resp[2:2+slen].decode('ascii', errors='replace')
                    print(f"  Vendor: '{vendor}'")
                else:
                    print(f"  (empty vendor string - but got response)")
            print(f"  OK! Full MCU round trip works")
            s.close()
            return True
        except socket.timeout:
            print("  TIMEOUT — DAP command sent but no response")
            print("  → UART MCU↔ESP32 path likely broken")
            s.close()
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_layer3_openocd():
    """Layer 3: DAP_Info via OpenOCD protocol port 6000 — requires full MCU round trip"""
    print()
    print("=" * 60)
    print("Layer 3: OpenOCD DAP_Info via port 6000 (MCU round trip)")
    print("=" * 60)
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((HOST, 6000))
        
        # OpenOCD header: [4B sig=0x00504144][2B LE len][1B type=0x01][1B rsv=0x00]
        # DAP_Info command: [0x00, 0x01]
        dap_cmd = bytes([0x00, 0x01])
        hdr = struct.pack('<IHBB', 0x00504144, len(dap_cmd), 0x01, 0x00)
        pkt = hdr + dap_cmd
        print(f"  TX: {pkt.hex()}")
        s.send(pkt)
        
        s.settimeout(5)
        try:
            resp = s.recv(1024)
            print(f"  RX ({len(resp)}B): {resp[:32].hex()}")
            if len(resp) >= 8:
                sig, rlen, rtype, _ = struct.unpack('<IHBB', resp[:8])
                print(f"  Header: sig=0x{sig:08x} len={rlen} type={rtype}")
                if len(resp) > 8:
                    dap_resp = resp[8:]
                    if dap_resp[0] == 0x00 and len(dap_resp) > 2:
                        slen = dap_resp[1]
                        if slen > 0:
                            vendor = dap_resp[2:2+slen].decode('ascii', errors='replace')
                            print(f"  Vendor: '{vendor}'")
            print(f"  OK! OpenOCD protocol works")
            s.close()
            return True
        except socket.timeout:
            print("  TIMEOUT — OpenOCD DAP command no response")
            s.close()
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

# ── Run all tests ──
print(f"Target: {HOST}")
print(f"Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
print()

r1 = test_layer1_wifi_status()
r1b = test_layer1_counter()
r2 = test_layer2_elaphurelink()
r3 = test_layer3_openocd()

print()
print("=" * 60)
print("Summary:")
print(f"  Layer 1  (TCP→ESP32 local):     {'PASS' if r1 else 'FAIL'}")
print(f"  Layer 1b (ESP32 counters):       {'PASS' if r1b else 'FAIL'}")
print(f"  Layer 2  (elaphureLink→MCU):     {'PASS' if r2 else 'FAIL'}")
print(f"  Layer 3  (OpenOCD→MCU):          {'PASS' if r3 else 'FAIL'}")
if r1 and not r2:
    print()
    print("  → TCP/WiFi OK, but UART MCU↔ESP32 path broken!")
elif r1 and r2:
    print()
    print("  → All layers working!")
elif not r1:
    print()
    print("  → ESP32 TCP server not responding — WiFi/TCP issue")
