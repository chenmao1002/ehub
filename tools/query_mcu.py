"""Query MCU UART2 diagnostic counters via CDC (COM19).
Sends bridge frame with CH=0xE0, subcmd=0xF1 and reads response."""
import serial, struct, time, sys

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM19'
BAUD = 115200

def build_frame(sof0, ch, data):
    sof1 = 0x55
    lh = (len(data) >> 8) & 0xFF
    ll = len(data) & 0xFF
    crc = ch ^ lh ^ ll
    for b in data: crc ^= b
    return bytes([sof0, sof1, ch, lh, ll]) + bytes(data) + bytes([crc & 0xFF])

ser = serial.Serial(PORT, BAUD, timeout=2)
time.sleep(0.1)
ser.reset_input_buffer()

# Send F1 counter query
frame = build_frame(0xAA, 0xE0, bytes([0xF1]))
print(f"TX ({len(frame)}B): {frame.hex()}")
ser.write(frame)
time.sleep(0.5)

# Read response
data = ser.read(256)
if not data:
    print("No response from MCU!")
    ser.close()
    sys.exit(1)

print(f"RX ({len(data)}B): {data.hex()}")

# Find bridge frame in response: BB 55 E0 ...
for start in range(len(data) - 5):
    if data[start] == 0xBB and data[start+1] == 0x55 and data[start+2] == 0xE0:
        plen = (data[start+3] << 8) | data[start+4]
        payload = data[start+5:start+5+plen]
        if payload[0] == 0xF1 and len(payload) >= 41:
            pos = 1
            names = ['tx_ok', 'tx_fail', 'rx_event', 'rx_bytes', 'error', 'frames',
                     'dma_init_rc', 'uart2_sr', 'dma_cr', 'dma_ndtr']
            for name in names:
                if pos + 4 <= len(payload):
                    val = struct.unpack('<I', payload[pos:pos+4])[0]
                    if name in ('uart2_sr', 'dma_cr'):
                        print(f"  {name:16s} = 0x{val:08X}")
                    else:
                        print(f"  {name:16s} = {val}")
                    pos += 4
            
            # Interpret key values
            sr = struct.unpack('<I', payload[29:33])[0]
            print()
            print(f"  USART2_SR flags: ", end="")
            flags = []
            if sr & (1<<7): flags.append("TXE")
            if sr & (1<<6): flags.append("TC")
            if sr & (1<<5): flags.append("RXNE")
            if sr & (1<<4): flags.append("IDLE")
            if sr & (1<<3): flags.append("ORE")
            if sr & (1<<2): flags.append("NE")
            if sr & (1<<1): flags.append("FE")
            if sr & (1<<0): flags.append("PE")
            print(" | ".join(flags) if flags else "(none)")
            
            dma_cr = struct.unpack('<I', payload[33:37])[0]
            dma_en = "ENABLED" if (dma_cr & 1) else "DISABLED"
            print(f"  DMA RX: {dma_en}")
            
            break
        break

ser.close()
