#!/usr/bin/env python3
"""Direct DAP TCP protocol test — multi-run reliability test."""
import socket, struct, time

HOST = '192.168.227.100'
PORT = 6000
SIG = 0x00504144

def send_dap_tcp(s, cmd):
    hdr = struct.pack('<IHBb', SIG, len(cmd), 1, 0)
    s.sendall(hdr + bytes(cmd))
    h = b''
    while len(h) < 8:
        chunk = s.recv(8 - len(h))
        if not chunk:
            raise ConnectionError("closed")
        h += chunk
    sig, length, ptype, _ = struct.unpack('<IHBb', h)
    d = b''
    while len(d) < length:
        chunk = s.recv(length - len(d))
        if not chunk:
            raise ConnectionError("closed")
        d += chunk
    return d

TESTS = [
    ("Info_FW",      [0x00, 0x04]),
    ("Info_Caps",    [0x00, 0xF0]),
    ("Info_PktSz",   [0x00, 0xFF]),
    ("Info_PktCnt",  [0x00, 0xFE]),
    ("Connect_SWD",  [0x02, 0x01]),
    ("SWJ_Clock",    [0x11, 0x40, 0x42, 0x0F, 0x00]),
    ("SWD_Config",   [0x13, 0x00]),
    ("SWJ_Seq51a",   [0x12, 51, 0xFF,0xFF,0xFF,0xFF,0xFF,0xFF, 0x03]),
    ("SWJ_Seq16",    [0x12, 16, 0x9E, 0xE7]),
    ("SWJ_Seq51b",   [0x12, 51, 0xFF,0xFF,0xFF,0xFF,0xFF,0xFF, 0x03]),
    ("SWJ_Seq8",     [0x12, 8, 0x00]),
    ("Transfer",     [0x05, 0x00, 0x01, 0x02]),
    ("Disconnect",   [0x03]),
]

def run_one(run_id):
    """Returns list of (name, ok, dt_ms)."""
    results = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((HOST, PORT))
    except Exception as e:
        return [(name, False, 0) for name, _ in TESTS]

    for name, cmd in TESTS:
        time.sleep(0.02)
        # Drain stale
        s.setblocking(False)
        try: s.recv(4096)
        except: pass
        s.setblocking(True)
        s.settimeout(3.0)
        try:
            t0 = time.perf_counter()
            r = send_dap_tcp(s, cmd)
            dt = (time.perf_counter() - t0) * 1000
            results.append((name, True, dt))
        except:
            results.append((name, False, 3000))
    s.close()
    return results

def main():
    RUNS = 5
    all_results = []  # list of lists
    total_ok = 0
    total_fail = 0

    for i in range(RUNS):
        print(f"Run {i+1}/{RUNS}...", end=" ", flush=True)
        res = run_one(i)
        ok_n = sum(1 for _, ok, _ in res if ok)
        fail_n = len(res) - ok_n
        total_ok += ok_n
        total_fail += fail_n
        fails = [n for n, ok, _ in res if not ok]
        avg_dt = sum(dt for _, ok, dt in res if ok) / max(ok_n, 1)
        print(f"OK={ok_n} FAIL={fail_n} avg={avg_dt:.0f}ms", end="")
        if fails:
            print(f"  FAILED: {', '.join(fails)}")
        else:
            print("  ALL OK")
        all_results.append(res)
        time.sleep(0.5)

    print(f"\n=== Summary: {total_ok}/{total_ok+total_fail} OK ({total_fail} failures in {RUNS} runs) ===")

    # Per-command stats
    print(f"\n{'Command':15s} {'OK':>4s} {'Fail':>4s} {'Avg(ms)':>8s}")
    print("-" * 35)
    for j, (name, _) in enumerate(TESTS):
        oks = [all_results[i][j][2] for i in range(RUNS) if all_results[i][j][1]]
        fail_count = RUNS - len(oks)
        avg = sum(oks)/len(oks) if oks else 0
        mark = " ←!" if fail_count > 0 else ""
        print(f"{name:15s} {len(oks):4d} {fail_count:4d} {avg:8.1f}{mark}")

if __name__ == '__main__':
    main()
