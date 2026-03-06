"""
DAP Speed Test — measure flash read throughput via elaphureLink (port 3240)
Performs actual SWD memory reads from STM32F103 flash.
"""

import socket
import struct
import time
import sys

HOST = "192.168.227.100"
PORT = 3240

def hexdump(data, n=32):
    return " ".join(f"{b:02x}" for b in data[:n])

def el_connect():
    """Connect and perform elaphureLink handshake."""
    sock = socket.create_connection((HOST, PORT), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    # Handshake
    req = struct.pack('>III', 0x8a656c70, 0, 1)
    sock.sendall(req)
    sock.settimeout(3)
    res = sock.recv(256)
    if len(res) < 12 or res[:4] != b'\x8a\x65\x6c\x70':
        raise Exception("Handshake failed")
    return sock

def dap_cmd(sock, cmd_bytes, timeout=5):
    """Send DAP command and receive response."""
    sock.sendall(cmd_bytes)
    sock.settimeout(timeout)
    resp = sock.recv(1024)
    return resp

def swd_init(sock):
    """Initialize SWD connection to STM32F103.
    
    DAP_Transfer request byte encoding:
      bit 0: APnDP (0=DP, 1=AP)
      bit 1: RnW (0=Write, 1=Read)
      bit 2-3: A[3:2]
    
    DP registers: DPIDR(0x00)=0b00, CTRL/STAT(0x04)=0b01, SELECT(0x08)=0b10, RDBUFF(0x0C)=0b11
    AP registers: CSW(0x00)=0b00, TAR(0x04)=0b01, DRW(0x0C)=0b11
    """
    DP_W_CTRLSTAT = 0x04   # DP write CTRL/STAT: APnDP=0, RnW=0, A[3:2]=0b01
    DP_R_CTRLSTAT = 0x06   # DP read  CTRL/STAT: APnDP=0, RnW=1, A[3:2]=0b01
    DP_R_DPIDR    = 0x02   # DP read  DPIDR:     APnDP=0, RnW=1, A[3:2]=0b00
    DP_W_SELECT   = 0x08   # DP write SELECT:    APnDP=0, RnW=0, A[3:2]=0b10
    AP_W_CSW      = 0x01   # AP write CSW:       APnDP=1, RnW=0, A[3:2]=0b00
    AP_W_TAR      = 0x05   # AP write TAR:       APnDP=1, RnW=0, A[3:2]=0b01
    AP_R_DRW      = 0x0F   # AP read  DRW:       APnDP=1, RnW=1, A[3:2]=0b11
    
    # DAP_Connect(SWD)
    resp = dap_cmd(sock, bytes([0x02, 0x01]))
    if resp[1] != 0x01:
        raise Exception(f"DAP_Connect failed: {hexdump(resp)}")
    
    # DAP_SWJ_Clock(1MHz)
    resp = dap_cmd(sock, bytes([0x11]) + struct.pack('<I', 1000000))
    if resp[1] != 0x00:
        raise Exception(f"SWJ_Clock failed: {hexdump(resp)}")
    
    # DAP_SWJ_Sequence — JTAG-to-SWD switch (ARM standard)
    switch_seq = bytes([0xFF]*7 + [0x9E, 0xE7] + [0xFF]*7 + [0x00])
    resp = dap_cmd(sock, bytes([0x12, len(switch_seq)*8 & 0xFF]) + switch_seq)
    
    # Read DPIDR
    resp = dap_cmd(sock, bytes([0x05, 0x00, 0x01, DP_R_DPIDR]))
    if len(resp) >= 7:
        dpidr = struct.unpack_from('<I', resp, 3)[0]
        print(f"  DPIDR: 0x{dpidr:08X}")
        if dpidr == 0x1BA01477:
            print(f"  → STM32F103 Cortex-M3 detected!")
    else:
        print(f"  DPIDR read failed: {hexdump(resp)}")
        return False
    
    # Power up debug: Write CTRL/STAT = 0x50000000
    val = struct.pack('<I', 0x50000000)
    resp = dap_cmd(sock, bytes([0x05, 0x00, 0x01, DP_W_CTRLSTAT]) + val)
    
    # Read back CTRL/STAT
    time.sleep(0.05)
    resp = dap_cmd(sock, bytes([0x05, 0x00, 0x01, DP_R_CTRLSTAT]))
    if len(resp) >= 7:
        ctrl_stat = struct.unpack_from('<I', resp, 3)[0]
        print(f"  CTRL/STAT: 0x{ctrl_stat:08X}")
        if ctrl_stat & 0xA0000000 == 0xA0000000:
            print(f"  → Debug powered up!")
    
    # Select AP 0, bank 0
    val = struct.pack('<I', 0x00000000)
    resp = dap_cmd(sock, bytes([0x05, 0x00, 0x01, DP_W_SELECT]) + val)
    
    # Configure AP CSW: 32-bit access, auto-increment
    csw_val = struct.pack('<I', 0x23000012)
    resp = dap_cmd(sock, bytes([0x05, 0x00, 0x01, AP_W_CSW]) + csw_val)
    
    return True

def swd_read_block(sock, addr, word_count):
    """Read a block of words from target memory via DAP_Transfer."""
    # Write TAR (AP reg 0x04): AP write, A[3:2]=0b01 → APnDP=1, RnW=0, A=0x04 → 0x05
    tar_val = struct.pack('<I', addr)
    
    # Read DRW (AP reg 0x0C): AP read, A[3:2]=0b11 → APnDP=1, RnW=1, A=0x0C → 0x0F
    # Use Transfer command to write TAR then read N words from DRW
    
    # Build DAP_Transfer command: write TAR + read DRW * word_count
    # Max words per packet: (PacketSize - 3 - 5) / 4 ≈ (512 - 8) / 4 = 126
    # But we also need space in request: 3 header + 1 (TAR write req) + 4 (TAR val) + N (DRW read req)
    # So max N = min(word_count, 126)
    
    cmd = bytearray([0x05, 0x00])  # DAP_Transfer, DAP_Index=0
    transfer_count = 1 + word_count  # 1 TAR write + N DRW reads
    cmd.append(transfer_count & 0xFF)
    
    # Write TAR
    cmd.append(0x05)  # AP write, A[3:2]=0b01
    cmd.extend(tar_val)
    
    # Read DRW word_count times
    for _ in range(word_count):
        cmd.append(0x0F)  # AP read, A[3:2]=0b11
    
    resp = dap_cmd(sock, bytes(cmd), timeout=10)
    
    if resp is None or len(resp) < 3:
        return None
    
    count = resp[1]
    last_resp = resp[2]
    
    if last_resp != 0x01:  # ACK OK
        return None
    
    # Response data: starts at offset 3, each word is 4 bytes
    data = resp[3:]
    words = []
    for i in range(0, min(len(data), word_count * 4), 4):
        if i + 4 <= len(data):
            words.append(struct.unpack_from('<I', data, i)[0])
    
    return words

def main():
    print("=" * 60)
    print("  DAP Speed Test — elaphureLink (port 3240)")
    print("=" * 60)
    
    # Connect
    print("\n--- Connecting ---")
    sock = el_connect()
    print("  Connected & handshake OK")
    
    # Init SWD
    print("\n--- SWD Init ---")
    if not swd_init(sock):
        print("  SWD init failed!")
        sock.close()
        return 1
    
    # Read first 32 bytes of flash to verify
    print("\n--- Verify Flash Read ---")
    words = swd_read_block(sock, 0x08000000, 8)
    if words:
        print(f"  Flash @ 0x08000000: " + " ".join(f"{w:08X}" for w in words[:4]))
        if words[0] == 0x20000E98 or (words[0] & 0xFF000000) == 0x20000000:
            print(f"  → Valid vector table detected! (SP=0x{words[0]:08X}, Reset=0x{words[1]:08X})")
    else:
        print("  Flash read failed!")
        # Try single word reads
        print("  Trying single-word read...")
        words = swd_read_block(sock, 0x08000000, 1)
        if words:
            print(f"  Single word: 0x{words[0]:08X}")
        else:
            print("  Single read also failed!")
            sock.close()
            return 1
    
    # Speed test — read 2KB block multiple times
    print("\n--- Speed Test: Read 2KB blocks ---")
    test_sizes = [8, 32, 64]  # words per transfer
    
    for words_per_xfer in test_sizes:
        block_size = 2048  # bytes
        words_total = block_size // 4
        iterations = words_total // words_per_xfer
        
        t0 = time.time()
        bytes_read = 0
        errors = 0
        
        for i in range(iterations):
            addr = 0x08000000 + i * words_per_xfer * 4
            result = swd_read_block(sock, addr, words_per_xfer)
            if result:
                bytes_read += len(result) * 4
            else:
                errors += 1
        
        elapsed = time.time() - t0
        speed_bps = (bytes_read * 8) / elapsed if elapsed > 0 else 0
        
        print(f"  {words_per_xfer} words/xfer: {bytes_read}B in {elapsed:.3f}s "
              f"= {speed_bps/1000:.1f} kbit/s ({errors} errors)")
    
    # Disconnect
    dap_cmd(sock, bytes([0x03]))  # DAP_Disconnect
    sock.close()
    
    print(f"\n{'=' * 60}")
    print(f"  Test Complete!")
    print(f"{'=' * 60}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
