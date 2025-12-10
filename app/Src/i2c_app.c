#include "stm32f4xx.h"
#include "stm32f4xx_i2c.h"

// -------------------------- 配置参数（根据实际修改）--------------------------
#define I2Cx            I2C1                    // 使用的I2C外设（I2C1/I2C2/I2C3）
#define I2C_SLAVE_ADDR  0x3C << 1               // 从机地址（7位地址左移1位，最低位为读写位）
#define I2C_TIMEOUT     10000                   // 通信超时时间（防止死等）
// -----------------------------------------------------------------------------

/**
 * @brief  I2C 发送数据（查询模式）
 * @param  regAddr: 从机寄存器地址（若从机无需寄存器地址，该参数可省略）
 * @param  pData: 发送数据缓冲区
 * @param  len: 发送数据长度
 * @retval 0: 成功; 非0: 失败（超时/错误码）
 */
uint8_t I2C_Master_SendData(uint8_t regAddr, uint8_t *pData, uint16_t len)
{
    uint32_t timeout = I2C_TIMEOUT;

    // 1. 等待I2C总线空闲
    while (I2C_GetFlagStatus(I2Cx, I2C_FLAG_BUSY))
    {
        if ((timeout--) == 0) return 1; // 总线忙超时
    }

    // 2. 发送START信号
    I2C_GenerateSTART(I2Cx, ENABLE);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_MODE_SELECT))
    {
        if ((timeout--) == 0) return 2; // 发送START失败超时
    }

    // 3. 发送从机地址 + 写命令（最低位0）
    I2C_Send7bitAddress(I2Cx, I2C_SLAVE_ADDR, I2C_Direction_Transmitter);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED))
    {
        if ((timeout--) == 0) return 3; // 从机无应答超时
    }

    // 4. 发送从机寄存器地址（若无需寄存器地址，删除此段）
    I2C_SendData(I2Cx, regAddr);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_BYTE_TRANSMITTED))
    {
        if ((timeout--) == 0) return 4; // 寄存器地址发送超时
    }

    // 5. 发送数据（循环发送len个字节）
    for (uint16_t i = 0; i < len; i++)
    {
        I2C_SendData(I2Cx, pData[i]);
        timeout = I2C_TIMEOUT;
        while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_BYTE_TRANSMITTED))
        {
            if ((timeout--) == 0) return 5 + i; // 第i个字节发送超时
        }
    }

    // 6. 发送STOP信号，释放总线
    I2C_GenerateSTOP(I2Cx, ENABLE);

    return 0; // 发送成功
}

/**
 * @brief  I2C 接收数据（查询模式）
 * @param  regAddr: 从机寄存器地址（若从机无需寄存器地址，该参数可省略，需修改函数逻辑）
 * @param  pData: 接收数据缓冲区（需提前分配内存）
 * @param  len: 接收数据长度
 * @retval 0: 成功; 非0: 失败（超时/错误码）
 */
uint8_t I2C_Master_ReceiveData(uint8_t regAddr, uint8_t *pData, uint16_t len)
{
    uint32_t timeout = I2C_TIMEOUT;

    // -------------------------- 第一步：发送寄存器地址（写模式）--------------------------
    // 1. 等待I2C总线空闲
    while (I2C_GetFlagStatus(I2Cx, I2C_FLAG_BUSY))
    {
        if ((timeout--) == 0) return 1;
    }

    // 2. 发送START信号
    I2C_GenerateSTART(I2Cx, ENABLE);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_MODE_SELECT))
    {
        if ((timeout--) == 0) return 2;
    }

    // 3. 发送从机地址 + 写命令（告知从机后续要写寄存器地址）
    I2C_Send7bitAddress(I2Cx, I2C_SLAVE_ADDR, I2C_Direction_Transmitter);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED))
    {
        if ((timeout--) == 0) return 3;
    }

    // 4. 发送要读取的寄存器地址
    I2C_SendData(I2Cx, regAddr);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_BYTE_TRANSMITTED))
    {
        if ((timeout--) == 0) return 4;
    }

    // -------------------------- 第二步：接收数据（读模式）--------------------------
    // 5. 重新发送START信号（重复START，切换为读模式）
    I2C_GenerateSTART(I2Cx, ENABLE);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_MODE_SELECT))
    {
        if ((timeout--) == 0) return 5;
    }

    // 6. 发送从机地址 + 读命令（告知从机后续要读取数据）
    I2C_Send7bitAddress(I2Cx, I2C_SLAVE_ADDR, I2C_Direction_Receiver);
    timeout = I2C_TIMEOUT;
    while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_RECEIVER_MODE_SELECTED))
    {
        if ((timeout--) == 0) return 6;
    }

    // 7. 接收数据（根据长度设置ACK/NACK）
    for (uint16_t i = 0; i < len; i++)
    {
        // 最后一个字节：接收前设置为NACK（告知从机停止发送）
        if (i == len - 1)
        {
            I2C_AcknowledgeConfig(I2Cx, DISABLE); // 关闭ACK
        }

        // 等待数据接收完成
        timeout = I2C_TIMEOUT;
        while (!I2C_CheckEvent(I2Cx, I2C_EVENT_MASTER_BYTE_RECEIVED))
        {
            if ((timeout--) == 0) return 7 + i;
        }

        // 读取接收的数据
        pData[i] = I2C_ReceiveData(I2Cx);
    }

    // 8. 发送STOP信号，释放总线
    I2C_GenerateSTOP(I2Cx, ENABLE);

    // 9. 恢复ACK使能（为下次通信做准备）
    I2C_AcknowledgeConfig(I2Cx, ENABLE);

    return 0; // 接收成功
}

// -------------------------- 示例调用 --------------------------
void I2C_Test(void)
{
    uint8_t tx_data[] = {0x12, 0x34, 0x56}; // 要发送的数据
    uint8_t rx_data[3] = {0};               // 接收数据缓冲区
    uint8_t status;

    // 1. 发送数据到从机寄存器0x00
    status = I2C_Master_SendData(0x00, tx_data, sizeof(tx_data));
    if (status == 0)
    {
        // 发送成功
    }
    else
    {
        // 发送失败，status为错误码
    }

    // 2. 从从机寄存器0x00读取3个字节
    status = I2C_Master_ReceiveData(0x00, rx_data, 3);
    if (status == 0)
    {
        // 接收成功，rx_data中为读取到的数据
    }
    else
    {
        // 接收失败，status为错误码
    }
}

