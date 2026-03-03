"""
EHUB DAP TCP 测试工具
验证无线 DAP 调试连接: PC → TCP:6000 → ESP32 → UART → MCU → DAP

使用方法:
    python dap_tcp_test.py [--host ehub.local] [--port 6000]

依赖: pip install zeroconf (可选，用于 mDNS 发现)
"""

import socket
import struct
import sys
import time
import argparse

# CMSIS-DAP Command IDs
ID_DAP_Info         = 0x00
ID_DAP_Connect      = 0x02
ID_DAP_Disconnect   = 0x03
ID_DAP_SWJ_Clock    = 0x11
ID_DAP_SWD_Configure = 0x13
ID_DAP_Transfer     = 0x05

# DAP_Info sub-IDs
DAP_ID_VENDOR       = 1
DAP_ID_PRODUCT      = 2
DAP_ID_SER_NUM      = 3
DAP_ID_FW_VER       = 4
DAP_ID_CAPABILITIES = 0xF0
DAP_ID_PACKET_COUNT = 0xFE
DAP_ID_PACKET_SIZE  = 0xFF


def send_dap_cmd(sock: socket.socket, cmd: bytes) -> bytes:
    """发送 DAP 命令并接收响应 (4字节LE长度头协议)"""
    # 发送: [4-byte LE length][DAP command]
    header = struct.pack('<I', len(cmd))
    sock.sendall(header + cmd)

    # 接收: [4-byte LE length][DAP response]
    resp_header = b''
    while len(resp_header) < 4:
        chunk = sock.recv(4 - len(resp_header))
        if not chunk:
            raise ConnectionError("连接断开")
        resp_header += chunk

    resp_len = struct.unpack('<I', resp_header)[0]
    if resp_len > 4096:
        raise ValueError(f"响应长度异常: {resp_len}")

    resp_data = b''
    while len(resp_data) < resp_len:
        chunk = sock.recv(resp_len - len(resp_data))
        if not chunk:
            raise ConnectionError("连接断开")
        resp_data += chunk

    return resp_data


def dap_info(sock: socket.socket, info_id: int) -> bytes:
    """DAP_Info 命令"""
    cmd = bytes([ID_DAP_Info, info_id])
    resp = send_dap_cmd(sock, cmd)
    if resp[0] != ID_DAP_Info:
        raise ValueError(f"意外的响应 ID: 0x{resp[0]:02X}")
    length = resp[1]
    return resp[2:2+length]


def dap_connect_swd(sock: socket.socket) -> bool:
    """DAP_Connect (SWD模式)"""
    cmd = bytes([ID_DAP_Connect, 1])  # 1 = SWD
    resp = send_dap_cmd(sock, cmd)
    return resp[0] == ID_DAP_Connect and resp[1] == 1


def dap_disconnect(sock: socket.socket):
    """DAP_Disconnect"""
    cmd = bytes([ID_DAP_Disconnect])
    send_dap_cmd(sock, cmd)


def dap_swj_clock(sock: socket.socket, clock_hz: int) -> bool:
    """DAP_SWJ_Clock"""
    cmd = bytes([ID_DAP_SWJ_Clock]) + struct.pack('<I', clock_hz)
    resp = send_dap_cmd(sock, cmd)
    return resp[0] == ID_DAP_SWJ_Clock and resp[1] == 0


def test_dap_connection(host: str, port: int, verbose: bool = True):
    """完整的 DAP TCP 连接测试"""
    print(f"\n{'='*60}")
    print(f"  EHUB DAP TCP 测试")
    print(f"  目标: {host}:{port}")
    print(f"{'='*60}\n")

    # 1. TCP 连接
    print(f"[1/6] 连接 TCP {host}:{port} ...", end=" ", flush=True)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("✓ 已连接")
    except Exception as e:
        print(f"✗ 失败: {e}")
        return False

    try:
        # 2. DAP_Info: Vendor
        print("[2/6] 读取 DAP_Info (Vendor) ...", end=" ", flush=True)
        vendor = dap_info(sock, DAP_ID_VENDOR)
        vendor_str = vendor.decode('ascii', errors='replace') if vendor else "(空)"
        print(f"✓ Vendor: {vendor_str}")

        # 3. DAP_Info: Product
        print("[3/6] 读取 DAP_Info (Product) ...", end=" ", flush=True)
        product = dap_info(sock, DAP_ID_PRODUCT)
        product_str = product.decode('ascii', errors='replace') if product else "(空)"
        print(f"✓ Product: {product_str}")

        # 4. DAP_Info: FW Version
        print("[4/6] 读取 DAP_Info (FW Version) ...", end=" ", flush=True)
        fw_ver = dap_info(sock, DAP_ID_FW_VER)
        fw_str = fw_ver.decode('ascii', errors='replace') if fw_ver else "(空)"
        print(f"✓ FW Version: {fw_str}")

        # 5. DAP_Info: Packet Size & Count
        print("[5/6] 读取 DAP_Info (Packet Size/Count) ...", end=" ", flush=True)
        pkt_size_raw = dap_info(sock, DAP_ID_PACKET_SIZE)
        pkt_count_raw = dap_info(sock, DAP_ID_PACKET_COUNT)
        pkt_size = struct.unpack('<H', pkt_size_raw)[0] if len(pkt_size_raw) >= 2 else 0
        pkt_count = pkt_count_raw[0] if pkt_count_raw else 0
        print(f"✓ Packet Size: {pkt_size}, Count: {pkt_count}")

        # 6. DAP_Connect (SWD) + Clock
        print("[6/6] DAP_Connect (SWD, 1MHz) ...", end=" ", flush=True)
        if dap_connect_swd(sock):
            dap_swj_clock(sock, 1000000)
            print("✓ SWD 已连接")
        else:
            print("✗ SWD 连接失败 (可能没有接目标芯片)")

        # 断开
        dap_disconnect(sock)

        # 延迟测试
        print("\n[BENCH] 延迟测试 (100次 DAP_Info) ...", end=" ", flush=True)
        t0 = time.perf_counter()
        for _ in range(100):
            dap_info(sock, DAP_ID_FW_VER)
        t1 = time.perf_counter()
        avg_ms = (t1 - t0) / 100 * 1000
        print(f"平均 {avg_ms:.2f} ms/次")

        print(f"\n{'='*60}")
        print("  ✓ DAP TCP 测试通过!")
        print(f"{'='*60}\n")
        return True

    except Exception as e:
        print(f"\n  ✗ 测试失败: {e}")
        return False
    finally:
        sock.close()


def discover_ehub(timeout: float = 3.0) -> str | None:
    """通过 mDNS 发现 EHUB 设备"""
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        return None

    found = []

    class Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                addr = socket.inet_ntoa(info.addresses[0])
                found.append(addr)

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    browser = ServiceBrowser(zc, "_dap._tcp.local.", Listener())
    time.sleep(timeout)
    zc.close()

    return found[0] if found else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EHUB DAP TCP 测试工具")
    parser.add_argument("--host", default="ehub.local",
                        help="EHUB ESP32 地址 (默认: ehub.local)")
    parser.add_argument("--port", type=int, default=6000,
                        help="DAP TCP 端口 (默认: 6000)")
    parser.add_argument("--discover", action="store_true",
                        help="使用 mDNS 自动发现设备")
    args = parser.parse_args()

    host = args.host
    if args.discover:
        print("正在通过 mDNS 搜索 EHUB 设备...", end=" ", flush=True)
        discovered = discover_ehub()
        if discovered:
            host = discovered
            print(f"找到: {host}")
        else:
            print("未找到，使用默认地址")

    success = test_dap_connection(host, args.port)
    sys.exit(0 if success else 1)
