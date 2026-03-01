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
 *   CS is driven externally — no software CS control in this driver.
 */

#include "usb_app.h"
#include "spi.h"
#include <string.h>

/* -------------------------------------------------------------------------
 * Bridge_SPI_Init
 * MX_SPI1_Init() already called by CubeMX-generated code.
 * Only the CS GPIO needs an initial state.
 * ------------------------------------------------------------------------- */
void Bridge_SPI_Init(void)
{
    /* CS controlled externally — nothing to initialise here */
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

    HAL_SPI_TransmitReceive(&hspi1, (uint8_t *)data, rx_buf, len, 50U);

    /* Return received bytes to PC */
    Bridge_SendToCDC(BRIDGE_CH_SPI, rx_buf, len);
}

/* -------------------------------------------------------------------------
 * Bridge_SPI_Config
 * BRIDGE_CFG_SPI_SPD : value = prescaler index 0-7
 *   index 0 → SPI_BAUDRATEPRESCALER_2   (42 MHz)
 *   index 1 → SPI_BAUDRATEPRESCALER_4   (21 MHz)
 *   index 2 → SPI_BAUDRATEPRESCALER_8   (10.5 MHz)
 *   index 3 → SPI_BAUDRATEPRESCALER_16  (5.25 MHz)
 *   index 4 → SPI_BAUDRATEPRESCALER_32  (2.625 MHz)
 *   index 5 → SPI_BAUDRATEPRESCALER_64  (1.31 MHz)
 *   index 6 → SPI_BAUDRATEPRESCALER_128 (656 kHz)
 *   index 7 → SPI_BAUDRATEPRESCALER_256 (328 kHz)
 * BRIDGE_CFG_SPI_MODE : value = 0/1/2/3 (CPOL<<1 | CPHA)
 * ------------------------------------------------------------------------- */
static const uint32_t s_spi_prescalers[8] = {
    SPI_BAUDRATEPRESCALER_2,
    SPI_BAUDRATEPRESCALER_4,
    SPI_BAUDRATEPRESCALER_8,
    SPI_BAUDRATEPRESCALER_16,
    SPI_BAUDRATEPRESCALER_32,
    SPI_BAUDRATEPRESCALER_64,
    SPI_BAUDRATEPRESCALER_128,
    SPI_BAUDRATEPRESCALER_256,
};

typedef enum {
    BRIDGE_SPI_MASTER = 0,
    BRIDGE_SPI_SLAVE  = 1,
} BridgeSpiRole_t;

static BridgeSpiRole_t s_spi_role = BRIDGE_SPI_MASTER;

void Bridge_SPI_Config(uint8_t param, uint32_t value)
{
    HAL_SPI_DeInit(&hspi1);

    if (param == BRIDGE_CFG_SPI_SPD)
    {
        if (value > 7U) { value = 7U; }
        hspi1.Init.BaudRatePrescaler = s_spi_prescalers[value];
    }
    else if (param == BRIDGE_CFG_SPI_MODE)
    {
        switch (value & 0x03U)
        {
            case 0: hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE; break;
            case 1: hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;  hspi1.Init.CLKPhase = SPI_PHASE_2EDGE; break;
            case 2: hspi1.Init.CLKPolarity = SPI_POLARITY_HIGH; hspi1.Init.CLKPhase = SPI_PHASE_1EDGE; break;
            case 3: hspi1.Init.CLKPolarity = SPI_POLARITY_HIGH; hspi1.Init.CLKPhase = SPI_PHASE_2EDGE; break;
            default: break;
        }
    }
    else if (param == BRIDGE_CFG_SPI_ROLE)
    {
        s_spi_role = (value == 0U) ? BRIDGE_SPI_MASTER : BRIDGE_SPI_SLAVE;
    }

    hspi1.Init.Mode = (s_spi_role == BRIDGE_SPI_MASTER) ? SPI_MODE_MASTER : SPI_MODE_SLAVE;

    HAL_SPI_Init(&hspi1);
}
