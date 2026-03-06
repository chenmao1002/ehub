"""
统一固件更新工具:
1. 通过 CDC 将新的 STM32 app 写入 staging 区并触发 bootloader 安装
2. 通过现有 CDC->USART2 透传链路刷写 ESP32 app
"""

import argparse
import io
import os
import subprocess
import sys
import time
import zlib

import serial

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BRIDGE_SOF0_CMD = 0xAA
BRIDGE_SOF1 = 0x55
BRIDGE_SOF0_RPY = 0xBB
BRIDGE_CH_BOOT = 0xE1

BOOT_SUBCMD_INFO = 0x01
BOOT_SUBCMD_BEGIN = 0x02
BOOT_SUBCMD_WRITE = 0x03
BOOT_SUBCMD_FINISH = 0x04

BOOT_STATUS_OK = 0x00

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MCU_BIN = os.path.join(ROOT_DIR, 'build', 'Debug', 'EHUB.bin')
DEFAULT_MCU_PORT = 'COM19'


def build_frame(channel, payload):
    crc = channel ^ ((len(payload) >> 8) & 0xFF) ^ (len(payload) & 0xFF)
    for byte in payload:
        crc ^= byte
    return bytes([
        BRIDGE_SOF0_CMD,
        BRIDGE_SOF1,
        channel,
        (len(payload) >> 8) & 0xFF,
        len(payload) & 0xFF,
        *payload,
        crc,
    ])


def read_reply(port, expected_channel, timeout=10.0):
    deadline = time.time() + timeout
    state = 0
    frame = bytearray()
    payload_len = 0
    payload = bytearray()

    while time.time() < deadline:
        chunk = port.read(1)
        if not chunk:
            continue
        byte = chunk[0]
        if state == 0:
            if byte == BRIDGE_SOF0_RPY:
                state = 1
        elif state == 1:
            state = 2 if byte == BRIDGE_SOF1 else 0
        elif state == 2:
            frame = bytearray([byte])
            state = 3
        elif state == 3:
            frame.append(byte)
            payload_len = byte << 8
            state = 4
        elif state == 4:
            frame.append(byte)
            payload_len |= byte
            payload = bytearray()
            state = 5 if payload_len > 0 else 6
        elif state == 5:
            payload.append(byte)
            if len(payload) >= payload_len:
                state = 6
        elif state == 6:
            crc = frame[0] ^ frame[1] ^ frame[2]
            for payload_byte in payload:
                crc ^= payload_byte
            if crc == byte and frame[0] == expected_channel:
                return bytes(payload)
            state = 0

    raise TimeoutError('等待设备回复超时')


def transact(port, channel, payload, timeout=10.0):
    port.write(build_frame(channel, payload))
    port.flush()
    return read_reply(port, channel, timeout=timeout)


def update_stm32_app(port_name, bin_path, chunk_size):
    with open(bin_path, 'rb') as file:
        image = file.read()

    image_crc = zlib.crc32(image) & 0xFFFFFFFF
    print(f'STM32 app: {len(image)} bytes, crc32=0x{image_crc:08X}')

    with serial.Serial(port_name, 115200, timeout=0.2) as port:
        info = transact(port, BRIDGE_CH_BOOT, bytes([BOOT_SUBCMD_INFO]), timeout=2.0)
        if len(info) < 10 or info[0] != BOOT_SUBCMD_INFO or info[1] != BOOT_STATUS_OK:
            raise RuntimeError('设备不支持 boot update 通道')

        app_max = int.from_bytes(info[2:6], 'little')
        if len(image) > app_max:
            raise RuntimeError(f'镜像过大: {len(image)} > {app_max}')

        reply = transact(
            port,
            BRIDGE_CH_BOOT,
            bytes([BOOT_SUBCMD_BEGIN]) + len(image).to_bytes(4, 'little') + image_crc.to_bytes(4, 'little'),
            timeout=15.0,
        )
        if reply[:2] != bytes([BOOT_SUBCMD_BEGIN, BOOT_STATUS_OK]):
            raise RuntimeError(f'BEGIN 失败: {reply.hex()}')

        for offset in range(0, len(image), chunk_size):
            chunk = image[offset:offset + chunk_size]
            reply = transact(
                port,
                BRIDGE_CH_BOOT,
                bytes([BOOT_SUBCMD_WRITE]) + offset.to_bytes(4, 'little') + chunk,
                timeout=5.0,
            )
            if reply[:2] != bytes([BOOT_SUBCMD_WRITE, BOOT_STATUS_OK]):
                raise RuntimeError(f'WRITE 失败 @0x{offset:08X}: {reply.hex()}')
            print(f'写入 STM32: {offset + len(chunk)}/{len(image)}', end='\r', flush=True)

        print()
        reply = transact(port, BRIDGE_CH_BOOT, bytes([BOOT_SUBCMD_FINISH]), timeout=5.0)
        if reply[:2] != bytes([BOOT_SUBCMD_FINISH, BOOT_STATUS_OK]):
            raise RuntimeError(f'FINISH 失败: {reply.hex()}')

    print('STM32 staging 完成，设备已自动复位进入 bootloader 安装。')


def flash_esp32(args):
    command = [sys.executable, os.path.join(ROOT_DIR, 'tools', 'flash_esp32.py')]
    if args.mcu_port:
        command.extend(['--mcu-port', args.mcu_port])
    if args.esp_port:
        command.extend(['--esp-port', args.esp_port])
    if args.esp_dir:
        command.extend(['--esp-dir', args.esp_dir])
    result = subprocess.run(command)
    if result.returncode != 0:
        raise RuntimeError('ESP32 刷写失败')


def main():
    parser = argparse.ArgumentParser(description='EHUB STM32/ESP32 统一 app 更新工具')
    parser.add_argument('--mcu-port', default=DEFAULT_MCU_PORT, help='MCU CDC COM 口')
    parser.add_argument('--mcu-bin', default=DEFAULT_MCU_BIN, help='STM32 app 二进制文件')
    parser.add_argument('--chunk-size', type=int, default=512, help='STM32 写入块大小')
    parser.add_argument('--stm32', action='store_true', help='更新 STM32 app')
    parser.add_argument('--esp32', action='store_true', help='更新 ESP32 app')
    parser.add_argument('--esp-port', help='ESP32 下载串口')
    parser.add_argument('--esp-dir', help='ESP32 PlatformIO 项目目录')
    args = parser.parse_args()

    if not args.stm32 and not args.esp32:
        parser.error('至少选择 --stm32 或 --esp32')

    if args.stm32:
        update_stm32_app(args.mcu_port, args.mcu_bin, args.chunk_size)

    if args.esp32:
        flash_esp32(args)


if __name__ == '__main__':
    main()