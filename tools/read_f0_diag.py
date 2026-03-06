import socket
import struct

HOST = "ehub.local"
PORT = 5000


def crc8(ch, payload):
    value = ch ^ ((len(payload) >> 8) & 0xFF) ^ (len(payload) & 0xFF)
    for b in payload:
        value ^= b
    return value & 0xFF


def build_frame(ch, payload, sof0=0xAA):
    return bytes([sof0, 0x55, ch, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload + bytes([crc8(ch, payload)])


def find_valid_frame(data):
    i = 0
    while i + 6 <= len(data):
        if data[i] in (0xAA, 0xBB) and data[i + 1] == 0x55:
            ch = data[i + 2]
            ln = (data[i + 3] << 8) | data[i + 4]
            if i + 6 + ln <= len(data):
                payload = data[i + 5:i + 5 + ln]
                c = data[i + 5 + ln]
                if c == crc8(ch, payload):
                    return ch, payload
        i += 1
    return None


with socket.create_connection((HOST, PORT), timeout=2) as s:
    s.settimeout(2)
    s.sendall(build_frame(0xE0, bytes([0xF0])))
    raw = s.recv(2048)

found = find_valid_frame(raw)
if not found:
    print("NO_VALID_FRAME", raw.hex())
    raise SystemExit(1)

ch, payload = found
print(f"CH=0x{ch:02X} LEN={len(payload)} SUB=0x{payload[0]:02X}")

offset = 1
u32 = lambda pos: struct.unpack_from('<I', payload, pos)[0]

dap_tcp_read = u32(offset); offset += 4
DAP_uart_tx = u32(offset); offset += 4
dap_uart_rx = u32(offset); offset += 4
dap_tcp_send = u32(offset); offset += 4
dap_timeout = u32(offset); offset += 4
uart_bytes_rx = u32(offset); offset += 4
uart_frames_rx = u32(offset); offset += 4

last_cmd_len = struct.unpack_from('<H', payload, offset)[0]; offset += 2
last_cmd_8 = payload[offset:offset + 8]; offset += 8

last_bridge_len = struct.unpack_from('<H', payload, offset)[0]; offset += 2
last_bridge_16 = payload[offset:offset + 16]; offset += 16

last_cmd_id = payload[offset]; offset += 1
last_rsp_id = payload[offset]; offset += 1
last_rsp_len = struct.unpack_from('<H', payload, offset)[0]; offset += 2
last_rsp_8 = payload[offset:offset + 8]; offset += 8
last_timeout_cmd_id = payload[offset]; offset += 1

gpio1 = payload[offset];
gpio3 = payload[offset + 1];
offset += 2

serial_avail = u32(offset); offset += 4
baud = u32(offset); offset += 4

print("dapTcpRead=", dap_tcp_read)
print("dapUartTx=", DAP_uart_tx)
print("dapUartRx=", dap_uart_rx)
print("dapTcpSend=", dap_tcp_send)
print("dapTimeout=", dap_timeout)
print("uartBytesRx=", uart_bytes_rx)
print("uartFramesRx=", uart_frames_rx)
print("lastCmdLen=", last_cmd_len, f"lastCmdId=0x{last_cmd_id:02X}", "lastCmd8=", last_cmd_8.hex())
print("lastRspLen=", last_rsp_len, f"lastRspId=0x{last_rsp_id:02X}", "lastRsp8=", last_rsp_8.hex())
print(f"lastTimeoutCmdId=0x{last_timeout_cmd_id:02X}", "lastBridgeLen=", last_bridge_len, "lastBridge16=", last_bridge_16.hex())
print("gpio1=", gpio1, "gpio3=", gpio3, "serialAvail=", serial_avail, "baud=", baud)
