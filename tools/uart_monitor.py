#!/usr/bin/env python3
"""Monitor COM18 (CH340) to see if MCU USART2 TX data appears.
If MCU PA2 → ESP32 GPIO3 → CH340 RX, we should see MCU's bridge frames."""
import serial, time, sys

out = open("C:/Users/MC/Desktop/uart_monitor.txt", "w")
def log(msg):
    out.write(msg + "\n")
    out.flush()

log("=== UART Monitor on COM18 ===")
log("Opening COM18 at 1Mbaud...")

try:
    s = serial.Serial('COM18', 1000000, timeout=2)
    log(f"Opened: {s.port}@{s.baudrate}")
    
    # Read for 10 seconds
    total = 0
    for i in range(5):
        time.sleep(2)
        avail = s.in_waiting
        if avail > 0:
            data = s.read(avail)
            total += len(data)
            log(f"  t={2*(i+1)}s: Got {len(data)} bytes: {data[:50].hex()}")
        else:
            log(f"  t={2*(i+1)}s: No data")
    
    log(f"\nTotal bytes received: {total}")
    if total > 0:
        log("CONCLUSION: MCU PA2 signal reaches CH340 RX (and ESP32 GPIO3)")
    else:
        log("CONCLUSION: NO data on COM18 — MCU PA2 is NOT reaching ESP32 GPIO3/CH340")
    
    s.close()
except Exception as e:
    log(f"Error: {e}")

out.close()
print("DONE_MONITOR")
