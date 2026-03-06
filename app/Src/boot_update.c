#include "boot_update.h"

#include "cmsis_os.h"
#include "main.h"

#include <string.h>

typedef struct {
    uint32_t imageSize;
    uint32_t imageCrc32;
    uint8_t active;
} BootUpdateSession;

static BootUpdateSession s_bootSession;

static void Boot_SendReply(uint8_t subcmd, uint8_t status, const uint8_t *payload, uint16_t payloadLen)
{
    uint8_t reply[32];
    uint16_t totalLen = (uint16_t)(2U + payloadLen);

    if (totalLen > sizeof(reply)) {
        totalLen = 2U;
        payloadLen = 0U;
    }

    reply[0] = subcmd;
    reply[1] = status;
    if (payloadLen > 0U) {
        memcpy(&reply[2], payload, payloadLen);
    }
    Bridge_SendToCDC(BRIDGE_CH_BOOT, reply, totalLen);
}

static HAL_StatusTypeDef Boot_EraseStaging(void)
{
    FLASH_EraseInitTypeDef eraseInit = {0};
    uint32_t sectorError = 0U;
    HAL_StatusTypeDef status;

    HAL_FLASH_Unlock();

    eraseInit.TypeErase = FLASH_TYPEERASE_SECTORS;
    eraseInit.VoltageRange = FLASH_VOLTAGE_RANGE_3;
    eraseInit.Sector = FLASH_SECTOR_6;
    eraseInit.NbSectors = 2U;

    status = HAL_FLASHEx_Erase(&eraseInit, &sectorError);
    HAL_FLASH_Lock();
    return status;
}

static HAL_StatusTypeDef Boot_WriteBytes(uint32_t address, const uint8_t *data, uint32_t len)
{
    HAL_StatusTypeDef status = HAL_OK;

    HAL_FLASH_Unlock();
    for (uint32_t idx = 0U; idx < len; idx++) {
        status = HAL_FLASH_Program(FLASH_TYPEPROGRAM_BYTE, address + idx, data[idx]);
        if (status != HAL_OK) {
            break;
        }
    }
    HAL_FLASH_Lock();
    return status;
}

static uint8_t Boot_WriteManifest(uint32_t imageSize, uint32_t imageCrc32)
{
    EHUB_BootManifest manifest;

    memset(&manifest, 0xFF, sizeof(manifest));
    manifest.magic = EHUB_MANIFEST_MAGIC;
    manifest.state = EHUB_MANIFEST_STATE_READY;
    manifest.image_size = imageSize;
    manifest.image_crc32 = imageCrc32;

    return (Boot_WriteBytes(EHUB_MANIFEST_ADDR, (const uint8_t *)&manifest, sizeof(manifest)) == HAL_OK)
        ? BOOT_STATUS_OK
        : BOOT_STATUS_FLASH;
}

void Boot_Update_Init(void)
{
    memset(&s_bootSession, 0, sizeof(s_bootSession));
}

uint8_t Boot_Update_HandleFrame(const BridgeMsg_t *msg)
{
    uint8_t info[8];
    uint8_t status;

    if ((msg == NULL) || (msg->len < 1U)) {
        return 0U;
    }

    switch (msg->buf[0]) {
        case BOOT_SUBCMD_INFO:
            memcpy(&info[0], &((uint32_t){EHUB_APP_MAX_SIZE}), 4U);
            memcpy(&info[4], &((uint32_t){EHUB_STAGING_MAX_SIZE}), 4U);
            Boot_SendReply(BOOT_SUBCMD_INFO, BOOT_STATUS_OK, info, sizeof(info));
            return 1U;

        case BOOT_SUBCMD_BEGIN:
            if (msg->len != 9U) {
                Boot_SendReply(BOOT_SUBCMD_BEGIN, BOOT_STATUS_BAD_ARG, NULL, 0U);
                return 1U;
            }

            memcpy(&s_bootSession.imageSize, &msg->buf[1], 4U);
            memcpy(&s_bootSession.imageCrc32, &msg->buf[5], 4U);
            if ((s_bootSession.imageSize == 0U) ||
                (s_bootSession.imageSize > EHUB_APP_MAX_SIZE) ||
                (s_bootSession.imageSize > EHUB_STAGING_MAX_SIZE)) {
                memset(&s_bootSession, 0, sizeof(s_bootSession));
                Boot_SendReply(BOOT_SUBCMD_BEGIN, BOOT_STATUS_RANGE, NULL, 0U);
                return 1U;
            }

            if (Boot_EraseStaging() != HAL_OK) {
                memset(&s_bootSession, 0, sizeof(s_bootSession));
                Boot_SendReply(BOOT_SUBCMD_BEGIN, BOOT_STATUS_FLASH, NULL, 0U);
                return 1U;
            }

            s_bootSession.active = 1U;
            Boot_SendReply(BOOT_SUBCMD_BEGIN, BOOT_STATUS_OK, NULL, 0U);
            return 1U;

        case BOOT_SUBCMD_WRITE:
            if ((msg->len < 6U) || (s_bootSession.active == 0U)) {
                Boot_SendReply(BOOT_SUBCMD_WRITE, BOOT_STATUS_STATE, NULL, 0U);
                return 1U;
            }

            {
                uint32_t offset = 0U;
                uint32_t writeLen = (uint32_t)(msg->len - 5U);
                memcpy(&offset, &msg->buf[1], 4U);

                if ((offset + writeLen) > s_bootSession.imageSize) {
                    Boot_SendReply(BOOT_SUBCMD_WRITE, BOOT_STATUS_RANGE, NULL, 0U);
                    return 1U;
                }

                status = (Boot_WriteBytes(EHUB_STAGING_START_ADDR + offset, &msg->buf[5], writeLen) == HAL_OK)
                    ? BOOT_STATUS_OK
                    : BOOT_STATUS_FLASH;
                Boot_SendReply(BOOT_SUBCMD_WRITE, status, NULL, 0U);
            }
            return 1U;

        case BOOT_SUBCMD_FINISH:
            if ((msg->len != 1U) || (s_bootSession.active == 0U)) {
                Boot_SendReply(BOOT_SUBCMD_FINISH, BOOT_STATUS_STATE, NULL, 0U);
                return 1U;
            }

            if (EHUB_Boot_Crc32((const void *)EHUB_STAGING_START_ADDR, s_bootSession.imageSize) != s_bootSession.imageCrc32) {
                Boot_SendReply(BOOT_SUBCMD_FINISH, BOOT_STATUS_CRC, NULL, 0U);
                return 1U;
            }

            status = Boot_WriteManifest(s_bootSession.imageSize, s_bootSession.imageCrc32);
            Boot_SendReply(BOOT_SUBCMD_FINISH, status, NULL, 0U);
            if (status == BOOT_STATUS_OK) {
                osDelay(100U);
                NVIC_SystemReset();
            }
            return 1U;

        default:
            return 0U;
    }
}