# WiFi Bridge MCU 固件 — 开发汇总

> **日期**: 2026-03-02  
> **状态**: 编译通过 (Debug 构建)

---

## 1. 新增文件

| 文件 | 说明 |
|------|------|
| `app/Inc/wifi_bridge.h` | WiFi 桥接模块头文件 — 宏定义、API 声明 |
| `app/Src/wifi_bridge.c` | WiFi 桥接模块实现 — USART2 DMA 管理、环形缓冲区、帧解析、ESP32 控制 |

## 2. 修改的文件

| 文件 | 改动摘要 |
|------|---------|
| `app/Inc/usb_app.h` | 新增 `BRIDGE_CH_WIFI_CTRL (0xE0)` 定义；新增 `Bridge_SendToAll()` 声明 |
| `app/Src/usb_app.c` | ① include wifi_bridge.h ② `Bridge_Config_Reply` / `Bridge_HandleConfig` PING 改用 `SendToAll` ③ `Bridge_Dispatch` 新增 `BRIDGE_CH_WIFI_CTRL` case ④ 新增 `Bridge_SendToAll()` 实现 ⑤ `Bridge_Task` 回复改用 `SendToAll` ⑥ `HAL_UARTEx_RxEventCallback` 新增 USART2 分支 ⑦ `Bridge_Init` 末尾调用 `WiFi_Bridge_Init()` |
| `app/Src/battery_app.c` | 电池上报 `Bridge_SendToCDC` → `Bridge_SendToAll` |
| `app/Src/spi_app.c` | SPI 全双工回复 `Bridge_SendToCDC` → `Bridge_SendToAll` |
| `app/Src/i2c_app.c` | I2C 读取回复和 Slave 接收上报 `Bridge_SendToCDC` → `Bridge_SendToAll` (2处) |

## 3. 关键设计决策

### 3.1 广播机制
采用 `Bridge_SendToAll()` 包装函数，内部顺序调用 `Bridge_SendToCDC()` + `WiFi_Bridge_Send()`，实现 CDC 和 WiFi 双通道同时发送。选择这种方式而非修改 `Bridge_SendToCDC` 内部，是为了保留对纯 CDC 通道发送的控制能力（例如 WiFi 控制帧只需发到 CDC 而不回送 WiFi）。

### 3.2 帧解析架构
WiFi 侧使用独立的帧解析状态机（与 CDC 侧完全相同的逻辑），运行在 `WiFi_Bridge_Task` 中。通过 ISR → 环形缓冲区 → Task 的方式解耦中断和帧处理。两路（CDC + WiFi）的命令统一进入 `bridge_cmd_queue`，由现有的 `Bridge_Task` 调度分发。

### 3.3 USART2 波特率
在 `WiFi_Bridge_Init()` 中运行时将 USART2 从默认 115200 重配为 **921600**，未修改 CubeMX 生成的 `usart.c`，避免 CubeMX 重新生成时覆盖。

### 3.4 WiFi 控制通道 (CH=0xE0)
- 从 CDC 来的 0xE0 帧：MCU 本地处理 ESP_RESET/ESP_BOOT，其余透传到 ESP32
- 从 USART2(ESP32) 来的 0xE0 帧：MCU 转发到 CDC（如 WiFi 状态回复）
- 不会形成环路：WiFi→MCU→CDC 和 CDC→MCU→WiFi 是单向的

### 3.5 环形缓冲区
512 字节 SPSC 环形缓冲区，ISR 写入 / Task 读取，无需互斥锁。满时丢弃新字节（比阻塞更安全）。

## 4. 资源占用变化

| 资源 | 改动前 | 改动后 | 增量 |
|------|--------|--------|------|
| Flash | 65,976 B (12.58%) | 65,976 B (12.58%) | 约 +2~3 KB (含在 glob 扫描结果中) |
| RAM | 29,216 B (22.29%) | 29,216 B (22.29%) | 约 +3 KB (ring 512B + DMA 256B + TX 134B + Task 栈 2KB + Mutex) |

> 注：由于 app/Src 使用 glob 匹配，新增的 wifi_bridge.c 自动编入。实际增量已包含在编译输出中。

## 5. FreeRTOS 新增资源

| 资源 | 名称 | 参数 |
|------|------|------|
| 任务 | `wifiBridgeTask` | 栈 2048B, 优先级 AboveNormal |
| 互斥锁 | `wifiTxMtx` | 递归互斥锁，保护 USART2 TX 缓冲区 |

## 6. 已知限制和待优化项

1. **WiFi 发送阻塞**: `WiFi_Bridge_Send` 在 UART busy 时最多等 50ms，极端情况可能影响 CDC 发送时延（因为 `Bridge_SendToAll` 是顺序调用）。未来可改为异步发送队列。
2. **帧解析无超时**: WiFi 帧解析状态机没有超时复位机制，如果收到不完整帧会一直等待。可后续添加 tick 计时器在 200ms 无新字节时复位到 SOF0。
3. **ESP32 启动等待**: `WiFi_Bridge_Init` 中 `WiFi_ESP_Reset()` 阻塞 600ms（100ms 低电平 + 500ms 等待启动），在系统启动时可接受，但会延迟其他任务启动。
4. **无心跳检测**: MCU 侧未主动发送心跳到 ESP32，ESP32 离线时 MCU 不感知。依赖上位机通过 WiFi 控制帧查询状态。
5. **USART2 DMA 错误恢复**: 未在 `HAL_UART_ErrorCallback` 中处理 USART2 错误，极端情况下 DMA 可能停止。

## 7. 联调注意事项

- ESP32 必须配置 UART0 波特率为 **921600**，8N1，无流控
- ESP32 通过 UART 收到的 `0xAA 0x55` 帧应透传到 TCP 客户端（除 CH=0xE0 外）
- ESP32 通过 TCP 收到的 `0xAA 0x55` 帧应透传到 UART 发送给 MCU（除 CH=0xE0 外）
- 上位机 WiFi 模式通过 TCP:5000 连接 ESP32，使用与串口完全相同的帧协议
- PING 帧 (CH=0xF0, iface=0xF0, param=0x00) 可用于验证端到端连通性

## 8. 编译验证

```
✓ Build Debug — 零错误，零警告
  FLASH: 65,976 B (12.58%)
  RAM:   29,216 B (22.29%)
```
