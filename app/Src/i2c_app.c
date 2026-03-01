#include "usb_app.h"
#include "i2c.h"
#include <string.h>

#define I2C_TIMEOUT_MS 100U

void Bridge_I2C_Init(void) {}

void Bridge_I2C_Send(const uint8_t *data, uint16_t len)
{
    if (!data || len < 2U) return;
    HAL_I2C_Master_Transmit(&hi2c1, (uint8_t)(data[0]<<1), (uint8_t*)&data[1], len-1, I2C_TIMEOUT_MS);
}

void Bridge_I2C_Read(const uint8_t *data, uint16_t len)
{
    if (!data || len < 2U) return;
    uint8_t addr=data[0]<<1, rx_len=data[1], rx_buf[128];
    if (!rx_len) return;
    if (len >= 3U) { uint8_t r=data[2]; HAL_I2C_Master_Transmit(&hi2c1,addr,&r,1,I2C_TIMEOUT_MS); }
    if (HAL_I2C_Master_Receive(&hi2c1,addr|1,rx_buf,rx_len,I2C_TIMEOUT_MS)==HAL_OK)
        Bridge_SendToCDC(BRIDGE_CH_I2C_R, rx_buf, rx_len);
}

/* -------------------------------------------------------------------------
 * Bridge_I2C_Config
 * BRIDGE_CFG_I2C_SPD : value = 100000 (standard) or 400000 (fast)
 * ------------------------------------------------------------------------- */
void Bridge_I2C_Config(uint8_t param, uint32_t value)
{
    if (param != BRIDGE_CFG_I2C_SPD) { return; }
    if (value != 100000U && value != 400000U) { return; }
    HAL_I2C_DeInit(&hi2c1);
    hi2c1.Init.ClockSpeed = value;
    hi2c1.Init.DutyCycle  = (value == 400000U) ? I2C_DUTYCYCLE_2 : I2C_DUTYCYCLE_2;
    HAL_I2C_Init(&hi2c1);
}
