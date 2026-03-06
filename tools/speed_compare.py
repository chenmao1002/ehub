"""
EHUB 三路速率对比测试
测量三种 CMSIS-DAP 连接方式对 STM32F407 Flash 读取的吞吐量:
  1. 有线 USB HID       (CMSIS-DAP v1, 64B 包, VID=0xC251 PID=0xF001)
  2. WiFi OpenOCD TCP  (port 6000, 8字节头 + 数据)
  3. WiFi elaphureLink (port 3240, 无帧, 最大 1048B 包)

依赖:
  pip install hid       # hidapi Python 绑定
  pip install pyusb     # (备用, 部分系统需要)
  pip install requests  # (不需要)

使用:
  python speed_compare.py [--host <ip>] [--skip-hid] [--skip-openocd] [--skip-el]
"""

import socket
import struct
import time
import sys
import argparse

# ───────────────────────────── 参数 ─────────────────────────────
WIFI_HOST        = "ehub.local"   # 或 "192.168.x.x"
OCD_PORT         = 6000
EL_PORT          = 3240
USB_VID          = 0xC251
USB_PID          = 0xF001

# 读取目标地址范围 (STM32F407 Flash)
READ_ADDR        = 0x08000000
READ_KB          = 32             # 每轮读 32KB

# ───────────────────────── TCP 辅助函数 ──────────────────────────

def tcp_connect(host, port, timeout=5):
    s = socket.create_connection((host, port), timeout=timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.settimeout(10)
    return s

def tcp_recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf

# ───────────────────── OpenOCD TCP 协议 ──────────────────────────
# 帧格式: [0x44 0x41 0x50 0x00][len_LE16][type][rsv][payload]
# type: 0x01=CMD, 0x02=RSP

OCD_SIG = b'DAP\x00'

def ocd_send(sock, payload):
    n = len(payload)
    hdr = OCD_SIG + struct.pack('<H', n) + bytes([0x01, 0x00])
    sock.sendall(hdr + bytes(payload))

def ocd_recv(sock):
    hdr = tcp_recv_exact(sock, 8)
    if hdr[:4] != OCD_SIG:
        raise ValueError(f"Bad OCD sig: {hdr.hex()}")
    n = struct.unpack_from('<H', hdr, 4)[0]
    return tcp_recv_exact(sock, n)

def ocd_cmd(sock, payload):
    ocd_send(sock, payload)
    return ocd_recv(sock)

# ─────────────────── elaphureLink 协议 ───────────────────────────

class TCPStream:
    """带残留缓冲区的 TCP 流包装，read_exact 精确读 n 字节不丢失多余数据"""
    def __init__(self, sock):
        self.sock = sock
        self._buf = b""

    def read_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("TCP connection closed")
            self._buf += chunk
        data = self._buf[:n]
        self._buf = self._buf[n:]
        return data

    def sendall(self, data):
        self.sock.sendall(data)

    def close(self):
        self.sock.close()


def el_connect(host, port):
    sock = tcp_connect(host, port)
    hs = struct.pack('>I', 0x8a656c70) + struct.pack('>II', 0, 1)
    sock.sendall(hs)
    resp = tcp_recv_exact(sock, 12)
    if resp[:4] != bytes([0x8a, 0x65, 0x6c, 0x70]):
        raise Exception(f"EL handshake failed: {resp.hex()}")
    return TCPStream(sock)


def el_cmd(stream, payload, expected=None):
    """通过 TCPStream 发送命令并精确接收响应"""
    stream.sendall(bytes(payload))
    if payload and payload[0] == 0x06:
        # DAP_TransferBlock: 先读 4 字节头部，再按 actual_count 读数据
        # 避免短响应（SWD 错误时服务器只发 4 字节）导致 read_exact(996) 死等
        hdr = stream.read_exact(4)  # [cmd_id, count_lo, count_hi, ack]
        if len(hdr) < 4 or hdr[0] != 0x06:
            return hdr
        actual_count = struct.unpack_from('<H', hdr, 1)[0]
        if actual_count > 0:
            return hdr + stream.read_exact(actual_count * 4)
        return hdr
    if expected:
        return stream.read_exact(expected)
    return stream.sock.recv(4096)

# ─────────────────────── SWD 初始化序列 ──────────────────────────

def swd_init_cmds():
    """返回 [(cmd_bytes, expected_resp_bytes), ...] 列表，初始化 SWD + 上电 + 配置 AP"""
    cmds = []
    # DAP_Connect SWD=1 → [0x02, mode] = 2字节
    cmds.append((bytes([0x02, 0x01]), 2))
    # DAP_SWJ_Clock 2MHz → [0x11, status] = 2字节
    cmds.append((bytes([0x11]) + struct.pack('<I', 2_000_000), 2))
    # DAP_SWD_Configure → [0x13, status] = 2字节
    cmds.append((bytes([0x13, 0x00]), 2))
    # JTAG→SWD 切换序列 (136 bits) → [0x12, status] = 2字节
    seq = bytearray([0x12, 136 & 0xFF])
    seq += b'\xff' * 7 + bytes([0x9E, 0xE7]) + b'\xff' * 7 + b'\x00'
    cmds.append((bytes(seq), 2))
    # Read DPIDR (DAP_Transfer: DP R A=0) → [0x05][1][ack][data LE32] = 7字节
    cmds.append((bytes([0x05, 0x00, 0x01, 0x02]), 7))
    # Power up: Write CTRL/STAT → [0x05][1][ack] = 3字节
    cmds.append((bytes([0x05, 0x00, 0x01, 0x04]) + struct.pack('<I', 0x50000000), 3))
    # Select AP0 bank0 → 3字节
    cmds.append((bytes([0x05, 0x00, 0x01, 0x08]) + struct.pack('<I', 0x00000000), 3))
    # AP CSW: 32-bit, auto-increment packed → 3字节
    cmds.append((bytes([0x05, 0x00, 0x01, 0x01]) + struct.pack('<I', 0x23000052), 3))
    return cmds

def build_read_block_cmd(addr, word_count):
    """构建 DAP_TransferBlock 命令: 写 TAR, 读 DRW×N
    0x06 [idx] [count_LE16] [req] [TAR_LE32]  (仅写, TAR)
    然后 0x06 [idx] [count_LE16] [req]       (连续读 DRW)
    
    实际用两条 DAP_Transfer 代替, 兼容性更好:
    1) Write TAR
    2) TransferBlock Read DRW × word_count
    """
    # Command 1: Write TAR (AP reg 0x04 = APnDP=1,RnW=0,A=0b01 → req=0x05)
    tar_cmd = bytes([0x05, 0x00, 0x01, 0x05]) + struct.pack('<I', addr)
    # Command 2: DAP_TransferBlock read DRW  
    # 0x06 [dap_index=0] [count LE16] [request: AP read DRW = APnDP=1,RnW=1,A=0b11 → 0x0F]
    blk_cmd = bytes([0x06, 0x00]) + struct.pack('<H', word_count) + bytes([0x0F])
    return tar_cmd, blk_cmd

def parse_transfer_block_resp(resp, word_count):
    """解析 DAP_TransferBlock 响应: [0x06][count LE16][ack][data...]"""
    if len(resp) < 4 or resp[0] != 0x06:
        return 0, 0, []
    count = struct.unpack_from('<H', resp, 1)[0]
    ack   = resp[3]
    words = []
    for i in range(count):
        off = 4 + i * 4
        if off + 4 <= len(resp):
            words.append(struct.unpack_from('<I', resp, off)[0])
    return count, ack, words

# ─────────────────── HID (有线) 路径 ─────────────────────────────

def hid_available():
    try:
        import hid
        return True
    except ImportError:
        return False

class HIDTransport:
    """CMSIS-DAP v1 over USB HID (64B 报告)"""
    HID_PKT = 64

    def __init__(self, vid=USB_VID, pid=USB_PID):
        import hid
        self.dev = hid.device()
        self.dev.open(vid, pid)
        self.dev.set_nonblocking(0)

    def close(self):
        self.dev.close()

    def cmd(self, payload, timeout_ms=5000):
        pkt = bytes([0x00]) + bytes(payload) + bytes(self.HID_PKT - len(payload))
        self.dev.write(pkt[:self.HID_PKT + 1])
        resp = self.dev.read(self.HID_PKT, timeout_ms)
        return bytes(resp)

# ─────────────────── 通用测试逻辑 ────────────────────────────────

def run_swd_init(send_fn):
    """执行 SWD 初始化, 返回 DPIDR 或 0"""
    dpidr = 0
    for cmd, expected in swd_init_cmds():
        resp = send_fn(cmd, expected)   # 精确接收每条初始化命令的响应
        if cmd[0] == 0x05 and len(cmd) == 4 and cmd[3] == 0x02:
            # DPIDR 响应: [0x05][count][ack][data LE32]
            if resp and len(resp) >= 7:
                dpidr = struct.unpack_from('<I', resp, 3)[0]
    return dpidr

def run_speed_test(send_fn, label, words_per_block=256, total_kb=READ_KB):
    """
    反复读取 Flash, 测量吞吐量.
    返回 (KB/s, elapsed_s, total_bytes, errors)
    """
    total_words    = total_kb * 1024 // 4
    blocks         = total_words // words_per_block
    total_bytes    = 0
    errors         = 0
    # 预计 TransferBlock 读响应大小: [id(1)][count LE16(2)][ack(1)][data(N*4)]
    expected_blk   = 4 + words_per_block * 4

    t0 = time.time()
    for b in range(blocks):
        addr = READ_ADDR + b * words_per_block * 4
        tar_cmd, blk_cmd = build_read_block_cmd(addr, words_per_block)
        send_fn(tar_cmd, 3)                     # TAR 写: 响应 3 字节
        resp = send_fn(blk_cmd, expected_blk)   # Block 读: 响应最大 expected_blk 字节
        count, ack, words = parse_transfer_block_resp(resp, words_per_block)
        if ack == 0x01 and count == words_per_block:
            total_bytes += count * 4
        else:
            errors += 1
            if errors > 5:
                break
    t1 = time.time()

    elapsed = t1 - t0
    kBs     = (total_bytes / elapsed / 1024) if elapsed > 0 else 0
    return kBs, elapsed, total_bytes, errors

# ───────────────────────── 主程序 ────────────────────────────────

def section(title):
    print(f"\n{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}")

def fmt_result(kBs, elapsed, total_bytes, errors):
    kbits = kBs * 8
    return (f"{kBs:7.1f} KB/s  ({kbits:6.0f} kbit/s)"
            f"  [{total_bytes//1024}KB / {elapsed:.2f}s]"
            + (f"  ⚠ {errors} err" if errors else ""))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",         default=WIFI_HOST)
    parser.add_argument("--skip-hid",     action="store_true")
    parser.add_argument("--skip-openocd", action="store_true")
    parser.add_argument("--skip-el",      action="store_true")
    parser.add_argument("--words",        type=int, default=248,
                        help="Words per DAP_TransferBlock (WiFi paths). "
                             "USB HID limited to ~14 due to 64B packet.")
    parser.add_argument("--kb",           type=int, default=READ_KB)
    args = parser.parse_args()

    host   = args.host
    wpb_wifi = args.words   # words per block for TCP paths (max ~260 with 1048B pkt)
    wpb_hid  = 14           # words per block for 64B HID (3 hdr + 3 hdr + 14×4 = 62B)
    total_kb = args.kb

    results = {}

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║        EHUB DAP 三路速率对比  —  STM32F407           ║")
    print(f"║  目标: READ {total_kb}KB Flash @ 0x{READ_ADDR:08X}             ║")
    print(f"╚══════════════════════════════════════════════════════╝")

    # ── 1. 有线 USB HID ──────────────────────────────────────────
    if not args.skip_hid:
        section("1/3  有线 USB HID  (VID=0xC251 PID=0xF001)")
        if not hid_available():
            print("  ⚠ 未安装 hid 模块: pip install hid")
            print("    跳过有线测试")
        else:
            try:
                import hid as _hid
                hid_dev = HIDTransport()
                print(f"  已连接 HID 设备")

                def hid_send(payload, expected=None):
                    return hid_dev.cmd(payload)

                dpidr = run_swd_init(hid_send)
                print(f"  DPIDR = 0x{dpidr:08X}")

                print(f"  运行速率测试 ({wpb_hid} words/block × {total_kb}KB)…")
                r = run_speed_test(hid_send, "HID", words_per_block=wpb_hid, total_kb=total_kb)
                results["USB HID"] = r
                print(f"  结果: {fmt_result(*r)}")
                hid_dev.close()
            except Exception as e:
                print(f"  ✗ HID 错误: {e}")
    else:
        print("\n[跳过 USB HID]")

    # ── 2. WiFi OpenOCD TCP ──────────────────────────────────────
    if not args.skip_openocd:
        section(f"2/3  WiFi OpenOCD TCP  ({host}:{OCD_PORT})")
        try:
            sock = tcp_connect(host, OCD_PORT)
            print(f"  已连接 OpenOCD TCP")

            def ocd_send_fn(payload, expected=None):
                return ocd_cmd(sock, payload)  # OCD 协议有帧头, 内部已精确读取

            dpidr = run_swd_init(ocd_send_fn)
            print(f"  DPIDR = 0x{dpidr:08X}")

            print(f"  运行速率测试 ({wpb_wifi} words/block × {total_kb}KB)…")
            r = run_speed_test(ocd_send_fn, "OCD", words_per_block=wpb_wifi, total_kb=total_kb)
            results["OpenOCD TCP"] = r
            print(f"  结果: {fmt_result(*r)}")
            sock.close()
        except Exception as e:
            print(f"  ✗ OpenOCD TCP 错误: {e}")
    else:
        print("\n[跳过 OpenOCD TCP]")

    # ── 3. WiFi elaphureLink ─────────────────────────────────────
    if not args.skip_el:
        section(f"3/3  WiFi elaphureLink  ({host}:{EL_PORT})")
        try:
            stream = el_connect(host, EL_PORT)
            print(f"  已连接 elaphureLink")

            def el_send_fn(payload, expected=None):
                return el_cmd(stream, payload, expected)

            dpidr = run_swd_init(el_send_fn)
            print(f"  DPIDR = 0x{dpidr:08X}")

            print(f"  运行速率测试 ({wpb_wifi} words/block × {total_kb}KB)…")
            r = run_speed_test(el_send_fn, "EL", words_per_block=wpb_wifi, total_kb=total_kb)
            results["elaphureLink"] = r
            print(f"  结果: {fmt_result(*r)}")
            stream.close()
        except Exception as e:
            print(f"  ✗ elaphureLink 错误: {e}")
    else:
        print("\n[跳过 elaphureLink]")

    # ── 汇总 ────────────────────────────────────────────────────
    if results:
        print(f"\n{'═'*56}")
        print(f"  汇总对比 ({total_kb}KB Flash 读取)")
        print(f"{'═'*56}")
        max_kBs = max(r[0] for r in results.values()) or 1
        for name, (kBs, elapsed, tot, err) in results.items():
            bar_len = int(kBs / max_kBs * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            rel = kBs / max_kBs * 100
            print(f"  {name:<14} {bar} {kBs:6.1f} KB/s  {rel:5.1f}%"
                  + (f"  ⚠{err}" if err else ""))
        print(f"{'═'*56}")

        # 相对倍率 vs 最慢
        if len(results) > 1:
            min_kBs = min(r[0] for r in results.values())
            if min_kBs > 0:
                print(f"\n  相对倍率 (以最慢为基准 1×):")
                for name, (kBs, *_) in results.items():
                    print(f"    {name:<14} {kBs/min_kBs:.2f}×")

if __name__ == "__main__":
    main()
