"""Test specific DAP_Info commands to OpenOCD TCP protocol"""
import socket, struct, time

HOST = "ehub.local"
PORT = 6000
SIGNATURE = 0x00504144  # "DAP\0" LE

def build_packet(data: bytes) -> bytes:
    """Build 8-byte header + payload"""
    hdr = struct.pack('<IHBx', SIGNATURE, len(data), 0x01)
    return hdr + data

def send_recv(sock, data: bytes, label: str) -> bytes:
    pkt = build_packet(data)
    print(f"\n--- {label} ---")
    print(f"  TX: {pkt.hex()}")
    sock.sendall(pkt)
    
    # Read 8-byte header
    hdr = b''
    while len(hdr) < 8:
        hdr += sock.recv(8 - len(hdr))
    
    sig, length, ptype = struct.unpack_from('<IHB', hdr)
    print(f"  RX hdr: sig=0x{sig:08X} len={length} type=0x{ptype:02X}")
    
    if sig != SIGNATURE:
        print(f"  ERROR: Bad signature!")
        return b''
    
    # Read payload
    payload = b''
    while len(payload) < length:
        payload += sock.recv(length - len(payload))
    
    print(f"  RX payload ({length}B): {payload[:32].hex()}")
    return payload

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect((HOST, PORT))
print(f"Connected to {HOST}:{PORT}")

# DAP_Info(0xF0) - Capabilities
resp = send_recv(sock, bytes([0x00, 0xF0]), "DAP_Info Capabilities (0xF0)")
if resp and resp[0] == 0x00:
    print(f"  CMD=0x{resp[0]:02X}, info_len={resp[1]}, data={resp[2:2+resp[1]].hex() if resp[1]>0 else 'none'}")

# DAP_Info(0x04) - FW Version
resp = send_recv(sock, bytes([0x00, 0x04]), "DAP_Info FW Version (0x04)")
if resp and resp[0] == 0x00:
    slen = resp[1]
    print(f"  CMD=0x{resp[0]:02X}, strlen={slen}, str='{resp[2:2+slen].decode('ascii','replace') if slen>0 else ''}'")

# DAP_Info(0x03) - Serial Number (THE ONE THAT FAILS)
t0 = time.time()
resp = send_recv(sock, bytes([0x00, 0x03]), "DAP_Info Serial (0x03)")
t1 = time.time()
print(f"  Time: {(t1-t0)*1000:.0f}ms")
if resp and resp[0] == 0x00:
    slen = resp[1]
    print(f"  CMD=0x{resp[0]:02X}, strlen={slen}")

# DAP_Info(0xFF) - Packet Size
resp = send_recv(sock, bytes([0x00, 0xFF]), "DAP_Info Packet Size (0xFF)")
if resp and resp[0] == 0x00:
    if resp[1] == 2:
        pkt_sz = resp[2] | (resp[3] << 8)
        print(f"  Packet Size = {pkt_sz}")

# DAP_Info(0xFE) - Packet Count
resp = send_recv(sock, bytes([0x00, 0xFE]), "DAP_Info Packet Count (0xFE)")
if resp and resp[0] == 0x00:
    if resp[1] == 1:
        print(f"  Packet Count = {resp[2]}")

# DAP_SWJ_Pins / SWD connect test
resp = send_recv(sock, bytes([0x02, 0x01]), "DAP_Connect SWD (0x02)")
if resp and resp[0] == 0x02:
    print(f"  Mode = {resp[1]} (1=SWD, 2=JTAG)")

# DAP_SWJ_Clock = 1MHz
clk = struct.pack('<I', 1000000)
resp = send_recv(sock, bytes([0x11]) + clk, "DAP_SWJ_Clock 1MHz (0x11)")
if resp and resp[0] == 0x11:
    print(f"  Status = {'OK' if resp[1]==0 else 'FAIL'}")

# DAP_SWD_Configure
resp = send_recv(sock, bytes([0x13, 0x00]), "DAP_SWD_Configure (0x13)")
if resp and resp[0] == 0x13:
    print(f"  Status = {'OK' if resp[1]==0 else 'FAIL'}")

# DAP_Transfer - read DPIDR
resp = send_recv(sock, bytes([0x05, 0x00, 0x01, 0x02]), "DAP_Transfer Read DPIDR (0x05)")
if resp and resp[0] == 0x05:
    count = resp[1]
    status = resp[2]
    print(f"  Count={count}, Status=0x{status:02X}")
    if count > 0 and len(resp) >= 7:
        dpidr = struct.unpack_from('<I', resp, 3)[0]
        print(f"  DPIDR = 0x{dpidr:08X}")

sock.close()
print("\nDone!")
