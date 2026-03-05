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
#include "usbd_cdc_if.h"
#include "usbd_def.h"
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

/* ---- Debug counters (exposed via BRIDGE_CH_WIFI_CTRL subcmd 0xF1) ------- */
volatile uint32_t s_dbg_uart2_tx_ok    = 0U;  /* WiFi_Bridge_Send DMA TX OK   */
volatile uint32_t s_dbg_uart2_tx_fail  = 0U;  /* WiFi_Bridge_Send DMA TX fail */
volatile uint32_t s_dbg_uart2_rx_event = 0U;  /* USART2 RxEvent callback      */
volatile uint32_t s_dbg_uart2_rx_bytes = 0U;  /* total bytes into ring buffer */
volatile uint32_t s_dbg_uart2_error    = 0U;  /* USART2 ErrorCallback count   */
volatile uint32_t s_dbg_uart2_frames   = 0U;  /* complete frames parsed        */
volatile uint32_t s_dbg_dma_init_rc    = 0xFFU; /* return code of ReceiveToIdle_DMA */
volatile uint32_t s_dbg_uart2_sr       = 0U;  /* USART2->SR snapshot          */
volatile uint32_t s_dbg_dma_cr         = 0U;  /* DMA stream CR snapshot       */
volatile uint32_t s_dbg_dma_ndtr       = 0U;  /* DMA stream NDTR snapshot     */

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

/* ---- Bootloader mode flag: when set, USART2 is deinitialized ----------- */
static volatile uint8_t s_esp_in_bootloader = 0U;

/* ---- Passthrough mode (CDC ↔ USART2 transparent for ESP32 flashing) ---- */
static volatile uint8_t  s_passthrough_mode = 0U;
static volatile uint32_t s_pt_new_baud = 0U;   /* deferred baud rate change */

#define PT_RING_SIZE  2048U
static volatile uint8_t  pt_c2u_ring[PT_RING_SIZE]; /* CDC → UART */
static volatile uint16_t pt_c2u_head = 0U;
static volatile uint16_t pt_c2u_tail = 0U;
static volatile uint8_t  pt_u2c_ring[PT_RING_SIZE]; /* UART → CDC */
static volatile uint16_t pt_u2c_head = 0U;
static volatile uint16_t pt_u2c_tail = 0U;
static volatile uint8_t  pt_cdc_rx_paused = 0U; /* USB CDC OUT endpoint paused */

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
    if (s_esp_in_bootloader) { return; }  /* USART2 deinitialized */
    s_dbg_uart2_rx_bytes += size;
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
    if (s_esp_in_bootloader) { return; }  /* USART2 deinitialized */
    if (len == 0U || len > BRIDGE_MAX_DATA) { return; }

    if (osMutexAcquire(s_wifi_tx_mutex, 200U) != osOK) { return; }

    uint8_t crc = 0U;
    s_wifi_tx_buf[0] = BRIDGE_SOF0_RPY;            /* 0xBB */
    s_wifi_tx_buf[1] = BRIDGE_SOF1;                 /* 0x55 */
    s_wifi_tx_buf[2] = ch;             crc ^= ch;
    s_wifi_tx_buf[3] = (uint8_t)(len >> 8U);    crc ^= s_wifi_tx_buf[3];
    s_wifi_tx_buf[4] = (uint8_t)(len & 0xFFU);  crc ^= s_wifi_tx_buf[4];
    memcpy(&s_wifi_tx_buf[5], data, len);
    for (uint16_t i = 0U; i < len; i++) { crc ^= data[i]; }
    s_wifi_tx_buf[5U + len] = crc;

    /* ---- Transmit: use polling for small frames (< 128 B), DMA for large ---- */
    uint16_t total = (uint16_t)(6U + len);
    if (total <= 128U)
    {
        /* Polling TX: deterministic, no DMA-interrupt dependency.
         * At 1 Mbaud 128 bytes takes ~1.3 ms — acceptable. */
        HAL_StatusTypeDef txrc = HAL_UART_Transmit(&huart2, s_wifi_tx_buf, total, 20U);
        if (txrc == HAL_OK) { s_dbg_uart2_tx_ok++; }
        else                { s_dbg_uart2_tx_fail++; }
    }
    else
    {
        /* Large frame: use DMA.  Wait for previous DMA to finish first. */
        uint32_t t0 = HAL_GetTick();
        while (HAL_UART_GetState(&huart2) & HAL_UART_STATE_BUSY_TX)
        {
            if ((HAL_GetTick() - t0) > 20U) {
                HAL_UART_AbortTransmit(&huart2);   /* Abort stuck DMA */
                break;
            }
            osDelay(1);
        }
        HAL_StatusTypeDef txrc = HAL_UART_Transmit_DMA(&huart2, s_wifi_tx_buf, total);
        if (txrc == HAL_OK) { s_dbg_uart2_tx_ok++; }
        else                { s_dbg_uart2_tx_fail++; }
    }

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

/*===========================================================================
 *  Passthrough — CDC ↔ USART2 transparent bridge for ESP32 flashing
 *===========================================================================*/

void WiFi_Passthrough_CDCRx(const uint8_t *data, uint16_t len)
{
    for (uint16_t i = 0U; i < len; i++) {
        uint16_t next = (pt_c2u_head + 1U) % PT_RING_SIZE;
        if (next == pt_c2u_tail) {
            /* Ring full — drop remaining bytes.
             * USB endpoint is already paused by DataOut handler.
             * Data loss shouldn't happen if flow control works. */
            break;
        }
        pt_c2u_ring[pt_c2u_head] = data[i];
        pt_c2u_head = next;
    }
}

void WiFi_Passthrough_UARTRx(const uint8_t *data, uint16_t len)
{
    for (uint16_t i = 0U; i < len; i++) {
        uint16_t next = (pt_u2c_head + 1U) % PT_RING_SIZE;
        if (next != pt_u2c_tail) {
            pt_u2c_ring[pt_u2c_head] = data[i];
            pt_u2c_head = next;
        }
    }
}

void WiFi_Passthrough_SetBaud(uint32_t baud)
{
    if (!s_passthrough_mode || baud == 0U) { return; }
    s_pt_new_baud = baud;   /* picked up in passthrough task loop */
}

void WiFi_Passthrough_SetLineState(uint16_t state)
{
    if (!s_passthrough_mode) { return; }
    /* NodeMCU auto-reset mapping (inverted by transistors on dev boards):
     * DTR asserted (1) → BOOT/GPIO0 LOW (bootloader)
     * RTS asserted (1) → EN LOW (reset)                */
    uint8_t dtr = (state & 0x01U) ? 1U : 0U;
    uint8_t rts = (state & 0x02U) ? 1U : 0U;
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin,
                      dtr ? GPIO_PIN_RESET : GPIO_PIN_SET);
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin,
                      rts ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

uint8_t WiFi_Passthrough_C2URingNearlyFull(void)
{
    uint16_t used = (pt_c2u_head >= pt_c2u_tail)
        ? (pt_c2u_head - pt_c2u_tail)
        : (PT_RING_SIZE - pt_c2u_tail + pt_c2u_head);
    return (used > (PT_RING_SIZE * 3U / 4U)) ? 1U : 0U;
}

void WiFi_Passthrough_SetCDCPaused(void)
{
    pt_cdc_rx_paused = 1U;
}

/** Process one iteration of the passthrough loop (called from task). */
static void WiFi_Passthrough_Process(void)
{
    /* ---- Deferred baud-rate change (requested from USB ISR) ---- */
    if (s_pt_new_baud) {
        uint32_t nb = s_pt_new_baud;
        s_pt_new_baud = 0U;
        HAL_UART_DMAStop(&huart2);
        HAL_UART_DeInit(&huart2);
        huart2.Init.BaudRate     = nb;
        huart2.Init.OverSampling = UART_OVERSAMPLING_16;
        HAL_UART_Init(&huart2);
        __HAL_UART_CLEAR_OREFLAG(&huart2);
        (void)huart2.Instance->DR;
        HAL_UARTEx_ReceiveToIdle_DMA(&huart2, s_wifi_rx_buf, WIFI_RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
    }

    /* ---- CDC → UART: drain ring, blocking TX ---- */
    uint8_t tx_chunk[64];
    uint16_t tn = 0U;
    while (tn < sizeof(tx_chunk) && pt_c2u_head != pt_c2u_tail) {
        tx_chunk[tn++] = pt_c2u_ring[pt_c2u_tail];
        pt_c2u_tail = (pt_c2u_tail + 1U) % PT_RING_SIZE;
    }
    if (tn > 0U) {
        HAL_UART_Transmit(&huart2, tx_chunk, tn, 100U);
    }

    /* ---- If CDC OUT endpoint was paused (ring was full), re-arm it ---- */
    if (pt_cdc_rx_paused) {
        uint16_t used = (pt_c2u_head >= pt_c2u_tail)
            ? (pt_c2u_head - pt_c2u_tail)
            : (PT_RING_SIZE - pt_c2u_tail + pt_c2u_head);
        if (used < PT_RING_SIZE / 2) {
            /* Enough space now — re-arm USB CDC OUT endpoint */
            extern void WiFi_Passthrough_RearmCDC(void);
            WiFi_Passthrough_RearmCDC();
            pt_cdc_rx_paused = 0U;
        }
    }

    /* ---- UART → CDC: drain ring, send via USB ---- */
    static uint8_t  cdc_chunk[64];
    static uint16_t cdc_pending = 0U;
    if (cdc_pending > 0U) {
        /* Retry previous unsent chunk */
        if (CDC_Transmit_FS(cdc_chunk, cdc_pending) != USBD_BUSY) {
            cdc_pending = 0U;
        }
    } else {
        uint16_t cn = 0U;
        while (cn < sizeof(cdc_chunk) && pt_u2c_head != pt_u2c_tail) {
            cdc_chunk[cn++] = pt_u2c_ring[pt_u2c_tail];
            pt_u2c_tail = (pt_u2c_tail + 1U) % PT_RING_SIZE;
        }
        if (cn > 0U) {
            if (CDC_Transmit_FS(cdc_chunk, cn) == USBD_BUSY) {
                cdc_pending = cn;
            }
        }
    }
}

void WiFi_Bridge_Task(void *argument)
{
    (void)argument;
    uint8_t byte;

    for (;;)
    {
        /* ---- Passthrough mode: bypass frame parser ---- */
        if (s_passthrough_mode) {
            WiFi_Passthrough_Process();
            osDelay(1);
            continue;
        }

        /* Drain ring buffer — process up to 1024 bytes per iteration */
        uint16_t budget = 1024U;
        while (budget-- > 0U && ring_get(&byte))
        {
            if (wifi_parse_byte(byte))
            {
                s_dbg_uart2_frames++;
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

        case 0xF1U:
        {
            /* MCU-side UART2 diagnostic counters → send back to CDC */
            uint8_t rpl[1 + 6*4];   /* subcmd + 6 x uint32 */
            rpl[0] = 0xF1U;
            uint32_t v;
            uint16_t pos = 1U;
            v = s_dbg_uart2_tx_ok;    memcpy(&rpl[pos], &v, 4U); pos += 4U;
            v = s_dbg_uart2_tx_fail;  memcpy(&rpl[pos], &v, 4U); pos += 4U;
            v = s_dbg_uart2_rx_event; memcpy(&rpl[pos], &v, 4U); pos += 4U;
            v = s_dbg_uart2_rx_bytes; memcpy(&rpl[pos], &v, 4U); pos += 4U;
            v = s_dbg_uart2_error;    memcpy(&rpl[pos], &v, 4U); pos += 4U;
            v = s_dbg_uart2_frames;   memcpy(&rpl[pos], &v, 4U); pos += 4U;
            Bridge_SendToCDC(BRIDGE_CH_WIFI_CTRL, rpl, pos);
            break;
        }

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
    /* 0. Set flag FIRST — prevents other tasks from touching USART2 */
    s_esp_in_bootloader = 1U;

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

uint8_t WiFi_Bridge_IsBootloader(void)
{
    return s_esp_in_bootloader;
}

uint8_t WiFi_Bridge_IsPassthrough(void)
{
    return s_passthrough_mode;
}

void WiFi_ESP_EnterPassthrough(void)
{
    /* 1. Block normal bridge operations immediately */
    s_esp_in_bootloader = 1U;

    /* 2. Stop USART2 */
    HAL_UART_DMAStop(&huart2);
    HAL_UART_DeInit(&huart2);

    /* 3. ESP32 bootloader entry: BOOT=LOW → EN pulse → release BOOT */
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_RESET);
    osDelay(50);
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_RESET);
    osDelay(100);
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_SET);
    osDelay(50);
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_SET);
    osDelay(50);

    /* 4. Reinit USART2 at 115200 baud (esptool default sync speed) */
    huart2.Init.BaudRate     = 115200U;
    huart2.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart2);

    /* 5. Clear errors and stale data */
    __HAL_UART_CLEAR_OREFLAG(&huart2);
    __HAL_UART_CLEAR_NEFLAG(&huart2);
    __HAL_UART_CLEAR_FEFLAG(&huart2);
    (void)huart2.Instance->DR;

    /* 6. Start DMA+IDLE receive */
    HAL_UARTEx_ReceiveToIdle_DMA(&huart2, s_wifi_rx_buf, WIFI_RX_BUF_SIZE);
    __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);

    /* 7. Reset passthrough ring buffers */
    pt_c2u_head = pt_c2u_tail = 0U;
    pt_u2c_head = pt_u2c_tail = 0U;
    s_pt_new_baud = 0U;
    pt_cdc_rx_paused = 0U;

    /* 8. Enable passthrough (LAST — task loop will pick this up) */
    s_passthrough_mode = 1U;
}

/*===========================================================================
 *  Section 6 — Initialisation
 *===========================================================================*/

static const osThreadAttr_t wifi_task_attrs = {
    .name       = "wifiBridgeTask",
    .stack_size = 1024U * 4U,
    .priority   = (osPriority_t)osPriorityAboveNormal,
};

void WiFi_Bridge_Init(void)
{
    /* 1. Reconfigure USART2 to 1 Mbaud.
     *    PCLK1 = 30 MHz  \u2192  OVER16: USARTDIV = 30 MHz / (16 \u00d7 1 MHz) = 1.875
     *                        BRR = 0x1E  \u2192  mantissa 1, fraction 14 \u2192 valid.
     *    1 Mbaud with OVER16 gives better noise margin than 2 Mbaud OVER8. */
    HAL_UART_DMAStop(&huart2);
    HAL_UART_DeInit(&huart2);
    huart2.Init.BaudRate     = WIFI_UART_BAUDRATE;          /* 1000000 */
    huart2.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart2) != HAL_OK)
    {
        /* Fallback: try to reinit at original baud (should not happen) */
        huart2.Init.BaudRate = 115200U;
        huart2.Init.OverSampling = UART_OVERSAMPLING_16;
        HAL_UART_Init(&huart2);
    }

    /* 2. Create TX mutex */
    s_wifi_tx_mutex = osMutexNew(&s_wifi_tx_mutex_attr);

    /* 3. Reset ESP32 FIRST (before arming DMA!) — avoids boot-noise
     *    at 74880 baud from corrupting the DMA receive state machine.  */
    WiFi_ESP_Reset();

    /* 4. Wait additional time for ESP32 to finish booting and call
     *    Serial.begin(2000000).  ESP32 ROM bootloader + 2nd stage +
     *    Arduino setup() typically takes ~800-1200 ms after EN release. */
    osDelay(1500);

    /* 5. Flush any residual UART errors, then start DMA+IDLE receive */
    __HAL_UART_CLEAR_OREFLAG(&huart2);
    __HAL_UART_CLEAR_NEFLAG(&huart2);
    __HAL_UART_CLEAR_FEFLAG(&huart2);
    /* Read DR to clear any stale data */
    (void)huart2.Instance->DR;

    HAL_StatusTypeDef dma_rc = HAL_UARTEx_ReceiveToIdle_DMA(&huart2, s_wifi_rx_buf, WIFI_RX_BUF_SIZE);
    s_dbg_dma_init_rc = (uint32_t)dma_rc;
    __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);

    /* 6. Create WiFi bridge task */
    osThreadNew(WiFi_Bridge_Task, NULL, &wifi_task_attrs);
}
