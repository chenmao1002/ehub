#ifndef WEB_CONFIG_H
#define WEB_CONFIG_H

#include <Arduino.h>
#include <WebServer.h>
#include "wifi_manager.h"
#include "tcp_server.h"
#include "config.h"

class WebConfig {
public:
    WebConfig();

    void begin(WiFiManager& wifiMgr, TCPBridgeServer& tcpSrv);  // 启动 HTTP 服务器
    void loop();                        // 处理 HTTP 请求

private:
    void handleRoot();
    void handleApiStatus();
    void handleApiWifi();
    void handleApiScan();
    void handleApiReset();
    void handleApiReboot();
    void handleNotFound();

    WebServer*       _server;
    WiFiManager*     _wifiMgr;
    TCPBridgeServer* _tcpSrv;
    unsigned long    _startTime;
};

#endif // WEB_CONFIG_H
