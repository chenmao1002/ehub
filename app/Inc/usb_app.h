/**
 * @file    usb_app.h
 * @brief   CDC↔Bus bridge — protocol defines and public API
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  Frame format  (PC → Device  and  Device → PC are symmetric)            │
 * │                                                                          │
 * │  Direction: PC → Device                                                  │
 * │  [0xAA][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]                      │
 * │                                                                          │
 * │  Direction: Device → PC  (reply / bus-received data)                    │
 * │  [0xBB][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]                      │
 * │                                                                          │
 * │  CRC8 = XOR(CH, LEN_H, LEN_L, DATA[0..LEN-1])                          │
 * │                                                                          │
 * │  Channel IDs (CH byte):                                                  │
 * │    0x01  USART1  raw bytes                                               │
 * │    0x02  RS485   (USART3, PD10 DE)  raw bytes                           │
 * │    0x03  RS422   (UART4)  raw bytes                                      │
 * │    0x04  SPI1    full-duplex TX/RX  raw bytes                            │
 * │    0x05  I2C1    write: data[0]=7bit-addr, data[1..]=payload             │
 * │    0x06  I2C1    read : data[0]=7bit-addr, data[1]=len, [data[2]=reg]   │
 * │    0x07  CAN1    data[0..3]=ID(BE), data[4]=DLC, data[5..]=payload      │
 * └──────────────────────────────────────────────────────────────────────────┘
 */

#ifndef __USB_APP_H__
#define __USB_APP_H__

#include <stdint.h>
#include "cmsis_os.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Frame delimiters ---------------------------------------------------- */
#define BRIDGE_SOF0_CMD     0xAAU   /* PC → Device: start byte 0 */
#define BRIDGE_SOF1         0x55U   /* both directions: start byte 1 */
#define BRIDGE_SOF0_RPY     0xBBU   /* Device → PC: start byte 0 */

/* ---- Channel IDs --------------------------------------------------------- */
#define BRIDGE_CH_USART1    0x01U   /* USART1 raw */
#define BRIDGE_CH_RS485     0x02U   /* USART3 + PD10 DE */
#define BRIDGE_CH_RS422     0x03U   /* UART4  */
#define BRIDGE_CH_SPI       0x04U   /* SPI1 full-duplex */
#define BRIDGE_CH_I2C_W     0x05U   /* I2C1 master write */
#define BRIDGE_CH_I2C_R     0x06U   /* I2C1 master read  */
#define BRIDGE_CH_CAN       0x07U   /* CAN1  */
#define BRIDGE_CH_BATTERY   0x08U   /* Battery voltage & charging status */
#define BRIDGE_CH_WIFI_CTRL 0xE0U   /* WiFi control channel (MCU + ESP32) */
#define BRIDGE_CH_CONFIG    0xF0U   /* peripheral re-configuration */

/* ---- CONFIG param types (data[1] of a BRIDGE_CH_CONFIG frame) ----------- */
#define BRIDGE_CFG_BAUD     0x01U   /* USART1/RS485/RS422 baud rate (uint32 BE) */
#define BRIDGE_CFG_SPI_SPD  0x02U   /* SPI prescaler index 0-7 (2/4/8/16/32/64/128/256) */
#define BRIDGE_CFG_SPI_MODE 0x03U   /* SPI CPOL/CPHA mode 0-3 */
#define BRIDGE_CFG_I2C_SPD  0x04U   /* I2C speed: 100000 or 400000 (uint32 BE) */
#define BRIDGE_CFG_CAN_BAUD 0x05U   /* CAN baud: 125000/250000/500000/1000000 (uint32 BE) */
#define BRIDGE_CFG_SPI_ROLE 0x06U   /* SPI role: 0=master, 1=slave */
#define BRIDGE_CFG_I2C_ROLE 0x07U   /* I2C role: 0=master, 1=slave */
#define BRIDGE_CFG_I2C_OWN  0x08U   /* I2C own 7-bit address (0x08~0x77) */

/* ---- Payload limits ------------------------------------------------------ */
#define BRIDGE_MAX_DATA     128U    /* max bytes in one bridge frame payload */

/* ---- Message type passed through the FreeRTOS queue --------------------- */
typedef struct {
    uint8_t  ch;
    uint16_t len;
    uint8_t  buf[BRIDGE_MAX_DATA];
} BridgeMsg_t;

/* Queue handles */
extern osMessageQueueId_t bridge_cmd_queue;  /* PC→Bus commands  */
extern osMessageQueueId_t bridge_rx_queue;   /* Bus→PC received data */

/**
 * @brief  Initialise all bridge buses and start the FreeRTOS bridge task.
 *         Call this once inside MX_FREERTOS_Init() user-code section,
 *         AFTER USB is started.
 */
void Bridge_Init(void);

/**
 * @brief  Pack a reply frame and transmit it to the PC host via CDC.
 *         May be called from task context (waits if CDC busy, max 50 ms).
 * @param  ch    Channel ID (BRIDGE_CH_*)
 * @param  data  Payload pointer
 * @param  len   Payload length (≤ BRIDGE_MAX_DATA)
 */
void Bridge_SendToCDC(uint8_t ch, const uint8_t *data, uint16_t len);

/**
 * @brief  Broadcast a reply frame to ALL active transports (CDC + WiFi).
 *         Use this instead of Bridge_SendToCDC when the reply must reach
 *         the PC regardless of which link it is connected on.
 */
void Bridge_SendToAll(uint8_t ch, const uint8_t *data, uint16_t len);

/**
 * @brief  FreeRTOS task entry — forwards bus-received frames to PC.
 *         Do NOT call directly; registered via Bridge_Init().
 */
void Bridge_Task(void *argument);

#ifdef __cplusplus
}
#endif

#endif /* __USB_APP_H__ */
