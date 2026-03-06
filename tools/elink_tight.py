"""
elaphureLink - tight loop test
No delays between reads, minimal logging
"""
import socket, struct, time, sys

HOST = "192.168.227.100"
PORT = 3240
RF = open("elink_tight.txt", "w")

def log(msg):
    RF.write(msg+"\n"); RF.flush()

def sr(s, d):
    s.settimeout(30); s.sendall(d); return s.recv(4096)

def xfer(s, transfers, idx=0):
    buf = bytearray([0x05, idx, len(transfers)])
    for ap, rw, a, wd in transfers:
        buf.append((ap&1)|((rw&1)<<1)|((a&3)<<2))
        if rw==0: buf.extend(struct.pack('<I', wd))
    r = sr(s, bytes(buf))
    cnt, ack = r[1], r[2]
    data, off = [], 3
    for i in range(cnt):
        if transfers[i][1]==1 and off+4<=len(r):
            data.append(struct.unpack_from('<I',r,off)[0]); off+=4
    return cnt, ack, data

def read_words(s, addr, n):
    transfers = [(1, 0, 1, addr)] + [(1, 1, 3, 0)] * n
    cnt, ack, data = xfer(s, transfers)
    return data

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10); s.connect((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    # Handshake
    sr(s, bytes([0x8a,0x65,0x6c,0x70,0,0,0,0,1,0,0,0]))
    log("Handshake OK")
    time.sleep(0.3)
    
    # Minimal SWD Init
    sr(s, bytes([0x02,0x01])); time.sleep(0.2)
    sr(s, bytes([0x11])+struct.pack('<I',1000000)); time.sleep(0.2)
    sr(s, bytes([0x13,0x00])); time.sleep(0.2)
    seq = bytearray([0x12,136])+bytearray([0xFF]*7)+bytearray([0x9E,0xE7])+bytearray([0xFF]*7)+bytearray([0x00])
    sr(s, bytes(seq)); time.sleep(0.2)
    cnt,ack,d = xfer(s, [(0,1,0,0)])
    log(f"DPIDR 0x{d[0]:08X}")
    time.sleep(0.2)
    xfer(s, [(0,0,1,0x50000000)]); time.sleep(0.3)
    xfer(s, [(0,1,1,0)]); time.sleep(0.1)
    xfer(s, [(0,0,2,0x00000000)]); time.sleep(0.1)
    xfer(s, [(1,0,0,0x23000052)]); time.sleep(0.1)
    log("Init OK")
    
    # Read 1: immediately after init
    d = read_words(s, 0x08000000, 4)
    log(f"Read1 OK: {[hex(v) for v in d]}")
    
    # Read 2-10: tight loop, NO delay
    log("Starting tight loop reads...")
    success = 0
    for i in range(50):
        addr = 0x08000000 + i * 16
        try:
            data = read_words(s, addr, 4)
            if data:
                success += 1
            else:
                log(f"Read {i+2} fail: no data")
                break
        except Exception as e:
            log(f"Read {i+2} exception at addr 0x{addr:08X}: {e}")
            break
    
    log(f"Tight loop: {success}/50 reads succeeded")
    
    if success == 50:
        # Speed test
        log("\n=== SPEED TEST (4KB, WPB=4) ===")
        blocks = 256
        total = 0
        t0 = time.time()
        for b in range(blocks):
            addr = 0x08000000 + b * 16
            data = read_words(s, addr, 4)
            if data: total += len(data) * 4
            else: log(f"Speed fail block {b}"); break
        t1 = time.time()
        dt = t1-t0
        log(f"4KB: {total}B / {dt:.3f}s = {total/dt/1024:.1f} KB/s")
        
        log("\n=== SPEED TEST (4KB, WPB=15) ===")
        blocks = 4096 // (15*4)
        total = 0
        t0 = time.time()
        for b in range(blocks):
            addr = 0x08000000 + b * 60
            data = read_words(s, addr, 15)
            if data: total += len(data) * 4
            else: log(f"Speed fail block {b}"); break
        t1 = time.time()
        dt = t1-t0
        log(f"4KB (WPB=15): {total}B / {dt:.3f}s = {total/dt/1024:.1f} KB/s")
    
    s.close()
    log("\nDONE")
except Exception as e:
    log(f"ERROR: {e}")
    import traceback; log(traceback.format_exc())
finally:
    try: s.close()
    except: pass
    RF.close()
