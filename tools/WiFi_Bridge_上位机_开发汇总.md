# WiFi Bridge 上位机开发汇总

## 1. 新增/修改文件清单

- 新增: `tools/ehub_wifi_debug.py`
- 新增: `tools/WiFi_Bridge_上位机_开发汇总.md`
- 修改: `tools/requirements.txt`
- 保留: `tools/ehub_debug.py`（原始 USB 版本未改动）

## 2. 与原 ehub_debug.py 的主要差异

- 新增传输抽象层 `Transport`，并实现 `SerialTransport` 与 `TCPTransport`
- 新增连接管理 `ConnectionManager`，支持 USB/WiFi 双模式连接
- 协议通道新增 `WIFI_CTRL (0xE0)` 并实现子命令解析
- GUI 顶部新增连接模式切换（USB CDC / WiFi TCP）
- 新增 WiFi 地址与端口输入、mDNS 扫描、WiFi 配置与 ESP32 重启按钮
- 新增 WiFi 状态显示（模式/IP/RSSI）
- 新增 WiFi 心跳机制（3 秒发送，10 秒超时断开）
- 保留原有 6 总线收发、CONFIG 下发、电池状态显示逻辑

## 3. 代码架构说明

- 协议层：
  - `build_frame / build_config_frame / build_ping_frame`
  - `FrameParser` 负责流式回复帧解析
- 传输层：
  - `Transport` 抽象接口
  - `SerialTransport`（USB CDC）
  - `TCPTransport`（WiFi TCP:5000）
- 连接层：
  - `ConnectionManager` 统一管理连接状态、读写线程、字节计数
- 发现层：
  - `EHUBDiscovery` 使用 mDNS 服务 `_ehub._tcp.local.` 扫描设备
- UI 层：
  - `EHUBApp` 统一管理连接、配置、收发、日志与状态栏刷新

## 4. 新增依赖及安装说明

```bash
pip install -r requirements.txt
```

新增依赖：

- `zeroconf>=0.131.0`（用于局域网 mDNS 自动发现）

## 5. 使用说明

### USB 模式

1. 选择 `USB CDC`
2. 点击 `🔍 自动检测` 或手动选择串口
3. 点击 `连接`
4. 连接成功后可在 USART/RS485/RS422/SPI/I2C/CAN 面板收发

### WiFi 模式

1. 选择 `WiFi TCP`
2. 输入地址（如 `ehub.local` 或设备 IP）和端口（默认 `5000`）
3. 可先点击 `扫描` 进行 mDNS 发现
4. 点击 `连接`
5. 连接后可查看 WiFi 状态，并可通过 `配置WiFi` 下发 SSID/密码

## 6. 已知限制和待优化项

- WiFi 扫描（mDNS）为短时阻塞式调用，可进一步改为后台线程
- WiFi 配置对话框当前为轻量实现，未展示加密类型等附加字段
- 心跳超时后执行断开提示，未做自动重连策略

## 7. 与 MCU/ESP32 联调注意事项

- TCP 端口固定为 `5000`
- 所有业务帧均使用统一 Bridge 协议：
  - `CMD: [AA 55 CH LEN_H LEN_L DATA CRC]`
  - `RPY: [BB 55 CH LEN_H LEN_L DATA CRC]`
- `PING` 使用 `CH=0xF0, payload=[F0 00 00 00 00 00]`
- WiFi 控制使用 `CH=0xE0`，已支持：
  - `0x01 WIFI_STATUS`
  - `0x02 WIFI_CONFIG`
  - `0x03 ESP_RESET`
  - `0x05 WIFI_SCAN`
  - `0x10 HEARTBEAT`

## 8. 截图

- 暂未附加截图，可在本地运行 `ehub_wifi_debug.py` 后截取连接区与 WiFi 状态区界面。
