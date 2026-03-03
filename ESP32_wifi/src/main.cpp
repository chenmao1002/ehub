#include <Arduino.h>
#include <ESPmDNS.h>
#include "config.h"
#include "wifi_manager.h"
#include "tcp_server.h"
#include "dap_tcp_server.h"
#include "uart_bridge.h"
#include "protocol.h"
#include "web_config.h"

// ═══════════════════════════════════════════════════════════════
// 全局对象
// ═══════════════════════════════════════════════════════════════
WiFiManager     wifiMgr;
TCPBridgeServer tcpServer;
DAPTCPServer    dapServer;         // CMSIS-DAP over TCP (port 6000)
UARTBridge      uart;
WebConfig       webCfg;
FrameParser     tcpParser;      // 解析 TCP 来的帧
FrameParser     uartParser;     // 解析 UART 来的帧

// ─── LED 状态 ───
static unsigned long lastLedToggle = 0;
static bool          ledState      = false;

// ─── 心跳 ───
static unsigned long lastHeartbeatSend = 0;
static unsigned long lastHeartbeatRecv = 0;

// ═══════════════════════════════════════════════════════════════
// WiFi 控制帧处理（来自 TCP/PC）
// ═══════════════════════════════════════════════════════════════
void handleWifiCtrl(const BridgeFrame& frame) {
    if (frame.len < 1) return;
    uint8_t subcmd = frame.data[0];

    switch (subcmd) {
        case 0x01: { // WIFI_STATUS
            uint8_t reply[7];
            reply[0] = 0x01;
            reply[1] = wifiMgr.getStatus();
            reply[2] = (uint8_t)wifiMgr.getRSSI();  // signed → unsigned cast
            IPAddress ip = wifiMgr.getIP();
            reply[3] = ip[0]; reply[4] = ip[1];
            reply[5] = ip[2]; reply[6] = ip[3];

            uint8_t txBuf[13];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, 7);
            tcpServer.write(txBuf, txLen);
            break;
        }
        case 0x02: { // WIFI_CONFIG
            if (frame.len < 3) break;
            uint8_t ssidLen = frame.data[1];
            if (frame.len < (uint16_t)(2 + ssidLen + 1)) break;
            char ssid[33] = {0};
            memcpy(ssid, &frame.data[2], min((int)ssidLen, 32));

            uint8_t passLen = frame.data[2 + ssidLen];
            char pass[65] = {0};
            if (passLen > 0 && frame.len >= (uint16_t)(3 + ssidLen + passLen)) {
                memcpy(pass, &frame.data[3 + ssidLen], min((int)passLen, 64));
            }

            bool ok = wifiMgr.configure(ssid, pass);
            wifiMgr.saveConfig();

            uint8_t reply[2] = { 0x02, ok ? (uint8_t)0x00 : (uint8_t)0xFF };
            uint8_t txBuf[8];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, 2);
            tcpServer.write(txBuf, txLen);

            // 延迟后重连
            delay(500);
            wifiMgr.reconnect();
            break;
        }
        case 0x05: { // WIFI_SCAN
            int n = WiFi.scanNetworks();
            uint8_t reply[BRIDGE_MAX_DATA];
            int pos = 0;
            reply[pos++] = 0x05;
            reply[pos++] = (uint8_t)min(n, 10);  // 最多10个结果
            for (int i = 0; i < min(n, 10) && pos < BRIDGE_MAX_DATA - 34; i++) {
                String ssid = WiFi.SSID(i);
                uint8_t sl = min((int)ssid.length(), 32);
                reply[pos++] = sl;
                memcpy(&reply[pos], ssid.c_str(), sl);
                pos += sl;
                reply[pos++] = (uint8_t)WiFi.RSSI(i);  // signed
            }

            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, pos);
            tcpServer.write(txBuf, txLen);
            WiFi.scanDelete();
            break;
        }
        case 0x10: { // HEARTBEAT — 原样回传
            lastHeartbeatRecv = millis();
            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL,
                                   frame.data, frame.len);
            tcpServer.write(txBuf, txLen);
            break;
        }
        // 0x03 ESP_RESET 和 0x04 ESP_BOOTLOADER 由 MCU 硬件控制
        // PC 发到 MCU，MCU 操作 EN/BOOT 引脚，这里不需要处理
    }
}

// ═══════════════════════════════════════════════════════════════
// WiFi 控制帧处理（来自 UART/MCU）
// ═══════════════════════════════════════════════════════════════
void handleWifiCtrlFromMCU(const BridgeFrame& frame) {
    if (frame.len < 1) return;
    uint8_t subcmd = frame.data[0];

    switch (subcmd) {
        case 0x02: { // WIFI_CONFIG — MCU 转发的配置命令
            if (frame.len < 3) break;
            uint8_t ssidLen = frame.data[1];
            if (frame.len < (uint16_t)(2 + ssidLen + 1)) break;
            char ssid[33] = {0};
            memcpy(ssid, &frame.data[2], min((int)ssidLen, 32));

            uint8_t passLen = frame.data[2 + ssidLen];
            char pass[65] = {0};
            if (passLen > 0 && frame.len >= (uint16_t)(3 + ssidLen + passLen)) {
                memcpy(pass, &frame.data[3 + ssidLen], min((int)passLen, 64));
            }

            bool ok = wifiMgr.configure(ssid, pass);
            wifiMgr.saveConfig();

            // 回复给 MCU
            uint8_t reply[2] = { 0x02, ok ? (uint8_t)0x00 : (uint8_t)0xFF };
            uint8_t txBuf[8];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, 2);
            uart.write(txBuf, txLen);

            delay(500);
            wifiMgr.reconnect();
            break;
        }
        case 0x05: { // WIFI_SCAN — MCU 请求扫描
            int n = WiFi.scanNetworks();
            uint8_t reply[BRIDGE_MAX_DATA];
            int pos = 0;
            reply[pos++] = 0x05;
            reply[pos++] = (uint8_t)min(n, 10);
            for (int i = 0; i < min(n, 10) && pos < BRIDGE_MAX_DATA - 34; i++) {
                String ssid = WiFi.SSID(i);
                uint8_t sl = min((int)ssid.length(), 32);
                reply[pos++] = sl;
                memcpy(&reply[pos], ssid.c_str(), sl);
                pos += sl;
                reply[pos++] = (uint8_t)WiFi.RSSI(i);
            }

            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, pos);
            uart.write(txBuf, txLen);
            WiFi.scanDelete();
            break;
        }
        case 0x01: { // WIFI_STATUS — MCU 查询状态
            uint8_t reply[7];
            reply[0] = 0x01;
            reply[1] = wifiMgr.getStatus();
            reply[2] = (uint8_t)wifiMgr.getRSSI();
            IPAddress ip = wifiMgr.getIP();
            reply[3] = ip[0]; reply[4] = ip[1];
            reply[5] = ip[2]; reply[6] = ip[3];

            uint8_t txBuf[13];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, 7);
            uart.write(txBuf, txLen);
            break;
        }
        case 0x10: { // HEARTBEAT 从 MCU
            lastHeartbeatRecv = millis();
            // 回传心跳
            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL,
                                   frame.data, frame.len);
            uart.write(txBuf, txLen);
            break;
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// LED 状态指示
// ═══════════════════════════════════════════════════════════════
void updateLED() {
    unsigned long now = millis();
    uint8_t wifiStatus = wifiMgr.getStatus();
    bool hasTcp = tcpServer.hasClient();

    if (wifiStatus == 0x01 && hasTcp) {
        // WiFi 已连接 + TCP 已连接：双闪
        if (now - lastLedToggle >= 125) {
            static uint8_t blinkPhase = 0;
            blinkPhase++;
            // 双闪模式: ON-OFF-ON-OFF----
            if (blinkPhase <= 2) {
                ledState = (blinkPhase % 2 == 1);
            } else if (blinkPhase <= 6) {
                ledState = false;
            } else {
                blinkPhase = 0;
            }
            lastLedToggle = now;
            digitalWrite(LED_PIN, ledState ? HIGH : LOW);
        }
    } else if (wifiStatus == 0x01) {
        // WiFi 已连接，无 TCP：常亮
        digitalWrite(LED_PIN, HIGH);
    } else if (wifiStatus == 0x00) {
        // WiFi 正在连接：快闪 (4Hz, 125ms)
        if (now - lastLedToggle >= 125) {
            ledState = !ledState;
            lastLedToggle = now;
            digitalWrite(LED_PIN, ledState ? HIGH : LOW);
        }
    } else {
        // AP 模式 / 其他：慢闪 (1Hz, 500ms)
        if (now - lastLedToggle >= 500) {
            ledState = !ledState;
            lastLedToggle = now;
            digitalWrite(LED_PIN, ledState ? HIGH : LOW);
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// 心跳
// ═══════════════════════════════════════════════════════════════
void handleHeartbeat() {
    unsigned long now = millis();

    // 定期向 MCU 发送心跳
    if (now - lastHeartbeatSend >= HEARTBEAT_INTERVAL_MS) {
        lastHeartbeatSend = now;

        uint8_t data[5];
        data[0] = 0x10;  // HEARTBEAT subcmd
        // 4 字节大端时间戳 (毫秒低 32 位)
        uint32_t tick = (uint32_t)now;
        data[1] = (uint8_t)(tick >> 24);
        data[2] = (uint8_t)(tick >> 16);
        data[3] = (uint8_t)(tick >> 8);
        data[4] = (uint8_t)(tick);

        uint8_t txBuf[11];
        int txLen = buildFrame(txBuf, BRIDGE_SOF0_CMD, BRIDGE_CH_WIFI_CTRL, data, 5);
        uart.write(txBuf, txLen);
    }
}

// ═══════════════════════════════════════════════════════════════
// Arduino setup()
// ═══════════════════════════════════════════════════════════════
void setup() {
    // 1. LED 初始化
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    // 2. UART (与 MCU 通信)
    uart.begin(UART_BAUDRATE);   // 921600

    // 3. WiFi
    wifiMgr.begin();

    // 4. mDNS
    if (MDNS.begin(MDNS_HOSTNAME)) {   // ehub.local
        MDNS.addService(MDNS_SERVICE, MDNS_PROTOCOL, TCP_PORT);
        MDNS.addServiceTxt(MDNS_SERVICE, MDNS_PROTOCOL, "version", FW_VERSION);
        MDNS.addServiceTxt(MDNS_SERVICE, MDNS_PROTOCOL, "device", "EHUB");
        // Advertise DAP TCP service for cmsis-dap discovery (OpenOCD)
        MDNS.addService("_dap", "_tcp", DAP_TCP_PORT);
        MDNS.addServiceTxt("_dap", "_tcp", "version", FW_VERSION);
        // Advertise elaphureLink service
        MDNS.addService("_elaphurelink", "_tcp", ELAPHURELINK_PORT);
    }

    // 5. TCP 服务器
    tcpServer.begin(TCP_PORT);   // 5000

    // 6. DAP TCP 服务器 (CMSIS-DAP over TCP + elaphureLink)
    dapServer.begin();  // port 6000 (OpenOCD) + port 3240 (elaphureLink)

    // 7. Web 配置
    webCfg.begin(wifiMgr, tcpServer);

    // 8. 初始化心跳时间
    lastHeartbeatSend = millis();
    lastHeartbeatRecv = millis();

    // 9. LED 指示就绪
    digitalWrite(LED_PIN, HIGH);
}

// ═══════════════════════════════════════════════════════════════
// Arduino loop()
// ═══════════════════════════════════════════════════════════════
void loop() {
    // ── WiFi 管理（自动重连）──
    wifiMgr.loop();

    // ── TCP → UART (PC 命令发往 MCU) ──
    tcpServer.loop();
    if (tcpServer.hasClient()) {
        uint8_t buf[256];
        int n = tcpServer.read(buf, sizeof(buf));
        for (int i = 0; i < n; i++) {
            BridgeFrame frame;
            if (tcpParser.feed(buf[i], frame)) {
                if (!frame.valid) {
                    // CRC 校验失败，丢弃
                    continue;
                }
                if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                    // ESP32 本地处理 WiFi 控制命令
                    handleWifiCtrl(frame);
                } else {
                    // 透传到 MCU: 重建完整帧发送到 UART
                    uint8_t txBuf[BRIDGE_MAX_DATA + 6];
                    int txLen = buildFrame(txBuf, frame.sof0, frame.ch,
                                           frame.data, frame.len);
                    uart.write(txBuf, txLen);
                }
            }
        }
    }

    // ── DAP TCP → UART (OpenOCD/elaphureLink DAP 命令发往 MCU) ──
    dapServer.loop();
    if (dapServer.hasClient()) {
        uint8_t dapCmd[DAP_TCP_MAX_PACKET];
        uint16_t dapLen;
        while (dapServer.readCommand(dapCmd, &dapLen)) {
            // Wrap DAP command in Bridge frame (CH=0xD0) and send to MCU
            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_CMD, BRIDGE_CH_DAP,
                                   dapCmd, dapLen);
            uart.write(txBuf, txLen);
        }
    }

    // ── UART → TCP / DAP TCP (MCU 回复) ──
    {
        uint8_t buf[256];
        int n = uart.read(buf, sizeof(buf));
        for (int i = 0; i < n; i++) {
            BridgeFrame frame;
            if (uartParser.feed(buf[i], frame)) {
                if (!frame.valid) {
                    // CRC 错误，丢弃该帧
                    continue;
                }
                if (frame.ch == BRIDGE_CH_DAP) {
                    // DAP 响应 → 发送到 DAP TCP 客户端 (带 4 字节长度头)
                    dapServer.sendResponse(frame.data, frame.len);
                } else if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                    // MCU 发来的 WiFi 控制帧，ESP32 处理
                    handleWifiCtrlFromMCU(frame);
                } else {
                    // 透传到 PC: 重建帧发送到 TCP
                    uint8_t txBuf[BRIDGE_MAX_DATA + 6];
                    int txLen = buildFrame(txBuf, frame.sof0, frame.ch,
                                           frame.data, frame.len);
                    tcpServer.write(txBuf, txLen);
                }
            }
        }
    }

    // ── Web 配置服务 ──
    webCfg.loop();

    // ── LED 状态指示 ──
    updateLED();

    // ── 心跳 ──
    handleHeartbeat();
}
