#ifndef __I2C_APP_H
#define __I2C_APP_H

#include "stm32f4xx.h"  // 包含STM32F4标准库核心头文件

// -------------------------- 可配置参数（根据实际硬件修改）--------------------------
#define I2Cx            I2C1                    // 使用的I2C外设（I2C1/I2C2/I2C3）
#define I2C_SLAVE_ADDR  0x3C << 1               // 从机7位地址左移1位（最低位为读写位）
#define I2C_TIMEOUT     10000                   // 通信超时阈值（防止死等）
#define I2C_CLOCK_SPEED 100000                  // I2C通信速率（100KHz/400000=400KHz）
// ----------------------------------------------------------------------------------

// -------------------------- I2C初始化函数声明（若需在其他文件调用）--------------------------
/**
 * @brief  I2C外设初始化（GPIO复用配置+I2C参数配置）
 * @param  无
 * @retval 无
 */
void I2Cx_Init(void);

// -------------------------- I2C收发函数声明 --------------------------
/**
 * @brief  I2C主机发送数据（查询模式，带寄存器地址）
 * @param  regAddr: 从机目标寄存器地址（若无需寄存器地址，可删除该参数并修改实现）
 * @param  pData: 发送数据缓冲区（需确保数据有效）
 * @param  len: 发送数据长度（最大支持uint16_t范围）
 * @retval uint8_t: 0=成功；非0=失败（错误码对应具体步骤）
 */
uint8_t I2C_Master_SendData(uint8_t regAddr, uint8_t *pData, uint16_t len);

/**
 * @brief  I2C主机接收数据（查询模式，带寄存器地址）
 * @param  regAddr: 从机目标寄存器地址（若无需寄存器地址，可删除该参数并修改实现）
 * @param  pData: 接收数据缓冲区（需提前分配足够内存）
 * @param  len: 接收数据长度（最大支持uint16_t范围）
 * @retval uint8_t: 0=成功；非0=失败（错误码对应具体步骤）
 */
uint8_t I2C_Master_ReceiveData(uint8_t regAddr, uint8_t *pData, uint16_t len);

/**
 * @brief  I2C通信测试函数（示例调用，可根据需求修改）
 * @param  无
 * @retval 无
 */
void I2C_Test(void);

// -------------------------- 错误码定义（可选，便于调试）--------------------------
typedef enum
{
    I2C_OK              = 0,    // 通信成功
    I2C_ERR_BUSY        = 1,    // 总线忙超时
    I2C_ERR_START       = 2,    // 发送START信号失败
    I2C_ERR_ADDR_ACK    = 3,    // 从机地址无应答
    I2C_ERR_REG_SEND    = 4,    // 寄存器地址发送失败
    I2C_ERR_DATA_SEND   = 5,    // 数据发送失败
    I2C_ERR_DATA_RECV   = 6     // 数据接收失败
} I2C_ErrorTypeDef;

#endif // __I2C_COMMUNICATION_H

