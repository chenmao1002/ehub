#include "wifi_manager.h"
#include <esp_wifi.h>

WiFiManager::WiFiManager()
    : _apActive(false)
    , _staConnected(false)
    , _lastReconnectAttempt(0)
{
}

// ─── 从 NVS 读取配置 ───
void WiFiManager::loadConfig() {
    _prefs.begin("wifi", true);  // 只读
    _staSSID = _prefs.getString("sta_ssid", DEFAULT_STA_SSID);
    _staPass = _prefs.getString("sta_pass", DEFAULT_STA_PASS);
    _apSSID  = _prefs.getString("ap_ssid", DEFAULT_AP_SSID);
    _apPass  = _prefs.getString("ap_pass", DEFAULT_AP_PASS);
    _prefs.end();
}

// ─── 保存配置到 NVS ───
void WiFiManager::saveConfig() {
    _prefs.begin("wifi", false);  // 读写
    _prefs.putString("sta_ssid", _staSSID);
    _prefs.putString("sta_pass", _staPass);
    _prefs.putString("ap_ssid", _apSSID);
    _prefs.putString("ap_pass", _apPass);
    _prefs.end();
}

// ─── 启动 STA 模式 ───
void WiFiManager::startSTA() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(_staSSID.c_str(), _staPass.c_str());

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED &&
           (millis() - start) < WIFI_CONNECT_TIMEOUT_MS) {
        delay(100);
    }

    if (WiFi.status() == WL_CONNECTED) {
        _staConnected = true;
        _apActive = false;
    } else {
        // STA 连接失败，切换到 AP+STA 模式
        _staConnected = false;
        startAPSTA();
    }
}

// ─── 启动 AP 模式 ───
void WiFiManager::startAP() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(_apSSID.c_str(), _apPass.c_str(), 1);  // 信道 1
    _apActive = true;
    _staConnected = false;
}

// ─── 启动 AP+STA 模式 ───
void WiFiManager::startAPSTA() {
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP(_apSSID.c_str(), _apPass.c_str(), 1);
    WiFi.begin(_staSSID.c_str(), _staPass.c_str());
    _apActive = true;
}

// ─── 初始化 ───
void WiFiManager::begin() {
    loadConfig();

    WiFi.setAutoReconnect(false);  // 我们自己管理重连

    if (_staSSID.length() > 0) {
        // 有 STA 配置，尝试连接
        startSTA();
    } else {
        // 没有 STA 配置，直接 AP 模式
        startAP();
    }

    // ─── 最大性能模式 ───
    // 禁用 WiFi modem sleep，保持射频始终开启，最小化接收延迟
    esp_wifi_set_ps(WIFI_PS_NONE);
    // 设置最大发射功率 (19.5 dBm)
    WiFi.setTxPower(WIFI_POWER_19_5dBm);
}

// ─── 主循环（自动重连）───
void WiFiManager::loop() {
    // 仅在有 STA 配置且当前未连接时尝试重连
    if (_staSSID.length() > 0 && WiFi.status() != WL_CONNECTED) {
        _staConnected = false;
        unsigned long now = millis();
        if (now - _lastReconnectAttempt >= WIFI_RECONNECT_INTERVAL) {
            _lastReconnectAttempt = now;
            WiFi.begin(_staSSID.c_str(), _staPass.c_str());
        }
    } else if (WiFi.status() == WL_CONNECTED) {
        if (!_staConnected) {
            _staConnected = true;
            // 如果 AP+STA 模式且 STA 已连接，可保持 AP 继续运行
            // 也可以选择关闭 AP，这里保持 AP 供后续配置使用
        }
    }
}

// ─── 状态查询 ───
bool WiFiManager::isConnected() {
    return WiFi.status() == WL_CONNECTED;
}

bool WiFiManager::isAPMode() {
    return _apActive;
}

IPAddress WiFiManager::getIP() {
    if (WiFi.status() == WL_CONNECTED) {
        return WiFi.localIP();
    }
    if (_apActive) {
        return WiFi.softAPIP();
    }
    return IPAddress(0, 0, 0, 0);
}

int8_t WiFiManager::getRSSI() {
    if (WiFi.status() == WL_CONNECTED) {
        return (int8_t)WiFi.RSSI();
    }
    return 0;
}

uint8_t WiFiManager::getStatus() {
    if (WiFi.status() == WL_CONNECTED) {
        return 0x01;  // STA 已连接
    }
    if (_apActive) {
        return 0x02;  // AP 模式
    }
    return 0x00;  // 未连接
}

// ─── 配置 ───
bool WiFiManager::configure(const char* ssid, const char* pass) {
    if (!ssid || strlen(ssid) == 0) {
        return false;
    }
    _staSSID = String(ssid);
    _staPass = String(pass ? pass : "");
    return true;
}

void WiFiManager::resetConfig() {
    _prefs.begin("wifi", false);
    _prefs.clear();
    _prefs.end();
    ESP.restart();
}

void WiFiManager::reconnect() {
    if (_staSSID.length() > 0) {
        WiFi.disconnect();
        delay(100);
        WiFi.begin(_staSSID.c_str(), _staPass.c_str());

        unsigned long start = millis();
        while (WiFi.status() != WL_CONNECTED &&
               (millis() - start) < WIFI_CONNECT_TIMEOUT_MS) {
            delay(100);
        }
        _staConnected = (WiFi.status() == WL_CONNECTED);
    }
}

String WiFiManager::getSSID() {
    return _staSSID;
}

String WiFiManager::getAPSSID() {
    return _apSSID;
}
