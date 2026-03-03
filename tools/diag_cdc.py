"""
Test DAP path: sends DAP command via WiFi TCP, monitors COM19 for MCU debug output.
If MCU processes the DAP command, it sends the response via BOTH WiFi UART and CDC.
"""
import socket, struct, time, threading, serial

HOST = "ehub.local"
COM_PORT = "COM19"

def hexdump(data):
    return " ".join(f"{b:02x}" for b in data) if data else "(none)"

# Thread to monitor COM19
cdc_data = bytearray()
stop_monitor = False

def cdc_monitor():
    global cdc_data, stop_monitor
    try:
        ser = serial.Serial(COM_PORT, 115200, timeout=0.1)
        print(f"  [CDC] Monitoring {COM_PORT}...")
        while not stop_monitor:
            data = ser.read(256)
            if data:
                cdc_data.extend(data)
                print(f"  [CDC] RX ({len(data)}B): {hexdump(data)}")
        ser.close()
    except Exception as e:
        print(f"  [CDC] Error: {e}")

# Start CDC monitor thread
print("=== DAP Path Diagnostic — CDC Monitor ===")
t = threading.Thread(target=cdc_monitor, daemon=True)
t.start()
time.sleep(1)  # Let monitor start

# Wait for WiFi
print(f"\n  Connecting to {HOST}:6000...")
time.sleep(5)  # Wait for ESP32 WiFi boot after MCU reset
try:
    sock = socket.create_connection((HOST, 6000), timeout=5)
except Exception as e:
    print(f"  Connection failed: {e}")
    print("  Trying again in 5s...")
    time.sleep(5)
    sock = socket.create_connection((HOST, 6000), timeout=5)

sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
print(f"  Connected!")

# Send DAP_Info(PacketCount)
cmd = bytes([0x00, 0xFE])
header = struct.pack('<IHBx', 0x00504144, len(cmd), 0x01)
print(f"\n  [TCP] TX: {hexdump(header + cmd)}")
sock.sendall(header + cmd)

# Wait for response on TCP
sock.settimeout(5)
try:
    resp = sock.recv(512)
    print(f"  [TCP] RX ({len(resp)}B): {hexdump(resp)}")
except socket.timeout:
    print(f"  [TCP] RX: TIMEOUT")

# Wait a bit more for any CDC data
time.sleep(2)

# Send another command
cmd2 = bytes([0x00, 0x01])  # DAP_Info(Vendor)
header2 = struct.pack('<IHBx', 0x00504144, len(cmd2), 0x01)
print(f"\n  [TCP] TX: {hexdump(header2 + cmd2)}")
sock.sendall(header2 + cmd2)

sock.settimeout(5)
try:
    resp = sock.recv(512)
    print(f"  [TCP] RX ({len(resp)}B): {hexdump(resp)}")
except socket.timeout:
    print(f"  [TCP] RX: TIMEOUT")

time.sleep(2)
sock.close()

# Check ESP32 debug counters
print(f"\n=== ESP32 Debug Counters ===")

def calc_crc(ch, length, data):
    crc = ch ^ ((length >> 8) & 0xFF) ^ (length & 0xFF)
    for b in data: crc ^= b
    return crc & 0xFF

def build_frame(ch, data):
    length = len(data)
    frame = bytearray([0xAA, 0x55, ch, (length >> 8) & 0xFF, length & 0xFF])
    frame.extend(data)
    frame.append(calc_crc(ch, length, data))
    return bytes(frame)

try:
    s2 = socket.create_connection((HOST, 5000), timeout=3)
    s2.sendall(build_frame(0xE0, bytes([0xF0])))
    s2.settimeout(3)
    resp = s2.recv(512)
    if len(resp) > 6 and resp[0] == 0xBB:
        data = resp[5:5+((resp[3]<<8)|resp[4])]
        if data[0] == 0xF0 and len(data) >= 49:
            pos = 1
            labels = ['TCP_Read', 'UART_TX', 'UART_RX', 'TCP_Send', 'Timeout', 'UART_BytesRX', 'UART_FramesRX']
            for l in labels:
                v = struct.unpack_from('<I', data, pos)[0]; pos += 4
                print(f"  {l:15s}: {v}")
    s2.close()
except Exception as e:
    print(f"  Error: {e}")

# Summary
stop_monitor = True
time.sleep(0.5)
print(f"\n=== Summary ===")
print(f"  Total CDC bytes received: {len(cdc_data)}")
if len(cdc_data) > 0:
    print(f"  CDC data: {hexdump(cdc_data[:64])}")
    print(f"  ✓ MCU IS processing DAP commands — issue is USART2 TX → ESP32 RX")
else:
    print(f"  ✗ MCU did NOT process any DAP commands!")
    print(f"    MCU either didn't receive the UART data, or WiFi_Bridge_Task isn't running")
