/**
 * @file    wifi_bridge.c
 * @brief   WiFi ↔ Bus bridge via ESP32 — USART2 transport layer
 *
 * Responsibilities
 * ────────────────
 * 1. Reconfigure USART2 to 921600 baud and start DMA+IDLE receive.
 * 2. ISR handler (WiFi_Bridge_RxHandler) copies raw USART2 bytes into
 *    a lock-free ring buffer.
 * 3. WiFi_Bridge_Task drains the ring buffer through a frame parser
 *    (same state machine as CDC) and either:
 *      • Enqueues bus-command frames into bridge_cmd_queue
 *      • Handles WiFi-control frames (CH=0xE0) locally
 * 4. WiFi_Bridge_Send packs a reply frame and transmits via USART2/DMA.
 * 5. ESP32 control helpers (reset, enter bootloader).
 */

#include "wifi_bridge.h"
#include "usb_app.h"
#include "usart.h"
#include "main.h"
#include "cmsis_os.h"
#include <string.h>

/* ---- DMA receive buffer ------------------------------------------------- */
static uint8_t s_wifi_rx_buf[WIFI_RX_BUF_SIZE];

uint8_t *WiFi_Bridge_GetRxBuf(void) { return s_wifi_rx_buf; }

/* ---- Lock-free ring buffer (single-producer ISR, single-consumer Task) -- */
static volatile uint8_t  s_ring[WIFI_RING_SIZE];
static volatile uint16_t s_ring_head = 0U;   /* written by ISR  */
static volatile uint16_t s_ring_tail = 0U;   /* read by Task    */

static inline void ring_put(uint8_t b)
{
    uint16_t next = (s_ring_head + 1U) % WIFI_RING_SIZE;
    if (next != s_ring_tail)            /* drop byte if full */
    {
        s_ring[s_ring_head] = b;
        s_ring_head = next;
    }
}

static inline int ring_get(uint8_t *b)
{
    if (s_ring_head == s_ring_tail) { return 0; }
    *b = s_ring[s_ring_tail];
    s_ring_tail = (s_ring_tail + 1U) % WIFI_RING_SIZE;
    return 1;
}

/* ---- TX buffer & mutex (shared by multiple callers of Send) ------------- */
static uint8_t  s_wifi_tx_buf[BRIDGE_MAX_DATA + 6U];
static osMutexId_t s_wifi_tx_mutex;
static const osMutexAttr_t s_wifi_tx_mutex_attr = {
    .name = "wifiTxMtx",
    .attr_bits = osMutexRecursive,
    .cb_mem = NULL,
    .cb_size = 0U,
};

/* ---- Frame parser state (mirrors CDC parser in usb_app.c) --------------- */
typedef enum {
    WPS_SOF0 = 0,
    WPS_SOF1,
    WPS_CH,
    WPS_LEN_H,
    WPS_LEN_L,
    WPS_DATA,
    WPS_CRC
} WifiParseState_t;

static WifiParseState_t w_state = WPS_SOF0;
static BridgeMsg_t      w_msg;
static uint8_t          w_crc;
static uint16_t         w_idx;

/* ---- Forward declarations ----------------------------------------------- */
static void WiFi_HandleCtrlFromCDC(const BridgeMsg_t *m);

/*===========================================================================
 *  Section 1 — ISR-side: receive raw bytes into ring buffer
 *===========================================================================*/

void WiFi_Bridge_RxHandler(const uint8_t *data, uint16_t size)
{
    for (uint16_t i = 0U; i < size; i++)
    {
        ring_put(data[i]);
    }
}

/*===========================================================================
 *  Section 2 — WiFi_Bridge_Send: pack reply and transmit via USART2/DMA
 *===========================================================================*/

void WiFi_Bridge_Send(uint8_t ch, const uint8_t *data, uint16_t len)
{
    if (len == 0U || len > BRIDGE_MAX_DATA) { return; }

    if (osMutexAcquire(s_wifi_tx_mutex, 60U) != osOK) { return; }

    uint8_t crc = 0U;
    s_wifi_tx_buf[0] = BRIDGE_SOF0_RPY;            /* 0xBB */
    s_wifi_tx_buf[1] = BRIDGE_SOF1;                 /* 0x55 */
    s_wifi_tx_buf[2] = ch;             crc ^= ch;
    s_wifi_tx_buf[3] = (uint8_t)(len >> 8U);    crc ^= s_wifi_tx_buf[3];
    s_wifi_tx_buf[4] = (uint8_t)(len & 0xFFU);  crc ^= s_wifi_tx_buf[4];
    memcpy(&s_wifi_tx_buf[5], data, len);
    for (uint16_t i = 0U; i < len; i++) { crc ^= data[i]; }
    s_wifi_tx_buf[5U + len] = crc;

    /* Wait for previous DMA transfer to finish (max 50 ms) */
    uint32_t t0 = HAL_GetTick();
    while (HAL_UART_GetState(&huart2) & HAL_UART_STATE_BUSY_TX)
    {
        if ((HAL_GetTick() - t0) > 50U) { break; }
        osDelay(1);
    }

    HAL_UART_Transmit_DMA(&huart2, s_wifi_tx_buf, (uint16_t)(6U + len));

    osMutexRelease(s_wifi_tx_mutex);
}

/*===========================================================================
 *  Section 3 — WiFi_Bridge_Task: drain ring → parse frames → dispatch
 *===========================================================================*/

/**
 * Process one byte through the frame parser.
 * Returns 1 when a complete, CRC-valid frame is available in w_msg.
 */
static int wifi_parse_byte(uint8_t b)
{
    switch (w_state)
    {
        case WPS_SOF0:
            if (b == BRIDGE_SOF0_CMD)      { w_state = WPS_SOF1; }
            else if (b == BRIDGE_SOF0_RPY) { w_state = WPS_SOF1; }
            /* Also accept RPY frames coming from ESP32 (e.g. WiFi status) */
            break;

        case WPS_SOF1:
            w_state = (b == BRIDGE_SOF1) ? WPS_CH : WPS_SOF0;
            break;

        case WPS_CH:
            w_msg.ch  = b;
            w_crc     = b;
            w_state   = WPS_LEN_H;
            break;

        case WPS_LEN_H:
            w_msg.len = (uint16_t)b << 8U;
            w_crc ^= b;
            w_state = WPS_LEN_L;
            break;

        case WPS_LEN_L:
            w_msg.len |= b;
            w_crc ^= b;
            w_idx  = 0U;
            if (w_msg.len == 0U || w_msg.len > BRIDGE_MAX_DATA)
            {
                w_state = WPS_SOF0;
            }
            else
            {
                w_state = WPS_DATA;
            }
            break;

        case WPS_DATA:
            w_msg.buf[w_idx++] = b;
            w_crc ^= b;
            if (w_idx >= w_msg.len) { w_state = WPS_CRC; }
            break;

        case WPS_CRC:
            w_state = WPS_SOF0;
            if (b == w_crc)
            {
                return 1;   /* frame ready in w_msg */
            }
            break;

        default:
            w_state = WPS_SOF0;
            break;
    }
    return 0;
}

void WiFi_Bridge_Task(void *argument)
{
    (void)argument;
    uint8_t byte;

    for (;;)
    {
        /* Drain ring buffer — process up to 256 bytes per iteration */
        uint16_t budget = 256U;
        while (budget-- > 0U && ring_get(&byte))
        {
            if (wifi_parse_byte(byte))
            {
                /* Complete frame available in w_msg */
                if (w_msg.ch == BRIDGE_CH_WIFI_CTRL)
                {
                    /* WiFi control — handle locally (either from PC-via-ESP32
                       or from ESP32 itself).  Some sub-commands the MCU
                       executes (reset/boot); others are forwarded to CDC. */
                    WiFi_HandleCtrlFromCDC(&w_msg);
                }
                else
                {
                    /* Normal bus command from PC via WiFi — enqueue for
                       Bridge_Task dispatch (same queue as CDC).          */
                    if (bridge_cmd_queue != NULL)
                    {
                        (void)osMessageQueuePut(bridge_cmd_queue, &w_msg, 0U, 0U);
                    }
                }
            }
        }

        /* Yield so other tasks get CPU time when ring is empty */
        osDelay(1);
    }
}

/*===========================================================================
 *  Section 4 — WiFi control sub-command handler (CH = 0xE0)
 *===========================================================================*/

static void WiFi_HandleCtrlFromCDC(const BridgeMsg_t *m)
{
    if (m->len < 1U) { return; }
    uint8_t subcmd = m->buf[0];

    switch (subcmd)
    {
        case WIFI_SUBCMD_ESP_RESET:
            /* MCU directly hard-resets ESP32 */
            WiFi_ESP_Reset();
            break;

        case WIFI_SUBCMD_ESP_BOOT:
            /* MCU puts ESP32 into bootloader mode */
            WiFi_ESP_EnterBootloader();
            break;

        case WIFI_SUBCMD_HEARTBEAT:
            /* Heartbeat from ESP32 — just forward to CDC so PC sees it */
            Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, m->buf, m->len);
            break;

        default:
            /* STATUS / CONFIG / SCAN responses from ESP32 → forward to CDC */
            Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, m->buf, m->len);
            break;
    }
}

/*===========================================================================
 *  Section 5 — ESP32 GPIO control
 *===========================================================================*/

void WiFi_ESP_Reset(void)
{
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_RESET);
    osDelay(100);
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_SET);
    osDelay(500);   /* wait for ESP32 to boot */
}

void WiFi_ESP_EnterBootloader(void)
{
    /* 1. Stop USART2 DMA and deinitialise — release PA2/PA3 to high-Z */
    HAL_UART_DMAStop(&huart2);
    HAL_UART_DeInit(&huart2);

    /* 2. Configure PA2/PA3 as Input (floating) so external programmer can use them */
    GPIO_InitTypeDef gi = {0};
    gi.Pin  = GPIO_PIN_2 | GPIO_PIN_3;
    gi.Mode = GPIO_MODE_INPUT;
    gi.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &gi);

    /* 3. BOOT low  → ESP32 GPIO0 = 0  */
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_RESET);
    osDelay(50);

    /* 4. Pulse EN low to reset into bootloader */
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_RESET);
    osDelay(100);
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_SET);
    osDelay(100);

    /* 5. Release BOOT (keep USART2 disabled — PC can now flash ESP32) */
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_SET);
}

/*===========================================================================
 *  Section 6 — Initialisation
 *===========================================================================*/

static const osThreadAttr_t wifi_task_attrs = {
    .name       = "wifiBridgeTask",
    .stack_size = 512U * 4U,
    .priority   = (osPriority_t)osPriorityAboveNormal,
};

void WiFi_Bridge_Init(void)
{
    /* 1. Reconfigure USART2 to 921600 baud */
    HAL_UART_DMAStop(&huart2);
    HAL_UART_DeInit(&huart2);
    huart2.Init.BaudRate = WIFI_UART_BAUDRATE;  /* 921600 */
    if (HAL_UART_Init(&huart2) != HAL_OK)
    {
        /* Fallback: try to reinit at original baud (should not happen) */
        huart2.Init.BaudRate = 115200U;
        HAL_UART_Init(&huart2);
    }

    /* 2. Create TX mutex */
    s_wifi_tx_mutex = osMutexNew(&s_wifi_tx_mutex_attr);

    /* 3. Start DMA+IDLE receive on USART2 */
    HAL_UARTEx_ReceiveToIdle_DMA(&huart2, s_wifi_rx_buf, WIFI_RX_BUF_SIZE);
    __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);

    /* 4. Reset ESP32 for a clean start */
    WiFi_ESP_Reset();

    /* 5. Create WiFi bridge task */
    osThreadNew(WiFi_Bridge_Task, NULL, &wifi_task_attrs);
}
