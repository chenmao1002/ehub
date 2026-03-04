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
#include "wifi_bridge.h"
#include "usbd_cdc_if.h"
#include "usbd_customhid.h"
#include "usbd_def.h"
#include "usart.h"
#include "main.h"
#include "cmsis_os.h"
#include "DAP.h"
#include "DAP_config.h"
#include "dap_app.h"
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
    Bridge_SendToAll(BRIDGE_CH_CONFIG, rep, 2U);
}

static void Bridge_HandleConfig(const BridgeMsg_t *m)
{
    if (m->len < 1U) { Bridge_Config_Reply(BRIDGE_CH_CONFIG, 0); return; }
    uint8_t  iface = m->buf[0];

    /* PING: iface=0xF0 param=0x00 — respond with magic "EHUB" */
    if (iface == BRIDGE_CH_CONFIG)
    {
        uint8_t rep[6] = { BRIDGE_CH_CONFIG, 0x00U, 'E', 'H', 'U', 'B' };
        Bridge_SendToAll(BRIDGE_CH_CONFIG, rep, 6U);
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
        {
            /* m->buf 指向 Bridge_Task 栈上的局部变量，DMA 异步读取，
               必须先拷贝到 static 缓冲区再启动 DMA，否则下次循环
               覆盖 msg.buf 时 DMA 仍在读取旧数据。
               同时等待上次传输完成，避免 HAL_BUSY 丢包。 */
            static uint8_t usart1_tx_buf[BRIDGE_MAX_DATA];
            uint32_t t = HAL_GetTick();
            while (HAL_UART_GetState(&huart1) & HAL_UART_STATE_BUSY_TX) {
                if ((HAL_GetTick() - t) > 50U) { break; }
                osDelay(1);
            }
            memcpy(usart1_tx_buf, m->buf, m->len);
            HAL_UART_Transmit_DMA(&huart1, usart1_tx_buf, m->len);
            break;
        }
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
        case BRIDGE_CH_DAP:
        {
            /* CMSIS-DAP commands from WiFi TCP — execute on MCU, reply to WiFi only */
            static uint8_t dap_wifi_req[DAP_PACKET_SIZE];
            static uint8_t dap_wifi_rsp[DAP_PACKET_SIZE];
            uint16_t copy_len = (m->len > DAP_PACKET_SIZE) ? DAP_PACKET_SIZE : m->len;
            memset(dap_wifi_req, 0, DAP_PACKET_SIZE);
            memset(dap_wifi_rsp, 0, DAP_PACKET_SIZE);
            memcpy(dap_wifi_req, m->buf, copy_len);

            if (dap_wifi_req[0] == ID_DAP_TransferAbort) {
                DAP_TransferAbort = 1U;
                break;
            }

            uint32_t rsp_len = DAP_ExecuteCommandLocked(dap_wifi_req, dap_wifi_rsp, DAP_PACKET_SIZE);
            /* DAP_ExecuteCommand returns (request_count << 16) | response_size.
             * Extract lower 16 bits for the actual response length. */
            uint16_t send_len = (uint16_t)(rsp_len & 0xFFFFU);
            if (send_len == 0U || send_len > DAP_PACKET_SIZE) {
                send_len = DAP_PACKET_SIZE;
            }
            WiFi_Bridge_Send(BRIDGE_CH_DAP, dap_wifi_rsp, send_len);
            break;
        }
        case BRIDGE_CH_WIFI_CTRL:
            /* WiFi control frames from CDC: forward to ESP32 via USART2,
               except ESP_RESET and ESP_BOOT which MCU handles locally. */
            if (m->len >= 1U && m->buf[0] == WIFI_SUBCMD_ESP_RESET) {
                WiFi_ESP_Reset();
            } else if (m->len >= 1U && m->buf[0] == WIFI_SUBCMD_ESP_BOOT) {
                WiFi_ESP_EnterBootloader();
            } else if (m->len >= 1U && m->buf[0] == WIFI_SUBCMD_ESP_PASSTHROUGH) {
                /* Enter CDC↔USART2 transparent passthrough for flashing ESP32 */
                uint8_t rpl[2] = {WIFI_SUBCMD_ESP_PASSTHROUGH, 0x00U};
                Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rpl, 2U);
                osDelay(50);  /* let CDC TX complete before switching mode */
                /* Flush any stale bus-RX replies so they can't leak 0xBB later */
                {
                    BridgeMsg_t flush_msg;
                    while (osMessageQueueGet(bridge_rx_queue, &flush_msg, NULL, 0U) == osOK) { /* discard */ }
                }
                WiFi_ESP_EnterPassthrough();
            } else if (m->len >= 1U && m->buf[0] == 0xF1U) {
                /* MCU-side UART2 diagnostic — handle locally */
                extern volatile uint32_t s_dbg_uart2_tx_ok;
                extern volatile uint32_t s_dbg_uart2_tx_fail;
                extern volatile uint32_t s_dbg_uart2_rx_event;
                extern volatile uint32_t s_dbg_uart2_rx_bytes;
                extern volatile uint32_t s_dbg_uart2_error;
                extern volatile uint32_t s_dbg_uart2_frames;
                extern volatile uint32_t s_dbg_dma_init_rc;
                extern volatile uint32_t s_dbg_uart2_sr;
                extern volatile uint32_t s_dbg_dma_cr;
                extern volatile uint32_t s_dbg_dma_ndtr;
                /* Snapshot DMA and UART status registers */
                s_dbg_uart2_sr = USART2->SR;
                if (huart2.hdmarx && huart2.hdmarx->Instance) {
                    DMA_Stream_TypeDef *dma = (DMA_Stream_TypeDef *)huart2.hdmarx->Instance;
                    s_dbg_dma_cr = dma->CR;
                    s_dbg_dma_ndtr = dma->NDTR;
                }
                uint8_t rpl[1 + 10*4];   /* subcmd + 10 x uint32 */
                rpl[0] = 0xF1U;
                uint32_t v; uint16_t pos = 1U;
                v = s_dbg_uart2_tx_ok;    memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_uart2_tx_fail;  memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_uart2_rx_event; memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_uart2_rx_bytes; memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_uart2_error;    memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_uart2_frames;   memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_dma_init_rc;    memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_uart2_sr;       memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_dma_cr;         memcpy(&rpl[pos], &v, 4U); pos += 4U;
                v = s_dbg_dma_ndtr;       memcpy(&rpl[pos], &v, 4U); pos += 4U;
                Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rpl, pos);
            } else if (m->len >= 2U && m->buf[0] == 0xF2U) {
                /* GPIO connectivity test: toggle PA2 (USART2_TX) as GPIO */
                uint8_t action = m->buf[1];
                if (action == 0U) {
                    /* Deinit USART2, set PA2 = OUTPUT LOW */
                    HAL_UART_DMAStop(&huart2);
                    HAL_UART_DeInit(&huart2);
                    GPIO_InitTypeDef gi = {0};
                    gi.Pin  = GPIO_PIN_2;
                    gi.Mode = GPIO_MODE_OUTPUT_PP;
                    gi.Pull = GPIO_NOPULL;
                    gi.Speed = GPIO_SPEED_FREQ_LOW;
                    HAL_GPIO_Init(GPIOA, &gi);
                    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_2, GPIO_PIN_RESET);
                    /* Also test PA3 as input */
                    gi.Pin = GPIO_PIN_3;
                    gi.Mode = GPIO_MODE_INPUT;
                    gi.Pull = GPIO_NOPULL;
                    HAL_GPIO_Init(GPIOA, &gi);
                    uint8_t rr[3] = {0xF2U, 0x00U,
                        (uint8_t)HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_3)};
                    Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rr, 3U);
                } else if (action == 1U) {
                    /* Set PA2 = HIGH */
                    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_2, GPIO_PIN_SET);
                    uint8_t rr[3] = {0xF2U, 0x01U,
                        (uint8_t)HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_3)};
                    Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rr, 3U);
                } else if (action == 2U) {
                    /* Restore USART2 */
                    GPIO_InitTypeDef gi = {0};
                    gi.Pin  = GPIO_PIN_2 | GPIO_PIN_3;
                    gi.Mode = GPIO_MODE_AF_PP;
                    gi.Pull = GPIO_NOPULL;
                    gi.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
                    gi.Alternate = GPIO_AF7_USART2;
                    HAL_GPIO_Init(GPIOA, &gi);
                    huart2.Init.BaudRate     = WIFI_UART_BAUDRATE;
                    huart2.Init.OverSampling = UART_OVERSAMPLING_16;
                    HAL_UART_Init(&huart2);
                    uint8_t *rxbuf = WiFi_Bridge_GetRxBuf();
                    HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rxbuf, WIFI_RX_BUF_SIZE);
                    __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
                    uint8_t rr[2] = {0xF2U, 0x02U};
                    Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rr, 2U);
                }
            } else if (m->len >= 1U && m->buf[0] == 0xF3U) {
                /* ---- Register dump + polling TX test ---- */
                uint8_t rpl3[1 + 7*4];  /* subcmd + 7 x uint32 */
                rpl3[0] = 0xF3U;
                uint16_t pos3 = 1U;
                uint32_t v3;

                /* 1) USART2 register snapshot */
                v3 = USART2->CR1;   memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                v3 = USART2->CR3;   memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                v3 = USART2->BRR;   memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                v3 = USART2->SR;    memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;

                /* 2) TX DMA stream snapshot (DMA1_Stream6) */
                if (huart2.hdmatx && huart2.hdmatx->Instance) {
                    DMA_Stream_TypeDef *dtx = (DMA_Stream_TypeDef *)huart2.hdmatx->Instance;
                    v3 = dtx->CR;   memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                    v3 = dtx->NDTR; memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                } else {
                    v3 = 0xDEADU;   memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                    v3 = 0xDEADU;   memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;
                }

                /* 3) Polling TX test — bypass DMA entirely */
                uint8_t test_msg[] = "HELLO_FROM_MCU\n";
                HAL_StatusTypeDef txrc = HAL_UART_Transmit(
                    &huart2, test_msg, sizeof(test_msg)-1, 500);
                v3 = (uint32_t)txrc;
                memcpy(&rpl3[pos3], &v3, 4U); pos3 += 4U;

                Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rpl3, pos3);
            } else {
                WiFi_Bridge_Send(BRIDGE_CH_WIFI_CTRL, m->buf, m->len);
            }
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
    /* Passthrough mode: raw bytes → USART2 (no frame parsing) */
    if (WiFi_Bridge_IsPassthrough()) {
        WiFi_Passthrough_CDCRx(Buf, (uint16_t)Len);
        return;
    }

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
                    if (bridge_cmd_queue != NULL) {
                        (void)osMessageQueuePut(bridge_cmd_queue, &s_rx_msg, 0U, 0U);
                    }
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
    /* Block all CDC bridge frames during ESP32 passthrough —
       any 0xBB-prefixed frame would corrupt the transparent stream. */
    if (WiFi_Bridge_IsPassthrough()) { return; }

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
 *  Bridge_SendToAll: broadcast to both CDC and WiFi
 *===========================================================================*/

void Bridge_SendToAll(uint8_t ch, const uint8_t *data, uint16_t len)
{
    Bridge_SendToCDC(ch, data, len);
    WiFi_Bridge_Send(ch, data, len);
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
        /* In passthrough mode, Bridge_Task idles — all CDC traffic
           is handled by the transparent passthrough path. */
        if (WiFi_Bridge_IsPassthrough()) {
            osDelay(100);
            continue;
        }

        /* 1) Prefer one host command first, keeping command latency bounded */
        if (osMessageQueueGet(bridge_cmd_queue, &msg, NULL, 1U) == osOK)
        {
            Bridge_Dispatch(&msg);
        }

        /* 2) Then flush at most a few bus-RX frames to avoid starving commands */
        for (uint8_t budget = 0U; budget < 4U; budget++)
        {
            if (osMessageQueueGet(bridge_rx_queue, &msg, NULL, 0U) != osOK) {
                break;
            }
            Bridge_SendToAll(msg.ch, msg.buf, msg.len);
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

    /* Initialise WiFi bridge (USART2 → ESP32) */
    WiFi_Bridge_Init();
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
        if (bridge_rx_queue != NULL) {
            (void)osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
        }
        /* Re-arm */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart1, usart1_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart1.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == USART3)
    {
        msg.ch = BRIDGE_CH_RS485;
        memcpy(msg.buf, usart3_rx_buf, msg.len);
        if (bridge_rx_queue != NULL) {
            (void)osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
        }
        /* Re-arm (DE already LOW — set by TxCplt callback or never changed) */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart3, usart3_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart3.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == UART4)
    {
        msg.ch = BRIDGE_CH_RS422;
        memcpy(msg.buf, uart4_rx_buf, msg.len);
        if (bridge_rx_queue != NULL) {
            (void)osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
        }
        /* Re-arm */
        HAL_UARTEx_ReceiveToIdle_DMA(&huart4, uart4_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart4.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == USART2)
    {
        /* Passthrough: forward raw UART data → CDC */
        if (WiFi_Bridge_IsPassthrough()) {
            uint8_t *rxbuf = WiFi_Bridge_GetRxBuf();
            WiFi_Passthrough_UARTRx(rxbuf, Size);
            HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rxbuf, WIFI_RX_BUF_SIZE);
            __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
            return;
        }
        /* WiFi bridge: copy raw data into ring buffer and re-arm DMA */
        if (WiFi_Bridge_IsBootloader()) return;  /* USART2 deinitialized */
        extern volatile uint32_t s_dbg_uart2_rx_event;
        s_dbg_uart2_rx_event++;
        uint8_t *rxbuf = WiFi_Bridge_GetRxBuf();
        WiFi_Bridge_RxHandler(rxbuf, Size);
        HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rxbuf, WIFI_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
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
 * Called when a UART error occurs (Overrun, Framing, Noise, Parity).
 * The HAL automatically aborts DMA and sets state to READY.
 * We MUST re-arm DMA-idle receive here, otherwise reception stops forever.
 */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        /* Clear error flags then restart DMA-idle receive */
        __HAL_UART_CLEAR_OREFLAG(&huart1);
        __HAL_UART_CLEAR_NEFLAG(&huart1);
        __HAL_UART_CLEAR_FEFLAG(&huart1);
        HAL_UARTEx_ReceiveToIdle_DMA(&huart1, usart1_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart1.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == USART2)
    {
        /* Passthrough: clear errors and re-arm DMA */
        if (WiFi_Bridge_IsPassthrough()) {
            __HAL_UART_CLEAR_OREFLAG(&huart2);
            __HAL_UART_CLEAR_NEFLAG(&huart2);
            __HAL_UART_CLEAR_FEFLAG(&huart2);
            uint8_t *rxbuf = WiFi_Bridge_GetRxBuf();
            HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rxbuf, WIFI_RX_BUF_SIZE);
            __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
            return;
        }
        /* WiFi bridge USART2 — re-arm DMA into the WiFi RX buffer */
        if (WiFi_Bridge_IsBootloader()) return;  /* USART2 deinitialized */
        extern volatile uint32_t s_dbg_uart2_error;
        s_dbg_uart2_error++;
        __HAL_UART_CLEAR_OREFLAG(&huart2);
        __HAL_UART_CLEAR_NEFLAG(&huart2);
        __HAL_UART_CLEAR_FEFLAG(&huart2);
        uint8_t *rxbuf = WiFi_Bridge_GetRxBuf();
        HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rxbuf, WIFI_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == USART3)
    {
        /* RS485 — ensure DE pin is LOW (receive mode) then re-arm */
        __HAL_UART_CLEAR_OREFLAG(&huart3);
        __HAL_UART_CLEAR_NEFLAG(&huart3);
        __HAL_UART_CLEAR_FEFLAG(&huart3);
        HAL_GPIO_WritePin(RS485_TX_EN_GPIO_Port, RS485_TX_EN_Pin, GPIO_PIN_RESET);
        HAL_UARTEx_ReceiveToIdle_DMA(&huart3, usart3_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart3.hdmarx, DMA_IT_HT);
    }
    else if (huart->Instance == UART4)
    {
        /* RS422 */
        __HAL_UART_CLEAR_OREFLAG(huart);
        __HAL_UART_CLEAR_NEFLAG(huart);
        __HAL_UART_CLEAR_FEFLAG(huart);
        HAL_UARTEx_ReceiveToIdle_DMA(&huart4, uart4_rx_buf, UART_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart4.hdmarx, DMA_IT_HT);
    }
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

/*===========================================================================
 *  Section 6 – CDC control callbacks (called from USB ISR via
 *              usbd_customhid.c SET_LINE_CODING / SET_CONTROL_LINE_STATE)
 *===========================================================================*/

/**
 * Called when host sends SET_LINE_CODING (baud rate change).
 * In passthrough mode, requests USART2 baud-rate update (deferred to task).
 */
void CDC_SetLineCoding_Callback(uint8_t *linecoding)
{
    uint32_t baud = (uint32_t)linecoding[0]
                  | ((uint32_t)linecoding[1] <<  8U)
                  | ((uint32_t)linecoding[2] << 16U)
                  | ((uint32_t)linecoding[3] << 24U);
    WiFi_Passthrough_SetBaud(baud);
}

/**
 * Called when host sends SET_CONTROL_LINE_STATE (DTR/RTS).
 * In passthrough mode, maps DTR→ESP32 BOOT, RTS→ESP32 EN.
 */
void CDC_SetControlLineState_Callback(uint16_t state)
{
    WiFi_Passthrough_SetLineState(state);
}

/**
 * Re-arm CDC OUT endpoint after passthrough ring buffer has been drained.
 * Called from WiFi_Passthrough_Process (task context).
 */
void WiFi_Passthrough_RearmCDC(void)
{
    extern USBD_HandleTypeDef hUsbDeviceFS;
    USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid =
        (USBD_CUSTOM_HID_ComposeHandleTypeDef *)hUsbDeviceFS.pClassData;
    if (hhid != NULL) {
        USBD_LL_PrepareReceive(&hUsbDeviceFS, CDC_OUT_EP_ADDR,
                               hhid->cdc_rx_buf, CDC_DATA_FS_MAX_PACKET_SIZE);
    }
}
