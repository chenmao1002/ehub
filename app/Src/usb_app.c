/**
 * @file    usb_app.c
 * @brief   CDC ↔ Bus bridge — core dispatcher
 *
 * Responsibilities
 * ────────────────
 * 1. Override CDC_Receive_FS — parse bridge frames arriving from the PC,
 *    dispatch payload to the target bus.
 * 2. Bridge_Task (FreeRTOS) — wait on bridge_rx_queue; pack a reply
 *    frame and transmit it to the PC via CDC.
 * 3. All UART/UART-idle callbacks — centralised here to avoid
 *    multiple-definition linker errors.
 *
 * Depends on the weak HAL callbacks:
 *   HAL_UARTEx_RxEventCallback (all three UART peripherals)
 *   HAL_UART_TxCpltCallback    (USART3 / RS485 direction pin)
 */

#include "usb_app.h"
#include "usbd_cdc_if.h"
#include "usbd_def.h"
#include "usart.h"
#include "main.h"
#include "cmsis_os.h"
#include <string.h>

/* ---- External bus-send functions (implemented in their own .c files) ----- */
extern void Bridge_RS485_Send(const uint8_t *data, uint16_t len);
extern void Bridge_RS422_Send(const uint8_t *data, uint16_t len);
extern void Bridge_SPI_Send  (const uint8_t *data, uint16_t len);
extern void Bridge_I2C_Send  (const uint8_t *data, uint16_t len);
extern void Bridge_I2C_Read  (const uint8_t *data, uint16_t len);
extern void Bridge_CAN_Send  (const uint8_t *data, uint16_t len);

extern void Bridge_RS485_Config(uint8_t param, uint32_t value);
extern void Bridge_RS422_Config(uint8_t param, uint32_t value);
extern void Bridge_SPI_Config  (uint8_t param, uint32_t value);
extern void Bridge_I2C_Config  (uint8_t param, uint32_t value);
extern void Bridge_CAN_Config  (uint8_t param, uint32_t value);
extern void Bridge_USART1_Config(uint8_t param, uint32_t value);

/* ---- External init functions --------------------------------------------- */
extern void Bridge_RS485_Init(void);
extern void Bridge_RS422_Init(void);
extern void Bridge_SPI_Init  (void);
extern void Bridge_I2C_Init  (void);
extern void Bridge_CAN_Init  (void);

/* ---- DMA receive buffers for UARTs (used by RxEventCallback) ------------- */
#define UART_RX_BUF_SIZE  128U
static uint8_t usart1_rx_buf[UART_RX_BUF_SIZE];
static uint8_t usart3_rx_buf[UART_RX_BUF_SIZE];   /* RS485 */
static uint8_t uart4_rx_buf [UART_RX_BUF_SIZE];   /* RS422 */

/* Public so RS485/RS422 init functions can re-arm DMA immediately */
uint8_t *Bridge_USART1_RxBuf(void) { return usart1_rx_buf; }
uint8_t *Bridge_USART3_RxBuf(void) { return usart3_rx_buf; }
uint8_t *Bridge_UART4_RxBuf (void) { return uart4_rx_buf;  }

/* ---- FreeRTOS queues ---------------------------------------------------- */
osMessageQueueId_t bridge_cmd_queue;   /* PC→Bus : CDC_Receive_FS → Bridge_Task */
osMessageQueueId_t bridge_rx_queue;   /* Bus→PC : ISR callbacks → Bridge_Task  */

/*===========================================================================
 *  Section 1 – CDC receive: parse bridge frames from PC
 *===========================================================================*/

typedef enum {
    PS_SOF0 = 0,
    PS_SOF1,
    PS_CH,
    PS_LEN_H,
    PS_LEN_L,
    PS_DATA,
    PS_CRC
} ParseState_t;

static ParseState_t s_state   = PS_SOF0;
static BridgeMsg_t  s_rx_msg;
static uint8_t      s_crc;
static uint16_t     s_idx;

static void Bridge_Config_Reply(uint8_t iface, uint8_t ok)
{
    uint8_t rep[2] = { iface, ok ? 0x00U : 0xFFU };
    Bridge_SendToCDC(BRIDGE_CH_CONFIG, rep, 2U);
}

static void Bridge_HandleConfig(const BridgeMsg_t *m)
{
    if (m->len < 1U) { Bridge_Config_Reply(m->buf[0], 0); return; }
    uint8_t  iface = m->buf[0];

    /* PING: iface=0xF0 param=0x00 — respond with magic "EHUB" */
    if (iface == BRIDGE_CH_CONFIG)
    {
        uint8_t rep[6] = { BRIDGE_CH_CONFIG, 0x00U, 'E', 'H', 'U', 'B' };
        Bridge_SendToCDC(BRIDGE_CH_CONFIG, rep, 6U);
        return;
    }

    if (m->len < 6U) { Bridge_Config_Reply(iface, 0); return; }
    uint8_t  param = m->buf[1];
    uint32_t value = ((uint32_t)m->buf[2] << 24U)
                   | ((uint32_t)m->buf[3] << 16U)
                   | ((uint32_t)m->buf[4] <<  8U)
                   |  (uint32_t)m->buf[5];
    switch (iface)
    {
        case BRIDGE_CH_USART1: Bridge_USART1_Config(param, value); break;
        case BRIDGE_CH_RS485:  Bridge_RS485_Config(param, value);  break;
        case BRIDGE_CH_RS422:  Bridge_RS422_Config(param, value);  break;
        case BRIDGE_CH_SPI:    Bridge_SPI_Config(param, value);    break;
        case BRIDGE_CH_I2C_W:
        case BRIDGE_CH_I2C_R:  Bridge_I2C_Config(param, value);    break;
        case BRIDGE_CH_CAN:    Bridge_CAN_Config(param, value);    break;
        default: Bridge_Config_Reply(iface, 0); return;
    }
    Bridge_Config_Reply(iface, 1);
}

static void Bridge_Dispatch(const BridgeMsg_t *m)
{
    switch (m->ch)
    {
        case BRIDGE_CH_USART1:
            HAL_UART_Transmit_DMA(&huart1, (uint8_t *)m->buf, m->len);
            break;
        case BRIDGE_CH_RS485:
            Bridge_RS485_Send(m->buf, m->len);
            break;
        case BRIDGE_CH_RS422:
            Bridge_RS422_Send(m->buf, m->len);
            break;
        case BRIDGE_CH_SPI:
            Bridge_SPI_Send(m->buf, m->len);   /* response sent inside */
            break;
        case BRIDGE_CH_I2C_W:
            Bridge_I2C_Send(m->buf, m->len);
            break;
        case BRIDGE_CH_I2C_R:
            Bridge_I2C_Read(m->buf, m->len);   /* response sent inside */
            break;
        case BRIDGE_CH_CAN:
            Bridge_CAN_Send(m->buf, m->len);
            break;
        case BRIDGE_CH_CONFIG:
            Bridge_HandleConfig(m);
            break;
        default:
            break;
    }
}

/**
 * Override the __weak CDC_Receive_FS defined in usbd_cdc_if.c.
 * Called from USB ISR context — ONLY enqueue, never block.
 */
void CDC_Receive_FS(uint8_t *Buf, uint32_t Len)
{
    for (uint32_t i = 0U; i < Len; i++)
    {
        uint8_t b = Buf[i];

        switch (s_state)
        {
            case PS_SOF0:
                if (b == BRIDGE_SOF0_CMD) { s_state = PS_SOF1; }
                break;

            case PS_SOF1:
                s_state = (b == BRIDGE_SOF1) ? PS_CH : PS_SOF0;
                break;

            case PS_CH:
                s_rx_msg.ch = b;
                s_crc       = b;
                s_state     = PS_LEN_H;
                break;

            case PS_LEN_H:
                s_rx_msg.len = (uint16_t)b << 8U;
                s_crc ^= b;
                s_state = PS_LEN_L;
                break;

            case PS_LEN_L:
                s_rx_msg.len |= b;
                s_crc  ^= b;
                s_idx   = 0U;
                if (s_rx_msg.len == 0U || s_rx_msg.len > BRIDGE_MAX_DATA) {
                    s_state = PS_SOF0;   /* invalid length → reset */
                } else {
                    s_state = PS_DATA;
                }
                break;

            case PS_DATA:
                s_rx_msg.buf[s_idx++] = b;
                s_crc ^= b;
                if (s_idx >= s_rx_msg.len) { s_state = PS_CRC; }
                break;

            case PS_CRC:
                if (b == s_crc) {
                    /* Post to command queue (non-blocking, ISR-safe) */
                    osMessageQueuePut(bridge_cmd_queue, &s_rx_msg, 0U, 0U);
                }
                s_state = PS_SOF0;
                break;

            default:
                s_state = PS_SOF0;
                break;
        }
    }
}

/*===========================================================================
 *  Section 2 – Bridge_SendToCDC: pack reply frame, send via CDC
 *===========================================================================*/

void Bridge_SendToCDC(uint8_t ch, const uint8_t *data, uint16_t len)
{
    /* Static TX buffer: SOF(2) + CH(1) + LEN(2) + DATA(≤128) + CRC(1) = 134 */
    static uint8_t tx_buf[BRIDGE_MAX_DATA + 6U];

    if (len == 0U || len > BRIDGE_MAX_DATA) { return; }

    uint8_t crc = 0U;
    tx_buf[0] = BRIDGE_SOF0_RPY;
    tx_buf[1] = BRIDGE_SOF1;
    tx_buf[2] = ch;             crc ^= ch;
    tx_buf[3] = (uint8_t)(len >> 8U);   crc ^= tx_buf[3];
    tx_buf[4] = (uint8_t)(len & 0xFFU); crc ^= tx_buf[4];
    memcpy(&tx_buf[5], data, len);
    for (uint16_t i = 0U; i < len; i++) { crc ^= data[i]; }
    tx_buf[5U + len] = crc;

    /* Wait up to 50 ms if a previous CDC transfer is still in progress */
    uint32_t t = HAL_GetTick();
    uint8_t  result;
    do {
        result = CDC_Transmit_FS(tx_buf, (uint16_t)(6U + len));
        if (result != USBD_BUSY) { break; }
        osDelay(1);
    } while ((HAL_GetTick() - t) < 50U);
}

/*===========================================================================
 *  Section 3 – Bridge_Task: command dispatch + bus-RX queue → PC
 *===========================================================================*/

void Bridge_Task(void *argument)
{
    (void)argument;
    BridgeMsg_t msg;

    for (;;)
    {
        /* 1. Forward all pending bus-received frames to PC (non-blocking) */
        while (osMessageQueueGet(bridge_rx_queue, &msg, NULL, 0U) == osOK)
        {
            Bridge_SendToCDC(msg.ch, msg.buf, msg.len);
        }

        /* 2. Handle one command from PC (block up to 1 ms for next event) */
        if (osMessageQueueGet(bridge_cmd_queue, &msg, NULL, 1U) == osOK)
        {
            Bridge_Dispatch(&msg);   /* SPI/I2C blocking calls are safe here */
        }
    }
}

/*===========================================================================
 *  Section 4 – Bridge_Init
 *===========================================================================*/

static const osThreadAttr_t bridge_task_attrs = {
    .name       = "bridgeTask",
    .stack_size = 512U * 4U,
    .priority   = (osPriority_t)osPriorityAboveNormal,
};

void Bridge_Init(void)
{
    /* Create the inter-task queues */
    bridge_cmd_queue = osMessageQueueNew(8U, sizeof(BridgeMsg_t), NULL); /* PC→Bus  */
    bridge_rx_queue  = osMessageQueueNew(8U, sizeof(BridgeMsg_t), NULL); /* Bus→PC  */

    /* Initialise hardware bridges */
    Bridge_RS485_Init();
    Bridge_RS422_Init();
    Bridge_SPI_Init();
    Bridge_I2C_Init();
    Bridge_CAN_Init();

    /* Arm USART1 DMA-idle receive */
    HAL_UARTEx_ReceiveToIdle_DMA(&huart1, usart1_rx_buf, UART_RX_BUF_SIZE);
    __HAL_DMA_DISABLE_IT(huart1.hdmarx, DMA_IT_HT);

    /* Start bridge task */
    osThreadNew(Bridge_Task, NULL, &bridge_task_attrs);
}

/*===========================================================================
 *  Section 5 – Centralised HAL UART callbacks
 *  (weak in HAL; only ONE definition allowed per project)
 *===========================================================================*/

/**
 * Called when:
 *  - DMA/IDLE event fires on USART1 (raw bridge)
 *  - DMA/IDLE event fires on USART3 (RS485 RX)
 *  - DMA/IDLE event fires on UART4  (RS422 RX)
 */
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    if (Size == 0U) { return; }

    BridgeMsg_t msg;
    msg.len = (Size > BRIDGE_MAX_DATA) ? BRIDGE_MAX_DATA : Size;

    if (huart->Instance == USART1)
    {
        msg.ch = BRIDGE_CH_USART1;
        memcpy(msg.buf, usart1_rx_buf, msg.len);
        osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
        /* Re-arm */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart1, usart1_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart1.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == USART3)
    {
        msg.ch = BRIDGE_CH_RS485;
        memcpy(msg.buf, usart3_rx_buf, msg.len);
        osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
        /* Re-arm (DE already LOW — set by TxCplt callback or never changed) */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart3, usart3_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart3.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == UART4)
    {
        msg.ch = BRIDGE_CH_RS422;
        memcpy(msg.buf, uart4_rx_buf, msg.len);
        osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
        /* Re-arm */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart4, uart4_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart4.hdmarx, DMA_IT_HT);
    }
}

/* -------------------------------------------------------------------------
 * Bridge_USART1_Config  (USART1 baud rate)
 * ------------------------------------------------------------------------- */
void Bridge_USART1_Config(uint8_t param, uint32_t value)
{
    if (param != BRIDGE_CFG_BAUD || value == 0U) { return; }
    HAL_UART_DMAStop(&huart1);
    HAL_UART_DeInit(&huart1);
    huart1.Init.BaudRate = value;
    HAL_UART_Init(&huart1);
    HAL_UARTEx_ReceiveToIdle_DMA(&huart1, usart1_rx_buf, UART_RX_BUF_SIZE);
    __HAL_DMA_DISABLE_IT(huart1.hdmarx, DMA_IT_HT);
}

/**
 * Called after the last DMA byte is written to the UART shift register.
 * Only needed by RS485 (USART3) to de-assert the transmit-enable pin.
 */
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART3)
    {
        /* Wait for the last stop bit to leave the line */
        while (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_TC) == RESET) {}

        /* Switch transceiver back to receive mode */
        HAL_GPIO_WritePin(RS485_TX_EN_GPIO_Port, RS485_TX_EN_Pin, GPIO_PIN_RESET);

        /* Re-arm DMA idle receive */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart3, usart3_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart3.hdmarx, DMA_IT_HT);
    }
}
