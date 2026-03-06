"""
elaphureLink 内存读取测试 - 精简版
测试通过 elaphureLink 协议能否读取 STM32F103 的 flash/SRAM
"""
import socket
import struct
import time
import sys

HOST = "192.168.227.100"
PORT = 3240
TIMEOUT = 10

def send_recv(sock, data, label="", timeout=TIMEOUT):
    """发送命令并接收响应"""
    sock.settimeout(timeout)
    # drain any stale data
    sock.setblocking(False)
    try:
        while True:
            sock.recv(4096)
    except:
        pass
    sock.setblocking(True)
    sock.settimeout(timeout)
    
    sock.sendall(data)
    try:
        resp = sock.recv(4096)
        if label:
            print(f"  [{label}] TX({len(data)}B) RX({len(resp)}B): {resp[:32].hex()}")
        return resp
    except socket.timeout:
        if label:
            print(f"  [{label}] TX({len(data)}B) TIMEOUT ({timeout}s)")
        return None

def dap_transfer(sock, dap_index, transfers, label=""):
    """
    DAP_Transfer command (0x05)
    transfers: list of (APnDP, RnW, A32, data_for_write)
    Returns (count, response, data_list)
    """
    buf = bytearray([0x05, dap_index, len(transfers)])
    for apndp, rnw, a32, wdata in transfers:
        req_byte = (apndp & 1) | ((rnw & 1) << 1) | ((a32 & 3) << 2)
        buf.append(req_byte)
        if rnw == 0:  # write
            buf.extend(struct.pack('<I', wdata))
    
    resp = send_recv(sock, bytes(buf), label)
    if resp is None:
        return None, None, []
    
    if len(resp) < 3:
        print(f"  [{label}] Short response: {resp.hex()}")
        return None, None, []
    
    count = resp[1]
    ack = resp[2]
    data_list = []
    offset = 3
    for i in range(count):
        apndp, rnw, a32, _ = transfers[i]
        if rnw == 1:  # read
            if offset + 4 <= len(resp):
                val = struct.unpack_from('<I', resp, offset)[0]
                data_list.append(val)
                offset += 4
            else:
                data_list.append(None)
    
    return count, ack, data_list

def main():
    print(f"=== elaphureLink 内存读取测试 ===")
    print(f"目标: {HOST}:{PORT}")
    
    # 1. Connect + Handshake
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((HOST, PORT))
    except Exception as e:
        print(f"连接失败: {e}")
        return
    
    print("\n[1] elaphureLink 握手")
    # Binary handshake: [4B identifier 0x8a656c70][4B cmd=0][4B version]
    handshake = bytes([
        0x8a, 0x65, 0x6c, 0x70,  # elaphureLink identifier
        0x00, 0x00, 0x00, 0x00,  # command: handshake
        0x01, 0x00, 0x00, 0x00   # client version: 1
    ])
    resp = send_recv(sock, handshake, "Handshake", 5)
    if not resp or len(resp) < 12:
        print(f"  握手失败! resp={resp}")
        sock.close()
        return
    # Expected response: 0x8a656c70 + cmd=0 + fw_version
    if resp[0:4] == bytes([0x8a, 0x65, 0x6c, 0x70]):
        fw_ver = struct.unpack_from('<I', resp, 8)[0]
        print(f"  握手成功! FW Version: {fw_ver >> 8}.{(fw_ver >> 4) & 0xF}.{fw_ver & 0xF}")
    else:
        print(f"  握手响应异常: {resp.hex()}")
        sock.close()
        return
    
    time.sleep(0.1)
    
    # 2. DAP_Connect SWD
    print("\n[2] DAP_Connect SWD")
    resp = send_recv(sock, bytes([0x02, 0x01]), "Connect", 5)
    if not resp or resp[1] != 0x01:
        print(f"  Connect 失败!")
        sock.close()
        return
    print(f"  SWD 连接成功")
    
    # 3. DAP_SWJ_Clock 1MHz
    print("\n[3] DAP_SWJ_Clock 1MHz")
    resp = send_recv(sock, bytes([0x11]) + struct.pack('<I', 1000000), "Clock", 5)
    if not resp or resp[1] != 0x00:
        print(f"  Clock设置失败!")
    else:
        print(f"  SWJ Clock = 1MHz OK")
    
    # 4. DAP_SWD_Configure (turnaround=1, data_phase=0)
    print("\n[4] DAP_SWD_Configure")
    resp = send_recv(sock, bytes([0x13, 0x00]), "SWD_Cfg", 5)
    print(f"  SWD_Configure OK")
    
    # 5. DAP_SWJ_Sequence: JTAG-to-SWD switch
    print("\n[5] SWJ Sequence (JTAG→SWD)")
    seq = bytes([0x12, 51,  # 51 bits
                 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  # 56 bits of 1s (send 51)
                 ])
    # Actually: standard JTAG-to-SWD: >50 high, 0xE79E, >50 high, >8 low
    jtag_to_swd = bytearray([0x12])
    bits = []
    # 56 bits high
    bits.extend([0xFF] * 7)
    # 16-bit SWD selection: 0x6DB7 (bit-reversed of 0xE79E)
    bits.extend([0x9E, 0xE7])
    # 56 bits high  
    bits.extend([0xFF] * 7)
    # 8 bits low
    bits.append(0x00)
    total_bits = 56 + 16 + 56 + 8  # = 136
    jtag_to_swd.append(total_bits)
    jtag_to_swd.extend(bits)
    resp = send_recv(sock, bytes(jtag_to_swd), "SWJ_Seq", 5)
    print(f"  SWJ Sequence OK")
    
    time.sleep(0.1)
    
    # 6. Read DPIDR
    print("\n[6] Read DPIDR (DP, Read, A=0x00)")
    count, ack, data = dap_transfer(sock, 0, [
        (0, 1, 0, 0),  # DP Read DPIDR (A[3:2]=0)
    ], "DPIDR")
    if count and data:
        print(f"  DPIDR = 0x{data[0]:08X}  (期望 0x1BA01477)")
        if data[0] != 0x1BA01477:
            print("  ⚠ DPIDR 不匹配，SWD通信可能有问题")
            sock.close()
            return
    else:
        print(f"  DPIDR 读取失败! count={count}, ack={ack}")
        sock.close()
        return
    
    # 7. Power up debug
    print("\n[7] 上电调试域")
    # Write CTRL/STAT: CSYSPWRUPREQ | CDBGPWRUPREQ
    count, ack, _ = dap_transfer(sock, 0, [
        (0, 0, 1, 0x50000000),  # DP Write CTRL/STAT (A[3:2]=1)
    ], "PwrUp")
    print(f"  写 CTRL/STAT = 0x50000000, count={count}, ack={ack}")
    
    time.sleep(0.2)
    
    # Read CTRL/STAT
    count, ack, data = dap_transfer(sock, 0, [
        (0, 1, 1, 0),  # DP Read CTRL/STAT (A[3:2]=1)
    ], "ReadCStat")
    if data:
        print(f"  CTRL/STAT = 0x{data[0]:08X}")
        if data[0] & 0xA0000000 != 0xA0000000:
            print("  ⚠ 调试域未完全上电")
    
    # 8. Select AP0, bank 0
    print("\n[8] SELECT AP0 Bank0")
    count, ack, _ = dap_transfer(sock, 0, [
        (0, 0, 2, 0x00000000),  # DP Write SELECT (A[3:2]=2): AP0, bank0
    ], "Select")
    print(f"  SELECT = 0x00000000, count={count}, ack={ack}")
    
    # 9. Write AP CSW: 32-bit access, auto-increment
    print("\n[9] AP CSW = 32-bit, auto-inc")
    count, ack, _ = dap_transfer(sock, 0, [
        (1, 0, 0, 0x23000052),  # AP Write CSW (A[3:2]=0): Size=Word, AddrInc=Single
    ], "CSW")
    print(f"  AP CSW write, count={count}, ack={ack}")
    
    # 10. Write AP TAR = 0x08000000 (flash start)
    print("\n[10] AP TAR = 0x08000000")
    count, ack, _ = dap_transfer(sock, 0, [
        (1, 0, 1, 0x08000000),  # AP Write TAR (A[3:2]=1)
    ], "TAR")
    print(f"  AP TAR write, count={count}, ack={ack}")
    
    # 11. Read single DRW (one word from flash)
    print("\n[11] ★ AP DRW 读取 (1 word)")
    count, ack, data = dap_transfer(sock, 0, [
        (1, 1, 3, 0),  # AP Read DRW (A[3:2]=3) - single read
    ], "DRW_1")
    if count is None:
        print(f"  ⛔ TIMEOUT! AP DRW 读取超时")
    elif count == 0:
        print(f"  ⚠ count=0, ack={ack} — SWD应答失败")
    else:
        if data:
            print(f"  DRW[0] = 0x{data[0]:08X}  count={count}, ack={ack}")
        else:
            print(f"  count={count}, ack={ack}, 但无数据")
    
    # 12. Read RDBUFF (get the actual posted read result)
    print("\n[12] DP RDBUFF")
    count, ack, data = dap_transfer(sock, 0, [
        (0, 1, 3, 0),  # DP Read RDBUFF (A[3:2]=3)
    ], "RDBUFF")
    if data:
        print(f"  RDBUFF = 0x{data[0]:08X}")
    else:
        print(f"  RDBUFF: count={count}, ack={ack}")
    
    # 13. Multi-word read test (4 words)
    print("\n[13] ★ 多字读取 (4 words from 0x08000000)")
    # Re-write TAR
    dap_transfer(sock, 0, [(1, 0, 1, 0x08000000)], "TAR2")
    
    count, ack, data = dap_transfer(sock, 0, [
        (1, 1, 3, 0),  # AP Read DRW
        (1, 1, 3, 0),  # AP Read DRW
        (1, 1, 3, 0),  # AP Read DRW
        (1, 1, 3, 0),  # AP Read DRW
    ], "DRW_4")
    if count is None:
        print(f"  ⛔ TIMEOUT!")
    elif count > 0 and data:
        for i, val in enumerate(data):
            if val is not None:
                print(f"  DRW[{i}] = 0x{val:08X}")
            else:
                print(f"  DRW[{i}] = None")
        print(f"  count={count}, ack={ack}")
    else:
        print(f"  count={count}, ack={ack}, data={data}")
    
    # 14. 速度测试: 大量读取
    if count and count > 0:
        print("\n[14] ★ 速度测试: 读取 flash")
        BLOCK_SIZE = 16  # 每次传输读 16 words = 64 bytes
        BLOCKS = 64       # 64 次 = 4096 bytes 总共
        
        total_bytes = 0
        t0 = time.time()
        
        for blk in range(BLOCKS):
            addr = 0x08000000 + blk * BLOCK_SIZE * 4
            # Write TAR
            dap_transfer(sock, 0, [(1, 0, 1, addr)], "")
            # Read DRW x BLOCK_SIZE
            reads = [(1, 1, 3, 0)] * BLOCK_SIZE
            cnt, a, d = dap_transfer(sock, 0, reads, "")
            if cnt and cnt > 0:
                total_bytes += cnt * 4
            else:
                print(f"  块 {blk} 读取失败: count={cnt}, ack={a}")
                break
        
        t1 = time.time()
        dt = t1 - t0
        if total_bytes > 0:
            speed_kbps = (total_bytes * 8) / dt / 1000
            print(f"  读取 {total_bytes} bytes / {dt:.3f}s = {speed_kbps:.1f} kbit/s = {total_bytes/dt/1024:.1f} KB/s")
        else:
            print(f"  无数据读取成功")
    else:
        print("\n[14] ⏩ 跳过速度测试 (DRW 读取未成功)")
    
    sock.close()
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    main()
