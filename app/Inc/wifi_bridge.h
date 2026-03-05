/**
 * @file    wifi_bridge.h
 * @brief   WiFi ↔ Bus bridge via ESP32 — USART2 transport layer
 *
 * The ESP32-N8 module is connected to MCU via USART2 (PA2 TX / PA3 RX)
 * at 1 Mbaud.  It acts as a transparent WiFi ↔ UART bridge so that
 * a PC on the same LAN can send / receive the same Bridge protocol
 * frames that currently travel over USB CDC.
 *
 * Control pins:
 *   PC2  (ESP_EN)   — high = run, pulse low = reset
 *   PC1  (ESP_BOOT) — low during reset = enter bootloader
 *
 * Frame format on USART2 is identical to CDC:
 *   CMD  [0xAA][0x55][CH][LEN_H][LEN_L][DATA…][CRC8]
 *   RPY  [0xBB][0x55][CH][LEN_H][LEN_L][DATA…][CRC8]
 */

#ifndef __WIFI_BRIDGE_H__
#define __WIFI_BRIDGE_H__

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- WiFi control channel (processed jointly by MCU + ESP32) ------------ */
#define BRIDGE_CH_WIFI_CTRL   0xE0U

/* ---- WiFi control sub-commands (data[0] of a 0xE0 frame) --------------- */
#define WIFI_SUBCMD_STATUS       0x01U  /* query WiFi status           */
#define WIFI_SUBCMD_CONFIG       0x02U  /* set WiFi SSID / password    */
#define WIFI_SUBCMD_ESP_RESET    0x03U  /* MCU hard-resets ESP32       */
#define WIFI_SUBCMD_ESP_BOOT     0x04U  /* MCU puts ESP32 in download  */
#define WIFI_SUBCMD_SCAN         0x05U  /* scan WiFi networks          */
#define WIFI_SUBCMD_ESP_PASSTHROUGH 0x06U /* CDC↔USART2 transparent passthrough */
#define WIFI_SUBCMD_HEARTBEAT    0x10U  /* heartbeat ping/pong         */

/* ---- MCU ↔ ESP32 UART fixed baud rate ---------------------------------- */
#define WIFI_UART_BAUDRATE       1000000U

/* ---- DMA receive buffer size (> max frame ≈ 1054 bytes) ---------------- */
#define WIFI_RX_BUF_SIZE         2048U

/* ---- Ring buffer between ISR and Task ----------------------------------- */
#define WIFI_RING_SIZE           4096U

/**
 * @brief  Initialise the WiFi bridge module.
 *         - Reconfigure USART2 to 921600 baud
 *         - Start DMA+IDLE receive on USART2
 *         - Reset ESP32 (clean start)
 *         - Create wifiBridgeTask
 *
 *         Call once at the end of Bridge_Init().
 */
void WiFi_Bridge_Init(void);

/**
 * @brief  Send a bridge reply frame to ESP32 via USART2.
 *         Frame layout: [0xBB][0x55][CH][LEN_H][LEN_L][DATA][CRC8]
 *
 * @param  ch    Channel ID (BRIDGE_CH_*)
 * @param  data  Payload pointer
 * @param  len   Payload length (1 .. 128)
 */
void WiFi_Bridge_Send(uint8_t ch, const uint8_t *data, uint16_t len);

/**
 * @brief  Called from HAL_UARTEx_RxEventCallback (ISR context) when
 *         USART2 DMA/IDLE fires.  Copies raw bytes into the ring buffer
 *         and re-arms DMA.
 *
 * @param  data  Pointer to USART2 DMA receive buffer
 * @param  size  Number of bytes received this event
 */
void WiFi_Bridge_RxHandler(const uint8_t *data, uint16_t size);

/**
 * @brief  Return pointer to the USART2 DMA receive buffer
 *         (used by usb_app.c to re-arm DMA after RxEvent).
 */
uint8_t *WiFi_Bridge_GetRxBuf(void);

/**
 * @brief  FreeRTOS task — drains the ring buffer, parses bridge frames,
 *         and either dispatches bus commands or handles WiFi-control
 *         sub-commands locally.
 */
void WiFi_Bridge_Task(void *argument);

/**
 * @brief  Hard-reset ESP32: pull PC2/ESP_EN low 100 ms then release.
 */
void WiFi_ESP_Reset(void);

/**
 * @brief  Put ESP32 into bootloader mode AND release USART2 pins:
 *         1. Stop USART2 DMA + HAL_UART_DeInit (PA2/PA3 → high-Z)
 *         2. BOOT low → EN low 100 ms → EN high → BOOT high
 *         After this call, an external programmer can flash ESP32 via
 *         the shared USART2 lines (COM port).  MCU firmware re-flash
 *         via OpenOCD will restore USART2 on next boot.
 */
void WiFi_ESP_EnterBootloader(void);

/**
 * @brief  Returns non-zero if ESP32 is in bootloader mode
 *         (USART2 deinitialized, PA2/PA3 floating).
 */
uint8_t WiFi_Bridge_IsBootloader(void);

/**
 * @brief  Enter CDC↔USART2 transparent passthrough mode for flashing ESP32.
 *         1. Put ESP32 into bootloader (BOOT/EN sequence)
 *         2. Reinit USART2 at 115200 (esptool default sync speed)
 *         3. Enter passthrough: raw CDC bytes ↔ USART2
 *         DTR/RTS → EN/BOOT, SET_LINE_CODING → USART2 baud rate.
 *         Exit: reset MCU.
 */
void WiFi_ESP_EnterPassthrough(void);

/** @brief  Returns non-zero if CDC↔USART2 passthrough is active. */
uint8_t WiFi_Bridge_IsPassthrough(void);

/** @brief  Passthrough: feed raw CDC data into CDC→UART ring (ISR-safe). */
void WiFi_Passthrough_CDCRx(const uint8_t *data, uint16_t len);

/** @brief  Passthrough: feed raw USART2 data into UART→CDC ring (ISR-safe). */
void WiFi_Passthrough_UARTRx(const uint8_t *data, uint16_t len);

/** @brief  Passthrough: request USART2 baud rate change (ISR-safe, deferred). */
void WiFi_Passthrough_SetBaud(uint32_t baud);

/** @brief  Passthrough: map CDC DTR/RTS to ESP32 EN/BOOT (ISR-safe). */
void WiFi_Passthrough_SetLineState(uint16_t state);

/** @brief  Passthrough: check if CDC→UART ring is nearly full (ISR-safe). */
uint8_t WiFi_Passthrough_C2URingNearlyFull(void);

/** @brief  Passthrough: mark CDC OUT endpoint as paused (called from USB ISR). */
void WiFi_Passthrough_SetCDCPaused(void);

#ifdef __cplusplus
}
#endif

#endif /* __WIFI_BRIDGE_H__ */
