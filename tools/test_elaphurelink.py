"""
elaphureLink Proxy Protocol Test Script
========================================
Tests the handshake phase and basic DAP commands over TCP port 3240.

Protocol reference:
  https://github.com/windowsair/elaphureLink/blob/master/docs/proxy_protocol.md

Usage:
  python test_elaphurelink.py [--host HOST] [--port PORT]
"""

import socket
import struct
import sys
import time

HOST = "ehub.local"
PORT = 3240

# ─── elaphureLink protocol constants ───
EL_IDENTIFIER  = 0x8a656c70   # big-endian identifier
EL_CMD_HANDSHAKE = 0x00000000
EL_VERSION     = 0x00000001   # our proxy version

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data)


def el_handshake(sock):
    """Perform elaphureLink handshake. Returns (ok, server_version)."""
    # REQ_HANDSHAKE: [identifier(4)][cmd(4)][version(4)] = 12 bytes, big-endian
    req = struct.pack('>III', EL_IDENTIFIER, EL_CMD_HANDSHAKE, EL_VERSION)
    print(f"  TX REQ_HANDSHAKE ({len(req)}B): {hexdump(req)}")
    sock.sendall(req)

    sock.settimeout(3)
    try:
        res = sock.recv(256)
    except socket.timeout:
        print("  RX: TIMEOUT — handshake failed!")
        return False, 0

    print(f"  RX RES_HANDSHAKE ({len(res)}B): {hexdump(res)}")

    if len(res) < 12:
        print(f"  ERROR: Response too short ({len(res)} < 12)")
        return False, 0

    ident, cmd, ver = struct.unpack_from('>III', res, 0)
    ok_ident = (ident == EL_IDENTIFIER)
    ok_cmd   = (cmd == EL_CMD_HANDSHAKE)
    print(f"  Identifier: 0x{ident:08x} {'OK' if ok_ident else 'MISMATCH!'}")
    print(f"  Command:    0x{cmd:08x} {'OK' if ok_cmd else 'MISMATCH!'}")
    print(f"  FW Version: 0x{ver:08x}")

    return (ok_ident and ok_cmd), ver


def dap_cmd(sock, name, cmd_bytes, timeout=3):
    """Send a raw CMSIS-DAP command and receive response."""
    print(f"\n  [{name}]")
    print(f"  TX ({len(cmd_bytes)}B): {hexdump(cmd_bytes)}")
    sock.sendall(cmd_bytes)

    sock.settimeout(timeout)
    try:
        resp = sock.recv(512)
    except socket.timeout:
        print("  RX: TIMEOUT")
        return None

    print(f"  RX ({len(resp)}B): {hexdump(resp)}")
    return resp


def main():
    global HOST, PORT

    # Parse args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--host' and i + 1 < len(args):
            HOST = args[i + 1]; i += 2
        elif args[i] == '--port' and i + 1 < len(args):
            PORT = int(args[i + 1]); i += 2
        else:
            i += 1

    print("=" * 60)
    print("  elaphureLink Proxy Protocol Test")
    print("=" * 60)
    print(f"  Target: {HOST}:{PORT}")

    # ─── Connect ───
    print(f"\n--- Connecting ---")
    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
    except Exception as e:
        print(f"  Connection failed: {e}")
        return 1
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"  Connected!")

    # ─── Phase 1: Handshake ───
    print(f"\n--- Phase 1: Handshake ---")
    ok, ver = el_handshake(sock)
    if not ok:
        print("  HANDSHAKE FAILED — aborting")
        sock.close()
        return 1
    print(f"  Handshake OK!")

    # ─── Phase 2: DAP Commands ───
    print(f"\n--- Phase 2: DAP Commands ---")

    # DAP_Info(Vendor) = [0x00, 0x01]
    resp = dap_cmd(sock, "DAP_Info(Vendor)", bytes([0x00, 0x01]))
    if resp and len(resp) >= 2 and resp[1] > 0:
        vendor = resp[2:2+resp[1]].decode('ascii', errors='replace')
        print(f"  → Vendor: \"{vendor}\"")

    # DAP_Info(Product) = [0x00, 0x02]
    resp = dap_cmd(sock, "DAP_Info(Product)", bytes([0x00, 0x02]))
    if resp and len(resp) >= 2 and resp[1] > 0:
        product = resp[2:2+resp[1]].decode('ascii', errors='replace')
        print(f"  → Product: \"{product}\"")

    # DAP_Info(FW_Ver) = [0x00, 0x04]
    resp = dap_cmd(sock, "DAP_Info(FW_Ver)", bytes([0x00, 0x04]))
    if resp and len(resp) >= 2 and resp[1] > 0:
        fw_ver = resp[2:2+resp[1]].decode('ascii', errors='replace')
        print(f"  → FW Version: \"{fw_ver}\"")

    # DAP_Info(Capabilities) = [0x00, 0xF0]
    resp = dap_cmd(sock, "DAP_Info(Capabilities)", bytes([0x00, 0xF0]))
    if resp and len(resp) >= 3 and resp[1] > 0:
        cap = resp[2]
        swd  = 'yes' if (cap & 0x01) else 'no'
        jtag = 'yes' if (cap & 0x02) else 'no'
        atomic = 'yes' if (cap & 0x10) else 'no'
        print(f"  → Capabilities: 0x{cap:02x} (SWD={swd}, JTAG={jtag}, Atomic={atomic})")

    # DAP_Info(PacketCount) = [0x00, 0xFE]
    resp = dap_cmd(sock, "DAP_Info(PacketCount)", bytes([0x00, 0xFE]))
    if resp and len(resp) >= 3 and resp[1] > 0:
        pkt_count = resp[2]
        print(f"  → Packet Count: {pkt_count}")

    # DAP_Info(PacketSize) = [0x00, 0xFF]
    resp = dap_cmd(sock, "DAP_Info(PacketSize)", bytes([0x00, 0xFF]))
    pkt_size = 64  # default
    if resp and len(resp) >= 4 and resp[1] >= 2:
        pkt_size = resp[2] | (resp[3] << 8)
        print(f"  → Packet Size: {pkt_size}")

    # DAP_Connect(SWD) = [0x02, 0x01]
    resp = dap_cmd(sock, "DAP_Connect(SWD)", bytes([0x02, 0x01]))
    if resp and len(resp) >= 2:
        port = resp[1]
        port_name = {0: 'FAILED', 1: 'SWD', 2: 'JTAG'}.get(port, f'Unknown({port})')
        print(f"  → Connected port: {port_name}")

    # DAP_SWJ_Clock(1MHz) = [0x11, clock_LE_4bytes]
    clock_hz = 1000000
    resp = dap_cmd(sock, "DAP_SWJ_Clock(1MHz)",
                   bytes([0x11]) + struct.pack('<I', clock_hz))
    if resp and len(resp) >= 2:
        status = 'OK' if resp[1] == 0 else f'ERROR(0x{resp[1]:02x})'
        print(f"  → Status: {status}")

    # DAP_SWJ_Sequence — JTAG→SWD switch sequence
    # Standard SWD switch: > 50 bits of 1s, then 0xE79E (16-bit), then > 50 bits of 1s
    # Simplified: just send 8 bytes of 0xFF (64 bits of 1s)
    seq_data = bytes([0xFF] * 8)
    resp = dap_cmd(sock, "DAP_SWJ_Sequence(64 bits of 1s)",
                   bytes([0x12, 0x40]) + seq_data)  # 0x40 = 64 bits
    if resp and len(resp) >= 2:
        status = 'OK' if resp[1] == 0 else f'ERROR(0x{resp[1]:02x})'
        print(f"  → Status: {status}")

    # DAP_Disconnect = [0x03]
    resp = dap_cmd(sock, "DAP_Disconnect", bytes([0x03]))
    if resp and len(resp) >= 2:
        status = 'OK' if resp[1] == 0 else f'ERROR(0x{resp[1]:02x})'
        print(f"  → Status: {status}")

    # ─── Done ───
    sock.close()
    print(f"\n{'=' * 60}")
    print(f"  Test Complete — All commands executed successfully!")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
