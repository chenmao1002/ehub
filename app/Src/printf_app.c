#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "printf_app.h"


// 使用USART1作为通信接口
extern UART_HandleTypeDef huart1;
/**
 * @brief  自定义打印函数
 * @param  format: 格式化字符串
 * @param  ...: 可变参数
 * @retval 打印的字符数
 */
int printf_u1(const char *format, ...)
{
  /* 使用 static 缓冲区：DMA 传输期间源地址必须有效，
     局部栈变量在函数返回后即被释放，导致 DMA 读取已回收内存 */
  static uint8_t buffer[512];
  va_list args;
  int len;

  va_start(args, format);
  len = vsnprintf((char *)buffer, sizeof(buffer), format, args);
  va_end(args);

  if (len <= 0) { return len; }
  if (len > (int)(sizeof(buffer) - 1)) { len = (int)(sizeof(buffer) - 1); }

  /* 等待上一次 DMA 或 IT 传输完成，再发起新传输 */
  uint32_t t = HAL_GetTick();
  while (HAL_UART_GetState(&huart1) & HAL_UART_STATE_BUSY_TX) {
    if ((HAL_GetTick() - t) > 50U) { return -1; } /* 超时放弃 */
  }

  HAL_UART_Transmit_DMA(&huart1, buffer, (uint16_t)len);
  return len;
}
