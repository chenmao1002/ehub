# EHUB Bootloader

STM32F407 flash layout:

- `0x08000000-0x0800FFFF`: bootloader (64KB)
- `0x08010000-0x0803FFFF`: STM32 app slot (192KB)
- `0x08040000-0x0807FEFF`: staging slot (for CDC upload)
- `0x0807FF00-0x0807FFFF`: update manifest

Update flow:

1. PC sends STM32 app binary to the running app over USB CDC (`BRIDGE_CH_BOOT`).
2. App erases the staging slot, writes the new image, checks CRC32, and stores a manifest.
3. App resets the MCU.
4. Bootloader copies the staged image into the app slot, verifies CRC32, clears the manifest, and jumps to the app.

ESP32 update flow remains CDC passthrough to `USART2`, driven by `tools/update_firmware.py` or `tools/flash_esp32.py`.