#!/usr/bin/env python3
"""
elaphureLink reliability test — sends many DAP commands and measures failure rate.
After the test, queries ESP32 debug counters to diagnose where losses occur.

Usage:  python tools/test_reliability.py [--host HOST] [--rounds 50]
"""
import socket, struct, time, sys

HOST = "192.168.227.100"
EL_PORT = 3240
DIAG_PORT = 5000

def crc8_xor(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c

def build_bridge_frame(sof0, ch, data):
    length = len(data)
    hdr = bytes([sof0, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF])
    payload = hdr + data
    crc = crc8_xor(payload[2:])
    return payload + bytes([crc])

def parse_bridge_frames(raw):
    i = 0
    while i < len(raw) - 5:
        if raw[i] in (0xAA, 0xBB) and raw[i+1] == 0x55:
            ch = raw[i+2]
            length = (raw[i+3] << 8) | raw[i+4]
            if length == 0 or i + 5 + length + 1 > len(raw):
                i += 1; continue
            data = raw[i+5 : i+5+length]
            crc = raw[i+5+length]
            expected = crc8_xor(raw[i+2 : i+5+length])
            if crc == expected:
                yield (ch, data)
                i += 5 + length + 1; continue
        i += 1

def query_esp32_counters(ip):
    """Query ESP32 0xF0 debug counters via bridge TCP port 5000."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((ip, DIAG_PORT))
        frame = build_bridge_frame(0xAA, 0xE0, bytes([0xF0]))
        s.sendall(frame)
        time.sleep(0.5)
        raw = s.recv(4096)
        s.close()
        for ch, data in parse_bridge_frames(raw):
            if ch == 0xE0 and len(data) >= 29 and data[0] == 0xF0:
                pos = 1
                vals = struct.unpack_from('<7I', data, pos)
                return {
                    'dapTcpRead': vals[0],
                    'dapUartTx': vals[1],
                    'dapUartRx': vals[2],
                    'dapTcpSend': vals[3],
                    'dapTimeout': vals[4],
                    'uartBytesRx': vals[5],
                    'uartFramesRx': vals[6],
                }
    except Exception as e:
        print(f"  ESP32 query error: {e}")
    return None

def el_handshake(sock):
    req = struct.pack('>III', 0x8a656c70, 0, 1)
    sock.sendall(req)
    sock.settimeout(5)
    res = sock.recv(256)
    if len(res) >= 12:
        ident = struct.unpack_from('>I', res, 0)[0]
        return ident == 0x8a656c70
    return False

def dap_cmd(sock, cmd_bytes, timeout=3):
    sock.sendall(cmd_bytes)
    sock.settimeout(timeout)
    try:
        resp = sock.recv(512)
        return resp
    except (socket.timeout, TimeoutError, OSError):
        return None

def connect_el(host):
    """Connect and handshake to elaphureLink. Returns socket or None."""
    try:
        sock = socket.create_connection((host, EL_PORT), timeout=5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if el_handshake(sock):
            return sock
        sock.close()
    except Exception as e:
        print(f"  Connect error: {e}")
    return None

def main():
    host = HOST
    rounds = 50
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--host' and i+1 < len(args):
            host = args[i+1]; i += 2
        elif args[i] == '--rounds' and i+1 < len(args):
            rounds = int(args[i+1]); i += 2
        else:
            i += 1

    print(f"=== elaphureLink Reliability Test ===")
    print(f"Host: {host}  Rounds: {rounds}")

    # Query ESP32 before
    print(f"\n--- ESP32 counters BEFORE ---")
    before = query_esp32_counters(host)
    if before:
        for k, v in before.items():
            print(f"  {k:20s} = {v}")
    else:
        print("  (no response)")

    # Connect to elaphureLink
    print(f"\n--- Connecting to {host}:{EL_PORT} ---")
    sock = connect_el(host)
    if not sock:
        print("  Handshake FAILED!")
        return

    print("  Handshake OK")

    # DAP test commands
    commands = [
        ("DAP_Info(Vendor)",   bytes([0x00, 0x01])),
        ("DAP_Info(Product)",  bytes([0x00, 0x02])),
        ("DAP_Info(FW_Ver)",   bytes([0x00, 0x04])),
        ("DAP_Info(Caps)",     bytes([0x00, 0xF0])),
        ("DAP_Info(PktCnt)",   bytes([0x00, 0xFE])),
        ("DAP_Info(PktSize)",  bytes([0x00, 0xFF])),
    ]

    print(f"\n--- Running {rounds} rounds of {len(commands)} commands ---")
    total = 0
    ok = 0
    fail = 0
    reconnects = 0
    fail_details = []
    times = []

    for r in range(rounds):
        for name, cmd in commands:
            total += 1
            t0 = time.time()
            resp = dap_cmd(sock, cmd, timeout=3)
            dt = (time.time() - t0) * 1000
            times.append(dt)
            if resp is not None:
                ok += 1
            else:
                fail += 1
                fail_details.append(f"  Round {r+1} {name}: TIMEOUT")
                # After timeout, reconnect to resync TCP stream
                try:
                    sock.close()
                except:
                    pass
                time.sleep(0.5)
                sock = connect_el(host)
                if sock:
                    reconnects += 1
                    fail_details.append(f"    (reconnected #{reconnects})")
                else:
                    fail_details.append(f"    (reconnect FAILED, aborting)")
                    print(f"\n  ABORT: cannot reconnect after timeout")
                    break
        else:
            # Print progress every 10 rounds
            if (r + 1) % 10 == 0:
                pct = ok / total * 100 if total > 0 else 0
                avg_ok = sum(t for t in times if t < 2500) / max(1, len([t for t in times if t < 2500]))
                print(f"  Round {r+1}/{rounds}: {ok}/{total} OK ({pct:.1f}%), avg={avg_ok:.0f}ms, reconnects={reconnects}")
            continue
        break  # break outer loop if inner broke

    try:
        sock.close()
    except:
        pass

    print(f"\n--- Results ---")
    print(f"  Total commands: {total}")
    print(f"  OK:   {ok} ({ok/total*100:.1f}%)")
    print(f"  FAIL: {fail} ({fail/total*100:.1f}%)")
    if times:
        times_ok = [t for t in times if t < 2500]  # exclude timeouts
        if times_ok:
            print(f"  Latency (ok): min={min(times_ok):.0f}ms avg={sum(times_ok)/len(times_ok):.0f}ms max={max(times_ok):.0f}ms")
    if fail_details:
        print(f"\n  Failures:")
        for d in fail_details[:20]:
            print(d)

    # Query ESP32 after
    print(f"\n--- ESP32 counters AFTER ---")
    time.sleep(1)
    after = query_esp32_counters(host)
    if after:
        for k, v in after.items():
            print(f"  {k:20s} = {v}")
    if before and after:
        print(f"\n--- Deltas ---")
        for k in before:
            d = after.get(k, 0) - before.get(k, 0)
            print(f"  {k:20s} = +{d}")

    print(f"\n=== Done ===")

if __name__ == '__main__':
    main()
