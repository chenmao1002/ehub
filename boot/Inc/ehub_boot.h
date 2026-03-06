#ifndef EHUB_BOOT_H
#define EHUB_BOOT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EHUB_FLASH_BASE_ADDR        0x08000000UL
#define EHUB_FLASH_END_ADDR         0x08080000UL

#define EHUB_BOOT_START_ADDR        0x08000000UL
#define EHUB_BOOT_SIZE              0x00010000UL

#define EHUB_APP_START_ADDR         0x08010000UL
#define EHUB_APP_MAX_SIZE           0x00030000UL
#define EHUB_APP_END_ADDR           (EHUB_APP_START_ADDR + EHUB_APP_MAX_SIZE)

#define EHUB_STAGING_START_ADDR     0x08040000UL
#define EHUB_STAGING_MAX_SIZE       0x0003FF00UL
#define EHUB_STAGING_END_ADDR       (EHUB_STAGING_START_ADDR + EHUB_STAGING_MAX_SIZE)

#define EHUB_MANIFEST_ADDR          0x0807FF00UL
#define EHUB_MANIFEST_MAGIC         0x42485545UL
#define EHUB_MANIFEST_STATE_READY   0x59444152UL

typedef struct {
    uint32_t magic;
    uint32_t state;
    uint32_t image_size;
    uint32_t image_crc32;
    uint32_t reserved[4];
} EHUB_BootManifest;

#define EHUB_BOOT_MANIFEST ((const EHUB_BootManifest *)EHUB_MANIFEST_ADDR)

uint32_t EHUB_Boot_Crc32(const void *data, uint32_t len);
uint32_t EHUB_Boot_GetSector(uint32_t address);
uint8_t EHUB_Boot_IsValidApp(uint32_t appAddress);

#ifdef __cplusplus
}
#endif

#endif