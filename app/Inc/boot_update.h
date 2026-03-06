#ifndef BOOT_UPDATE_H
#define BOOT_UPDATE_H

#include <stdint.h>
#include "usb_app.h"
#include "ehub_boot.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_SUBCMD_INFO            0x01U
#define BOOT_SUBCMD_BEGIN           0x02U
#define BOOT_SUBCMD_WRITE           0x03U
#define BOOT_SUBCMD_FINISH          0x04U

#define BOOT_STATUS_OK              0x00U
#define BOOT_STATUS_BAD_ARG         0x01U
#define BOOT_STATUS_RANGE           0x02U
#define BOOT_STATUS_FLASH           0x03U
#define BOOT_STATUS_CRC             0x04U
#define BOOT_STATUS_STATE           0x05U

void Boot_Update_Init(void);
uint8_t Boot_Update_HandleFrame(const BridgeMsg_t *msg);

#ifdef __cplusplus
}
#endif

#endif