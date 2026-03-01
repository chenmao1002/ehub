/**
 * @file    rs485_app.c
 * @brief   RS485 bridge  (USART3, DE = PD10 / RS485_TX_EN_Pin)
 *
 * Direction control:
 *   Transmit → DE HIGH (RS485_TX_EN_Pin SET)
 *   Receive  → DE LOW  (RS485_TX_EN_Pin RESET)  ← default after reset
 *
 * DMA-receive + IDLE-line detection is armed by Bridge_RS485_Init()
 * and automatically re-armed in usb_app.c :: HAL_UARTEx_RxEventCallback
 * and HAL_UART_TxCpltCallback.
 */

#include "usb_app.h"
#include "usart.h"
#include "main.h"
#include <string.h>

/* usart3_rx_buf lives in usb_app.c; access via Bridge_USART3_RxBuf() */
extern uint8_t *Bridge_USART3_RxBuf(void);

#define RS485_RX_BUF_SIZE   128U

/* -------------------------------------------------------------------------
 * Bridge_RS485_Init
 * Called once from Bridge_Init() after HAL init is complete.
 * ------------------------------------------------------------------------- */
void Bridge_RS485_Init(void)
{
    /* Ensure DE pin is LOW → receive mode */
    HAL_GPIO_WritePin(RS485_TX_EN_GPIO_Port, RS485_TX_EN_Pin, GPIO_PIN_RESET);

    /* Start DMA-idle receive — callback in usb_app.c */
    HAL_UARTEx_ReceiveToIdle_DMA(&huart3, Bridge_USART3_RxBuf(), RS485_RX_BUF_SIZE);
    __HAL_DMA_DISABLE_IT(huart3.hdmarx, DMA_IT_HT);
}

/* -------------------------------------------------------------------------
 * Bridge_RS485_Send
 * Assert DE, start DMA TX.
 * DE is de-asserted (and DMA RX re-armed) in
 * usb_app.c :: HAL_UART_TxCpltCallback after TC flag clears.
 * ------------------------------------------------------------------------- */
void Bridge_RS485_Send(const uint8_t *data, uint16_t len)
{
    if (data == NULL || len == 0U) { return; }

    /* Switch transceiver to transmit mode */
    HAL_GPIO_WritePin(RS485_TX_EN_GPIO_Port, RS485_TX_EN_Pin, GPIO_PIN_SET);

    /* Non-blocking DMA transmit */
    HAL_UART_Transmit_DMA(&huart3, (uint8_t *)data, len);
}

/* -------------------------------------------------------------------------
 * Bridge_RS485_Config
 * param = BRIDGE_CFG_BAUD, value = baud rate (e.g. 115200)
 * ------------------------------------------------------------------------- */
void Bridge_RS485_Config(uint8_t param, uint32_t value)
{
    if (param != BRIDGE_CFG_BAUD || value == 0U) { return; }
    HAL_UART_DMAStop(&huart3);
    HAL_UART_DeInit(&huart3);
    huart3.Init.BaudRate = value;
    HAL_UART_Init(&huart3);
    HAL_GPIO_WritePin(RS485_TX_EN_GPIO_Port, RS485_TX_EN_Pin, GPIO_PIN_RESET);
    HAL_UARTEx_ReceiveToIdle_DMA(&huart3, Bridge_USART3_RxBuf(), 128U);
    __HAL_DMA_DISABLE_IT(huart3.hdmarx, DMA_IT_HT);
}
