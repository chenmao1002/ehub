"""Quick DAP test via elaphureLink (port 3240) and bridge (port 5000)"""
import socket, struct, time, sys

HOST = '192.168.227.100'

def test_elaphure():
    """Test DAP via elaphureLink protocol on port 3240"""
    print("[elaphureLink:3240]")
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((HOST, 3240))
        # Handshake: "elp" magic + version
        hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x01])
        s.send(hs)
        r = s.recv(256)
        print(f"  Handshake: {r.hex()}")
        
        # DAP_Info(0x00) - Get Vendor ID (0x01)
        s.send(bytes([0x00, 0x01]))
        time.sleep(1)
        r = s.recv(256)
        print(f"  DAP_Info resp ({len(r)}B): {r[:32].hex()}")
        if r[0] == 0x00 and len(r) > 2:
            slen = r[1]
            print(f"  Vendor: '{r[2:2+slen].decode('ascii', errors='replace')}'")
        s.close()
        return True
    except socket.timeout:
        print("  TIMEOUT!")
        s.close()
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_bridge():
    """Test DAP via raw bridge protocol on port 5000"""
    print("[Bridge:5000]")
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((HOST, 5000))
        # Bridge frame: SOF0=0xAA SOF1=0x55 CH=0xD0 LEN=0x0002 DATA=[0x00,0x01] CRC
        ch, data = 0xD0, bytes([0x00, 0x01])
        lh, ll = (len(data) >> 8) & 0xFF, len(data) & 0xFF
        crc = ch ^ lh ^ ll
        for b in data: crc ^= b
        frame = bytes([0xAA, 0x55, ch, lh, ll]) + data + bytes([crc])
        print(f"  Sending: {frame.hex()}")
        s.send(frame)
        time.sleep(2)
        r = s.recv(4096)
        print(f"  Response ({len(r)}B): {r[:64].hex()}")
        s.close()
        return True
    except socket.timeout:
        print("  TIMEOUT!")
        s.close()
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_heartbeat():
    """Check if ESP32 heartbeats arrive on bridge port 5000 (passive listen)"""
    print("[Heartbeat:5000]")
    s = socket.socket()
    s.settimeout(8)
    try:
        s.connect((HOST, 5000))
        # Just listen for heartbeats from ESP32
        r = s.recv(4096)
        print(f"  Received ({len(r)}B): {r[:64].hex()}")
        s.close()
        return True
    except socket.timeout:
        print("  No heartbeat received in 8s")
        s.close()
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

print("=== DAP Quick Test ===")
print()
test_heartbeat()
print()
test_elaphure()
print()
test_bridge()
