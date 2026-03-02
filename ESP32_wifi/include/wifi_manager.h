#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include "config.h"

class WiFiManager {
public:
    WiFiManager();

    void begin();                    // 初始化，读取配置并开始连接
    void loop();                     // 主循环调用，处理自动重连

    bool isConnected();              // STA 是否已连接
    bool isAPMode();                 // 是否运行在 AP 模式
    IPAddress getIP();               // 获取当前 IP（STA 或 AP）
    int8_t getRSSI();                // 获取 WiFi 信号强度
    uint8_t getStatus();             // 0=断开, 1=STA已连, 2=AP模式

    bool configure(const char* ssid, const char* pass);  // 设置 STA 参数
    void saveConfig();               // 保存到 NVS
    void resetConfig();              // 恢复出厂配置并重启
    void reconnect();                // 手动触发重连

    String getSSID();                // 当前 STA SSID
    String getAPSSID();              // 当前 AP SSID

private:
    void loadConfig();               // 从 NVS 读取配置
    void startSTA();                 // 启动 STA 模式
    void startAP();                  // 启动 AP 模式
    void startAPSTA();               // 启动 AP+STA 模式

    Preferences _prefs;
    String _staSSID;
    String _staPass;
    String _apSSID;
    String _apPass;

    bool   _apActive;               // AP 是否已启动
    bool   _staConnected;           // STA 是否已连接
    unsigned long _lastReconnectAttempt;  // 上次重连时间
};

#endif // WIFI_MANAGER_H
