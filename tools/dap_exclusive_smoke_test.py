#!/usr/bin/env python3
import argparse
import socket
import struct
import time

SOF_CMD = 0xAA
SOF_RPY = 0xBB
SOF1 = 0x55
CH_WIFI_CTRL = 0xE0
CH_CONFIG = 0xF0

DAP_SIG = 0x00504144  # 'DAP\0' LE
DAP_TYPE_REQ = 0x01


def crc8(ch: int, payload: bytes) -> int:
    v = ch ^ ((len(payload) >> 8) & 0xFF) ^ (len(payload) & 0xFF)
    for b in payload:
        v ^= b
    return v & 0xFF


def build_bridge(ch: int, payload: bytes, sof0: int = SOF_CMD) -> bytes:
    hdr = bytes([sof0, SOF1, ch, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF])
    return hdr + payload + bytes([crc8(ch, payload)])


def recv_one_bridge(sock: socket.socket, timeout: float = 1.0):
    sock.settimeout(timeout)
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            chunk = sock.recv(1024)
        except socket.timeout:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
        if len(buf) < 6:
            continue
        i = 0
        while i + 6 <= len(buf):
            if buf[i] not in (SOF_CMD, SOF_RPY) or buf[i + 1] != SOF1:
                i += 1
                continue
            ch = buf[i + 2]
            ln = (buf[i + 3] << 8) | buf[i + 4]
            end = i + 6 + ln - 0
            if i + 6 + ln > len(buf):
                break
            payload = bytes(buf[i + 5:i + 5 + ln])
            c = buf[i + 5 + ln]
            if c == crc8(ch, payload):
                return ch, payload
            i += 1
    return None


def test_wifi_ctrl(host: str, port: int, timeout: float):
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        req = build_bridge(CH_WIFI_CTRL, bytes([0x01]))  # WIFI_STATUS
        s.sendall(req)
        rsp = recv_one_bridge(s, timeout)
        if not rsp:
            raise RuntimeError('WIFI_CTRL no response on port 5000')
        ch, payload = rsp
        if ch != CH_WIFI_CTRL or len(payload) < 2 or payload[0] != 0x01:
            raise RuntimeError(f'Unexpected WIFI_CTRL response: ch=0x{ch:02X}, payload={payload.hex()}')
        return payload
    finally:
        s.close()


def test_dap_openocd(host: str, port: int, timeout: float):
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    try:
        dap_cmd = bytes([0x00, 0xFE])  # ID_DAP_Info, DAP_ID_PACKET_SIZE
        hdr = struct.pack('<IHBb', DAP_SIG, len(dap_cmd), DAP_TYPE_REQ, 0)
        s.sendall(hdr + dap_cmd)

        rh = s.recv(8)
        if len(rh) != 8:
            raise RuntimeError('DAP header too short')
        sig, ln, typ, _ = struct.unpack('<IHBb', rh)
        if sig != DAP_SIG or typ != 0x02 or ln == 0:
            raise RuntimeError(f'Bad DAP response header: sig=0x{sig:08X}, len={ln}, type={typ}')
        payload = s.recv(ln)
        if len(payload) != ln:
            raise RuntimeError('DAP payload truncated')
        if payload[0] != 0x00:
            raise RuntimeError(f'Unexpected DAP response cmd id: 0x{payload[0]:02X}')
        return s, payload
    except Exception:
        s.close()
        raise


def test_exclusive_filter(host: str, port: int, timeout: float):
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        req = build_bridge(CH_CONFIG, bytes([CH_CONFIG]))  # config ping; normal mode should echo EHUB
        s.sendall(req)
        rsp = recv_one_bridge(s, timeout)
        return rsp is None
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description='EHUB DAP exclusive mode smoke test')
    ap.add_argument('--host', default='ehub.local')
    ap.add_argument('--bridge-port', type=int, default=5000)
    ap.add_argument('--dap-port', type=int, default=6000)
    ap.add_argument('--timeout', type=float, default=1.5)
    args = ap.parse_args()

    print(f'[1/3] WIFI_CTRL check on {args.host}:{args.bridge_port} ...')
    wifi_payload = test_wifi_ctrl(args.host, args.bridge_port, args.timeout)
    print(f'  OK WIFI_STATUS payload={wifi_payload.hex()}')

    print(f'[2/3] DAP TCP check on {args.host}:{args.dap_port} ...')
    dap_sock, dap_payload = test_dap_openocd(args.host, args.dap_port, args.timeout)
    print(f'  OK DAP_Info payload={dap_payload.hex()}')

    print(f'[3/3] Exclusive filter check (while DAP session alive) ...')
    blocked = test_exclusive_filter(args.host, args.bridge_port, timeout=0.8)
    dap_sock.close()
    if not blocked:
        raise SystemExit('FAIL: non-WIFI_CTRL traffic was not filtered during active DAP session')
    print('  OK non-WIFI_CTRL filtered during DAP session')

    print('PASS')


if __name__ == '__main__':
    main()
