"""Read from COM18 (CH340) to check if we can see ESP32 TX data.
CH340 RX is on the same line as MCU PA3 (RX) / ESP32 GPIO1 (TX).
If we see data, CH340 is functional and connected."""
import serial, time, sys

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM18'
BAUD = 1000000  # Match the bridge baud rate

print(f"Opening {PORT} at {BAUD} baud...")
try:
    ser = serial.Serial(PORT, BAUD, timeout=0.5)
except Exception as e:
    print(f"Cannot open {PORT}: {e}")
    print("If COM18 is in use, the CH340 TX may be actively driven!")
    sys.exit(1)

time.sleep(0.1)
ser.reset_input_buffer()

print(f"Listening for 6 seconds...")
total = 0
for i in range(12):
    data = ser.read(1024)
    if data:
        total += len(data)
        # Check if it looks like bridge frames (BB 55 E0 ...)
        hex_preview = data[:32].hex()
        print(f"  [{i*0.5:.1f}s] Got {len(data)}B: {hex_preview}...")
    else:
        print(f"  [{i*0.5:.1f}s] (no data)")

print(f"\nTotal: {total} bytes in 6s")
if total > 0:
    print("CH340 is receiving ESP32 TX data — CH340 is connected and powered.")
else:
    print("No data — CH340 may not be receiving ESP32 TX.")

ser.close()
