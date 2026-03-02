#ifndef UART_BRIDGE_H
#define UART_BRIDGE_H

#include <Arduino.h>
#include "config.h"

class UARTBridge {
public:
    UARTBridge();

    void begin(unsigned long baud = UART_BAUDRATE);

    int available();                 // UART 接收缓冲区可读字节数
    int read(uint8_t* buf, int maxLen);  // 读取 UART 数据
    void write(const uint8_t* buf, int len);  // 发送到 UART/MCU
};

#endif // UART_BRIDGE_H
