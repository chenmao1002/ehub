
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

/**
 * @brief  线程安全执行 DAP 命令，并按当前链路设置上报包长。
 * @param  request   DAP 请求缓冲区
 * @param  response  DAP 响应缓冲区
 * @param  packet_size_report  对主机上报的 DAP 包长（HID=64，WiFi=512）
 * @retval DAP_ExecuteCommand 返回值
 */
uint32_t DAP_ExecuteCommandLocked(const uint8_t *request, uint8_t *response, uint16_t packet_size_report);

#ifdef __cplusplus
}
#endif

#endif /* __DAP_APP_H__ */

