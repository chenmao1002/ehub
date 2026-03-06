"""Quick check: is MCU actively transmitting UART data right now?
Open COM18 at 1Mbaud and listen for a few seconds."""
import serial, time

ser = serial.Serial('COM18', 1000000, timeout=0.5)
print("Listening on COM18 at 1Mbaud for 4 seconds...")
start = time.time()
total = 0
while time.time() - start < 4:
    data = ser.read(256)
    if data:
        total += len(data)
        print(f"  [{time.time()-start:.1f}s] Got {len(data)} bytes: {data[:32].hex()}")

ser.close()
print(f"\nTotal bytes received: {total}")
if total == 0:
    print("MCU is NOT transmitting on USART2 TX!")
else:
    print("MCU IS transmitting UART data.")
