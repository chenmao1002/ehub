"""elaphureLink speed test v3 - robust with file output"""
import socket, struct, time

HOST = "192.168.227.100"
PORT = 3240
RF = open("elink_speed_results.txt", "w")

def log(msg):
    print(msg, flush=True)
    RF.write(msg+"\n"); RF.flush()

def sr(s, d, t=20):
    s.settimeout(t); s.sendall(d); return s.recv(4096)

def xfer(s, transfers, idx=0):
    buf = bytearray([0x05, idx, len(transfers)])
    for ap, rw, a, wd in transfers:
        buf.append((ap&1)|((rw&1)<<1)|((a&3)<<2))
        if rw==0: buf.extend(struct.pack('<I', wd))
    s.settimeout(20); s.sendall(bytes(buf))
    r = s.recv(4096)
    cnt, ack = r[1], r[2]
    data, off = [], 3
    for i in range(cnt):
        if transfers[i][1]==1 and off+4<=len(r):
            data.append(struct.unpack_from('<I',r,off)[0]); off+=4
    return cnt, ack, data

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10); s.connect((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    # Handshake
    r = sr(s, bytes([0x8a,0x65,0x6c,0x70,0,0,0,0,1,0,0,0]))
    log(f"Handshake: OK")
    time.sleep(0.5)
    
    # SWD Init with delays
    sr(s, bytes([0x02,0x01])); time.sleep(0.3)
    sr(s, bytes([0x11])+struct.pack('<I',1000000)); time.sleep(0.3)
    sr(s, bytes([0x13,0x00])); time.sleep(0.3)
    seq = bytearray([0x12,136])+bytearray([0xFF]*7)+bytearray([0x9E,0xE7])+bytearray([0xFF]*7)+bytearray([0x00])
    sr(s, bytes(seq)); time.sleep(0.3)
    
    cnt,ack,d = xfer(s, [(0,1,0,0)])
    log(f"DPIDR: 0x{d[0]:08X}")
    time.sleep(0.3)
    
    xfer(s, [(0,0,1,0x50000000)]); time.sleep(0.5)
    cnt,ack,d = xfer(s, [(0,1,1,0)])
    log(f"CTRL/STAT: 0x{d[0]:08X}")
    time.sleep(0.3)
    
    xfer(s, [(0,0,2,0x00000000)]); time.sleep(0.2)
    xfer(s, [(1,0,0,0x23000052)]); time.sleep(0.2)
    log("SWD init OK")
    
    # Verify
    xfer(s, [(1,0,1,0x08000000)]); time.sleep(0.1)
    cnt,ack,d = xfer(s, [(1,1,3,0)]*4)
    log(f"Verify: {[f'0x{v:08X}' for v in d]}")
    time.sleep(0.5)
    
    # ==================== SPEED TESTS ====================
    log("\n=== READ SPEED TESTS ===")
    
    for wpb in [4, 8, 16]:
        total_target = 4096
        blocks = total_target // (wpb * 4)
        total_bytes = 0
        errs = 0
        
        time.sleep(0.5)
        t0 = time.time()
        for b in range(blocks):
            addr = 0x08000000 + b * wpb * 4
            # TAR write
            xfer(s, [(1,0,1,addr)])
            # DRW reads
            cnt,ack,data = xfer(s, [(1,1,3,0)]*wpb)
            if cnt > 0:
                total_bytes += cnt * 4
            else:
                errs += 1
                log(f"  Block {b} fail cnt={cnt} ack={ack}")
                if errs > 2: break
        t1 = time.time()
        dt = t1 - t0
        if total_bytes > 0:
            log(f"WPB={wpb:2d}: {total_bytes}B / {dt:.3f}s = {total_bytes/dt/1024:.1f} KB/s ({total_bytes*8/dt/1000:.1f} kbit/s) errs={errs}")
        else:
            log(f"WPB={wpb:2d}: FAILED errs={errs}")
    
    # 16KB block test
    log("\n=== 16KB READ (WPB=16) ===")
    time.sleep(0.5)
    WPB = 16
    blocks = 16384 // (WPB * 4)
    total_bytes = 0
    t0 = time.time()
    for b in range(blocks):
        addr = 0x08000000 + b * WPB * 4
        xfer(s, [(1,0,1,addr)])
        cnt,ack,data = xfer(s, [(1,1,3,0)]*WPB)
        if cnt > 0:
            total_bytes += cnt * 4
        else:
            log(f"  Block {b} fail")
            break
    t1 = time.time()
    dt = t1 - t0
    if total_bytes > 0:
        log(f"16KB: {total_bytes}B / {dt:.3f}s = {total_bytes/dt/1024:.1f} KB/s ({total_bytes*8/dt/1000:.1f} kbit/s)")
    
    s.close()
    log("\n=== DONE ===")

except Exception as e:
    log(f"ERROR: {e}")
    import traceback; log(traceback.format_exc())
finally:
    try: s.close()
    except: pass
    RF.close()
