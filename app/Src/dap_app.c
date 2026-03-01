/**
 * @file    dap_app.c
 * @brief   CMSIS-DAP HID 应用层 (FreeRTOS 任务 + USB HID 回调)
 *
 * 原先这些变量和函数写在 main.c 的 USER CODE 段里，并在 while(1) 中
 * 轮询 DAP 命令，导致 osKernelStart() 永远无法被调用，FreeRTOS 不启动，
 * Bridge_Init() 也就从未执行，CDC↔总线桥接完全失效。
 *
 * 修复方案：将 DAP 处理移到独立的 FreeRTOS 任务 (StartDAPTask)，
 * 让 main() 正常进入 osKernelStart()。
 */

#include "dap_app.h"
#include "DAP.h"
#include "DAP_config.h"
#include "usbd_custom_hid_if.h"
#include "cmsis_os.h"
#include <string.h>

extern USBD_HandleTypeDef hUsbDeviceFS;

/* ---- HID report/request 类型常量 ---------------------------------------- */
#define HID_REPORT_INPUT            0x81U
#define HID_REPORT_OUTPUT           0x91U
#define HID_REPORT_FEATURE          0xB1U
#define USBD_HID_REQ_EP_CTRL        0x01U
#define USBD_HID_REQ_PERIOD_UPDATE  0x02U
#define USBD_HID_REQ_EP_INT         0x03U

/* ---- HID 请求/响应环形缓冲区 -------------------------------------------- */
static volatile uint16_t USB_RequestIndexI;
static volatile uint16_t USB_RequestIndexO;
static volatile uint16_t USB_RequestCountI;
static volatile uint16_t USB_RequestCountO;

static volatile uint16_t USB_ResponseIndexI;
static volatile uint16_t USB_ResponseIndexO;
static volatile uint16_t USB_ResponseCountI;
static volatile uint16_t USB_ResponseCountO;

static volatile uint8_t  USB_ResponseIdle;

static uint8_t USB_Request [DAP_PACKET_COUNT][DAP_PACKET_SIZE];
static uint8_t USB_Response[DAP_PACKET_COUNT][DAP_PACKET_SIZE];

/*===========================================================================
 * USB HID 回调 — 由 USB 中断上下文调用
 *===========================================================================*/

int32_t USBD_HID0_GetReport(uint8_t rtype, uint8_t req, uint8_t rid, uint8_t *buf)
{
    (void)rid;
    switch (rtype) {
        case HID_REPORT_INPUT:
            switch (req) {
                case USBD_HID_REQ_EP_CTRL:
                case USBD_HID_REQ_PERIOD_UPDATE:
                    break;
                case USBD_HID_REQ_EP_INT:
                    if (USB_ResponseCountI != USB_ResponseCountO) {
                        memcpy(buf, USB_Response[USB_ResponseIndexO], DAP_PACKET_SIZE);
                        USB_ResponseIndexO++;
                        if (USB_ResponseIndexO == DAP_PACKET_COUNT) { USB_ResponseIndexO = 0U; }
                        USB_ResponseCountO++;
                        return (int32_t)DAP_PACKET_SIZE;
                    } else {
                        USB_ResponseIdle = 1U;
                    }
                    break;
            }
            break;
        case HID_REPORT_FEATURE:
            break;
    }
    return 0;
}

uint8_t USBD_HID0_SetReport(uint8_t rtype, uint8_t req, uint8_t rid,
                             const uint8_t *buf, int32_t len)
{
    (void)req; (void)rid;
    switch (rtype) {
        case HID_REPORT_OUTPUT:
            if (len == 0) { break; }
            if (buf[0] == ID_DAP_TransferAbort) { DAP_TransferAbort = 1U; break; }
            if ((uint16_t)(USB_RequestCountI - USB_RequestCountO) == DAP_PACKET_COUNT) {
                break; /* 缓冲满，丢弃 */
            }
            memcpy(USB_Request[USB_RequestIndexI], buf, (uint32_t)len);
            USB_RequestIndexI++;
            if (USB_RequestIndexI == DAP_PACKET_COUNT) { USB_RequestIndexI = 0U; }
            USB_RequestCountI++;
            break;
        case HID_REPORT_FEATURE:
            break;
    }
    return 1U;
}

void USBD_HID0_Initialize(void)
{
    USB_RequestIndexI  = 0U;  USB_RequestIndexO  = 0U;
    USB_RequestCountI  = 0U;  USB_RequestCountO  = 0U;
    USB_ResponseIndexI = 0U;  USB_ResponseIndexO = 0U;
    USB_ResponseCountI = 0U;  USB_ResponseCountO = 0U;
    USB_ResponseIdle   = 1U;
}

void USBD_InEvent(void)
{
    int32_t len;
    USBD_CUSTOM_HID_HandleTypeDef *hhid =
        (USBD_CUSTOM_HID_HandleTypeDef *)hUsbDeviceFS.pClassData;
    if ((len = USBD_HID0_GetReport(HID_REPORT_INPUT, USBD_HID_REQ_EP_INT, 0,
                                    hhid->Report_buf)) > 0) {
        USBD_CUSTOM_HID_SendReport(&hUsbDeviceFS, hhid->Report_buf, len);
    }
}

void USBD_OutEvent(void)
{
    USBD_CUSTOM_HID_HandleTypeDef *hhid =
        (USBD_CUSTOM_HID_HandleTypeDef *)hUsbDeviceFS.pClassData;
    USBD_HID0_SetReport(HID_REPORT_OUTPUT, 0, 0,
                        hhid->Report_buf, USBD_CUSTOMHID_OUTREPORT_BUF_SIZE);
}

/*===========================================================================
 * StartDAPTask — FreeRTOS 任务，处理 CMSIS-DAP 命令
 *===========================================================================*/

void StartDAPTask(void *argument)
{
    (void)argument;
    uint32_t n;

    for (;;) {
        while (USB_RequestCountI != USB_RequestCountO) {
            /* 将排队命令标记为批量执行 */
            n = USB_RequestIndexO;
            while (USB_Request[n][0] == ID_DAP_QueueCommands) {
                USB_Request[n][0] = ID_DAP_ExecuteCommands;
                n++;
                if (n == DAP_PACKET_COUNT) { n = 0U; }
                if (n == USB_RequestIndexI) { break; }
            }

            DAP_ExecuteCommand(USB_Request[USB_RequestIndexO],
                               USB_Response[USB_ResponseIndexI]);

            USB_RequestIndexO++;
            if (USB_RequestIndexO == DAP_PACKET_COUNT) { USB_RequestIndexO = 0U; }
            USB_RequestCountO++;

            USB_ResponseIndexI++;
            if (USB_ResponseIndexI == DAP_PACKET_COUNT) { USB_ResponseIndexI = 0U; }
            USB_ResponseCountI++;

            if (USB_ResponseIdle && (USB_ResponseCountI != USB_ResponseCountO)) {
                n = USB_ResponseIndexO++;
                if (USB_ResponseIndexO == DAP_PACKET_COUNT) { USB_ResponseIndexO = 0U; }
                USB_ResponseCountO++;
                USB_ResponseIdle = 0U;
                USBD_CUSTOM_HID_SendReport(&hUsbDeviceFS,
                                           USB_Response[n], DAP_PACKET_SIZE);
            }
        }
        osDelay(1); /* 无待处理命令时让出 CPU */
    }
}
