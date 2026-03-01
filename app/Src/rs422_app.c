/**
 * @file    rs422_app.c
 * @brief   RS422 bridge  (UART4 — full-duplex, no direction pin)
 *
 * DMA-receive + IDLE-line detection is armed here and automatically
 * re-armed in usb_app.c :: HAL_UARTEx_RxEventCallback.
 */

#include "usb_app.h"
#include "usart.h"
#include <string.h>

/* uart4_rx_buf lives in usb_app.c; access via Bridge_UART4_RxBuf() */
extern uint8_t *Bridge_UART4_RxBuf(void);

#define RS422_RX_BUF_SIZE   128U

/* -------------------------------------------------------------------------
 * Bridge_RS422_Init
 * ------------------------------------------------------------------------- */
void Bridge_RS422_Init(void)
{
    HAL_UARTEx_ReceiveToIdle_DMA(&huart4, Bridge_UART4_RxBuf(), RS422_RX_BUF_SIZE);
    __HAL_DMA_DISABLE_IT(huart4.hdmarx, DMA_IT_HT);
}

/* -------------------------------------------------------------------------
 * Bridge_RS422_Send
 * Non-blocking DMA transmit.
 * ------------------------------------------------------------------------- */
void Bridge_RS422_Send(const uint8_t *data, uint16_t len)
{
    static uint8_t rs422_tx_buf[BRIDGE_MAX_DATA];

    if (data == NULL || len == 0U) { return; }
    if (len > BRIDGE_MAX_DATA) { len = BRIDGE_MAX_DATA; }

    uint32_t t = HAL_GetTick();
    while ((HAL_UART_GetState(&huart4) & HAL_UART_STATE_BUSY_TX) != 0U) {
        if ((HAL_GetTick() - t) > 50U) { return; }
        osDelay(1);
    }

    memcpy(rs422_tx_buf, data, len);
    (void)HAL_UART_Transmit_DMA(&huart4, rs422_tx_buf, len);
}

/* -------------------------------------------------------------------------
 * Bridge_RS422_Config
 * param = BRIDGE_CFG_BAUD, value = baud rate
 * ------------------------------------------------------------------------- */
void Bridge_RS422_Config(uint8_t param, uint32_t value)
{
    if (param != BRIDGE_CFG_BAUD || value == 0U) { return; }
    HAL_UART_DMAStop(&huart4);
    HAL_UART_DeInit(&huart4);
    huart4.Init.BaudRate = value;
    HAL_UART_Init(&huart4);
    HAL_UARTEx_ReceiveToIdle_DMA(&huart4, Bridge_UART4_RxBuf(), 128U);
    __HAL_DMA_DISABLE_IT(huart4.hdmarx, DMA_IT_HT);
}
