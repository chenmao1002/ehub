"""Minimal elaphureLink test - diagnose connectivity"""
import socket, struct, time

HOST = "192.168.227.100"
PORT = 3240
RESULT = "elink_diag.txt"

f = open(RESULT, "w")
def log(msg):
    print(msg, flush=True)
    f.write(msg+"\n"); f.flush()

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    log("TCP connected")

    # Handshake
    s.sendall(bytes([0x8a,0x65,0x6c,0x70,0,0,0,0,1,0,0,0]))
    r = s.recv(12)
    log(f"Handshake: {r.hex()} ({'OK' if r[:4]==bytes([0x8a,0x65,0x6c,0x70]) else 'FAIL'})")
    
    time.sleep(1)
    
    # DAP_Connect SWD (cmd 0x02, port 0x01)
    log("Sending DAP_Connect SWD...")
    s.settimeout(20)
    s.sendall(bytes([0x02, 0x01]))
    try:
        r = s.recv(256)
        log(f"DAP_Connect: {r.hex()}")
    except socket.timeout:
        log("DAP_Connect: TIMEOUT (20s)")
        s.close(); f.close()
        exit()
    
    time.sleep(0.5)
    
    # DAP_SWJ_Clock 1MHz
    log("Sending DAP_SWJ_Clock...")
    s.sendall(bytes([0x11]) + struct.pack('<I', 1000000))
    try:
        r = s.recv(256)
        log(f"DAP_SWJ_Clock: {r.hex()}")
    except socket.timeout:
        log("DAP_SWJ_Clock: TIMEOUT")
        s.close(); f.close()
        exit()
    
    time.sleep(0.5)
    
    # DAP_SWD_Configure
    log("Sending DAP_SWD_Configure...")
    s.sendall(bytes([0x13, 0x00]))
    try:
        r = s.recv(256)
        log(f"DAP_SWD_Configure: {r.hex()}")
    except socket.timeout:
        log("DAP_SWD_Configure: TIMEOUT")
        s.close(); f.close()
        exit()
    
    time.sleep(0.5)
    
    # SWJ Sequence
    log("Sending SWJ_Sequence (136 bits)...")
    seq = bytearray([0x12, 136])
    seq.extend([0xFF]*7)  # 56 bits high
    seq.extend([0x9E, 0xE7])  # SWD select
    seq.extend([0xFF]*7)  # 56 bits high
    seq.append(0x00)  # 8 bits low
    s.sendall(bytes(seq))
    try:
        r = s.recv(256)
        log(f"SWJ_Sequence: {r.hex()}")
    except socket.timeout:
        log("SWJ_Sequence: TIMEOUT")
        s.close(); f.close()
        exit()
    
    time.sleep(0.5)
    
    # DAP_Transfer: read DPIDR
    log("Reading DPIDR...")
    s.sendall(bytes([0x05, 0x00, 0x01, 0x02]))  # DP Read A[3:2]=0
    try:
        r = s.recv(256)
        if len(r) >= 7:
            dpidr = struct.unpack_from('<I', r, 3)[0]
            log(f"DPIDR: 0x{dpidr:08X} (raw: {r.hex()})")
        else:
            log(f"DPIDR short response: {r.hex()}")
    except socket.timeout:
        log("DPIDR: TIMEOUT")
    
    log("Basic test complete")
    s.close()

except Exception as e:
    log(f"Error: {e}")
    import traceback
    log(traceback.format_exc())

f.close()
