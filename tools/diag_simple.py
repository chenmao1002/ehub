"""Simple diagnostic: send DAP via port 6000, then check counters"""
import socket, struct, time

HOST = "ehub.local"

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data) if data else "(none)"

def calc_crc(ch, length, data):
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data: crc ^= b
    return crc & 0xFF

def build_frame(ch, data):
    length = len(data)
    frame = bytearray([0xAA, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF])
    frame.extend(data)
    frame.append(calc_crc(ch, length, data))
    return bytes(frame)

def query_debug():
    sock = socket.create_connection((HOST, 5000), timeout=3)
    sock.sendall(build_frame(0xE0, bytes([0xF0])))
    sock.settimeout(3)
    try:
        resp = sock.recv(512)
        if len(resp) > 6 and resp[0] == 0xBB:
            data = resp[5:5+((resp[3]<<8)|resp[4])]
            if data[0] == 0xF0 and len(data) >= 49:
                pos = 1
                vals = []
                for _ in range(7):
                    vals.append(struct.unpack_from('<I', data, pos)[0]); pos += 4
                cmd_len = struct.unpack_from('<H', data, pos)[0]; pos += 2
                cmd = data[pos:pos+8]; pos += 8
                bridge_len = struct.unpack_from('<H', data, pos)[0]; pos += 2
                bridge = data[pos:pos+16]
                labels = ['TCP_Read', 'UART_TX', 'UART_RX', 'TCP_Send', 'Timeout', 'UART_BytesRX', 'UART_FramesRX']
                for l, v in zip(labels, vals):
                    print(f"  {l:15s}: {v}")
                print(f"  LastCmd ({cmd_len}B): {hexdump(cmd[:min(cmd_len,8)])}")
                print(f"  LastBridge ({bridge_len}B): {hexdump(bridge[:min(bridge_len,16)])}")
    except socket.timeout:
        print("  Debug query: TIMEOUT")
    sock.close()

print("=== Initial counters ===")
query_debug()

print("\n=== Send DAP_Info(PacketCount) via port 6000 ===")
sock = socket.create_connection((HOST, 6000), timeout=5)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
cmd = bytes([0x00, 0xFE])
header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
print(f"  TX: {hexdump(header + cmd)}")
sock.sendall(header + cmd)
sock.settimeout(3)
try:
    resp = sock.recv(512)
    print(f"  RX ({len(resp)}B): {hexdump(resp)}")
except socket.timeout:
    print(f"  RX: TIMEOUT (expected — investigating why)")
sock.close()

print("\n=== Counters after DAP ===")
time.sleep(1)
query_debug()
