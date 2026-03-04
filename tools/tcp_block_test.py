"""Direct TCP test: send DAP_TransferBlock to read exact word counts."""
import socket, struct, time, sys

HOST = "192.168.227.100"
PORT = 6000  # OpenOCD DAP TCP

DAP_SIG = b'\x44\x41\x50\x00'
DAP_REQ = 0x01
DAP_RSP = 0x02

def send_dap(sock, cmd, timeout=5.0):
    """Send a DAP command via OpenOCD TCP protocol and receive response."""
    # Build header: [sig 4B][len 2B LE][type 1B][rsv 1B]
    hdr = DAP_SIG + struct.pack('<HBB', len(cmd), DAP_REQ, 0)
    sock.sendall(hdr + bytes(cmd))
    
    # Read response header
    sock.settimeout(timeout)
    rsp_hdr = b''
    while len(rsp_hdr) < 8:
        chunk = sock.recv(8 - len(rsp_hdr))
        if not chunk: return None
        rsp_hdr += chunk
    
    sig = rsp_hdr[:4]
    if sig != DAP_SIG:
        print(f"  BAD SIG: {rsp_hdr.hex()}")
        return None
    
    rsp_len = struct.unpack_from('<H', rsp_hdr, 4)[0]
    rsp_type = rsp_hdr[6]
    
    # Read response data
    data = b''
    while len(data) < rsp_len:
        chunk = sock.recv(rsp_len - len(data))
        if not chunk: break
        data += chunk
    
    return data

def main():
    s = socket.socket()
    s.settimeout(5)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.connect((HOST, PORT))
    print(f"Connected to {HOST}:{PORT}")
    
    # DAP_Info: Product Name
    r = send_dap(s, [0x00, 0x02])
    if r: print(f"  Product: {r[1:1+r[1]].decode('ascii', errors='replace') if r[1]>0 else 'N/A'}")
    
    # DAP_Info: MAX_PACKET_SIZE
    r = send_dap(s, [0x00, 0xFF])
    if r and len(r) >= 3:
        pkt_size = struct.unpack_from('<H', r, 2)[0] if r[1] == 2 else 0
        print(f"  MAX_PACKET_SIZE: {pkt_size}")
    
    # DAP_Connect(SWD)
    r = send_dap(s, [0x02, 0x01])
    print(f"  Connect: port={r[1] if r else 'fail'}")
    
    # DAP_SWJ_Clock(1MHz)
    r = send_dap(s, [0x11] + list(struct.pack('<I', 1000000)))
    print(f"  Clock: {'OK' if r and r[1]==0 else 'FAIL'}")
    
    # SWD configure
    r = send_dap(s, [0x13, 0x00])
    print(f"  SWDcfg: {'OK' if r and r[1]==0 else 'FAIL'}")
    
    # JTAG-to-SWD sequence
    send_dap(s, [0x12, 0xFF] + [0xFF]*32)
    send_dap(s, [0x12, 16, 0x9E, 0xE7])
    send_dap(s, [0x12, 0xFF] + [0xFF]*32)
    send_dap(s, [0x12, 8, 0x00])
    print("  SWJ sequences sent")
    
    # Read DPIDR
    r = send_dap(s, [0x05, 0x00, 0x01, 0x02])
    if r and len(r) >= 7 and r[2] == 0x01:
        dpidr = struct.unpack_from('<I', r, 3)[0]
        print(f"  DPIDR: 0x{dpidr:08X}")
    else:
        print(f"  DPIDR: FAIL {r.hex() if r else 'None'}")
        s.close(); return
    
    # Power up: CTRL/STAT = 0x50000000
    send_dap(s, [0x05, 0x00, 0x01, 0x04] + list(struct.pack('<I', 0x50000000)))
    time.sleep(0.1)
    
    # SELECT = 0 (AP0, bank0)
    send_dap(s, [0x05, 0x00, 0x01, 0x08] + list(struct.pack('<I', 0x00000000)))
    
    # CSW = 0x23000012 (32-bit, auto-inc)
    send_dap(s, [0x05, 0x00, 0x01, 0x01] + list(struct.pack('<I', 0x23000012)))
    print("  AHB-AP configured")
    
    # Now test DAP_TransferBlock reads of increasing sizes
    # TAR = address, then TransferBlock read DRW
    def read_block(addr, nwords):
        """Send TAR write + TransferBlock read."""
        # Write TAR via DAP_Transfer
        tar_cmd = [0x05, 0x00, 0x01, 0x05] + list(struct.pack('<I', addr))
        r = send_dap(s, tar_cmd)
        if not r or r[2] != 0x01:
            return None, "TAR write failed"
        
        # DAP_TransferBlock: read DRW
        # [0x06][DAP_index=0][count_lo][count_hi][request=0x0F (AP read DRW)]
        tb_cmd = [0x06, 0x00] + list(struct.pack('<H', nwords)) + [0x0F]
        t0 = time.perf_counter()
        r = send_dap(s, tb_cmd, timeout=10)
        dt = (time.perf_counter() - t0) * 1000
        
        if not r:
            return None, f"No response ({dt:.0f}ms)"
        
        cmd_byte = r[0]
        if cmd_byte != 0x06:
            return None, f"MISMATCH: got cmd=0x{cmd_byte:02X} expected 0x06 ({dt:.0f}ms), resp={r[:8].hex()}"
        
        count = struct.unpack_from('<H', r, 1)[0]
        status = r[3]
        
        if status != 0x01:
            return None, f"status=0x{status:02X} count={count} ({dt:.0f}ms)"
        
        return count, f"OK count={count} ({dt:.0f}ms)"
    
    print(f"\n{'='*50}")
    print("  Sequential DAP_TransferBlock read test")
    print(f"{'='*50}")
    
    # Test: multiple sequential TransferBlock reads
    addr = 0x08000000
    for i in range(10):
        nwords = 64  # small batch
        count, msg = read_block(addr + i * nwords * 4, nwords)
        status = "OK" if count else "FAIL"
        print(f"  Block {i}: {nwords}w @ 0x{addr + i*nwords*4:08X}  {status}  {msg}")
        if count is None:
            break
    
    print(f"\n{'='*50}")
    print("  Single large TransferBlock test")
    print(f"{'='*50}")
    
    # Test: single large TransferBlock (127 words = max for 512-byte packet)
    count, msg = read_block(0x08000000, 127)
    print(f"  127 words: {msg}")
    
    count, msg = read_block(0x08000000, 100)
    print(f"  100 words: {msg}")
    
    count, msg = read_block(0x08000000, 64)
    print(f"   64 words: {msg}")
    
    # Disconnect
    send_dap(s, [0x03])
    s.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
