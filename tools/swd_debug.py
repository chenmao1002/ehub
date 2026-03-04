"""Step-by-step SWD init test via elaphureLink."""
import socket, struct, time

HOST = '192.168.227.100'
PORT = 3240

def hexdump(data):
    return ' '.join(f'{b:02x}' for b in data)

sock = socket.create_connection((HOST, PORT), timeout=5)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

# Handshake
req = struct.pack('>III', 0x8a656c70, 0, 1)
sock.sendall(req)
sock.settimeout(3)
res = sock.recv(256)
print(f'Handshake: {hexdump(res)}')

def dap(name, cmd, timeout=5):
    print(f'\n{name}')
    print(f'  TX ({len(cmd)}B): {hexdump(cmd)}')
    sock.sendall(cmd)
    sock.settimeout(timeout)
    try:
        r = sock.recv(1024)
        print(f'  RX ({len(r)}B): {hexdump(r)}')
        return r
    except socket.timeout:
        print(f'  RX: TIMEOUT')
        return None

# Step-by-step SWD init
dap('1. DAP_Connect(SWD)', bytes([0x02, 0x01]))
time.sleep(0.1)

dap('2. DAP_SWJ_Clock(1MHz)', bytes([0x11]) + struct.pack('<I', 1000000))
time.sleep(0.1)

dap('3. DAP_TransferConfigure', bytes([0x04, 0x00, 0x50, 0x00, 0x00, 0x00]))
time.sleep(0.1)

dap('4. DAP_SWD_Configure', bytes([0x13, 0x00]))
time.sleep(0.1)

# Standard JTAG-to-SWD switch: line reset + switch code + line reset + idle
seq = bytes([0xFF]*8 + [0x9E, 0xE7] + [0xFF]*8 + [0x00, 0x00])
dap('5. DAP_SWJ_Sequence (JTAG-to-SWD switch)', bytes([0x12, len(seq)*8 & 0xFF]) + seq)
time.sleep(0.2)

# Read DPIDR
r = dap('6. DAP_Transfer: Read DPIDR', bytes([0x05, 0x00, 0x01, 0x02]), timeout=10)
if r and len(r) >= 7:
    dpidr = struct.unpack_from('<I', r, 3)[0]
    print(f'  DPIDR = 0x{dpidr:08X}')

    # Power up debug
    val = struct.pack('<I', 0x50000000)
    dap('7. Write CTRL/STAT', bytes([0x05, 0x00, 0x01, 0x04]) + val)
    time.sleep(0.1)

    r = dap('8. Read CTRL/STAT', bytes([0x05, 0x00, 0x01, 0x06]))
    if r and len(r) >= 7:
        cs = struct.unpack_from('<I', r, 3)[0]
        print(f'  CTRL/STAT = 0x{cs:08X}')

    # Select AP0 bank0
    val = struct.pack('<I', 0x00000000)
    dap('9. Write SELECT', bytes([0x05, 0x00, 0x01, 0x08]) + val)
    time.sleep(0.1)

    # Write AP CSW
    csw = struct.pack('<I', 0x23000012)
    dap('10. Write AP CSW', bytes([0x05, 0x00, 0x01, 0x01]) + csw)
    time.sleep(0.1)

    # Write TAR = 0x08000000
    tar = struct.pack('<I', 0x08000000)
    dap('11. Write AP TAR', bytes([0x05, 0x00, 0x01, 0x05]) + tar)
    time.sleep(0.1)

    # Read DRW (x4 times for 16 bytes)
    r = dap('12. Read AP DRW x4', bytes([0x05, 0x00, 0x04, 0x0F, 0x0F, 0x0F, 0x0F]), timeout=10)
    if r and len(r) > 3:
        print(f'  count={r[1]} resp=0x{r[2]:02x}')
        for i in range(0, min(16, len(r)-3), 4):
            if i+4+3 <= len(r):
                w = struct.unpack_from('<I', r, 3+i)[0]
                print(f'  [0x{0x08000000+i:08X}] = 0x{w:08X}')

sock.close()
print('\nDone')
