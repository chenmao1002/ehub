"""
elaphureLink 内存读写速度测试 - v2
"""
import socket
import struct
import time
import sys

HOST = "192.168.227.100"
PORT = 3240
TIMEOUT = 15

class ElaphureClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
    
    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.host, self.port))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # Binary handshake
        hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00])
        self.sock.sendall(hs)
        resp = self.sock.recv(12)
        if len(resp) < 12 or resp[0:4] != bytes([0x8a, 0x65, 0x6c, 0x70]):
            raise Exception(f"Handshake failed: {resp.hex()}")
        print(f"  握手成功")
        return True
    
    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
    
    def _send_recv(self, data, timeout=TIMEOUT):
        self.sock.settimeout(timeout)
        self.sock.sendall(data)
        return self.sock.recv(4096)
    
    def dap_cmd(self, data, timeout=TIMEOUT):
        """Send raw DAP command, return response bytes"""
        return self._send_recv(data, timeout)
    
    def dap_transfer(self, transfers, dap_index=0, timeout=TIMEOUT, debug=False):
        """
        DAP_Transfer (0x05)
        transfers: list of (APnDP, RnW, A32, data_for_write)
        Returns (count, ack, data_list)
        """
        buf = bytearray([0x05, dap_index, len(transfers)])
        for apndp, rnw, a32, wdata in transfers:
            req_byte = (apndp & 1) | ((rnw & 1) << 1) | ((a32 & 3) << 2)
            buf.append(req_byte)
            if rnw == 0:
                buf.extend(struct.pack('<I', wdata))
        
        resp = self._send_recv(bytes(buf), timeout)
        
        if debug:
            print(f"    TX({len(buf)}B): {buf.hex()}")
            print(f"    RX({len(resp)}B): {resp.hex()}")
        
        if len(resp) < 3:
            return 0, 0, []
        
        count = resp[1]
        ack = resp[2]
        data_list = []
        offset = 3
        for i in range(count):
            apndp, rnw, a32, _ = transfers[i]
            if rnw == 1:
                if offset + 4 <= len(resp):
                    val = struct.unpack_from('<I', resp, offset)[0]
                    data_list.append(val)
                    offset += 4
        
        return count, ack, data_list
    
    def swd_init(self):
        """Initialize SWD: connect, clock, sequence, power up"""
        # DAP_Connect SWD
        r = self.dap_cmd(bytes([0x02, 0x01]))
        if r[1] != 0x01:
            raise Exception("DAP_Connect SWD failed")
        print(f"  SWD连接成功")
        
        # DAP_SWJ_Clock 1MHz
        self.dap_cmd(bytes([0x11]) + struct.pack('<I', 1000000))
        
        # DAP_SWD_Configure
        self.dap_cmd(bytes([0x13, 0x00]))
        
        # SWJ Sequence: JTAG-to-SWD
        seq = bytearray([0x12, 136])  # 136 bits
        seq.extend([0xFF] * 7)  # 56 high
        seq.extend([0x9E, 0xE7])  # 16-bit SWD select
        seq.extend([0xFF] * 7)  # 56 high
        seq.append(0x00)  # 8 low
        self.dap_cmd(bytes(seq))
        
        # Read DPIDR
        cnt, ack, data = self.dap_transfer([(0, 1, 0, 0)], debug=True)
        if cnt == 0 or not data:
            print(f"  DPIDR read failed: cnt={cnt}, ack={ack}, data={data}")
            # Try again after a short delay
            time.sleep(0.5)
            # Re-do SWJ sequence
            self.dap_cmd(bytes(seq))
            time.sleep(0.1)
            cnt, ack, data = self.dap_transfer([(0, 1, 0, 0)], debug=True)
            if cnt == 0 or not data:
                raise Exception(f"DPIDR read failed after retry: cnt={cnt}, ack={ack}")
        dpidr = data[0]
        print(f"  DPIDR = 0x{dpidr:08X}")
        
        # Power up debug domain
        self.dap_transfer([(0, 0, 1, 0x50000000)])  # Write CTRL/STAT
        time.sleep(0.1)
        cnt, ack, data = self.dap_transfer([(0, 1, 1, 0)])  # Read CTRL/STAT
        ctrlstat = data[0] if data else 0
        print(f"  CTRL/STAT = 0x{ctrlstat:08X}")
        
        # Select AP0 bank0
        self.dap_transfer([(0, 0, 2, 0x00000000)])
        
        # AP CSW: 32-bit, auto-increment
        self.dap_transfer([(1, 0, 0, 0x23000052)])
        
        print(f"  SWD初始化完成")
        return dpidr
    
    def read_mem_block(self, addr, word_count):
        """Read words from memory. Returns list of 32-bit values."""
        # Write TAR
        self.dap_transfer([(1, 0, 1, addr)])
        # Read DRW x word_count
        reads = [(1, 1, 3, 0)] * word_count
        cnt, ack, data = self.dap_transfer(reads)
        return data if cnt > 0 else []

def main():
    print(f"=== elaphureLink 速度测试 ===")
    print(f"目标: {HOST}:{PORT}\n")
    
    cl = ElaphureClient(HOST, PORT)
    
    try:
        # 连接 + SWD初始化
        cl.connect()
        dpidr = cl.swd_init()
        
        # 验证内存读取
        print(f"\n--- 内存读取验证 ---")
        data = cl.read_mem_block(0x08000000, 4)
        if data:
            for i, v in enumerate(data):
                print(f"  [0x{0x08000000+i*4:08X}] = 0x{v:08X}")
        else:
            print("  内存读取失败!")
            return
        
        # ============ 读速度测试 ============
        print(f"\n--- 读取速度测试 ---")
        
        # 测试不同块大小
        for words_per_block in [4, 8, 16]:
            bytes_per_block = words_per_block * 4
            total_blocks = max(1, 4096 // bytes_per_block)  # ~4KB total
            total_bytes = 0
            errors = 0
            
            t0 = time.time()
            for blk in range(total_blocks):
                addr = 0x08000000 + blk * bytes_per_block
                data = cl.read_mem_block(addr, words_per_block)
                if data:
                    total_bytes += len(data) * 4
                else:
                    errors += 1
                    if errors > 3:
                        break
            t1 = time.time()
            
            dt = t1 - t0
            if total_bytes > 0 and dt > 0:
                speed_kBs = total_bytes / dt / 1024
                print(f"  {words_per_block}W/block × {total_blocks}blocks: "
                      f"{total_bytes}B / {dt:.3f}s = {speed_kBs:.1f} KB/s "
                      f"({total_bytes*8/dt/1000:.1f} kbit/s)")
            else:
                print(f"  {words_per_block}W/block: 失败 (errors={errors})")
        
        # 大块测试: 16KB
        print(f"\n--- 16KB 大块读取测试 ---")
        WORDS_PER_BLOCK = 16
        TOTAL_BYTES_TARGET = 16384
        blocks_needed = TOTAL_BYTES_TARGET // (WORDS_PER_BLOCK * 4)
        total_bytes = 0
        
        t0 = time.time()
        for blk in range(blocks_needed):
            addr = 0x08000000 + blk * WORDS_PER_BLOCK * 4
            data = cl.read_mem_block(addr, WORDS_PER_BLOCK)
            if data:
                total_bytes += len(data) * 4
            else:
                print(f"  块 {blk} 失败")
                break
        t1 = time.time()
        dt = t1 - t0
        
        if total_bytes > 0 and dt > 0:
            speed_kBs = total_bytes / dt / 1024
            print(f"  16KB读取: {total_bytes}B / {dt:.3f}s = {speed_kBs:.1f} KB/s ({total_bytes*8/dt/1000:.1f} kbit/s)")
        
        print(f"\n=== 测试完成 ===")
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cl.close()

if __name__ == "__main__":
    main()
