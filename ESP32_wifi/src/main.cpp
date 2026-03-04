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

// ─── Debug counters ───
static volatile uint32_t dbg_dapTcpRead   = 0;   // DAP commands read from TCP
static volatile uint32_t dbg_dapUartTx     = 0;   // Bridge frames sent to UART
static volatile uint32_t dbg_dapUartRx     = 0;   // DAP responses received from UART
static volatile uint32_t dbg_dapTcpSend    = 0;   // DAP responses sent to TCP
static volatile uint32_t dbg_dapTimeout    = 0;   // DAP response timeouts
static volatile uint32_t dbg_uartBytesRx   = 0;   // Total UART bytes received
static volatile uint32_t dbg_uartFramesRx  = 0;   // Total UART frames parsed
static uint8_t dbg_lastDapCmd[8] = {0};           // First 8 bytes of last DAP command
static uint16_t dbg_lastDapCmdLen = 0;
static uint8_t dbg_lastBridgeTx[16] = {0};       // First 16 bytes of last bridge frame TX
static uint16_t dbg_lastBridgeTxLen = 0;

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
        case 0xF0: { // DEBUG_DIAG — return DAP debug counters + GPIO diag
            uint8_t reply[80];
            int pos = 0;
            reply[pos++] = 0xF0;  // subcmd echo
            // Copy volatile counters to local vars first
            uint32_t v;
            v = dbg_dapTcpRead;  memcpy(&reply[pos], &v, 4); pos += 4;
            v = dbg_dapUartTx;   memcpy(&reply[pos], &v, 4); pos += 4;
            v = dbg_dapUartRx;   memcpy(&reply[pos], &v, 4); pos += 4;
            v = dbg_dapTcpSend;  memcpy(&reply[pos], &v, 4); pos += 4;
            v = dbg_dapTimeout;  memcpy(&reply[pos], &v, 4); pos += 4;
            v = dbg_uartBytesRx; memcpy(&reply[pos], &v, 4); pos += 4;
            v = dbg_uartFramesRx;memcpy(&reply[pos], &v, 4); pos += 4;
            // 2 bytes: lastDapCmdLen
            uint16_t v16 = dbg_lastDapCmdLen;
            memcpy(&reply[pos], &v16, 2); pos += 2;
            // 8 bytes: lastDapCmd
            memcpy(&reply[pos], dbg_lastDapCmd, 8); pos += 8;
            // 2 bytes: lastBridgeTxLen
            v16 = dbg_lastBridgeTxLen;
            memcpy(&reply[pos], &v16, 2); pos += 2;
            // 16 bytes: lastBridgeTx
            memcpy(&reply[pos], dbg_lastBridgeTx, 16); pos += 16;

            // GPIO state diagnostics — read raw pin level via input register
            // On ESP32, GPIO input register reflects actual pin level even in
            // peripheral (UART) mode. Safe to read without disrupting UART.
            {
                uint32_t gpio_in = REG_READ(GPIO_IN_REG);
                reply[pos++] = (gpio_in >> 1) & 1;  // GPIO1 (TX) actual level
                reply[pos++] = (gpio_in >> 3) & 1;  // GPIO3 (RX) actual level
            }
            // Serial.available() counter
            v = (uint32_t)Serial.available();
            memcpy(&reply[pos], &v, 4); pos += 4;
            // UART baud rate verification
            v = (uint32_t)Serial.baudRate();
            memcpy(&reply[pos], &v, 4); pos += 4;

            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL,
                                   reply, pos);
            tcpServer.write(txBuf, txLen);
            break;
        }
        case 0xF4: { // GPIO3 PIN LEVEL TEST — stop UART, read pin, restart
            // Temporarily release UART0 to read GPIO3 as plain digital input.
            // This is the only reliable way since IO_MUX bypasses GPIO_IN_REG.
            Serial.end();
            delay(5);  // let UART hardware fully release

            pinMode(3, INPUT);
            delay(2);

            // Read GPIO3 multiple times to get stable reading
            uint8_t readings[10];
            for (int i = 0; i < 10; i++) {
                readings[i] = digitalRead(3);
                delayMicroseconds(100);
            }

            // Also read GPIO1 (TX) for reference
            // Don't change pinMode of GPIO1 - it's our debug output
            uint8_t gpio1_level = digitalRead(1);

            // Restart UART
            Serial.setRxBufferSize(UART_RX_BUF_SIZE);
            Serial.begin(UART_BAUDRATE);
            delay(5);

            // Build reply: [0xF4][gpio1][10 x gpio3_readings]
            uint8_t reply[12];
            reply[0] = 0xF4;
            reply[1] = gpio1_level;
            memcpy(&reply[2], readings, 10);

            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL,
                                   reply, 12);
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

// Track whether a DAP session is active to reduce non-essential processing
static bool dapSessionActive = false;

void loop() {
    // ── WiFi 管理（自动重连）──
    wifiMgr.loop();

    // ── DAP TCP 处理 (最高优先级) ──
    dapServer.loop();
    bool dapConnected = dapServer.hasClient();

    // Track DAP session state changes
    if (dapConnected && !dapSessionActive) {
        dapSessionActive = true;
        // Set UART timeout to minimum for fast DAP response reads
        Serial.setTimeout(10);
    } else if (!dapConnected && dapSessionActive) {
        dapSessionActive = false;
        Serial.setTimeout(1000);
    }

    if (dapConnected) {
        uint8_t dapCmd[DAP_TCP_MAX_PACKET];
        uint16_t dapLen;
        while (dapServer.readCommand(dapCmd, &dapLen)) {
            dbg_dapTcpRead++;
            // Save debug info
            dbg_lastDapCmdLen = dapLen;
            memcpy(dbg_lastDapCmd, dapCmd, (dapLen < 8) ? dapLen : 8);

            // Wrap DAP command in Bridge frame (CH=0xD0) and send to MCU
            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_CMD, BRIDGE_CH_DAP,
                                   dapCmd, dapLen);
            
            // Save bridge TX debug info
            dbg_lastBridgeTxLen = txLen;
            memcpy(dbg_lastBridgeTx, txBuf, (txLen < 16) ? txLen : 16);
            
            // 单次发送 + 等待响应（不重发）
            // DAP 命令在目标侧是有状态的，重发可能打乱 Flash 算法流程。
            uart.write(txBuf, txLen);
            dbg_dapUartTx++;

            bool gotResponse = false;
            unsigned long t0 = millis();
            while (!gotResponse && (millis() - t0 < 2500)) {
                uint8_t uBuf[1024];
                int n = uart.read(uBuf, sizeof(uBuf));
                dbg_uartBytesRx += n;
                for (int i = 0; i < n; i++) {
                    BridgeFrame frame;
                    if (uartParser.feed(uBuf[i], frame)) {
                        dbg_uartFramesRx++;
                        if (!frame.valid) continue;
                        if (frame.ch == BRIDGE_CH_DAP) {
                            dbg_dapUartRx++;
                            dapServer.sendResponse(frame.data, frame.len);
                            dbg_dapTcpSend++;
                            gotResponse = true;
                            break;
                        } else if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                            handleWifiCtrlFromMCU(frame);
                        } else {
                            uint8_t fwdBuf[BRIDGE_MAX_DATA + 6];
                            int fwdLen = buildFrame(fwdBuf, frame.sof0, frame.ch,
                                                    frame.data, frame.len);
                            tcpServer.write(fwdBuf, fwdLen);
                        }
                    }
                }
                if (!gotResponse) delayMicroseconds(100);
            }
            if (!gotResponse) {
                dbg_dapTimeout++;
                // Send error response to keep TCP stream aligned
                uint8_t errResp[4];
                uint16_t errLen;
                if (dapCmd[0] == 0x06) {
                    errResp[0] = 0x06; errResp[1] = 0; errResp[2] = 0; errResp[3] = 0x07;
                    errLen = 4;
                } else if (dapCmd[0] == 0x05) {
                    errResp[0] = 0x05; errResp[1] = 0; errResp[2] = 0x00;
                    errLen = 3;
                } else {
                    errResp[0] = dapCmd[0]; errResp[1] = 0xFF;
                    errLen = 2;
                }
                dapServer.sendResponse(errResp, errLen);
                dbg_dapTcpSend++;
            }
        }
    }

    // ── TCP → UART (PC 命令发往 MCU) ──
    tcpServer.loop();
    if (tcpServer.hasClient()) {
        uint8_t buf[1024];
        int n = tcpServer.read(buf, sizeof(buf));
        for (int i = 0; i < n; i++) {
            BridgeFrame frame;
            if (tcpParser.feed(buf[i], frame)) {
                if (!frame.valid) {
                    continue;
                }
                if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                    handleWifiCtrl(frame);
                } else {
#if DAP_EXCLUSIVE_MODE
                    if (dapSessionActive) {
                        /* DAP 会话独占期间，丢弃非 WIFI_CTRL 通道命令 */
                        continue;
                    }
#endif
                    uint8_t txBuf[BRIDGE_MAX_DATA + 6];
                    int txLen = buildFrame(txBuf, frame.sof0, frame.ch,
                                           frame.data, frame.len);
                    uart.write(txBuf, txLen);
                }
            }
        }
    }

    // ── UART → TCP / DAP TCP (MCU 回复 — 非 DAP 活跃时处理) ──
    {
        uint8_t buf[1024];
        int n = uart.read(buf, sizeof(buf));
        for (int i = 0; i < n; i++) {
            BridgeFrame frame;
            if (uartParser.feed(buf[i], frame)) {
                if (!frame.valid) continue;
                if (frame.ch == BRIDGE_CH_DAP) {
                    // Stale DAP response — discard silently to avoid corrupting TCP stream
                    // (can happen after retry sends duplicate command to MCU)
                } else if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                    handleWifiCtrlFromMCU(frame);
                } else {
#if DAP_EXCLUSIVE_MODE
                    if (dapSessionActive) {
                        /* DAP 会话独占期间，不转发非 WIFI_CTRL 返回到扩展坞 TCP */
                        continue;
                    }
#endif
                    uint8_t txBuf[BRIDGE_MAX_DATA + 6];
                    int txLen = buildFrame(txBuf, frame.sof0, frame.ch,
                                           frame.data, frame.len);
                    tcpServer.write(txBuf, txLen);
                }
            }
        }
    }

    // ── 低优先级服务 (DAP 活跃时减少处理频率) ──
    static unsigned long lastSlowService = 0;
    unsigned long now = millis();
    if (!dapSessionActive || (now - lastSlowService >= 100)) {
        lastSlowService = now;
        webCfg.loop();
        updateLED();
    }

    // ── 心跳 (DAP 活跃时暂停，避免 UART 干扰) ──
    if (!dapSessionActive) {
        handleHeartbeat();
    }

    yield(); // Ensure WiFi stack gets CPU time
}
