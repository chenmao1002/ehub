#!/usr/bin/env python3
"""
Direct CMSIS-DAP over TCP test — bypass OpenOCD entirely.
Sends raw DAP commands and checks responses.

Protocol: OpenOCD cmsis-dap tcp
  Request:  [4B sig 44 41 50 00][2B LE len][1B type=0x01][1B rsv=0x00][payload]
  Response: [4B sig 44 41 50 00][2B LE len][1B type=0x02][1B rsv=0x00][payload]
"""
import socket
import struct
import sys
import time

HOST = "ehub.local"
PORT = 6000
TIMEOUT = 3.0

DAP_SIG = b'DAP\x00'
DAP_TYPE_REQ = 0x01
DAP_TYPE_RSP = 0x02

# CMSIS-DAP command IDs
ID_DAP_Info            = 0x00
ID_DAP_HostStatus      = 0x01
ID_DAP_Connect         = 0x02
ID_DAP_Disconnect      = 0x03
ID_DAP_TransferConfigure = 0x04
ID_DAP_Transfer        = 0x05
ID_DAP_SWJ_Pins        = 0x10
ID_DAP_SWJ_Clock       = 0x11
ID_DAP_SWJ_Sequence    = 0x12
ID_DAP_SWD_Configure   = 0x13

# DAP_Info IDs
INFO_VENDOR     = 0x01
INFO_PRODUCT    = 0x02
INFO_SER_NUM    = 0x03
INFO_FW_VER     = 0x04
INFO_CAPABILITIES = 0xF0
INFO_PACKET_CNT = 0xFE
INFO_PACKET_SZ  = 0xFF

def make_request(payload: bytes) -> bytes:
    """Build an OpenOCD-protocol DAP TCP request."""
    hdr = DAP_SIG + struct.pack('<HBB', len(payload), DAP_TYPE_REQ, 0x00)
    return hdr + payload

def recv_response(sock: socket.socket) -> bytes:
    """Read one complete DAP TCP response. Returns payload bytes."""
    hdr = b''
    while len(hdr) < 8:
        chunk = sock.recv(8 - len(hdr))
        if not chunk:
            raise ConnectionError("Connection closed during header read")
        hdr += chunk
    sig = hdr[:4]
    plen, ptype, _ = struct.unpack('<HBB', hdr[4:8])
    if sig != DAP_SIG:
        raise ValueError(f"Bad signature: {sig.hex()}")
    if ptype != DAP_TYPE_RSP:
        raise ValueError(f"Bad type: {ptype:#x} (expected {DAP_TYPE_RSP:#x})")
    data = b''
    while len(data) < plen:
        chunk = sock.recv(plen - len(data))
        if not chunk:
            raise ConnectionError("Connection closed during payload read")
        data += chunk
    return data

def dap_cmd(sock, payload, label=""):
    """Send a DAP command and get the response."""
    cmd_id = payload[0]
    sock.sendall(make_request(payload))
    t0 = time.time()
    resp = recv_response(sock)
    dt = (time.time() - t0) * 1000
    resp_id = resp[0] if resp else 0xFF
    ok = resp_id == cmd_id
    status = "OK" if ok else "MISMATCH"
    print(f"  [{status}] {label:30s} sent=0x{cmd_id:02X} recv=0x{resp_id:02X}  "
          f"len={len(resp):3d}  {dt:6.1f}ms  data={resp[:16].hex()}")
    return resp, ok

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Connecting to {host}:{port} ...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.connect((host, port))
    print("Connected.\n")

    errors = 0
    total = 0

    # 1. DAP_Info queries
    for info_id, name in [
        (INFO_FW_VER,      "DAP_Info FW_VER"),
        (INFO_VENDOR,      "DAP_Info VENDOR"),
        (INFO_PRODUCT,     "DAP_Info PRODUCT"),
        (INFO_CAPABILITIES,"DAP_Info CAPABILITIES"),
        (INFO_PACKET_SZ,   "DAP_Info PACKET_SIZE"),
        (INFO_PACKET_CNT,  "DAP_Info PACKET_COUNT"),
    ]:
        total += 1
        resp, ok = dap_cmd(sock, bytes([ID_DAP_Info, info_id]), name)
        if not ok:
            errors += 1
        if ok and resp[1] > 0:
            info_data = resp[2:2+resp[1]]
            if info_id in (INFO_PACKET_SZ,):
                val = struct.unpack('<H', info_data[:2])[0]
                print(f"         → Packet size = {val}")
            elif info_id in (INFO_PACKET_CNT,):
                print(f"         → Packet count = {info_data[0]}")
            elif info_id == INFO_CAPABILITIES:
                print(f"         → Caps = {info_data.hex()}")
            else:
                try:
                    print(f"         → \"{info_data.decode('utf-8', errors='replace')}\"")
                except:
                    print(f"         → {info_data.hex()}")

    # 2. DAP_HostStatus (LED)
    total += 1
    resp, ok = dap_cmd(sock, bytes([ID_DAP_HostStatus, 0x00, 0x01]), "DAP_HostStatus (connect)")
    if not ok: errors += 1

    # 3. DAP_Connect (SWD)
    total += 1
    resp, ok = dap_cmd(sock, bytes([ID_DAP_Connect, 0x01]), "DAP_Connect (SWD)")
    if not ok: errors += 1
    if ok:
        port_mode = resp[1] if len(resp) > 1 else 0
        print(f"         → Port = {port_mode} ({'SWD' if port_mode==1 else 'JTAG' if port_mode==2 else 'Failed'})")

    # 4. DAP_TransferConfigure
    total += 1
    resp, ok = dap_cmd(sock, bytes([ID_DAP_TransferConfigure, 0x00, 0x50, 0x00, 0x00, 0x00]),
                       "DAP_TransferConfigure")
    if not ok: errors += 1

    # 5. DAP_SWD_Configure
    total += 1
    resp, ok = dap_cmd(sock, bytes([ID_DAP_SWD_Configure, 0x00]), "DAP_SWD_Configure")
    if not ok: errors += 1

    # 6. DAP_SWJ_Clock (100kHz)
    total += 1
    freq = 100000
    resp, ok = dap_cmd(sock, bytes([ID_DAP_SWJ_Clock]) + struct.pack('<I', freq),
                       f"DAP_SWJ_Clock ({freq//1000}kHz)")
    if not ok: errors += 1

    # 7. DAP_SWJ_Sequence (JTAG-to-SWD switch: >50 TMS=1, then 16-bit JTAG-to-SWD pattern 0xE79E)
    total += 1
    # 56 bits all-1 + 16 bits 0xE79E + 56 bits all-1 + 8 bits all-0
    swj_data = bytes([0xFF]*7) + bytes([0x9E, 0xE7]) + bytes([0xFF]*7) + bytes([0x00])
    resp, ok = dap_cmd(sock, bytes([ID_DAP_SWJ_Sequence, len(swj_data)*8]) + swj_data,
                       "DAP_SWJ_Sequence (JTAG→SWD)")
    if not ok: errors += 1

    # 8. Read DPIDR via DAP_Transfer
    total += 1
    # Read DP register 0 (DPIDR): AP_nDP=0, RnW=1, A[3:2]=0 → cmd byte = 0x02
    resp, ok = dap_cmd(sock, bytes([ID_DAP_Transfer, 0x00, 0x01, 0x02]),
                       "DAP_Transfer (Read DPIDR)")
    if not ok: errors += 1
    if ok and len(resp) >= 7:
        count = resp[1]
        status_val = resp[2]
        dpidr = struct.unpack('<I', resp[3:7])[0]
        print(f"         → Count={count} Status=0x{status_val:02X} DPIDR=0x{dpidr:08X}")

    # 9. DAP_Disconnect
    total += 1
    resp, ok = dap_cmd(sock, bytes([ID_DAP_Disconnect]), "DAP_Disconnect")
    if not ok: errors += 1

    sock.close()
    print(f"\n{'='*60}")
    print(f"Results: {total - errors}/{total} passed, {errors} failed")
    return 1 if errors > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
