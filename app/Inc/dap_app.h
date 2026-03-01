
#ifndef __DAP_APP_H__
#define __DAP_APP_H__

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"

/**
 * @brief  初始化 CMSIS-DAP HID 请求/响应环形缓冲区。
 *         必须在 MX_USB_DEVICE_Init() 之前或之后立即调用。
 */
void USBD_HID0_Initialize(void);

/**
 * @brief  FreeRTOS 任务: 从 USB HID 缓冲区取出 DAP 命令、执行并回复。
 *         通过 osThreadNew() 创建。
 */
void StartDAPTask(void *argument);

/**
 * @brief  USB HID Input Report 完成回调 (usbd_custom_hid_if.c 中 extern 声明)。
 */
void USBD_InEvent(void);

/**
 * @brief  USB HID Output Report 接收回调 (usbd_custom_hid_if.c 中 extern 声明)。
 */
void USBD_OutEvent(void);

#ifdef __cplusplus
}
#endif

#endif /* __DAP_APP_H__ */

