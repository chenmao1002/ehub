#include "usb_app.h"
#include "i2c.h"
#include <string.h>

#define I2C_TIMEOUT_MS 100U

typedef enum {
    BRIDGE_I2C_MASTER = 0,
    BRIDGE_I2C_SLAVE  = 1,
} BridgeI2cRole_t;

static BridgeI2cRole_t s_i2c_role = BRIDGE_I2C_MASTER;
static uint8_t s_i2c_own_addr = 0x3CU;

static uint8_t  s_i2c_slave_rx_buf[BRIDGE_MAX_DATA];
static uint16_t s_i2c_slave_rx_len = 0U;
static uint8_t  s_i2c_slave_tx_buf[BRIDGE_MAX_DATA] = {0x00U};
static uint16_t s_i2c_slave_tx_len = 1U;

static void Bridge_I2C_ApplyMode(void)
{
    HAL_I2C_DeInit(&hi2c1);

    hi2c1.Init.OwnAddress1 = (uint32_t)(s_i2c_own_addr << 1U);
    HAL_I2C_Init(&hi2c1);

    if (s_i2c_role == BRIDGE_I2C_SLAVE)
    {
        s_i2c_slave_rx_len = 0U;
        HAL_I2C_EnableListen_IT(&hi2c1);
    }
}

void Bridge_I2C_Init(void)
{
    Bridge_I2C_ApplyMode();
}

void Bridge_I2C_Send(const uint8_t *data, uint16_t len)
{
    if (!data || len < 2U) return;

    if (s_i2c_role == BRIDGE_I2C_SLAVE)
    {
        if (len > BRIDGE_MAX_DATA) { len = BRIDGE_MAX_DATA; }
        memcpy(s_i2c_slave_tx_buf, data, len);
        s_i2c_slave_tx_len = len;
        return;
    }

    HAL_I2C_Master_Transmit(&hi2c1, (uint8_t)(data[0] << 1U), (uint8_t *)&data[1], len - 1U, I2C_TIMEOUT_MS);
}

void Bridge_I2C_Read(const uint8_t *data, uint16_t len)
{
    if (s_i2c_role != BRIDGE_I2C_MASTER) return;
    if (!data || len < 2U) return;
    uint8_t addr=data[0]<<1, rx_len=data[1], rx_buf[BRIDGE_MAX_DATA];
    if (!rx_len) return;
    if (rx_len > BRIDGE_MAX_DATA) { rx_len = BRIDGE_MAX_DATA; }
    if (len >= 3U) { uint8_t r=data[2]; HAL_I2C_Master_Transmit(&hi2c1,addr,&r,1,I2C_TIMEOUT_MS); }
    if (HAL_I2C_Master_Receive(&hi2c1,addr,rx_buf,rx_len,I2C_TIMEOUT_MS)==HAL_OK)
        Bridge_SendToAll(BRIDGE_CH_I2C_R, rx_buf, rx_len);
}

/* -------------------------------------------------------------------------
 * Bridge_I2C_Config
 * BRIDGE_CFG_I2C_SPD : value = 100000 (standard) or 400000 (fast)
 * ------------------------------------------------------------------------- */
void Bridge_I2C_Config(uint8_t param, uint32_t value)
{
    switch (param)
    {
        case BRIDGE_CFG_I2C_SPD:
            if (value == 100000U || value == 400000U) {
                hi2c1.Init.ClockSpeed = value;
            }
            break;

        case BRIDGE_CFG_I2C_ROLE:
            s_i2c_role = (value == 0U) ? BRIDGE_I2C_MASTER : BRIDGE_I2C_SLAVE;
            break;

        case BRIDGE_CFG_I2C_OWN:
            if (value >= 0x08U && value <= 0x77U) {
                s_i2c_own_addr = (uint8_t)value;
            }
            break;

        default:
            return;
    }

    Bridge_I2C_ApplyMode();
}

void HAL_I2C_AddrCallback(I2C_HandleTypeDef *hi2c, uint8_t TransferDirection, uint16_t AddrMatchCode)
{
    (void)AddrMatchCode;

    if (hi2c != &hi2c1 || s_i2c_role != BRIDGE_I2C_SLAVE) { return; }

    if (TransferDirection == I2C_DIRECTION_TRANSMIT)
    {
        s_i2c_slave_rx_len = 0U;
        HAL_I2C_Slave_Seq_Receive_IT(&hi2c1, &s_i2c_slave_rx_buf[s_i2c_slave_rx_len], 1U, I2C_NEXT_FRAME);
    }
    else
    {
        uint16_t tx_len = (s_i2c_slave_tx_len == 0U) ? 1U : s_i2c_slave_tx_len;
        HAL_I2C_Slave_Seq_Transmit_IT(&hi2c1, s_i2c_slave_tx_buf, tx_len, I2C_LAST_FRAME);
    }
}

void HAL_I2C_SlaveRxCpltCallback(I2C_HandleTypeDef *hi2c)
{
    if (hi2c != &hi2c1 || s_i2c_role != BRIDGE_I2C_SLAVE) { return; }

    if (s_i2c_slave_rx_len < BRIDGE_MAX_DATA) {
        s_i2c_slave_rx_len++;
    }

    if (s_i2c_slave_rx_len < BRIDGE_MAX_DATA) {
        HAL_I2C_Slave_Seq_Receive_IT(&hi2c1, &s_i2c_slave_rx_buf[s_i2c_slave_rx_len], 1U, I2C_NEXT_FRAME);
    }
}

void HAL_I2C_ListenCpltCallback(I2C_HandleTypeDef *hi2c)
{
    if (hi2c != &hi2c1 || s_i2c_role != BRIDGE_I2C_SLAVE) { return; }

    if (s_i2c_slave_rx_len > 0U) {
        Bridge_SendToAll(BRIDGE_CH_I2C_W, s_i2c_slave_rx_buf, s_i2c_slave_rx_len);
        s_i2c_slave_rx_len = 0U;
    }

    HAL_I2C_EnableListen_IT(&hi2c1);
}

void HAL_I2C_ErrorCallback(I2C_HandleTypeDef *hi2c)
{
    if (hi2c != &hi2c1 || s_i2c_role != BRIDGE_I2C_SLAVE) { return; }
    s_i2c_slave_rx_len = 0U;
    HAL_I2C_EnableListen_IT(&hi2c1);
}
