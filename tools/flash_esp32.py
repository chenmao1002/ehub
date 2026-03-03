"""
flash_esp32.py — 一键刷写 ESP32 固件
===========================================
自动化流程:
  1. 通过 USB CDC 向 MCU 发送 "ESP32 进入下载模式" 命令
     (Bridge协议: CH=0xE0, subcmd=0x04)
     MCU 会: 拉低 BOOT → 复位 ESP32 → 释放 USART2 引脚
  2. 等待 ESP32 进入 bootloader
  3. 调用 PlatformIO 刷写 ESP32 固件
  4. (可选) 重新刷写 MCU 固件以恢复 USART2

用法:
  python flash_esp32.py --mcu-port COM5 --esp-port COM18
  python flash_esp32.py --mcu-port COM5 --esp-port COM18 --skip-mcu
  python flash_esp32.py --mcu-port COM5 --esp-port COM18 --esp-dir ../ESP32_wifi
"""

import argparse
import serial
import subprocess
import sys
import time
import os
import io

# Fix Windows GBK encoding issue
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── Bridge 协议常量 ──
BRIDGE_SOF0_CMD = 0xAA
BRIDGE_SOF1     = 0x55
BRIDGE_CH_WIFI  = 0xE0
SUBCMD_ESP_BOOT = 0x04

# ── 默认配置 ──
DEFAULT_MCU_PORT = "COM19"
DEFAULT_ESP_PORT = "COM18"
DEFAULT_MCU_BAUD = 115200      # CDC 虚拟串口,波特率无实际意义
DEFAULT_ESP_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ESP32_wifi")
DEFAULT_OPENOCD  = "F:/vscode/openstm32/xpack-openocd/xpack-openocd-0.12.0-4/bin/openocd.exe"
DEFAULT_OPENOCD_SCRIPTS = "F:/vscode/openstm32/xpack-openocd/xpack-openocd-0.12.0-4/openocd/scripts"
DEFAULT_OPENOCD_CFG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openocd.cfg")
DEFAULT_HEX_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "Debug", "EHUB.hex")


def build_bridge_frame(ch, data):
    """构建 Bridge 协议帧: [0xAA][0x55][CH][LEN_H][LEN_L][DATA...][CRC8_XOR]"""
    length = len(data)
    frame = bytearray()
    frame.append(BRIDGE_SOF0_CMD)  # SOF0
    frame.append(BRIDGE_SOF1)      # SOF1
    frame.append(ch)               # Channel
    frame.append((length >> 8) & 0xFF)  # LEN_H
    frame.append(length & 0xFF)         # LEN_L
    frame.extend(data)
    # CRC8 = XOR of all data bytes
    crc = 0
    for b in data:
        crc ^= b
    frame.append(crc)
    return bytes(frame)


def send_esp_download_cmd(port, baud=DEFAULT_MCU_BAUD):
    """通过 USB CDC 向 MCU 发送 ESP32 进入下载模式命令"""
    frame = build_bridge_frame(BRIDGE_CH_WIFI, bytes([SUBCMD_ESP_BOOT]))
    print(f"  发送命令到 MCU ({port})...")
    print(f"  帧数据: {frame.hex()}")
    
    try:
        ser = serial.Serial(port, baud, timeout=1)
        ser.write(frame)
        ser.flush()
        time.sleep(0.5)  # 等待 MCU 处理
        ser.close()
        print(f"  ✓ 命令已发送，ESP32 应已进入下载模式")
        return True
    except serial.SerialException as e:
        print(f"  ✗ 串口错误: {e}")
        return False


def flash_esp32(esp_port, esp_dir):
    """使用 PlatformIO 刷写 ESP32"""
    print(f"\n[2] 刷写 ESP32 固件 ({esp_port})...")
    
    cmd = [
        "pio", "run", "-t", "upload",
        "--upload-port", esp_port,
        "-d", esp_dir
    ]
    print(f"  命令: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, cwd=esp_dir)
    if result.returncode == 0:
        print(f"  ✓ ESP32 固件刷写成功")
        return True
    else:
        print(f"  ✗ ESP32 固件刷写失败 (exit code: {result.returncode})")
        return False


def flash_mcu(openocd, scripts_dir, cfg_file, hex_file):
    """使用 OpenOCD 刷写 MCU (顺便复位 MCU, 恢复 USART2)"""
    print(f"\n[3] 刷写 MCU 固件 (OpenOCD)...")
    
    cmd = [
        openocd,
        "-s", scripts_dir,
        "-f", cfg_file,
        "-c", f"program {hex_file} verify reset exit"
    ]
    print(f"  命令: {' '.join(cmd[:4])} ...")
    
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"  ✓ MCU 固件刷写成功，USART2 已恢复")
        return True
    else:
        print(f"  ✗ MCU 固件刷写失败 (exit code: {result.returncode})")
        return False


def reset_mcu_only(openocd, scripts_dir, cfg_file):
    """仅复位 MCU (不刷写, 只是恢复 USART2 和正常运行)"""
    print(f"\n[3] 复位 MCU (恢复 USART2)...")
    
    cmd = [
        openocd,
        "-s", scripts_dir,
        "-f", cfg_file,
        "-c", "init",
        "-c", "reset run",
        "-c", "exit"
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0:
        print(f"  ✓ MCU 已复位")
        return True
    else:
        print(f"  ✗ MCU 复位失败")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="一键刷写 ESP32 固件 (通过 MCU 控制下载模式)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python flash_esp32.py                           # 使用默认端口
  python flash_esp32.py --mcu-port COM5 --esp-port COM18
  python flash_esp32.py --skip-mcu                # 刷完ESP32不重刷MCU,仅复位
  python flash_esp32.py --flash-mcu               # 刷完ESP32也重刷MCU
"""
    )
    parser.add_argument("--mcu-port", default=DEFAULT_MCU_PORT,
                        help=f"MCU USB CDC 串口 (默认: {DEFAULT_MCU_PORT})")
    parser.add_argument("--esp-port", default=DEFAULT_ESP_PORT,
                        help=f"ESP32 下载串口 (默认: {DEFAULT_ESP_PORT})")
    parser.add_argument("--esp-dir", default=DEFAULT_ESP_DIR,
                        help=f"ESP32 PlatformIO 项目目录")
    parser.add_argument("--flash-mcu", action="store_true",
                        help="ESP32刷完后重新刷写MCU固件")
    parser.add_argument("--skip-mcu", action="store_true",
                        help="ESP32刷完后仅复位MCU(不重刷固件)")
    parser.add_argument("--openocd", default=DEFAULT_OPENOCD,
                        help="OpenOCD 路径")
    parser.add_argument("--openocd-scripts", default=DEFAULT_OPENOCD_SCRIPTS,
                        help="OpenOCD scripts 目录")
    parser.add_argument("--openocd-cfg", default=DEFAULT_OPENOCD_CFG,
                        help="OpenOCD 配置文件")
    parser.add_argument("--hex", default=DEFAULT_HEX_FILE,
                        help="MCU HEX 固件文件")
    args = parser.parse_args()

    print("=" * 50)
    print("  EHUB ESP32 一键刷写工具")
    print("=" * 50)
    print(f"  MCU 端口:  {args.mcu_port}")
    print(f"  ESP32 端口: {args.esp_port}")
    print(f"  ESP32 项目: {args.esp_dir}")
    print()

    # Step 1: 发送下载模式命令
    print("[1] 让 ESP32 进入下载模式...")
    if not send_esp_download_cmd(args.mcu_port):
        print("\n✗ 无法发送命令到 MCU, 中止")
        sys.exit(1)

    # 等待 ESP32 bootloader 就绪
    print("  等待 ESP32 bootloader 就绪 (2秒)...")
    time.sleep(2)

    # Step 2: 刷写 ESP32
    if not flash_esp32(args.esp_port, args.esp_dir):
        print("\n✗ ESP32 刷写失败")
        # 尝试恢复 MCU
        reset_mcu_only(args.openocd, args.openocd_scripts, args.openocd_cfg)
        sys.exit(1)

    # Step 3: 恢复 MCU
    if args.flash_mcu:
        flash_mcu(args.openocd, args.openocd_scripts, args.openocd_cfg, args.hex)
    elif args.skip_mcu:
        reset_mcu_only(args.openocd, args.openocd_scripts, args.openocd_cfg)
    else:
        # 默认: 重刷 MCU (因为之前的 EnterBootloader 修改了 USART2 状态)
        flash_mcu(args.openocd, args.openocd_scripts, args.openocd_cfg, args.hex)

    print("\n" + "=" * 50)
    print("  ✓ 全部完成!")
    print("=" * 50)


if __name__ == "__main__":
    main()
