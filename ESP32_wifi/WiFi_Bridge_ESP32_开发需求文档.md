# EHUB WiFi↔Bus Bridge — ESP32 固件开发需求文档

> **版本**: 1.0  
> **日期**: 2026-03-02  
> **范围**: ESP32-N8 模块固件 — WiFi ↔ UART 透明桥接  
> **开发环境**: PlatformIO IDE (VS Code) + Arduino 框架  
> **关联文档**: `WiFi_Bridge_MCU_开发需求文档.md` (项目根目录), `tools/WiFi_Bridge_上位机_开发需求文档.md`  
> **完成后**: 在本目录创建 `WiFi_Bridge_ESP32_开发汇总.md`

---

## 1. 项目背景

EHUB 是一个多总线调试器，当前通过 USB CDC 与 PC 上位机通信。本 ESP32 模块作为 **WiFi ↔ UART 透明桥接器**，实现以下功能：

1. 通过 WiFi 局域网接收 PC 上位机的 TCP 连接
2. 将 TCP 数据透传到 UART 发送给 MCU (STM32F407)
3. 将 MCU 通过 UART 返回的数据透传到 TCP 发送给 PC
4. 处理 WiFi 管理相关的控制命令（状态查询、WiFi 配置等）
5. 提供简易 Web 配置页面用于 WiFi 参数设置

**数据流**:
```
PC 上位机  ←── TCP:5000 / WiFi ──→  ESP32  ←── UART (921600) ──→  STM32 MCU  ←──→  总线设备
```

---

## 2. 硬件连接

| ESP32 引脚 | 连接目标 | 说明 |
|------------|---------|------|
| **GPIO1** (TXD0/UART0_TX) | MCU PA3 (USART2_RX) | ESP32 → MCU 数据 |
| **GPIO3** (RXD0/UART0_RX) | MCU PA2 (USART2_TX) | MCU → ESP32 数据 |
| **EN** | MCU PC2 (ESP_EN) | MCU 控制复位，高=运行，低脉冲=复位 |
| **GPIO0** (BOOT) | MCU PC1 (ESP_BOOT) | MCU 控制启动模式，低+复位=下载模式 |

> **注意**: UART0 是 ESP32 的默认串口，也是下载固件的串口。正常运行时用于与 MCU 通信。调试信息请勿使用 `Serial.println()`，而应通过 WiFi 或内存日志输出。

---

## 3. PlatformIO 项目配置

### 3.1 目录结构

```
ESP32_wifi/
├── platformio.ini
├── src/
│   └── main.cpp
├── include/
│   ├── config.h          // 全局配置常量
│   ├── wifi_manager.h    // WiFi 连接管理
│   ├── tcp_server.h      // TCP 服务器
│   ├── uart_bridge.h     // UART 桥接
│   ├── web_config.h      // Web 配置页面
│   └── protocol.h        // 协议定义与帧处理
├── data/                  // SPIFFS 文件（Web 页面等）
│   └── index.html
├── lib/
│   └── README
└── WiFi_Bridge_ESP32_开发汇总.md   // 开发完成后创建
```

### 3.2 platformio.ini

```ini
[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 921600
upload_speed = 921600

; 分区表 - 需要包含 SPIFFS
board_build.partitions = default.csv

; 库依赖
lib_deps =
    ; 无需额外库，使用 Arduino 内置 WiFi/WebServer/SPIFFS/mDNS

; 编译选项
build_flags =
    -DCORE_DEBUG_LEVEL=0
    -DARDUINO_USB_CDC_ON_BOOT=0
```

---

## 4. 通信协议（三端统一，必须严格遵循）

### 4.1 MCU ↔ ESP32 UART 物理层

| 参数 | 值 |
|------|----|
| **波特率** | **921600** |
| 数据位 | 8 |
| 校验 | 无 |
| 停止位 | 1 |
| 流控 | 无 |

### 4.2 ESP32 ↔ PC TCP 传输层

| 参数 | 值 |
|------|----|
| 协议 | TCP |
| 端口 | **5000** |
| 最大连接数 | **1**（仅允许一个客户端连接） |
| mDNS 服务名 | `_ehub._tcp` |
| mDNS 主机名 | `ehub` (即 `ehub.local`) |

### 4.3 帧格式

与 MCU 端完全一致，ESP32 **原样透传**大部分帧：

```
PC → 设备 (Command):  [0xAA][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]
设备 → PC (Reply):    [0xBB][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]

CRC8 = XOR(CH, LEN_H, LEN_L, DATA[0], DATA[1], ..., DATA[LEN-1])
```

### 4.4 通道 ID

| CH 值 | 类别 | ESP32 行为 |
|--------|------|-----------|
| 0x01~0x08 | 总线数据 | **透传** (TCP ↔ UART 不修改) |
| 0xF0 | 配置命令 | **透传** (TCP ↔ UART 不修改) |
| **0xE0** | **WiFi 控制** | **ESP32 拦截处理**，不转发到 MCU |

### 4.5 WiFi 控制通道详情 (CH = 0xE0)

ESP32 需要解析 TCP 收到的帧，当 CH == 0xE0 时，自行处理并回复，**不转发到 UART/MCU**。

同时，**MCU 可能通过 UART 发送 CH=0xE0 的帧给 ESP32**（MCU 侧某些 WiFi 控制命令会透传到 ESP32），ESP32 也需要能接收并处理来自 UART 侧的 0xE0 帧。

#### 4.5.1 子命令列表

| subcmd (data[0]) | 名称 | 来源 | 请求 DATA | 回复 DATA (0xBB帧) |
|-------------------|------|------|-----------|---------------------|
| 0x01 | WIFI_STATUS | TCP 来的 CMD 帧 | 无额外参数 | `[0x01][status][rssi][ip0][ip1][ip2][ip3]` |
| 0x02 | WIFI_CONFIG | TCP 或 UART 来的 CMD 帧 | `[0x02][ssid_len][ssid...][pass_len][pass...]` | `[0x02][0x00]` 成功 / `[0x02][0xFF]` 失败 |
| 0x03 | ESP_RESET | TCP 来的 CMD 帧 | 无额外参数 | 无回复 (由 MCU 执行硬件复位) |
| 0x04 | ESP_BOOTLOADER | TCP 来的 CMD 帧 | 无额外参数 | 无回复 (由 MCU 执行) |
| 0x05 | WIFI_SCAN | TCP 或 UART 来的 CMD 帧 | 无额外参数 | `[0x05][count][ssid1_len][ssid1...][rssi1_signed]...` |
| 0x10 | HEARTBEAT | 双向 | `[0x10][tick:4B BE]` | 相同格式回传 |

**status 字段**: 0x00=未连接WiFi, 0x01=WiFi已连接(STA), 0x02=AP模式运行中  
**rssi 字段**: 有符号 int8_t，WiFi 信号强度 (dBm)，未连接时为 0  
**ip 字段**: 4字节 IPv4 地址，如 192.168.1.100 → `[0xC0][0xA8][0x01][0x64]`

#### 4.5.2 WIFI_STATUS 回复示例

```
帧: BB 55 E0 00 07 01 01 D0 C0 A8 01 64 [CRC]
解析: SOF=BB55, CH=E0, LEN=7, subcmd=0x01,
      status=0x01(已连接), rssi=-48(0xD0 signed),
      ip=192.168.1.100
```

#### 4.5.3 WIFI_CONFIG 命令格式

```
请求 DATA: [0x02][ssid_len(1B)][ssid(N字节)][pass_len(1B)][pass(M字节)]
示例: 配置 SSID="MyWiFi" PASS="12345678"
DATA: 02 06 4D 79 57 69 46 69 08 31 32 33 34 35 36 37 38
```

---

## 5. 软件架构

### 5.1 模块划分

```
main.cpp
  ├── config.h ─────── 全局常量（波特率、端口号、PIN 定义等）
  ├── wifi_manager ─── WiFi STA/AP 模式管理、自动重连
  ├── tcp_server ───── TCP 服务器，接收/发送 Bridge 帧
  ├── uart_bridge ──── UART 收发，DMA/中断缓冲
  ├── protocol ─────── 帧解析/构建、CRC 计算
  └── web_config ───── HTTP 服务器，WiFi 参数配置页面
```

### 5.2 全局配置 (`config.h`)

```cpp
#ifndef CONFIG_H
#define CONFIG_H

// ─── UART 配置 ───
#define UART_BAUDRATE       921600
#define UART_RX_PIN         3       // GPIO3 = RXD0
#define UART_TX_PIN         1       // GPIO1 = TXD0
#define UART_RX_BUF_SIZE    1024    // 接收缓冲区

// ─── TCP 配置 ───
#define TCP_PORT            5000
#define TCP_MAX_CLIENTS     1       // 仅允许 1 个客户端

// ─── WiFi 默认配置 ───
#define DEFAULT_AP_SSID     "EHUB_WiFi"
#define DEFAULT_AP_PASS     "12345678"
#define DEFAULT_STA_SSID    ""      // 出厂为空，需配置
#define DEFAULT_STA_PASS    ""

// ─── Web Config ───
#define WEB_PORT            80

// ─── mDNS ───
#define MDNS_HOSTNAME       "ehub"
#define MDNS_SERVICE        "_ehub"
#define MDNS_PROTOCOL       "_tcp"

// ─── 协议常量 ───
#define BRIDGE_SOF0_CMD     0xAA
#define BRIDGE_SOF1         0x55
#define BRIDGE_SOF0_RPY     0xBB
#define BRIDGE_CH_WIFI_CTRL 0xE0
#define BRIDGE_MAX_DATA     128

// ─── 心跳 ───
#define HEARTBEAT_INTERVAL_MS  3000   // 每 3 秒发送一次心跳到 MCU
#define HEARTBEAT_TIMEOUT_MS   10000  // 超时则认为连接断开

// ─── LED 状态指示 (可选，使用板载 LED) ───
#define LED_PIN             2       // ESP32 DevKit 板载 LED

#endif
```

### 5.3 WiFi 管理模块 (`wifi_manager.h/.cpp`)

#### 功能需求：

1. **双模式运行策略**:
   - 启动时读取 SPIFFS 中保存的 STA SSID/Password
   - 如果有 STA 配置：尝试连接路由器（超时 15 秒）
     - 连接成功：纯 STA 模式运行
     - 连接失败：切换到 AP+STA 模式（AP 用于配置）
   - 如果没有 STA 配置：直接 AP 模式运行
   
2. **AP 模式参数**:
   - SSID: `EHUB_WiFi` (默认，可通过 Web 修改)
   - 密码: `12345678` (默认)
   - IP: `192.168.4.1`
   - 信道: 1
   
3. **自动重连**: STA 模式下断开后每 5 秒自动尝试重连

4. **配置持久化**: 使用 `Preferences` 库（或 SPIFFS 文件）存储 WiFi 配置
   ```cpp
   #include <Preferences.h>
   Preferences prefs;
   prefs.begin("wifi", false);
   prefs.putString("sta_ssid", ssid);
   prefs.putString("sta_pass", password);
   prefs.end();
   ```

#### 接口定义:

```cpp
class WiFiManager {
public:
    void begin();                    // 初始化，读取配置并开始连接
    bool isConnected();              // STA 是否已连接
    bool isAPMode();                 // 是否运行在 AP 模式
    IPAddress getIP();               // 获取当前 IP（STA 或 AP）
    int8_t getRSSI();                // 获取 WiFi 信号强度
    uint8_t getStatus();             // 0=断开, 1=STA已连, 2=AP模式
    
    bool configure(const char* ssid, const char* pass);  // 设置 STA 参数
    void saveConfig();               // 保存到 NVS
    void resetConfig();              // 恢复出厂配置
    void reconnect();                // 手动触发重连
    
    String getSSID();                // 当前 STA SSID
};
```

### 5.4 TCP 服务器模块 (`tcp_server.h/.cpp`)

#### 功能需求:

1. 监听端口 **5000**
2. 仅允许 **1 个**客户端同时连接，新连接到来时踢掉旧连接
3. 接收 TCP 数据流，缓存后供主循环读取
4. 发送数据到已连接的客户端
5. 检测客户端断开（TCP keepalive 或读取超时）

#### 接口定义:

```cpp
class TCPBridgeServer {
public:
    void begin(uint16_t port = TCP_PORT);
    void loop();                     // 在主循环中调用，处理新连接和数据
    
    bool hasClient();                // 是否有客户端连接
    int available();                 // TCP 接收缓冲区中可读字节数
    int read(uint8_t* buf, int maxLen);  // 读取 TCP 数据
    void write(const uint8_t* buf, int len);  // 发送数据到客户端
    void disconnect();               // 断开当前客户端
    
    IPAddress clientIP();            // 当前客户端 IP
};
```

### 5.5 UART 桥接模块 (`uart_bridge.h/.cpp`)

#### 功能需求:

1. 使用 `Serial` (UART0) 与 MCU 通信，波特率 **921600**
2. 接收 MCU 数据并缓存
3. 发送数据到 MCU
4. 使用 Arduino `Serial` API 的内部缓冲区

#### 接口定义:

```cpp
class UARTBridge {
public:
    void begin(unsigned long baud = UART_BAUDRATE);
    
    int available();                 // UART 接收缓冲区可读字节数
    int read(uint8_t* buf, int maxLen);  // 读取 UART 数据
    void write(const uint8_t* buf, int len);  // 发送到 UART/MCU
};
```

> **重要**: Arduino ESP32 的 `Serial` 默认 RX 缓冲区为 256 字节，需在 `begin()` 之前设置更大的缓冲区：
> ```cpp
> Serial.setRxBufferSize(UART_RX_BUF_SIZE);  // 1024
> Serial.begin(UART_BAUDRATE);
> ```

### 5.6 协议处理模块 (`protocol.h/.cpp`)

#### 功能需求:

1. **帧解析状态机**: 与 MCU 侧完全一致的解析逻辑
2. **帧构建**: 构造回复帧
3. **CRC8 计算**: XOR 校验
4. **WiFi 控制帧处理**: 拦截 CH=0xE0 的帧

#### 接口定义:

```cpp
// 帧结构
struct BridgeFrame {
    uint8_t  sof0;          // 0xAA 或 0xBB
    uint8_t  ch;            // 通道 ID
    uint16_t len;           // 载荷长度
    uint8_t  data[128];     // 载荷数据
    bool     valid;         // CRC 校验结果
};

// 帧解析器（流式，逐字节输入）
class FrameParser {
public:
    void reset();
    // 输入一个字节，如果解析出完整帧返回 true
    bool feed(uint8_t byte, BridgeFrame& outFrame);
};

// 帧构建
int buildFrame(uint8_t* outBuf, uint8_t sof0, uint8_t ch,
               const uint8_t* data, uint16_t len);
// 返回总帧长度 (6 + len)

// CRC8 计算
uint8_t calcCRC8(uint8_t ch, uint16_t len, const uint8_t* data);
```

### 5.7 Web 配置模块 (`web_config.h/.cpp`)

#### 功能需求:

1. 运行 HTTP 服务器（端口 80）
2. 提供简易配置页面:
   - 显示当前 WiFi 状态（STA/AP 模式、IP、RSSI）
   - 表单输入 WiFi SSID 和密码
   - 保存并重连按钮
   - 恢复出厂设置按钮
   - 显示设备信息（固件版本、MAC 地址）
3. RESTful API:
   - `GET /` — 配置页面
   - `GET /api/status` — JSON 格式状态
   - `POST /api/wifi` — 设置 WiFi 参数
   - `POST /api/reset` — 恢复出厂设置
   - `GET /api/scan` — 扫描周围 WiFi

#### 接口定义:

```cpp
class WebConfig {
public:
    void begin(WiFiManager& wifiMgr);  // 启动 HTTP 服务器
    void loop();                        // 处理 HTTP 请求
};
```

---

## 6. 主程序逻辑 (`main.cpp`)

### 6.1 伪代码

```cpp
#include "config.h"
#include "wifi_manager.h"
#include "tcp_server.h"
#include "uart_bridge.h"
#include "protocol.h"
#include "web_config.h"

WiFiManager   wifiMgr;
TCPBridgeServer tcpServer;
UARTBridge    uart;
WebConfig     webCfg;
FrameParser   tcpParser;     // 解析 TCP 来的帧
FrameParser   uartParser;    // 解析 UART 来的帧

void setup() {
    // 1. LED
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
    
    // 2. UART (与 MCU 通信)
    uart.begin(UART_BAUDRATE);   // 921600
    
    // 3. WiFi
    wifiMgr.begin();
    
    // 4. mDNS
    MDNS.begin(MDNS_HOSTNAME);              // ehub.local
    MDNS.addService(MDNS_SERVICE, MDNS_PROTOCOL, TCP_PORT);
    
    // 5. TCP 服务器
    tcpServer.begin(TCP_PORT);   // 5000
    
    // 6. Web 配置
    webCfg.begin(wifiMgr);
    
    // 7. LED 指示就绪
    digitalWrite(LED_PIN, HIGH);
}

void loop() {
    // ── TCP → UART (PC 命令发往 MCU) ──
    tcpServer.loop();
    if (tcpServer.hasClient()) {
        uint8_t buf[256];
        int n = tcpServer.read(buf, sizeof(buf));
        for (int i = 0; i < n; i++) {
            BridgeFrame frame;
            if (tcpParser.feed(buf[i], frame)) {
                if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                    // ESP32 本地处理 WiFi 控制命令
                    handleWifiCtrl(frame);
                } else {
                    // 透传到 MCU: 原始字节直接转发
                    // 重建完整帧发送到 UART
                    uint8_t txBuf[BRIDGE_MAX_DATA + 6];
                    int txLen = buildFrame(txBuf, frame.sof0, frame.ch,
                                           frame.data, frame.len);
                    uart.write(txBuf, txLen);
                }
            }
        }
    }
    
    // ── UART → TCP (MCU 回复发往 PC) ──
    {
        uint8_t buf[256];
        int n = uart.read(buf, sizeof(buf));
        for (int i = 0; i < n; i++) {
            BridgeFrame frame;
            if (uartParser.feed(buf[i], frame)) {
                if (frame.ch == BRIDGE_CH_WIFI_CTRL) {
                    // MCU 转发来的 WiFi 控制帧，ESP32 处理后回复 PC
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
    
    // ── 心跳 (可选) ──
    handleHeartbeat();
}
```

### 6.2 WiFi 控制帧处理函数

```cpp
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
            
            // 构建回复帧通过 TCP 发给 PC
            uint8_t txBuf[13];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, 7);
            tcpServer.write(txBuf, txLen);
            break;
        }
        case 0x02: { // WIFI_CONFIG
            // 解析 SSID 和密码
            if (frame.len < 3) break;
            uint8_t ssidLen = frame.data[1];
            if (frame.len < 2 + ssidLen + 1) break;
            char ssid[33] = {0};
            memcpy(ssid, &frame.data[2], min((int)ssidLen, 32));
            
            uint8_t passLen = frame.data[2 + ssidLen];
            char pass[65] = {0};
            if (passLen > 0 && frame.len >= 3 + ssidLen + passLen) {
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
            // 扫描并构建回复
            int n = WiFi.scanNetworks();
            uint8_t reply[BRIDGE_MAX_DATA];
            int pos = 0;
            reply[pos++] = 0x05;
            reply[pos++] = (uint8_t)min(n, 10);  // 最多10个结果
            for (int i = 0; i < min(n, 10) && pos < BRIDGE_MAX_DATA - 34; i++) {
                String ssid = WiFi.SSID(i);
                uint8_t ssidLen = min((int)ssid.length(), 32);
                reply[pos++] = ssidLen;
                memcpy(&reply[pos], ssid.c_str(), ssidLen);
                pos += ssidLen;
                reply[pos++] = (uint8_t)WiFi.RSSI(i);  // signed
            }
            
            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL, reply, pos);
            tcpServer.write(txBuf, txLen);
            WiFi.scanDelete();
            break;
        }
        case 0x10: { // HEARTBEAT — 原样回传
            uint8_t txBuf[BRIDGE_MAX_DATA + 6];
            int txLen = buildFrame(txBuf, BRIDGE_SOF0_RPY, BRIDGE_CH_WIFI_CTRL,
                                   frame.data, frame.len);
            tcpServer.write(txBuf, txLen);
            break;
        }
        // 0x03 ESP_RESET 和 0x04 ESP_BOOTLOADER 由 MCU 硬件控制，
        // 这里不需要处理（PC 发到 MCU，MCU 操作引脚）
    }
}
```

### 6.3 LED 状态指示

| LED 状态 | 含义 |
|----------|------|
| 常灭 | 初始化中 |
| 慢闪 (1Hz) | WiFi 未连接 / AP 模式等待配置 |
| 快闪 (4Hz) | WiFi 正在连接中 |
| 常亮 | WiFi 已连接，无 TCP 客户端 |
| 呼吸/双闪 | WiFi 已连接 + TCP 客户端已连接 |

---

## 7. 数据处理要求

### 7.1 透传性能

- **延迟**: TCP↔UART 单向延迟 < 5ms（不含 WiFi 传输延迟）
- **吞吐**: 支持持续 100KB/s 双向透传
- **缓冲**: UART RX 缓冲区 1024 字节，TCP RX 使用 WiFiClient 内部缓冲区

### 7.2 帧完整性

- ESP32 对透传通道 (0x01~0x08, 0xF0) **不拆分、不合并**帧
- 帧解析只用于识别 CH=0xE0 的控制帧
- 对于透传帧，可以选择以下两种策略之一：
  - **策略A（推荐）**: 先解析帧，确认非0xE0后重建完整帧转发
  - **策略B**: 维护一个字节级透传通道，同时用影子解析器检测0xE0帧

> 推荐策略A，因为协议帧有明确边界，可确保每个帧的完整性。

### 7.3 异常处理

| 场景 | 处理 |
|------|------|
| TCP 客户端断开 | 清理连接状态，继续监听新连接 |
| WiFi 断开 | 自动重连，TCP 服务器在重连后继续工作 |
| UART 数据异常 (CRC错误) | 丢弃该帧，复位解析状态机 |
| TCP 接收缓冲区溢出 | 丢弃旧数据（TCP 内部有流控，一般不会出现） |
| UART 接收缓冲区溢出 | 丢失数据，需要足够大的缓冲区避免 |

---

## 8. Web 配置页面

### 8.1 页面功能

提供一个简洁的 HTML 页面（存储在代码中或 SPIFFS 中），功能包括：

1. **状态显示**:
   - 当前 WiFi 模式 (STA/AP)
   - 已连接的 SSID 和 IP 地址
   - 信号强度 (RSSI)
   - TCP 客户端连接状态
   - 设备运行时间
   - 固件版本

2. **WiFi 配置**:
   - 下拉框选择 SSID（从扫描结果中选择）或手动输入
   - 密码输入框
   - "扫描" 按钮
   - "保存并连接" 按钮

3. **系统操作**:
   - "重启 ESP32" 按钮
   - "恢复出厂设置" 按钮

### 8.2 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 返回配置页面 HTML |
| GET | `/api/status` | `{"mode":"STA","ssid":"xxx","ip":"192.168.1.100","rssi":-45,"tcp_client":true,"uptime":3600}` |
| POST | `/api/wifi` | Body: `{"ssid":"xxx","pass":"xxx"}` → `{"ok":true}` |
| GET | `/api/scan` | `{"networks":[{"ssid":"xxx","rssi":-45,"enc":true},...]}`  |
| POST | `/api/reset` | 恢复出厂 → `{"ok":true}` 然后重启 |
| POST | `/api/reboot` | 重启 ESP32 → `{"ok":true}` |

---

## 9. mDNS 服务发现

ESP32 启动后注册以下 mDNS 服务，供上位机自动发现：

```cpp
MDNS.begin("ehub");                         // ehub.local
MDNS.addService("_ehub", "_tcp", 5000);     // 服务类型
MDNS.addServiceTxt("_ehub", "_tcp", "version", "1.0");
MDNS.addServiceTxt("_ehub", "_tcp", "device", "EHUB");
```

上位机通过以下方式发现设备：
1. 尝试解析 `ehub.local` 
2. 或搜索 `_ehub._tcp` 服务

---

## 10. 编译和烧录

```bash
# PlatformIO 命令行
cd ESP32_wifi

# 编译
pio run

# 烧录 (通过 MCU 控制的 BOOT + EN 引脚自动进入下载模式)
pio run --target upload --upload-port COMx

# 串口监视器 (调试用，921600 波特率)
pio device monitor --baud 921600 --port COMx
```

---

## 11. 测试需求

### 11.1 基本功能测试
- [ ] ESP32 上电后成功进入 AP 模式（无 STA 配置时）
- [ ] 通过 Web 页面配置 WiFi 后成功连接路由器
- [ ] PC 通过 `ehub.local:5000` 或 IP:5000 连接 TCP 成功
- [ ] UART 921600 波特率收发正确

### 11.2 透传测试
- [ ] PC 通过 TCP 发送 Bridge 命令帧，ESP32 正确转发到 UART
- [ ] MCU 通过 UART 发送 Bridge 回复帧，ESP32 正确转发到 TCP
- [ ] 连续大量数据透传无丢帧
- [ ] 各通道 (0x01~0x08, 0xF0) 透传正确

### 11.3 WiFi 控制测试
- [ ] 通过 TCP 查询 WiFi 状态 (CH=0xE0, subcmd=0x01)
- [ ] 通过 TCP 配置 WiFi (CH=0xE0, subcmd=0x02)
- [ ] WiFi 扫描功能 (CH=0xE0, subcmd=0x05)
- [ ] 心跳帧收发 (CH=0xE0, subcmd=0x10)

### 11.4 异常测试
- [ ] WiFi 断开后自动重连
- [ ] TCP 客户端断开后新客户端可连接
- [ ] UART 收到错误帧不崩溃
- [ ] 长时间运行稳定性 (> 24 小时)

---

## 12. 汇总文档要求

开发完成后，请在 `ESP32_wifi/` 目录下创建 `WiFi_Bridge_ESP32_开发汇总.md`，包含：

1. **实际实现的文件清单**及功能说明
2. **PlatformIO 配置最终版本**
3. **内存占用**（Flash / RAM）
4. **WiFi 性能指标**（连接时间、透传延迟、吞吐量实测）
5. **已知限制和待优化项**
6. **烧录步骤和调试方法**
7. **与 MCU/上位机联调注意事项**
