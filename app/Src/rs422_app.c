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
    if (data == NULL || len == 0U) { return; }
    HAL_UART_Transmit_DMA(&huart4, (uint8_t *)data, len);
}
