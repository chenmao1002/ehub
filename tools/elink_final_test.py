"""
elaphureLink 速度测试 - 结果输出到文件
"""
import socket, struct, time, sys

HOST = "192.168.227.100"
PORT = 3240
RESULT_FILE = "elink_results.txt"

# Open result file
rf = open(RESULT_FILE, "w", encoding="utf-8")

def log(msg):
    print(msg, flush=True)
    rf.write(msg + "\n")
    rf.flush()

def sr(s, d, t=15):
    s.settimeout(t)
    s.sendall(d)
    return s.recv(4096)

def xfer(s, transfers, idx=0, timeout=15):
    buf = bytearray([0x05, idx, len(transfers)])
    for ap, rw, a, wd in transfers:
        buf.append((ap & 1) | ((rw & 1) << 1) | ((a & 3) << 2))
        if rw == 0:
            buf.extend(struct.pack('<I', wd))
    s.settimeout(timeout)
    s.sendall(bytes(buf))
    r = s.recv(4096)
    cnt, ack = r[1], r[2]
    data, off = [], 3
    for i in range(cnt):
        ap, rw, a, _ = transfers[i]
        if rw == 1 and off + 4 <= len(r):
            data.append(struct.unpack_from('<I', r, off)[0])
            off += 4
    return cnt, ack, data

def read_block(s, addr, wcount):
    xfer(s, [(1, 0, 1, addr)])  # TAR
    return xfer(s, [(1, 1, 3, 0)] * wcount)  # DRW x wcount

try:
    log(f"=== elaphureLink Speed Test ===")
    log(f"Host: {HOST}:{PORT}")
    log(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # Handshake
    r = sr(s, bytes([0x8a, 0x65, 0x6c, 0x70] + [0]*4 + [1, 0, 0, 0]))
    log(f"Handshake: OK ({r.hex()})")

    # SWD Init
    time.sleep(0.2)
    sr(s, bytes([0x02, 0x01]))  # Connect SWD
    time.sleep(0.2)
    sr(s, bytes([0x11]) + struct.pack('<I', 1000000))  # Clock 1MHz
    time.sleep(0.2)
    sr(s, bytes([0x13, 0x00]))  # SWD_Config
    time.sleep(0.2)
    seq = bytearray([0x12, 136]) + bytearray([0xFF]*7) + bytearray([0x9E, 0xE7]) + bytearray([0xFF]*7) + bytearray([0x00])
    sr(s, bytes(seq))
    time.sleep(0.2)

    cnt, ack, d = xfer(s, [(0, 1, 0, 0)])  # DPIDR
    log(f"DPIDR: 0x{d[0]:08X}")
    time.sleep(0.2)

    cnt, ack, d = xfer(s, [(0, 0, 1, 0x50000000)])  # power up
    log(f"Power up write: cnt={cnt} ack={ack}")
    time.sleep(0.5)
    
    cnt, ack, d = xfer(s, [(0, 1, 1, 0)])
    log(f"CTRL/STAT: 0x{d[0]:08X}" if d else f"CTRL/STAT: FAIL cnt={cnt} ack={ack}")
    time.sleep(0.2)

    xfer(s, [(0, 0, 2, 0x00000000)])  # SELECT AP0
    time.sleep(0.2)
    xfer(s, [(1, 0, 0, 0x23000052)])  # CSW 32bit autoinc
    time.sleep(0.2)
    log(f"SWD Init: OK")

    # Verify read
    cnt, ack, d = read_block(s, 0x08000000, 4)
    log(f"Verify @0x08000000: cnt={cnt} data=[{', '.join(f'0x{v:08X}' for v in d)}]")

    # ========== Speed Tests ==========
    log(f"\n--- READ Speed Tests ---")
    
    results = []
    for wpb in [4, 8, 16, 32]:
        total_target = 4096  # 4KB per test
        blocks = total_target // (wpb * 4)
        if blocks < 1:
            blocks = 1
        total_bytes = 0
        errors = 0
        
        time.sleep(0.3)  # Small delay before each test
        t0 = time.time()
        for b in range(blocks):
            addr = 0x08000000 + b * wpb * 4
            try:
                cnt, ack, data = read_block(s, addr, wpb)
                if cnt > 0:
                    total_bytes += cnt * 4
                else:
                    errors += 1
                    log(f"  Block {b} fail: cnt={cnt} ack={ack}")
                    if errors > 3:
                        break
            except Exception as ex:
                errors += 1
                log(f"  Block {b} exception: {ex}")
                if errors > 3:
                    break
        t1 = time.time()
        dt = t1 - t0
        
        if total_bytes > 0 and dt > 0:
            speed_kBs = total_bytes / dt / 1024
            speed_kbps = total_bytes * 8 / dt / 1000
            result = f"WPB={wpb:2d}: {total_bytes}B / {dt:.3f}s = {speed_kBs:.1f} KB/s ({speed_kbps:.1f} kbit/s) [errors={errors}]"
            results.append((wpb, total_bytes, dt, speed_kBs, speed_kbps))
        else:
            result = f"WPB={wpb:2d}: FAILED (total={total_bytes}B, errors={errors})"
        log(result)
    
    # Large block test: 16KB
    log(f"\n--- 16KB Read Test (WPB=16) ---")
    WPB = 16
    TARGET = 16384
    blocks = TARGET // (WPB * 4)
    total_bytes = 0
    time.sleep(0.5)
    t0 = time.time()
    for b in range(blocks):
        addr = 0x08000000 + b * WPB * 4
        try:
            cnt, ack, data = read_block(s, addr, WPB)
            if cnt > 0:
                total_bytes += cnt * 4
            else:
                log(f"  Block {b} fail: cnt={cnt}")
                break
        except Exception as ex:
            log(f"  Block {b} exception: {ex}")
            break
    t1 = time.time()
    dt = t1 - t0
    if total_bytes > 0:
        log(f"16KB: {total_bytes}B / {dt:.3f}s = {total_bytes/dt/1024:.1f} KB/s ({total_bytes*8/dt/1000:.1f} kbit/s)")
    
    s.close()
    log(f"\n=== TEST COMPLETE ===")

except Exception as e:
    log(f"ERROR: {e}")
    import traceback
    tb = traceback.format_exc()
    log(tb)

rf.close()
print(f"\nResults saved to {RESULT_FILE}")
