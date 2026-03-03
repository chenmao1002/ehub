#ifndef TCP_SERVER_H
#define TCP_SERVER_H

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"

class TCPBridgeServer {
public:
    TCPBridgeServer();

    void begin(uint16_t port = TCP_PORT);
    void loop();                     // 在主循环中调用，处理新连接和数据

    bool hasClient();                // 是否有客户端连接
    int available();                 // TCP 接收缓冲区中可读字节数
    int read(uint8_t* buf, int maxLen);  // 读取 TCP 数据
    void write(const uint8_t* buf, int len);  // 发送数据到客户端
    void disconnect();               // 断开当前客户端

    IPAddress clientIP();            // 当前客户端 IP

private:
    WiFiServer* _server;
    WiFiClient  _client;
    bool        _clientConnected;
};

#endif // TCP_SERVER_H
