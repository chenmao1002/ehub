#include "ehub_boot.h"

uint32_t EHUB_Boot_Crc32(const void *data, uint32_t len)
{
    const uint8_t *bytes = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFUL;

    while (len-- > 0U) {
        crc ^= (uint32_t)(*bytes++);
        for (uint32_t bit = 0; bit < 8U; bit++) {
            uint32_t mask = (uint32_t)(-(int32_t)(crc & 1U));
            crc = (crc >> 1U) ^ (0xEDB88320UL & mask);
        }
    }

    return ~crc;
}

uint32_t EHUB_Boot_GetSector(uint32_t address)
{
    if (address < 0x08004000UL) { return 0U; }
    if (address < 0x08008000UL) { return 1U; }
    if (address < 0x0800C000UL) { return 2U; }
    if (address < 0x08010000UL) { return 3U; }
    if (address < 0x08020000UL) { return 4U; }
    if (address < 0x08040000UL) { return 5U; }
    if (address < 0x08060000UL) { return 6U; }
    return 7U;
}

uint8_t EHUB_Boot_IsValidApp(uint32_t appAddress)
{
    const uint32_t stackPointer = *(const uint32_t *)appAddress;
    const uint32_t resetVector = *(const uint32_t *)(appAddress + 4U);

    if ((stackPointer < 0x20000000UL) || (stackPointer > 0x20020000UL)) {
        return 0U;
    }

    if ((resetVector < EHUB_APP_START_ADDR) || (resetVector >= EHUB_FLASH_END_ADDR)) {
        return 0U;
    }

    if ((resetVector & 1UL) == 0UL) {
        return 0U;
    }

    return 1U;
}