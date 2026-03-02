# EHUB WiFi↔Bus Bridge — MCU 固件开发需求文档# EHUB WiFi↔Bus Bridge — MCU 固件开发需求文档






































































































































































































































































































































































































































6. **与 ESP32/上位机的联调注意事项**5. **已知限制或待优化项**4. **资源占用**：新增 Flash/RAM 估算、FreeRTOS 堆使用变化3. **编译验证结果**（是否通过编译）2. **新增文件列表**及功能说明1. **实际修改的文件列表**及每个文件的改动摘要开发完成后，请在项目根目录创建 `WiFi_Bridge_MCU_开发汇总.md`，包含：## 9. 汇总文档要求---- [ ] PING 命令通过 WiFi 正常响应- [ ] ESP32 复位 / 进入 Bootloader 功能- [ ] WiFi + CDC 同时工作互不干扰- [ ] WiFi 链路动态配置（修改波特率等）- [ ] WiFi 链路接收电池状态上报- [ ] WiFi 链路 I2C 读写- [ ] WiFi 链路透传 SPI 数据（全双工）- [ ] WiFi 链路透传 CAN 数据（各波特率）- [ ] WiFi 链路透传 RS422 数据- [ ] WiFi 链路透传 RS485 数据- [ ] WiFi 链路透传 USART1 数据（发送+接收）### 8.2 集成测试- [ ] 环形缓冲区溢出保护- [ ] 帧解析状态机：正常帧、CRC 错误帧、超长帧、不完整帧- [ ] USART2 921600 波特率收发正确性（回环测试）### 8.1 单元测试## 8. 测试需求---| ESP32 无响应 | 上位机可通过 WIFI_CTRL 的 ESP_RESET 命令复位 ESP32 || WiFi_Bridge_Send 超时 | 放弃本帧发送，不重试 || 帧长度超限 (>128) | 丢弃该帧，复位解析状态机 || 帧 CRC 校验失败 | 丢弃该帧，复位解析状态机 || USART2 DMA 错误 | 在 `HAL_UART_ErrorCallback` 中重新初始化 USART2 并重启 DMA 接收 ||------|----------|| 场景 | 处理方式 |## 7. 错误处理---- 如果队列满，WiFi 侧命令通过 `osMessageQueuePut(..., 0U)` 非阻塞投递，满时丢弃- `bridge_cmd_queue` 统一接收两路命令，按 FIFO 处理- WiFi 发送失败（USART2 BUSY 超时）**不影响** CDC 正常工作- WiFi 链路和 CDC 链路 **独立运行、互不阻塞**## 6. 数据优先级与流控---| 添加 `app/Src/wifi_bridge.c` | 编译新增源文件 ||--------|------|| 修改点 | 说明 |### 5.5 `CMakeLists.txt`| **不需要修改** | USART2 的波特率在 `WiFi_Bridge_Init()` 中运行时重配为 921600 ||--------|------|| 修改点 | 说明 |### 5.4 `Core/Src/usart.c`| 新增 `Bridge_SendToAll()` 声明 | 公共 API || 新增 `BRIDGE_CH_WIFI_CTRL 0xE0U` 定义 | WiFi 控制通道 ||--------|------|| 修改点 | 说明 |### 5.3 `app/Inc/usb_app.h`| 电池上报处 | 将 `Bridge_SendToCDC` 替换为 `Bridge_SendToAll` || 添加 `#include "wifi_bridge.h"` | 引入头文件 ||--------|------|| 修改点 | 说明 |### 5.2 `app/Src/battery_app.c`| `Bridge_Dispatch` switch | 新增 `BRIDGE_CH_WIFI_CTRL` 分支 || `Bridge_Init()` 末尾 | 添加 `WiFi_Bridge_Init()` 调用 || `HAL_UARTEx_RxEventCallback` | 新增 `USART2` 分支，将数据写入环形缓冲区 || `Bridge_HandleConfig` PING 回复 | 将 `Bridge_SendToCDC` 替换为 `Bridge_SendToAll` || `Bridge_Config_Reply` 函数 | 将 `Bridge_SendToCDC` 替换为 `Bridge_SendToAll` || `Bridge_Task` 中的回复发送 | 将 `Bridge_SendToCDC` 替换为 `Bridge_SendToAll` || 新增 `Bridge_SendToAll()` 函数 | 封装同时发送到 CDC 和 WiFi || 添加 `#include "wifi_bridge.h"` | 引入 WiFi 桥接头文件 ||--------|------|| 修改点 | 说明 |### 5.1 `app/Src/usb_app.c`## 5. 需修改的现有文件---- 需确保线程安全（单生产者单消费者模型，无需互斥锁）- 读取端: `WiFi_Bridge_Task` (任务上下文)- 写入端: `HAL_UARTEx_RxEventCallback` (ISR 上下文)- 用于在 ISR 和 Task 之间传递 USART2 DMA 接收到的原始数据- 大小: 512 字节### 4.5 环形缓冲区规格| 创建位置 | `WiFi_Bridge_Init()` 内 || 优先级 | `osPriorityAboveNormal` (与 bridgeTask 相同) || 栈大小 | 512 × 4 = 2048 字节 || 任务名 | `wifiBridgeTask` ||------|----|| 属性 | 值 |### 4.4 FreeRTOS 任务配置```}    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_SET);    osDelay(50);    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_SET);    osDelay(100);    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_RESET);    osDelay(50);    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_RESET);{void WiFi_ESP_EnterBootloader(void)}    osDelay(500);  // 等待 ESP32 启动完成    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_SET);    osDelay(100);    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_RESET);{void WiFi_ESP_Reset(void)```c#### 4.3.5 ESP32 引脚控制```}    HAL_UART_Transmit_DMA(&huart2, wifi_tx_buf, 6U + len);    }        osDelay(1);        if ((HAL_GetTick() - t) > 50U) break;    while (HAL_UART_GetState(&huart2) & HAL_UART_STATE_BUSY_TX) {    uint32_t t = HAL_GetTick();    // 等待上次传输完成    wifi_tx_buf[5 + len] = crc;    for (uint16_t i = 0; i < len; i++) crc ^= data[i];    memcpy(&wifi_tx_buf[5], data, len);    wifi_tx_buf[4] = (uint8_t)(len & 0xFF);  crc ^= wifi_tx_buf[4];    wifi_tx_buf[3] = (uint8_t)(len >> 8);    crc ^= wifi_tx_buf[3];    wifi_tx_buf[2] = ch;               crc ^= ch;    wifi_tx_buf[1] = BRIDGE_SOF1;      // 0x55    wifi_tx_buf[0] = BRIDGE_SOF0_RPY;  // 0xBB    uint8_t crc = 0U;    if (len == 0U || len > BRIDGE_MAX_DATA) return;    static uint8_t wifi_tx_buf[BRIDGE_MAX_DATA + 6U];{void WiFi_Bridge_Send(uint8_t ch, const uint8_t *data, uint16_t len)```c#### 4.3.4 WiFi_Bridge_Send 实现然后将所有现有的 `Bridge_SendToCDC()` 调用替换为 `Bridge_SendToAll()`。```}    WiFi_Bridge_Send(ch, data, len);    Bridge_SendToCDC(ch, data, len);{void Bridge_SendToAll(uint8_t ch, const uint8_t *data, uint16_t len)// 在 usb_app.c 中新增```c**建议实现方式**: 创建统一的 `Bridge_SendToAll()` 包装函数：4. **`battery_app.c` 中的 `Bridge_SendToCDC` 调用处** — 电池状态也需转发3. **`Bridge_HandleConfig` 的 PING 回复中** — PING 回复也需转发2. **`Bridge_Config_Reply` 函数中** — 配置回复也需转发1. **`Bridge_Task` 中的 `Bridge_SendToCDC` 调用处** — 每次发送 CDC 回复后，同时调用 `WiFi_Bridge_Send(msg.ch, msg.buf, msg.len)`在 `usb_app.c` 的以下位置添加 `WiFi_Bridge_Send()` 调用：**关键修改**: 所有总线回复不仅发送到 CDC，还需同时发送到 WiFi。#### 4.3.3 发送路径修改  - 其他通道 (0x01~0xF0, SOF0=0xAA): 推入 `bridge_cmd_queue`，走现有总线调度  - 如果是 ESP32 回复的 `0xE0` 帧（SOF0=0xBB）: 转发到 CDC 给 PC    - 其他 subcmd: 帧来自 PC，**直接透传到 ESP32**（通过 USART2 发送）    - `subcmd == 0x04` (ESP_BOOTLOADER): MCU 本地执行 `WiFi_ESP_EnterBootloader()`    - `subcmd == 0x03` (ESP_RESET): MCU 本地执行 `WiFi_ESP_Reset()`  - 如果 `CH == 0xE0` (WIFI_CTRL):- 解析出完整帧后：- `WiFi_Bridge_Task` 循环从环形缓冲区取数据，运行与 CDC 相同的状态机解析帧  - 重新启动 DMA 接收  - 将收到的原始数据拷贝到环形缓冲区 `wifi_rx_ring`- 在 `HAL_UARTEx_RxEventCallback` 中（已存在于 `usb_app.c`），**新增 USART2 分支**：- 使用 **DMA + IDLE 中断**接收：缓冲区大小 256 字节#### 4.3.2 USART2 接收与帧解析```  └── osThreadNew(WiFi_Bridge_Task, NULL, &wifi_task_attrs)  ├── WiFi_ESP_Reset()          // 确保 ESP32 干净启动  ├── __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT)  ├── HAL_UARTEx_ReceiveToIdle_DMA(&huart2, wifi_rx_buf, 256)  ├── HAL_UART_Init(&huart2)  ├── huart2.Init.BaudRate = 921600  ├── HAL_UART_DeInit(&huart2)WiFi_Bridge_Init()```#### 4.3.1 初始化流程### 4.3 实现要求 (`wifi_bridge.c`)```#endif /* __WIFI_BRIDGE_H__ */#endif}#ifdef __cplusplusvoid WiFi_ESP_EnterBootloader(void); */ *         时序: ESP_BOOT=LOW → ESP_EN=LOW(100ms) → ESP_EN=HIGH → 延时50ms → ESP_BOOT=HIGH * @brief  使 ESP32 进入 Bootloader 下载模式/**void WiFi_ESP_Reset(void); */ * @brief  硬件复位 ESP32 (拉低 PC2/ESP_EN 100ms 后拉高)/**void WiFi_Bridge_Task(void *argument); */ *         解析 USART2 接收缓冲区，将完整帧推入 bridge_cmd_queue * @brief  WiFi 桥接 FreeRTOS 任务入口/**void WiFi_Bridge_Send(uint8_t ch, const uint8_t *data, uint16_t len); */ * @param  len   载荷长度 (≤128) * @param  data  载荷 * @param  ch    通道 ID (BRIDGE_CH_*) *         帧格式与 CDC 相同: [0xBB][0x55][CH][LEN_H][LEN_L][DATA][CRC8] * @brief  通过 USART2 发送桥接帧到 ESP32/**void WiFi_Bridge_Init(void); */ *         在 Bridge_Init() 之后调用 *         - 复位 ESP32 (确保干净启动) *         - 创建 WiFi 桥接 FreeRTOS 任务 *         - 启动 USART2 DMA 空闲接收 *         - 重新配置 USART2 为 921600 波特率 * @brief  初始化 WiFi 桥接模块/**#define WIFI_UART_BAUDRATE       921600U/* MCU↔ESP32 UART 波特率 (固定) */#define WIFI_SUBCMD_HEARTBEAT    0x10U#define WIFI_SUBCMD_SCAN         0x05U#define WIFI_SUBCMD_ESP_BOOT     0x04U#define WIFI_SUBCMD_ESP_RESET    0x03U#define WIFI_SUBCMD_CONFIG       0x02U#define WIFI_SUBCMD_STATUS       0x01U/* WiFi 控制子命令 */#define BRIDGE_CH_WIFI_CTRL   0xE0U/* WiFi 控制通道 ID */#endifextern "C" {#ifdef __cplusplus#include <stdint.h>#define __WIFI_BRIDGE_H__#ifndef __WIFI_BRIDGE_H__```c### 4.2 模块接口定义 (`wifi_bridge.h`)| `wifi_bridge.c` | `app/Src/` | WiFi 桥接模块实现 || `wifi_bridge.h` | `app/Inc/` | WiFi 桥接模块头文件 ||------|------|------|| 文件 | 位置 | 说明 |### 4.1 新增文件## 4. 软件架构---> **注意**: WIFI_CONFIG (0x02) 和 WIFI_SCAN (0x05) 帧需要 MCU **透传**到 ESP32 处理；WIFI_STATUS (0x01) 由 ESP32 回复后通过 MCU 转发到 PC；ESP_RESET (0x03) 和 ESP_BOOTLOADER (0x04) 由 MCU 本地执行。| 0x10 | HEARTBEAT | 双向 | `[tick_3][tick_2][tick_1][tick_0]` | 相同格式回复 || 0x05 | WIFI_SCAN | CMD→RPY | 无 | `[0x05][count][ssid1_len][ssid1...][rssi1]...` || 0x04 | ESP_BOOTLOADER | CMD | 无 | 无 (MCU操作PC1+PC2进入下载模式) || 0x03 | ESP_RESET | CMD | 无 | 无 (MCU直接操作PC2复位ESP32) || 0x02 | WIFI_CONFIG | CMD | `[ssid_len][ssid...][pass_len][pass...]` | `[0x02][0x00]` 成功 / `[0x02][0xFF]` 失败 || 0x01 | WIFI_STATUS | CMD→RPY | 无 | `[0x01][status][rssi_signed][ip0][ip1][ip2][ip3]` status: 0=未连接, 1=已连接 ||--------|------|------|------|------|| subcmd | 名称 | 方向 | 参数 | 回复 |**命令格式**: `[subcmd][params...]`此通道用于 WiFi 状态查询和 ESP32 控制。**此通道帧由 MCU 和 ESP32 共同处理**。### 3.4 WIFI_CTRL 帧 (CH=0xE0，新增)**CONFIG 回复**: `[iface][status]` — status: 0x00=成功, 0xFF=失败**PING 特殊命令**: `iface=0xF0, param=0x00` → 回复 `[0xF0][0x00]['E']['H']['U']['B']`| 0x07 CAN | 0x05 CAN_BAUD | 125000/250000/500000/1000000 | CAN 波特率 || 0x05/0x06 I2C | 0x08 I2C_OWN | 0x08~0x77 | Slave 自身地址 || 0x05/0x06 I2C | 0x07 I2C_ROLE | 0/1 | 0=Master, 1=Slave || 0x05/0x06 I2C | 0x04 I2C_SPD | 100000/400000 | I2C 速度 || 0x04 SPI | 0x06 SPI_ROLE | 0/1 | 0=Master, 1=Slave || 0x04 SPI | 0x03 SPI_MODE | 0~3 | CPOL/CPHA 模式 || 0x04 SPI | 0x02 SPI_SPD | 0~7 | 预分频: 2/4/8/16/32/64/128/256 || 0x03 RS422 | 0x01 BAUD | 波特率值 | 动态修改 RS422 波特率 || 0x02 RS485 | 0x01 BAUD | 波特率值 | 动态修改 RS485 波特率 || 0x01 USART1 | 0x01 BAUD | 波特率值 | 动态修改 USART1 波特率 ||-------|-------------------|---------------------|------|| iface | param (0x01~0x08) | value (uint32 大端) | 说明 |**命令格式**: `[iface][param][value_3][value_2][value_1][value_0]` (6 字节)### 3.3 CONFIG 帧 (CH=0xF0) 详情| **WIFI_CTRL** | **0xE0** | **双向** | **WiFi 控制帧（新增）**, 见 3.4 节 || CONFIG | 0xF0 | 双向 | 配置帧，见下方 || BATTERY | 0x08 | RPY | `[V_H][V_L][percent][charging]` (周期性上报) || CAN | 0x07 | 双向 | `[ID_3][ID_2][ID_1][ID_0][DLC][data...]` (ID 大端) || I2C_R | 0x06 | CMD→RPY | CMD: `[7bit_addr][read_len][reg?]`, RPY: 读取数据 || I2C_W | 0x05 | CMD | `[7bit_addr][payload...]` || SPI | 0x04 | 双向 | 全双工 TX/RX 原始字节 || RS422 | 0x03 | 双向 | 原始字节透传 (UART4 全双工) || RS485 | 0x02 | 双向 | 原始字节透传 (USART3 + PD10 DE) || USART1 | 0x01 | 双向 | 原始字节透传 ||--------|-------|------|-----------|| 通道名 | CH 值 | 方向 | DATA 格式 |### 3.2 通道 ID 定义| CRC8 | 1 | 异或校验 || DATA | LEN | 载荷数据 (1~128 字节) || LEN_L | 1 | 载荷长度低字节 || LEN_H | 1 | 载荷长度高字节 || CH | 1 | 通道 ID（见下表） || SOF1 | 1 | 固定 0x55 || SOF0 | 1 | 方向标识: 0xAA=命令(PC→设备), 0xBB=回复(设备→PC) ||------|--------|------|| 字段 | 字节数 | 说明 |```CRC8 = XOR(CH, LEN_H, LEN_L, DATA[0], DATA[1], ..., DATA[LEN-1])设备→PC (Reply):    [0xBB][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]PC→设备 (Command):  [0xAA][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]```所有方向使用相同的帧结构：### 3.1 帧格式## 3. 通信协议（三端统一）---> **重要**：USART2 当前在 CubeMX 中已初始化为 115200，需要在 `WiFi_Bridge_Init()` 中重新配置为 **921600**。| DMA RX | DMA1_Stream5 (已分配) || DMA TX | DMA1_Stream6 (已分配) || 流控 | 无 || 停止位 | 1 || 校验 | 无 || 数据位 | 8 || 波特率 | **921600** ||------|----|| 参数 | 值 |**USART2 参数（固定，不可运行时修改）**：| ESP_BOOT | PC1 (Output PP) | GPIO0/BOOT | MCU 控制 ESP32 启动模式，高=正常运行, 低=下载模式 || ESP_EN | PC2 (Output PP) | EN | MCU 控制 ESP32 使能/复位，高电平运行 || USART2_RX | PA3 (AF7) | UART0_TX (GPIO1) | ESP32 → MCU 数据 || USART2_TX | PA2 (AF7) | UART0_RX (GPIO3) | MCU → ESP32 数据 ||------|----------|------------|------|| 信号 | MCU 引脚 | ESP32 引脚 | 说明 |## 2. 硬件接口---两条链路 **共用同一套帧协议和通道ID**，可同时工作、互不干扰。```上位机(PC)  ←── USB CDC  ──→  MCU(STM32F407)  ←──→  目标总线上位机(PC)  ←── WiFi TCP ──→  ESP32  ←── USART2 (921600) ──→  MCU(STM32F407)  ←──→  目标总线```**整体数据流**：EHUB 设备当前通过 **USB CDC** 实现 PC ↔ 总线桥接调试（USART1/RS485/RS422/CAN/SPI/I2C/电量显示）。现需新增 **WiFi 局域网调试链路**，通过板载 ESP32-N8 模块建立第二条透明桥接通道，使上位机可通过 WiFi 完成所有与 USB CDC 相同的调试功能。## 1. 项目背景---> **关联文档**: `ESP32_wifi/WiFi_Bridge_ESP32_开发需求文档.md`, `tools/WiFi_Bridge_上位机_开发需求文档.md`> **范围**: STM32F407VET6 MCU 侧固件新增 WiFi 桥接模块  > **日期**: 2026-03-02  > **版本**: 1.0  
> **版本**: v1.0  
> **日期**: 2026-03-02  
> **范围**: STM32F407VET6 MCU 端固件新增 WiFi Bridge 模块  
> **完成后**: 在项目根目录创建 `WiFi_Bridge_MCU_开发汇总.md`，记录实际实现细节、测试结果和注意事项

---

## 1. 项目背景

EHUB 是一个多总线调试器，MCU 通过 USB CDC 与上位机通信，采用自定义 Bridge 协议转发 USART/RS485/RS422/CAN/SPI/I2C 数据并上报电池状态。  
本次需求：**新增 WiFi 通路**，通过 ESP32-N8 模块让上位机也可以通过 WiFi 局域网完成所有调试功能（与 USB CDC 并行双通道）。

---

## 2. 硬件接口

| MCU 引脚 | 功能 | 连接目标 | 说明 |
|----------|------|---------|------|
| **PA2** (TX) | USART2_TX | ESP32 UART0 RX (RXD0) | 数据链路 |
| **PA3** (RX) | USART2_RX | ESP32 UART0 TX (TXD0) | 数据链路 |
| **PC2** | GPIO Output PP | ESP32 EN 引脚 | 高电平使能，低脉冲复位 ESP32 |
| **PC1** | GPIO Output PP | ESP32 BOOT 引脚 | 低电平 + 复位 = 进入下载模式 |

> USART2 已在 CubeMX 中初始化（`MX_USART2_UART_Init()`），带 DMA：  
> TX = DMA1_Stream6，RX = DMA1_Stream5，IRQ 优先级 = 1。  
> GPIO PC1 (`ESP_BOOT_Pin`) 和 PC2 (`ESP_EN_Pin`) 已在 `gpio.c` 中配置为推挽输出，初始高电平。

---

## 3. 通信协议（三端统一，必须严格遵循）

### 3.1 UART 物理层参数

| 参数 | 值 |
|------|-----|
| **波特率** | **921600** |
| 数据位 | 8 |
| 校验位 | 无 (None) |
| 停止位 | 1 |
| 硬件流控 | 无 |

> ⚠️ **关键**：MCU USART2 波特率必须改为 **921600**（不再是默认的 115200），需在初始化时修改 `huart2.Init.BaudRate = 921600`。

### 3.2 帧格式（与现有 USB CDC Bridge 协议 100% 一致）

```
PC → 设备 (命令):  [0xAA][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]
设备 → PC (应答):  [0xBB][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]

CRC8 = XOR(CH, LEN_H, LEN_L, DATA[0], DATA[1], ..., DATA[LEN-1])
```

- 帧头 `0xAA 0x55` 表示 PC→设备命令
- 帧头 `0xBB 0x55` 表示设备→PC 应答/上报
- LEN 为大端序 16 位，表示 DATA 段字节数
- 最大有效载荷 **128 字节** (`BRIDGE_MAX_DATA`)

### 3.3 通道 ID（CH 字段）

| CH 值 | 宏名 | 说明 |
|--------|------|------|
| `0x01` | `BRIDGE_CH_USART1` | USART1 原始字节透传 |
| `0x02` | `BRIDGE_CH_RS485` | RS485 (USART3 + DE) |
| `0x03` | `BRIDGE_CH_RS422` | RS422 (UART4) |
| `0x04` | `BRIDGE_CH_SPI` | SPI1 全双工 |
| `0x05` | `BRIDGE_CH_I2C_W` | I2C1 写 |
| `0x06` | `BRIDGE_CH_I2C_R` | I2C1 读 |
| `0x07` | `BRIDGE_CH_CAN` | CAN1 |
| `0x08` | `BRIDGE_CH_BATTERY` | 电池状态上报 |
| `0xE0` | `BRIDGE_CH_WIFI` | **新增** WiFi 状态/管理（ESP32 拦截处理，不转发到 MCU） |
| `0xF0` | `BRIDGE_CH_CONFIG` | 外设配置 |

### 3.4 CONFIG 帧格式（CH = 0xF0）

```
DATA = [iface(1B)][param(1B)][value(4B, 大端序)]
```

| param | 值 | 说明 |
|-------|-----|------|
| `BRIDGE_CFG_BAUD` | `0x01` | UART 波特率 (uint32 BE) |
| `BRIDGE_CFG_SPI_SPD` | `0x02` | SPI 预分频 0-7 |
| `BRIDGE_CFG_SPI_MODE` | `0x03` | SPI 模式 0-3 |
| `BRIDGE_CFG_I2C_SPD` | `0x04` | I2C 速度 100000/400000 |
| `BRIDGE_CFG_CAN_BAUD` | `0x05` | CAN 波特率 |
| `BRIDGE_CFG_SPI_ROLE` | `0x06` | SPI 角色 0=Master 1=Slave |
| `BRIDGE_CFG_I2C_ROLE` | `0x07` | I2C 角色 0=Master 1=Slave |
| `BRIDGE_CFG_I2C_OWN` | `0x08` | I2C 从机地址 |

**PING 帧**：`iface=0xF0, param=0x00` → 设备应答 `[0xF0][0x00]['E']['H']['U']['B']`

### 3.5 WiFi 管理通道（CH = 0xE0，新增）

此通道由 **ESP32 拦截处理**，MCU 收到 CH=0xE0 的帧直接忽略即可，不做转发。  
ESP32 处理后直接在 WiFi 侧回复给 PC。

| 子命令 (data[0]) | 说明 | 请求数据 | 应答数据 |
|------------------|------|---------|---------|
| `0x01` | 查询 WiFi 状态 | 无 | `[0x01][status][RSSI_signed][IP:4B]` |
| `0x02` | 查询设备名/版本 | 无 | `[0x02][name_string\0]` |
| `0x03` | 设置 WiFi SSID | `[0x03][ssid_string\0]` | `[0x03][0x00=OK/0xFF=FAIL]` |
| `0x04` | 设置 WiFi 密码 | `[0x04][pass_string\0]` | `[0x04][0x00=OK/0xFF=FAIL]` |
| `0x05` | 保存并重连 WiFi | 无 | `[0x05][0x00]` |
| `0x06` | 恢复出厂设置 WiFi | 无 | `[0x06][0x00]` |

---

## 4. 软件架构设计

### 4.1 新增文件

| 文件 | 路径 | 说明 |
|------|------|------|
| `wifi_bridge.h` | `app/Inc/wifi_bridge.h` | WiFi bridge 模块头文件 |
| `wifi_bridge.c` | `app/Src/wifi_bridge.c` | WiFi bridge 模块实现 |

### 4.2 模块接口定义

```c
/* ---- wifi_bridge.h ---- */
#ifndef __WIFI_BRIDGE_H__
#define __WIFI_BRIDGE_H__

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief  初始化 WiFi bridge 模块
 *         - 将 USART2 波特率配置为 921600
 *         - 启动 USART2 DMA+IDLE 接收
 *         - 创建 WiFiBridge FreeRTOS 任务
 *         在 Bridge_Init() 末尾调用一次
 */
void WiFi_Bridge_Init(void);

/**
 * @brief  通过 USART2 → ESP32 → WiFi → PC 发送桥接回复帧
 *         帧格式与 Bridge_SendToCDC() 完全相同 (0xBB 0x55 CH LEN DATA CRC)
 * @param  ch    通道 ID (BRIDGE_CH_*)
 * @param  data  有效载荷指针
 * @param  len   有效载荷长度 (≤ BRIDGE_MAX_DATA)
 */
void WiFi_Bridge_Send(uint8_t ch, const uint8_t *data, uint16_t len);

/**
 * @brief  复位 ESP32 (拉低 PC2/ESP_EN 100ms 再拉高)
 */
void WiFi_ESP_Reset(void);

/**
 * @brief  使 ESP32 进入下载模式
 *         (先拉低 PC1/ESP_BOOT，再执行复位序列，然后释放 BOOT)
 */
void WiFi_ESP_EnterBootloader(void);

#ifdef __cplusplus
}
#endif
#endif /* __WIFI_BRIDGE_H__ */
```

### 4.3 内部实现要求

#### 4.3.1 USART2 DMA+IDLE 接收与帧解析

```c
#define WIFI_RX_BUF_SIZE  256U  /* DMA 环形缓冲区，比 CDC 大以容纳 WiFi 突发 */
static uint8_t usart2_rx_buf[WIFI_RX_BUF_SIZE];
```

- 使用 `HAL_UARTEx_ReceiveToIdle_DMA(&huart2, ...)` 启动接收
- 禁用半传输中断 `__HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT)`
- 在 `HAL_UARTEx_RxEventCallback` 中增加 `huart->Instance == USART2` 分支
- 收到的原始字节送入**帧解析状态机**（与 `CDC_Receive_FS` 中的解析逻辑相同）
- 解析完成的帧放入 `bridge_cmd_queue`（与 CDC 命令走同一队列）
- 帧头为 `0xAA 0x55` 的才是有效命令帧

> ⚠️ 由于 `HAL_UARTEx_RxEventCallback` 是全局唯一的，已定义在 `usb_app.c` 中。  
> 需要在该回调中增加 USART2 分支。具体方式：
> 1. 在 `usb_app.c` 的 `HAL_UARTEx_RxEventCallback` 中添加 `else if (huart->Instance == USART2)` 分支
> 2. 该分支调用 `wifi_bridge.c` 中导出的处理函数：`WiFi_Bridge_RxHandler(uint8_t *data, uint16_t size)`
> 3. `WiFi_Bridge_RxHandler` 执行帧解析并入队

#### 4.3.2 USART2 DMA 发送

```c
#define WIFI_TX_BUF_SIZE  (BRIDGE_MAX_DATA + 6U)  /* SOF(2)+CH(1)+LEN(2)+DATA(128)+CRC(1) */
static uint8_t usart2_tx_buf[WIFI_TX_BUF_SIZE];
```

- `WiFi_Bridge_Send()` 构建帧格式：`[0xBB][0x55][CH][LEN_H][LEN_L][DATA][CRC8]`
- 通过 `HAL_UART_Transmit_DMA(&huart2, ...)` 发送
- 发送前检查 UART 状态，如果 busy 则等待最多 50ms（与 CDC 发送逻辑一致）
- 使用互斥锁（`osMutex`）保护 `usart2_tx_buf`，防止多任务并发写入

#### 4.3.3 FreeRTOS 任务（可选）

如果觉得不需要独立任务，也可以不创建。核心逻辑是：
- USART2 RX 数据通过 DMA+IDLE 中断 → 帧解析 → 入队 `bridge_cmd_queue`
- 出队和派发由已有 `Bridge_Task` 完成
- 发送回复时由各总线回调直接调用 `WiFi_Bridge_Send()`

如果需要独立任务（例如处理 ESP32 心跳检测等），可创建：
```c
static const osThreadAttr_t wifi_task_attrs = {
    .name       = "wifiBridgeTask",
    .stack_size = 256U * 4U,
    .priority   = (osPriority_t)osPriorityNormal,
};
```

### 4.4 修改现有文件清单

#### 4.4.1 `app/Src/usb_app.c` — 主要修改

1. **`#include "wifi_bridge.h"`**

2. **`Bridge_Init()` 末尾添加**：
   ```c
   WiFi_Bridge_Init();
   ```

3. **`Bridge_SendToCDC()` → 重命名或新增广播函数**：  
   所有之前调用 `Bridge_SendToCDC()` 的地方，需要同时发送到 WiFi。  
   **方案 A**（推荐）：在 `Bridge_SendToCDC()` 内部末尾追加 `WiFi_Bridge_Send()` 调用：
   ```c
   void Bridge_SendToCDC(uint8_t ch, const uint8_t *data, uint16_t len)
   {
       /* ... 原有 CDC 发送逻辑保持不变 ... */
       
       /* 同时转发到 WiFi 通道 */
       WiFi_Bridge_Send(ch, data, len);
   }
   ```
   **方案 B**：新建 `Bridge_Broadcast()` 函数，逐一替换所有调用点。  
   **选用方案 A**，改动最小。

4. **`HAL_UARTEx_RxEventCallback()` 增加 USART2 分支**：
   ```c
   else if (huart->Instance == USART2)
   {
       WiFi_Bridge_RxHandler(usart2_rx_buf_ptr, Size);
       /* Re-arm */
       HAL_UARTEx_ReceiveToIdle_DMA(&huart2, usart2_rx_buf_ptr, WIFI_RX_BUF_SIZE);
       __HAL_DMA_DISABLE_IT(huart2.hdmarx, DMA_IT_HT);
   }
   ```
   其中 `usart2_rx_buf_ptr` 通过 `wifi_bridge.c` 导出的 getter 函数获取。

5. **`Bridge_Task()` 中 bus→PC 的回复发送**：  
   由于采用方案 A（在 `Bridge_SendToCDC` 内部追加），`Bridge_Task` 不需要修改。

#### 4.4.2 `Core/Src/usart.c` — USART2 波特率

在 `MX_USART2_UART_Init()` 中：
```c
huart2.Init.BaudRate = 921600;  // 原为 115200，改为 921600
```

> 或者在 `WiFi_Bridge_Init()` 中动态 DeInit + 重新 Init 并设置 921600。  
> 推荐在 CubeMX 生成代码中直接改，或在 `WiFi_Bridge_Init()` 中覆盖。

#### 4.4.3 `Core/Src/stm32f4xx_it.c` — 确认中断已使能

确认 `USART2_IRQHandler` 和 `DMA1_Stream5_IRQHandler`（RX）、`DMA1_Stream6_IRQHandler`（TX）已在中断向量表中启用。  
如果 CubeMX 生成时已配置 DMA，则应该已存在。

#### 4.4.4 `CMakeLists.txt` — 添加新源文件

在源文件列表中添加：
```cmake
app/Src/wifi_bridge.c
```

---

## 5. ESP32 控制引脚逻辑

### 5.1 复位 ESP32

```c
void WiFi_ESP_Reset(void)
{
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_RESET);  // PC2 拉低
    osDelay(100);  // 保持 100ms
    HAL_GPIO_WritePin(ESP_EN_GPIO_Port, ESP_EN_Pin, GPIO_PIN_SET);    // PC2 拉高
    osDelay(500);  // 等待 ESP32 启动
}
```

### 5.2 进入下载模式

```c
void WiFi_ESP_EnterBootloader(void)
{
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_RESET);  // PC1 BOOT 拉低
    osDelay(50);
    WiFi_ESP_Reset();  // 复位
    osDelay(50);
    HAL_GPIO_WritePin(ESP_BOOT_GPIO_Port, ESP_BOOT_Pin, GPIO_PIN_SET);    // 释放 BOOT
}
```

---

## 6. 数据流图

```
                    ┌──────────────────────────────┐
                    │          PC 上位机            │
                    │  (USB CDC)      (WiFi TCP)   │
                    └────┬──────────────┬──────────┘
                         │              │
                    USB CDC         TCP:5000
                         │              │
                    ┌────┴───┐    ┌─────┴─────┐
                    │  MCU   │    │   ESP32    │
                    │ USB端点 │    │ TCP↔UART  │
                    └────┬───┘    └─────┬─────┘
                         │         UART0 (921600)
                         │              │
                         │         USART2 (921600)
                         │              │
                    ┌────┴──────────────┴──────┐
                    │     Bridge 协议解析器      │
                    │     bridge_cmd_queue       │
                    └────────────┬──────────────┘
                                 │
              ┌──────┬───────┬───┴───┬───────┬───────┐
              │      │       │       │       │       │
           USART1  RS485   RS422    SPI    I2C     CAN
```

---

## 7. 错误处理

1. **USART2 DMA 错误**：在 `HAL_UART_ErrorCallback` 中检测 `huart->Instance == USART2`，执行 DeInit + ReInit + 重新启动 DMA 接收
2. **帧解析超时**：帧状态机如果在 PS_DATA 状态超过 200ms 没收到新字节，自动复位到 PS_SOF0
3. **队列满**：`osMessageQueuePut` 返回非 osOK 时丢弃当前帧（与 CDC 行为一致）
4. **ESP32 无响应**：可选实现心跳检测，定期通过 USART2 发送 PING，超时 3 秒未收到回复则标记 WiFi 离线

---

## 8. 编译和构建

```bash
# 使用现有构建系统
# CMake Debug 构建
cmake -S . -B build/Debug -DCMAKE_BUILD_TYPE=Debug -G Ninja
cmake --build build/Debug --parallel
```

确保 `CMakeLists.txt` 中包含 `app/Src/wifi_bridge.c`。

---

## 9. 测试要求

| 测试项 | 验证标准 |
|--------|---------|
| USART2 基本通信 | MCU 发送已知数据，ESP32 通过串口监视器可看到正确内容 |
| WiFi 帧解析 | 从 ESP32 侧发送合法 Bridge 帧，MCU 正确解析并派发到目标总线 |
| CDC + WiFi 并行 | 同时通过 USB CDC 和 WiFi 发送命令，两个通道均能正确响应 |
| 总线回复双发 | 总线接收的数据同时通过 CDC 和 WiFi 两个通道返回给 PC |
| 电池上报 | 电池状态通过 CDC 和 WiFi 两个通道同时上报 |
| ESP32 复位 | 调用 `WiFi_ESP_Reset()` 后 ESP32 正常重启 |
| 错误恢复 | 拔掉 ESP32 后 MCU 不死机，重新插入后自动恢复通信 |

---

## 10. 开发完成后

请在项目根目录创建 **`WiFi_Bridge_MCU_开发汇总.md`**，记录：
1. 实际新增/修改的文件清单
2. 关键实现决策和取舍说明
3. 已知限制和待优化项
4. 测试结果记录
5. USART2 实际使用的 DMA stream 和中断配置确认
