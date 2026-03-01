/**
 * @file    spi_app.c
 * @brief   SPI1 bridge  (master, full-duplex)
 *
 * PC → Device frame payload (channel = BRIDGE_CH_SPI):
 *   Raw bytes to clock out on MOSI.  The device performs a full-duplex
 *   TransmitReceive and immediately returns the MISO bytes to the PC
 *   using the same channel (BRIDGE_CH_SPI).
 *
 * Chip-select pin:
 *   Default = PA4  (SPI1_NSS in software-NSS mode).
 *   Change SPI_CS_PORT / SPI_CS_PIN below if your board wires it elsewhere.
 */

#include "usb_app.h"
#include "spi.h"
#include "main.h"
#include <string.h>

/* ---- CS pin configuration — modify to match your hardware --------------- */
#ifndef SPI_CS_PORT
  #define SPI_CS_PORT   GPIOA
#endif
#ifndef SPI_CS_PIN
  #define SPI_CS_PIN    GPIO_PIN_4
#endif

/* -------------------------------------------------------------------------
 * Bridge_SPI_Init
 * MX_SPI1_Init() already called by CubeMX-generated code.
 * Only the CS GPIO needs an initial state.
 * ------------------------------------------------------------------------- */
void Bridge_SPI_Init(void)
{
    /* De-assert CS (idle HIGH) */
    HAL_GPIO_WritePin(SPI_CS_PORT, SPI_CS_PIN, GPIO_PIN_SET);
}

/* -------------------------------------------------------------------------
 * Bridge_SPI_Send
 * Full-duplex transfer: MOSI = data, MISO captured and forwarded to PC.
 * ------------------------------------------------------------------------- */
void Bridge_SPI_Send(const uint8_t *data, uint16_t len)
{
    static uint8_t rx_buf[BRIDGE_MAX_DATA];

    if (data == NULL || len == 0U) { return; }
    if (len > BRIDGE_MAX_DATA) { len = BRIDGE_MAX_DATA; }

    HAL_GPIO_WritePin(SPI_CS_PORT, SPI_CS_PIN, GPIO_PIN_RESET);  /* CS LOW  */
    HAL_SPI_TransmitReceive(&hspi1, (uint8_t *)data, rx_buf, len, 50U);
    HAL_GPIO_WritePin(SPI_CS_PORT, SPI_CS_PIN, GPIO_PIN_SET);     /* CS HIGH */

    /* Return received bytes to PC */
    Bridge_SendToCDC(BRIDGE_CH_SPI, rx_buf, len);
}
