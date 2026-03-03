"""
DAP TCP 诊断工具 — 测试 OpenOCD cmsis-dap tcp 协议
8字节头: [4B signature "DAP\0"][2B LE length][1B type][1B reserved]
"""
import socket
import struct
import time
import sys

HOST = "ehub.local"
PORT = 6000
TIMEOUT = 3.0

DAP_SIGNATURE = 0x00504144  # "DAP\0"
DAP_TYPE_REQUEST  = 0x01
DAP_TYPE_RESPONSE = 0x02
HEADER_SIZE = 8

def send_dap_cmd(sock, cmd_bytes):
    """发送 DAP 命令 (8字节头 + 数据)"""
    header = struct.pack('<IHBx', DAP_SIGNATURE, len(cmd_bytes), DAP_TYPE_REQUEST)
    sock.sendall(header + cmd_bytes)
    print(f"  TX: len={len(cmd_bytes)}, data={cmd_bytes.hex()}")

def recv_dap_rsp(sock, timeout=3.0):
    """接收 DAP 响应 (8字节头 + 数据)"""
    sock.settimeout(timeout)
    try:
        # 读取8字节头
        header = b''
        while len(header) < HEADER_SIZE:
            chunk = sock.recv(HEADER_SIZE - len(header))
            if not chunk:
                print("  RX: 连接关闭")
                return None
            header += chunk
        
        sig, rsp_len, pkt_type = struct.unpack('<IHBx', header)
        print(f"  RX: sig=0x{sig:08x}, len={rsp_len}, type=0x{pkt_type:02x}")
        
        if sig != DAP_SIGNATURE:
            print(f"  RX: 错误的签名! 期望 0x{DAP_SIGNATURE:08x}")
            return None
        if pkt_type != DAP_TYPE_RESPONSE:
            print(f"  RX: 错误的类型! 期望 0x{DAP_TYPE_RESPONSE:02x}")
            return None
        
        # 读取数据
        data = b''
        while len(data) < rsp_len:
            chunk = sock.recv(rsp_len - len(data))
            if not chunk:
                print("  RX: 数据读取中连接关闭")
                return None
            data += chunk
        
        print(f"  RX: data={data.hex()}")
        return data
    except socket.timeout:
        print("  RX: 超时 (无响应)")
        return None

def test_raw_recv(sock, timeout=3.0):
    """尝试接收任何原始数据"""
    sock.settimeout(timeout)
    try:
        data = sock.recv(256)
        print(f"  RAW RX: {data.hex()} ({len(data)} bytes)")
        return data
    except socket.timeout:
        print("  RAW RX: 超时 (无数据)")
        return None

def main():
    print(f"=== DAP TCP 诊断 ===")
    print(f"目标: {HOST}:{PORT}")
    print()

    # 1. 连接
    print("[1] 连接...")
    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"  已连接到 {sock.getpeername()}")
    except Exception as e:
        print(f"  连接失败: {e}")
        return

    # 2. 先检查是否有主动推送的数据
    print("\n[2] 检查是否有ESP32主动发送的数据...")
    test_raw_recv(sock, timeout=1.0)

    # 3. 发送 DAP_Info (ID=0x00, SubCmd=0xFE: Get Packet Count)
    print("\n[3] 发送 DAP_Info: Get Packet Count (0x00 0xFE)...")
    send_dap_cmd(sock, bytes([0x00, 0xFE]))
    rsp = recv_dap_rsp(sock, timeout=3.0)
    
    if rsp is None:
        print("\n  >>> 没有收到响应！可能原因:")
        print("     1. ESP32 固件未更新 (需要 pio run -t upload)")
        print("     2. Bridge 帧未正确发送到 MCU")
        print("     3. MCU 未处理 BRIDGE_CH_DAP (0xD0)")
        print("     4. UART 通信问题")
        
        # 再试一次原始接收
        print("\n[3b] 再等3秒看是否有延迟响应...")
        test_raw_recv(sock, timeout=3.0)

    # 4. 发送 DAP_Info: Vendor Name (0x00, 0x01)
    print("\n[4] 发送 DAP_Info: Vendor Name (0x00 0x01)...")
    send_dap_cmd(sock, bytes([0x00, 0x01]))
    rsp = recv_dap_rsp(sock, timeout=3.0)
    if rsp and len(rsp) > 1:
        try:
            name = rsp[1:].split(b'\x00')[0].decode('ascii')
            print(f"  Vendor Name: {name}")
        except:
            pass

    # 5. 发送 DAP_Info: Product Name (0x00, 0x02)
    print("\n[5] 发送 DAP_Info: Product Name (0x00 0x02)...")
    send_dap_cmd(sock, bytes([0x00, 0x02]))
    rsp = recv_dap_rsp(sock, timeout=3.0)
    if rsp and len(rsp) > 1:
        try:
            name = rsp[1:].split(b'\x00')[0].decode('ascii')
            print(f"  Product Name: {name}")
        except:
            pass

    # 6. 发送 DAP_Info: FW Version (0x00, 0x04)  
    print("\n[6] 发送 DAP_Info: FW Version (0x00 0x04)...")
    send_dap_cmd(sock, bytes([0x00, 0x04]))
    rsp = recv_dap_rsp(sock, timeout=3.0)
    if rsp and len(rsp) > 1:
        try:
            ver = rsp[1:].split(b'\x00')[0].decode('ascii')
            print(f"  FW Version: {ver}")
        except:
            pass

    sock.close()
    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
