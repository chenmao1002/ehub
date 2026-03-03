/* ==================== ESP32C6终极优化版本 ==================== */
/* 性能目标: 8-12ms往返时间 */
/* 协议保持不变: TX直接发数据, RX接收2字节长度+数据 */

#include <WiFi.h>
#include <driver/uart.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

/* ==================== 配置参数 ==================== */
#define WIFI_SSID     "xiaomiao"
#define WIFI_PASS     "12345678a"
#define DAP_TCP_PORT  3240

// UART配置 - 激进优化
#define UART_BAUDRATE       2000000    // 提升波特率
#define UART_NUM            UART_NUM_0
#define UART_TX_PIN         1
#define UART_RX_PIN         3
#define UART_BUF_SIZE       4096      // 加大缓冲区
#define DAP_PKT_SIZE        2048

// 超时优化 - 大幅缩短
#define RX_TOTAL_TIMEOUT_MS 50        // 总超时
#define RX_STABLE_CHECKS    2         // 稳定检查次数(原20改为2)
#define TX_WAIT_TIMEOUT_MS  5         // TX等待超时

/* ==================== 数据结构 ==================== */
struct msgbuf_t {
    uint8_t data[6144];  // 3 * DAP_PKT_SIZE
    size_t  len;
};

static msgbuf_t msgbuf;
static uint8_t response_buf[DAP_PKT_SIZE + 4];  // 响应缓冲区

WiFiServer server(DAP_TCP_PORT);
WiFiClient client;
uint8_t elaphureLink_flag = 0;

/* ==================== 内联工具函数 ==================== */
static inline void msgbuf_init(msgbuf_t *b) {
    b->len = 0;
}

static inline int msgbuf_add(msgbuf_t *b, WiFiClient &c) {
    int added = 0;
    while (c.available() && b->len < sizeof(b->data)) {
        b->data[b->len++] = c.read();
        added++;
    }
    return (b->len >= sizeof(b->data)) ? -1 : added;
}

/* ==================== 核心UART交换函数 - 零重试版本 ==================== */
static int uart_exchange_fast(const uint8_t *tx_data, uint16_t tx_len, 
                               uint8_t *rx_data, uint16_t *rx_len) {
    *rx_len = 0;
    
    // 清空UART接收缓冲区
    uart_flush_input(UART_NUM);
    
    // 发送数据
    int sent = uart_write_bytes(UART_NUM, tx_data, tx_len);
    if (sent != tx_len) {
        //Serial.printf("TX_ERR: %d/%d\n", sent, tx_len);
        return -1;
    }
    
    // 快速等待发送完成
    uart_wait_tx_done(UART_NUM, TX_WAIT_TIMEOUT_MS / portTICK_PERIOD_MS);
    
    // ========== 优化接收逻辑 ==========
    // 策略: 先读2字节长度头,再精确读取剩余数据
    
    uint32_t start_time = millis();
    size_t available = 0;
    
    // 第一阶段: 等待长度头(2字节)
    while (millis() - start_time < RX_TOTAL_TIMEOUT_MS) {
        uart_get_buffered_data_len(UART_NUM, &available);
        
        if (available >= 2) {
            // 读取长度头
            int read_cnt = uart_read_bytes(UART_NUM, rx_data, 2, 0);
            if (read_cnt != 2) {
                return -2;
            }
            
            uint16_t expected_len = (rx_data[0] << 8) | rx_data[1];
            
            // 验证长度合法性
            if (expected_len == 0 || expected_len > DAP_PKT_SIZE) {
                //Serial.printf("INVALID_LEN: %d\n", expected_len);
                return -3;
            }
            
            // 第二阶段: 读取数据体
            uint16_t received = 0;
            uint32_t data_start = millis();
            
            while (received < expected_len && 
                   (millis() - data_start) < (RX_TOTAL_TIMEOUT_MS - 10)) {
                
                uart_get_buffered_data_len(UART_NUM, &available);
                
                if (available > 0) {
                    int to_read = min((int)available, (int)(expected_len - received));
                    int read_cnt = uart_read_bytes(UART_NUM, 
                                                   rx_data + 2 + received, 
                                                   to_read, 
                                                   5 / portTICK_PERIOD_MS);
                    if (read_cnt > 0) {
                        received += read_cnt;
                    }
                }
                
                // 微秒级延迟,减少CPU占用
                if (received < expected_len) {
                    delayMicroseconds(100);
                }
            }
            
            if (received == expected_len) {
                *rx_len = 2 + expected_len;
                return 0;  // 成功
            } else {
                //Serial.printf("INCOMPLETE: %d/%d\n", received, expected_len);
                return -4;
            }
        }
        
        // 等待长度头时的延迟
        delayMicroseconds(200);
    }
    
    // 超时
   // Serial.println("RX_TIMEOUT");
    return -5;
}

/* ==================== elaphureLink协议处理 ==================== */
void msgbuf_elaphureLink(msgbuf_t *b, WiFiClient &c) {
    // 握手包处理 (12字节)
    if (b->len == 12) {
        if (b->data[0] == 0x8a && b->data[1] == 0x65 && b->data[2] == 0x6c) {
            elaphureLink_flag = 1;
           // Serial.println("elaphureLink ACTIVE");
            
            // 修改响应
            b->data[8] = 0; 
            b->data[9] = 0; 
            b->data[10] = 0; 
            b->data[11] = 1;
            
            c.write(b->data, 12);
            b->len = 0;
            uart_flush(UART_NUM);
            return;
        }
    }
    
    // 数据传输处理
    if (elaphureLink_flag && b->len > 0) {
        uint16_t send_len = b->len;
        
        if (send_len > DAP_PKT_SIZE) {
           // Serial.printf("DATA_TOO_LARGE: %d\n", send_len);
            send_len = DAP_PKT_SIZE;
        }
        
        // UART交换
        uint16_t response_len = 0;
        int result = uart_exchange_fast(b->data, send_len, 
                                       response_buf, &response_len);
        
        b->len = 0;  // 清空输入缓冲区
        
        if (result == 0 && response_len > 2) {
            // 成功: 发送数据部分(跳过2字节长度头)
            uint16_t data_len = (response_buf[0] << 8) | response_buf[1];
            c.write(&response_buf[2], data_len);
        } else {
            // 失败: 发送错误标志(可选)
            // 根据DAP协议,某些情况下可以发送0xFF响应
            // 这里选择不发送,让客户端超时重试
          //  Serial.printf("EXCHANGE_FAIL: %d\n", result);
        }
    }
}

/* ==================== Setup ==================== */
void setup() {
   // Serial.begin(921600);
    delay(100);
    
  //  Serial.println("\n\n=== ESP32C6 Ultra-Fast Edition ===");
  //  Serial.println("Target: 8-12ms Round-trip Time");
    
    // ========== UART配置 ==========
    uart_config_t uart_config = {
        .baud_rate = UART_BAUDRATE,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .rx_flow_ctrl_thresh = 100,  // 降低阈值
        .source_clk = UART_SCLK_DEFAULT,
    };
    
    ESP_ERROR_CHECK(uart_param_config(UART_NUM, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM, UART_TX_PIN, UART_RX_PIN, 
                                  UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    
    // 安装驱动,加大缓冲区
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM, 
                                        UART_BUF_SIZE * 2, 
                                        UART_BUF_SIZE * 2, 
                                        0, NULL, 0));
    
    // 设置UART超时(可选)
    uart_set_rx_timeout(UART_NUM, 10);  // 10个字符时间
    
   // Serial.printf("UART: %d baud, RX/TX buf: %d bytes\n", 
      //           UART_BAUDRATE, UART_BUF_SIZE);
    
    delay(500);
    
    // ========== WiFi配置 ==========
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);  // 禁用WiFi省电
    
    // 底层WiFi优化
    esp_wifi_set_ps(WIFI_PS_NONE);
    esp_wifi_set_max_tx_power(82);
    
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  //  Serial.print("Connecting WiFi");
    
    uint8_t retry = 0;
    while (WiFi.status() != WL_CONNECTED && retry < 40) {
        delay(500);
       // Serial.print(".");
        if (retry % 15 == 0) {
            WiFi.begin(WIFI_SSID, WIFI_PASS);
        }
        retry++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi OK");
        Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\nWiFi FAILED!");
        return;
    }
    
    // ========== TCP服务器配置 ==========
    server.begin();
    server.setNoDelay(true);  // 禁用Nagle算法
    
    msgbuf_init(&msgbuf);
    
    Serial.printf("Listening on port %d\n", DAP_TCP_PORT);
    Serial.println("Ready for high-speed operation!");
}

/* ==================== Loop - 高频轮询 ==================== */
void loop() {
    // 客户端连接管理
    if (!client || !client.connected()) {
        WiFiClient newClient = server.available();
        if (newClient) {
            if (client) {
                client.stop();
            }
            
            client = newClient;
            client.setNoDelay(true);  // 关键: 客户端也禁用Nagle
            
            msgbuf_init(&msgbuf);
            elaphureLink_flag = 0;
            
          //  Serial.println("Client CONNECTED");
        }
        return;
    }
    
    // 批量读取TCP数据
    if (client.available()) {
        if (msgbuf_add(&msgbuf, client) < 0) {
          //  Serial.println("BUF_OVERFLOW");
            client.stop();
            return;
        }
    }
    
    // 处理数据
    if (msgbuf.len > 0) {
        msgbuf_elaphureLink(&msgbuf, client);
        msgbuf.len = 0;  // 清空已处理数据
    }
    
    // 减少任务切换开销 - 更激进的轮询
    // 不调用yield(),让FreeRTOS自行调度
}
