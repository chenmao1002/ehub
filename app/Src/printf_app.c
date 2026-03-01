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
  va_list args;
  char buffer[512];  // 定义缓冲区
  int len;
  
  // 解析可变参数
  va_start(args, format);
  len = vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);

  // 确保不超过缓冲区大小
  if (len > sizeof(buffer) - 1) {
    len = sizeof(buffer) - 1;
  }
  // 发送数据
  HAL_UART_Transmit_DMA(&huart1, (uint8_t *)buffer, len);

  // 延时确保数据发送完成
//  HAL_Delay((len/10)+1);
  return len;
}
