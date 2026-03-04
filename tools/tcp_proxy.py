"""TCP proxy: capture OpenOCD ←→ ESP32 DAP TCP traffic."""
import socket, select, struct, sys

LOCAL_PORT = 6001
REMOTE_HOST = "192.168.227.100"
REMOTE_PORT = 6000
DAP_SIG = b'\x44\x41\x50\x00'

CMD_NAMES = {
    0x00:'Info', 0x01:'HostStatus', 0x02:'Connect', 0x03:'Disconnect',
    0x04:'WriteAbort', 0x05:'Transfer', 0x06:'TransferBlock',
    0x08:'TransferCfg', 0x10:'SWJ_Pins', 0x11:'SWJ_Clock',
    0x12:'SWJ_Seq', 0x13:'SWD_Cfg',
}

def log_pkt(num, direction, data):
    """Parse and log one TCP chunk."""
    pos = 0
    while pos + 8 <= len(data):
        sig = data[pos:pos+4]
        if sig != DAP_SIG:
            print(f"  [{num}] {direction} BAD_SIG @ offset {pos}: {data[pos:pos+16].hex()}")
            return
        plen = struct.unpack_from('<H', data, pos+4)[0]
        ptype = data[pos+6]
        if pos + 8 + plen > len(data):
            print(f"  [{num}] {direction} INCOMPLETE plen={plen} avail={len(data)-pos-8}")
            return
        payload = data[pos+8:pos+8+plen]
        cmd = payload[0] if payload else 0xFF
        name = CMD_NAMES.get(cmd, f'0x{cmd:02X}')
        tstr = 'REQ' if ptype == 1 else 'RSP'

        extra = ''
        if cmd == 0x06:
            if ptype == 1 and plen >= 5:
                cnt = struct.unpack_from('<H', payload, 2)[0]
                extra = f" count={cnt}"
            elif ptype == 2 and plen >= 4:
                cnt = struct.unpack_from('<H', payload, 1)[0]
                st = payload[3]
                extra = f" count={cnt} st=0x{st:02X} datalen={plen-4}"
        elif cmd == 0x05:
            if ptype == 1 and plen >= 3:
                cnt = payload[2]
                extra = f" count={cnt}"
            elif ptype == 2 and plen >= 3:
                cnt = payload[1]; st = payload[2]
                extra = f" count={cnt} st=0x{st:02X}"

        print(f"  [{num}] {direction} {tstr} {name:16s} len={plen}{extra}")
        pos += 8 + plen
        num += 1
    return num

def main():
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', LOCAL_PORT)); srv.listen(1)
    print(f"Proxy: :{LOCAL_PORT} → {REMOTE_HOST}:{REMOTE_PORT}")
    cli, addr = srv.accept()
    cli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"Client: {addr}")
    rem = socket.socket()
    rem.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    rem.connect((REMOTE_HOST, REMOTE_PORT))
    print("Connected to ESP32\n")
    n = 0
    try:
        while True:
            r, _, _ = select.select([cli, rem], [], [], 60)
            if not r:
                print("Timeout"); break
            for s in r:
                d = s.recv(8192)
                if not d: raise SystemExit
                if s is cli:
                    nn = log_pkt(n, '>>>', d)
                    if nn: n = nn
                    else: n += 1
                    rem.sendall(d)
                else:
                    nn = log_pkt(n, '<<<', d)
                    if nn: n = nn
                    else: n += 1
                    cli.sendall(d)
    except (KeyboardInterrupt, SystemExit):
        pass
    cli.close(); rem.close(); srv.close()
    print(f"\nDone. {n} events.")

if __name__ == '__main__':
    main()
