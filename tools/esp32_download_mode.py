"""
esp32_download_mode.py - 让 ESP32 进入下载模式
================================================
通过 USB CDC 向 MCU 发送 Bridge 命令 (CH=0xE0, subcmd=0x04)
MCU 会:
  1. 停止 USART2 DMA
  2. HAL_UART_DeInit(&huart2) 释放 PA2/PA3
  3. 拉低 BOOT, 复位 ESP32, 释放 BOOT
  4. ESP32 进入 bootloader, PA2/PA3 空闲供外部烧录

之后可以用 esptool / PlatformIO 通过 COM18 刷写 ESP32
刷完后重刷/复位 MCU 即可恢复 USART2 通信

用法:
  python esp32_download_mode.py              # 默认 COM19
  python esp32_download_mode.py --port COM5  # 指定端口
"""
import argparse
import serial
import sys
import time

DEFAULT_PORT = "COM19"

def main():
    parser = argparse.ArgumentParser(description="ESP32 Enter Download Mode")
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"MCU CDC COM port (default: {DEFAULT_PORT})")
    args = parser.parse_args()
    
    # Bridge frame: [0xAA][0x55][0xE0][0x00][0x01][0x04][CRC=0x04]
    frame = bytes([0xAA, 0x55, 0xE0, 0x00, 0x01, 0x04, 0x04])
    
    try:
        s = serial.Serial(args.port, 115200, timeout=1)
        s.write(frame)
        s.flush()
        time.sleep(0.5)
        s.close()
        print(f"[OK] ESP32 download mode - USART2 released")
        print(f"     Now flash via: pio run -t upload --upload-port COM18")
        print(f"     Then reflash MCU to restore USART2")
    except serial.SerialException as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
