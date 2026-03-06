#!/usr/bin/env python3
"""Query MCU F1 counters and ESP32 F0 counters, write to file."""
import serial, socket, struct, time, sys

out = open("C:/Users/MC/Desktop/diag_result.txt", "w")

def log(msg):
    out.write(msg + "\n")
    out.flush()

# === MCU F1 via CDC ===
log("=== MCU F1 Counters ===")
try:
    s = serial.Serial('COM19', 115200, timeout=2)
    f = bytearray([0xAA, 0x55, 0xE0, 0x00, 0x01, 0xF1])
    crc = 0xE0 ^ 0 ^ 1 ^ 0xF1
    f.append(crc)
    s.write(f)
    time.sleep(0.5)
    d = s.read(256)
    log(f"Raw ({len(d)} bytes): {d.hex()}")
    
    # Parse first frame
    if len(d) >= 5 and d[0] == 0xBB and d[1] == 0x55:
        flen = (d[3] << 8) | d[4]
        data = d[5:5+flen]
        log(f"Frame CH=0x{d[2]:02X} LEN={flen}")
        if len(data) >= 41 and data[0] == 0xF1:
            fields = []
            for i in range(10):
                v = struct.unpack_from('<I', data, 1 + i*4)[0]
                fields.append(v)
            names = ['tx_ok','tx_fail','rx_event','rx_bytes','error','frames',
                     'dma_init_rc','USART2_SR','USART2_BRR','gState']
            for name, val in zip(names, fields):
                if name == 'USART2_SR':
                    log(f"  {name:20s} = 0x{val:08X}")
                elif name == 'USART2_BRR':
                    brr16 = val & 0xFFFF
                    mant = brr16 >> 4
                    frac = brr16 & 0xF
                    usartdiv = mant + frac/16
                    baud_calc = 30000000 / (16 * usartdiv) if usartdiv > 0 else 0
                    log(f"  {name:20s} = 0x{val:08X} (lower16=0x{brr16:04X}, mant={mant}, frac={frac}, USARTDIV={usartdiv:.4f}, baud≈{baud_calc:.0f})")
                elif name == 'gState':
                    log(f"  {name:20s} = 0x{val:08X}")
                else:
                    log(f"  {name:20s} = {val}")
    s.close()
except Exception as e:
    log(f"MCU error: {e}")

# === Quick DAP test ===
log("\n=== Quick DAP Test (5 commands) ===")
try:
    sk = socket.socket()
    sk.settimeout(5)
    sk.connect(('ehub.local', 3240))
    sk.send(bytes(12))
    r = sk.recv(64)
    log(f"Handshake: {r.hex()}")
    
    ok = fail = 0
    for i in range(5):
        cmd = bytes([0x00, 0x04, 0x00, 0x00]) + bytes([0x00, 0x00])
        sk.send(cmd)
        try:
            r = sk.recv(512)
            log(f"  Cmd {i+1}: OK ({len(r)} bytes)")
            ok += 1
        except socket.timeout:
            log(f"  Cmd {i+1}: TIMEOUT")
            fail += 1
            sk.close()
            time.sleep(0.5)
            sk = socket.socket()
            sk.settimeout(5)
            sk.connect(('ehub.local', 3240))
            sk.send(bytes(12))
            sk.recv(64)
    sk.close()
    log(f"\nResult: {ok}/5 OK, {fail}/5 FAIL")
except Exception as e:
    log(f"DAP error: {e}")

out.close()
print("DONE")
