#ifndef CONFIG_H
#define CONFIG_H

// ─── 固件版本 ───
#define FW_VERSION          "1.0.0"

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

// ─── WiFi 连接参数 ───
#define WIFI_CONNECT_TIMEOUT_MS  15000  // STA 连接超时 15 秒
#define WIFI_RECONNECT_INTERVAL  5000   // 断开后重连间隔 5 秒

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

// ─── LED 状态指示 ───
#define LED_PIN             2       // ESP32 DevKit 板载 LED

#endif // CONFIG_H
