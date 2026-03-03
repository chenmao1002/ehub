"""Wireshark-like TCP stream monitor — run this alongside OpenOCD to see what's happening"""
import socket, select, struct, time, sys, threading

HOST = "ehub.local"
PORT = 6000
SIGNATURE = 0x00504144

def main():
    # Create a proxy: PC connects to local:6001, we relay to ESP32:6000
    # This lets us see all traffic in both directions
    
    proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy.bind(('0.0.0.0', 6001))
    proxy.listen(1)
    print(f"Proxy listening on port 6001. Configure OpenOCD to connect to localhost:6001")
    print(f"Waiting for connection...")
    
    client, addr = proxy.accept()
    print(f"Client connected from {addr}")
    
    # Connect to ESP32
    remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote.settimeout(10)
    remote.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"Connecting to {HOST}:{PORT}...")
    remote.connect((HOST, PORT))
    print(f"Connected to ESP32!")
    
    client.setblocking(False)
    remote.setblocking(False)
    
    cmd_count = 0
    
    while True:
        readable, _, _ = select.select([client, remote], [], [], 1.0)
        
        for sock in readable:
            if sock is client:
                # Data from OpenOCD → ESP32
                try:
                    data = client.recv(4096)
                    if not data:
                        print("Client disconnected")
                        return
                    cmd_count += 1
                    t = time.time()
                    
                    # Parse header
                    if len(data) >= 8:
                        sig, length, ptype = struct.unpack_from('<IHB', data)
                        if sig == SIGNATURE:
                            payload = data[8:8+length] if len(data) >= 8+length else data[8:]
                            cmd_byte = payload[0] if payload else 0xFF
                            cmd_name = {0x00: "DAP_Info", 0x02: "DAP_Connect", 0x03: "DAP_Disconnect",
                                       0x04: "DAP_Write_ABORT", 0x05: "DAP_Transfer", 
                                       0x06: "DAP_TransferBlock", 0x08: "DAP_TransferConfigure",
                                       0x11: "DAP_SWJ_Clock", 0x12: "DAP_SWJ_Sequence",
                                       0x13: "DAP_SWD_Configure", 0x17: "DAP_SWJ_Pins"}.get(cmd_byte, f"0x{cmd_byte:02X}")
                            info_id = ""
                            if cmd_byte == 0x00 and len(payload) >= 2:
                                info_id = f"({payload[1]:02X})"
                            print(f"[{t:.3f}] OCD→ESP #{cmd_count}: {cmd_name}{info_id} ({len(data)}B) payload={payload[:8].hex()}")
                        else:
                            print(f"[{t:.3f}] OCD→ESP #{cmd_count}: raw ({len(data)}B) {data[:20].hex()}")
                    
                    remote.sendall(data)
                except ConnectionError:
                    print("Client error")
                    return
                    
            if sock is remote:
                # Data from ESP32 → OpenOCD
                try:
                    data = remote.recv(4096)
                    if not data:
                        print("Remote disconnected")
                        return
                    t = time.time()
                    
                    if len(data) >= 8:
                        sig, length, ptype = struct.unpack_from('<IHB', data)
                        if sig == SIGNATURE:
                            payload = data[8:8+length] if len(data) >= 8+length else data[8:]
                            print(f"[{t:.3f}] ESP→OCD: rsp ({len(data)}B, payload={length}B) first_bytes={payload[:8].hex()}")
                        else:
                            print(f"[{t:.3f}] ESP→OCD: raw ({len(data)}B) {data[:20].hex()}")
                    else:
                        print(f"[{t:.3f}] ESP→OCD: partial ({len(data)}B) {data.hex()}")
                    
                    client.sendall(data)
                except ConnectionError:
                    print("Remote error")
                    return

if __name__ == "__main__":
    main()
