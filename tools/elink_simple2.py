"""elaphureLink speed test - simple"""
import socket, struct, time, sys

HOST = "192.168.227.100"
PORT = 3240
OUT = open("elink_result.txt", "w")

def log(msg):
    log(msg, flush=True)
    OUT.write(msg + "\n")
    OUT.flush()

def sr(s, d, t=15):
    s.settimeout(t)
    s.sendall(d)
    return s.recv(4096)

def xfer(s, transfers, idx=0):
    buf = bytearray([0x05, idx, len(transfers)])
    for ap, rw, a, wd in transfers:
        buf.append((ap&1)|((rw&1)<<1)|((a&3)<<2))
        if rw==0: buf.extend(struct.pack('<I', wd))
    r = sr(s, bytes(buf))
    cnt, ack = r[1], r[2]
    data, off = [], 3
    for i in range(cnt):
        ap, rw, a, _ = transfers[i]
        if rw==1 and off+4<=len(r):
            data.append(struct.unpack_from('<I',r,off)[0]); off+=4
    return cnt, ack, data

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # Handshake
    r = sr(s, bytes([0x8a,0x65,0x6c,0x70]+[0]*4+[1,0,0,0]))
    log(f"Handshake: {r.hex()}")

    # SWD init
    sr(s, bytes([0x02,0x01]))
    sr(s, bytes([0x11])+struct.pack('<I',1000000))
    sr(s, bytes([0x13,0x00]))
    seq = bytearray([0x12,136])+bytearray([0xFF]*7)+bytearray([0x9E,0xE7])+bytearray([0xFF]*7)+bytearray([0x00])
    sr(s, bytes(seq))
    cnt,ack,d = xfer(s, [(0,1,0,0)])
    log(f"DPIDR = 0x{d[0]:08X}")
    xfer(s, [(0,0,1,0x50000000)])
    time.sleep(0.1)
    cnt,ack,d = xfer(s, [(0,1,1,0)])
    log(f"CTRL/STAT = 0x{d[0]:08X}")
    xfer(s, [(0,0,2,0x00000000)])
    xfer(s, [(1,0,0,0x23000052)])
    log("SWD init OK")

    # Verify read
    xfer(s, [(1,0,1,0x08000000)])
    cnt,ack,d = xfer(s, [(1,1,3,0)]*4)
    log(f"Verify: cnt={cnt} data={[f'0x{v:08X}' for v in d]}")

    # Speed tests
    for wpb in [4, 8, 16]:
        blocks = 4096 // (wpb * 4)
        total = 0
        t0 = time.time()
        for b in range(blocks):
            addr = 0x08000000 + b * wpb * 4
            xfer(s, [(1,0,1,addr)])
            cnt,ack,data = xfer(s, [(1,1,3,0)]*wpb)
            if cnt > 0:
                total += cnt * 4
            else:
                log(f"Block {b} fail: cnt={cnt} ack={ack}")
                break
        t1 = time.time()
        dt = t1 - t0
        log(f"WPB={wpb:2d}: {total}B / {dt:.3f}s = {total/dt/1024:.1f} KB/s ({total*8/dt/1000:.1f} kbit/s)")

    s.close()
    log("DONE")
except Exception as e:
    log(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

