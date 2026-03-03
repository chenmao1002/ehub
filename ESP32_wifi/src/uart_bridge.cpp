#include "uart_bridge.h"

UARTBridge::UARTBridge() {
}

void UARTBridge::begin(unsigned long baud) {
    // 设置更大的 RX 缓冲区（默认 256 字节不够用）
    Serial.setRxBufferSize(UART_RX_BUF_SIZE);  // 4096
    // 使用默认 UART0 引脚 (GPIO1=TX, GPIO3=RX)，通过 IO_MUX 路由
    Serial.begin(baud);
}

int UARTBridge::available() {
    return Serial.available();
}

int UARTBridge::read(uint8_t* buf, int maxLen) {
    int avail = Serial.available();
    if (avail <= 0) return 0;
    int toRead = (avail < maxLen) ? avail : maxLen;
    return Serial.readBytes(buf, toRead);
}

void UARTBridge::write(const uint8_t* buf, int len) {
    Serial.write(buf, len);
}
