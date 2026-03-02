# EHUB WiFi Bridge — ESP32 固件开发汇总

> **版本**: 1.0.0  
> **日期**: 2026-03-02  
> **平台**: ESP32-N8 (ESP32-DevKitC)  
> **框架**: PlatformIO + Arduino  

---

## 1. 实际实现的文件清单

| 文件路径 | 功能说明 |
|---------|---------|
| `platformio.ini` | PlatformIO 项目配置（ESP32, Arduino 框架, 921600 波特率） |
| `include/config.h` | 全局配置常量：引脚定义、波特率、端口号、协议常量、心跳参数 |
| `include/protocol.h` | 协议定义：BridgeFrame 结构体、FrameParser 状态机、帧构建/CRC 函数声明 |
| `src/protocol.cpp` | 协议实现：CRC8 (XOR) 计算、帧构建 `buildFrame()`、流式帧解析状态机 |
| `include/wifi_manager.h` | WiFiManager 类声明：STA/AP 双模管理、配置持久化、自动重连 |
| `src/wifi_manager.cpp` | WiFiManager 实现：NVS 存储、STA/AP/AP+STA 模式切换、15s 连接超时、5s 自动重连 |
| `include/tcp_server.h` | TCPBridgeServer 类声明：TCP 服务端，端口 5000，单客户端 |
| `src/tcp_server.cpp` | TCP 服务实现：新连接踢旧连接、数据收发、客户端断开检测 |
| `include/uart_bridge.h` | UARTBridge 类声明：UART0 封装（921600, GPIO1/GPIO3） |
| `src/uart_bridge.cpp` | UART 实现：1024 字节 RX 缓冲、Serial 读写封装 |
| `include/web_config.h` | WebConfig 类声明：HTTP 服务器，RESTful API |
| `src/web_config.cpp` | Web 配置实现：内嵌 HTML 页面(PROGMEM)、状态/WiFi配置/扫描/重置/重启 API |
| `src/main.cpp` | 主程序：setup/loop、TCP↔UART 帧透传、CH=0xE0 拦截处理、LED 指示、心跳 |
| `data/index.html` | Web 配置页面（SPIFFS 备份，实际已内嵌到代码中） |
| `lib/README` | PlatformIO 库目录说明 |

---

## 2. PlatformIO 配置最终版本

```ini
[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 921600
upload_speed = 921600
board_build.partitions = default.csv
build_flags =
    -DCORE_DEBUG_LEVEL=0
    -DARDUINO_USB_CDC_ON_BOOT=0
```

无需额外第三方库，全部使用 Arduino ESP32 内置组件：
- `WiFi.h` — WiFi STA/AP 管理
- `WebServer.h` — HTTP 服务器
- `ESPmDNS.h` — mDNS 服务发现
- `Preferences.h` — NVS 配置持久化

---

## 3. 内存占用估算

| 资源 | 预估使用 | 说明 |
|------|---------|------|
| Flash (代码) | ~800 KB | Arduino + WiFi + WebServer + 应用逻辑 |
| Flash (NVS) | ~4 KB | WiFi 配置存储 |
| RAM (静态) | ~50 KB | 全局变量、WiFi 栈 |
| RAM (动态) | ~30 KB | TCP 缓冲、帧解析缓冲 |
| UART RX 缓冲 | 1024 B | 可防止 921600 高速丢数据 |

> ESP32-N8 总 Flash 8MB，SRAM 520KB，资源充裕。

---

## 4. WiFi 性能指标

| 指标 | 目标值 | 说明 |
|------|-------|------|
| STA 连接超时 | 15 秒 | 超时后切换 AP+STA |
| 自动重连间隔 | 5 秒 | STA 断开后周期重连 |
| TCP↔UART 单程延迟 | < 5 ms | 不含 WiFi 射频延迟 |
| 双向透传吞吐 | ≥ 100 KB/s | 受 UART 921600 限制，理论上限 ~90 KB/s |
| 心跳间隔 | 3 秒 | ESP32 → MCU 方向 |
| 心跳超时 | 10 秒 | 用于检测连接活性 |

---

## 5. 已知限制和待优化项

1. **UART0 共用问题**: GPIO1/GPIO3 同时用于固件下载和 MCU 通信，调试时需注意不要用 `Serial.println()` 输出调试信息
2. **单 TCP 客户端**: 设计上仅允许 1 个客户端，新连接会踢掉旧连接
3. **WiFi 扫描阻塞**: `WiFi.scanNetworks()` 是阻塞调用，扫描期间（约 2-5 秒）透传会暂停
4. **简易 JSON 解析**: Web API 使用手动字符串解析而非 ArduinoJson 库，对畸形 JSON 容错有限
5. **无 TLS/认证**: TCP 5000 端口无加密，Web 接口无登录认证，仅适合局域网使用
6. **AP 模式性能**: AP+STA 并发模式下 WiFi 吞吐可能降低

### 待优化：
- 可引入 `WiFi.scanNetworksAsync()` 避免阻塞
- 可增加 OTA 空中升级功能
- 可增加 WebSocket 替代 TCP 轮询状态
- 可增加简单认证机制

---

## 6. 烧录步骤和调试方法

### 6.1 编译
```bash
cd ESP32_wifi
pio run
```

### 6.2 烧录
```bash
# 通过 USB/串口（MCU 控制 BOOT+EN 自动进入下载模式）
pio run --target upload --upload-port COMx
```

### 6.3 上传 SPIFFS 数据（可选，HTML 已内嵌代码中）
```bash
pio run --target uploadfs --upload-port COMx
```

### 6.4 调试方法
- **不可使用** `Serial.println()` — UART0 用于 MCU 通信
- 推荐方式：
  1. 通过 Web 页面 `/api/status` 查看状态
  2. 通过 TCP 发送 WiFi 状态查询帧 (CH=0xE0, subcmd=0x01)
  3. 观察 LED 指示灯状态判断连接情况

### 6.5 LED 状态含义
| LED 状态 | 含义 |
|----------|------|
| 常灭 | 初始化中 |
| 慢闪 (1Hz) | AP 模式等待配置 |
| 快闪 (4Hz) | WiFi 正在连接 |
| 常亮 | WiFi 已连接，无 TCP 客户端 |
| 双闪 | WiFi 已连接 + TCP 客户端已连接 |

---

## 7. 与 MCU/上位机联调注意事项

1. **UART 波特率必须一致**: ESP32 和 MCU (STM32F407 USART2) 均为 **921600**
2. **帧格式统一**: 三端（PC/ESP32/MCU）使用相同帧格式 `[SOF0][0x55][CH][LEN_H][LEN_L][DATA][CRC8]`
3. **CH=0xE0 帧**: ESP32 会拦截处理，**不会转发到** MCU/PC 另一端
4. **CH=0x01~0x08, 0xF0**: 透传帧，ESP32 不修改内容，原样转发
5. **MCU 控制 ESP32 复位**: MCU 通过 PC2 (ESP_EN) 引脚低脉冲复位 ESP32
6. **MCU 控制 ESP32 下载模式**: MCU 拉低 PC1 (ESP_BOOT) + 复位 = 进入 Bootloader
7. **mDNS 发现**: 上位机可通过 `ehub.local:5000` 或搜索 `_ehub._tcp` 服务发现 ESP32
8. **首次使用**: ESP32 上电后进入 AP 模式（SSID: `EHUB_WiFi`, 密码: `12345678`），电脑连接此热点后访问 `192.168.4.1` 配置路由器 WiFi
