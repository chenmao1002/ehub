# EHUB WiFi↔Bus Bridge — 上位机开发需求文档

> **版本**: 1.0  
> **日期**: 2026-03-02  
> **范围**: PC 上位机调试工具 — 新增 WiFi 局域网调试功能  
> **语言**: Python 3.x + customtkinter + pyserial  
> **关联文档**: `WiFi_Bridge_MCU_开发需求文档.md` (项目根目录), `ESP32_wifi/WiFi_Bridge_ESP32_开发需求文档.md`  
> **完成后**: 在本目录创建 `WiFi_Bridge_上位机_开发汇总.md`

---

## 1. 项目背景

EHUB 已有一个基于 USB CDC 串口的上位机调试工具 `ehub_debug.py`（v1.1），支持 USART/RS485/RS422/SPI/I2C/CAN 6 种总线的收发调试和电池状态显示。

本次需求：**在现有工具基础上新增 WiFi 连接模式**，使上位机可以通过 WiFi 局域网 TCP 连接到 EHUB 设备，完成与 USB CDC 完全相同的调试功能。用户可在 USB 和 WiFi 两种连接方式之间自由切换。

**数据流**:
```
USB 模式:   上位机  ←── 串口 (CDC) ──→  MCU (STM32F407)  ←──→  总线设备
WiFi 模式:  上位机  ←── TCP:5000 ──→  ESP32  ←── UART ──→  MCU  ←──→  总线设备
```

两种模式使用 **完全相同的 Bridge 帧协议**，仅底层传输不同。

---

## 2. 现有代码分析

### 2.1 现有文件

| 文件 | 说明 |
|------|------|
| `tools/ehub_debug.py` | 主程序 v1.1，978 行，基于 customtkinter GUI |
| `tools/requirements.txt` | 依赖: `customtkinter>=5.2.0`, `pyserial>=3.5` |
| `tools/_ping_test.py` | 简单 PING 测试脚本 |

### 2.2 现有架构特点

- 设备连接通过 `pyserial` 的串口
- 自动发现: USB VID/PID (`0x0D28:0x0204`) 定位 COM 口，失败则 PING 帧扫描
- 热插拔检测: 每秒检测设备连接状态
- 协议帧通过串口 `serial.Serial` 收发
- 6 个子面板: USART / RS485 / RS422 / SPI / I2C / CAN
- 电池状态栏
- 运行时配置面板

---

## 3. 通信协议（三端统一，必须严格遵循）

### 3.1 帧格式

```
PC → 设备 (Command):  [0xAA][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]
设备 → PC (Reply):    [0xBB][0x55][CH][LEN_H][LEN_L][DATA × LEN][CRC8]

CRC8 = XOR(CH, LEN_H, LEN_L, DATA[0], DATA[1], ..., DATA[LEN-1])
```

### 3.2 通道 ID

| 通道名 | CH 值 | 说明 |
|--------|-------|------|
| USART1 | 0x01 | USART 原始字节透传 |
| RS485 | 0x02 | RS485 透传 |
| RS422 | 0x03 | RS422 透传 |
| SPI | 0x04 | SPI 全双工 |
| I2C_W | 0x05 | I2C 写 |
| I2C_R | 0x06 | I2C 读 |
| CAN | 0x07 | CAN 数据 |
| BATTERY | 0x08 | 电池状态 (设备→PC) |
| **WIFI_CTRL** | **0xE0** | **WiFi 控制（新增）** |
| CONFIG | 0xF0 | 外设运行时配置 |

### 3.3 WiFi 连接参数

| 参数 | 值 |
|------|----|
| 协议 | **TCP** |
| 端口 | **5000** |
| mDNS 主机名 | **ehub.local** |
| mDNS 服务 | **_ehub._tcp** |

### 3.4 CONFIG 帧 (CH=0xF0) 详情

与现有 `ehub_debug.py` 中的实现完全一致：

| iface | param | value | 说明 |
|-------|-------|-------|------|
| 0x01 | 0x01 BAUD | uint32 BE | USART1 波特率 |
| 0x02 | 0x01 BAUD | uint32 BE | RS485 波特率 |
| 0x03 | 0x01 BAUD | uint32 BE | RS422 波特率 |
| 0x04 | 0x02 SPI_SPD | 0~7 | SPI 预分频 |
| 0x04 | 0x03 SPI_MODE | 0~3 | SPI 模式 |
| 0x04 | 0x06 SPI_ROLE | 0/1 | SPI Master/Slave |
| 0x05/0x06 | 0x04 I2C_SPD | 100000/400000 | I2C 速度 |
| 0x05/0x06 | 0x07 I2C_ROLE | 0/1 | I2C Master/Slave |
| 0x05/0x06 | 0x08 I2C_OWN | 0x08~0x77 | I2C 从机地址 |
| 0x07 | 0x05 CAN_BAUD | 125k/250k/500k/1M | CAN 波特率 |

**PING**: `iface=0xF0, param=0x00` → 回复含 `EHUB` 标识

### 3.5 WiFi 控制帧 (CH=0xE0)

| subcmd (data[0]) | 名称 | 方向 | 请求 DATA | 回复 DATA |
|-------------------|------|------|-----------|-----------|
| 0x01 | WIFI_STATUS | CMD→RPY | `[0x01]` | `[0x01][status][rssi_signed][ip0][ip1][ip2][ip3]` |
| 0x02 | WIFI_CONFIG | CMD→RPY | `[0x02][ssid_len][ssid...][pass_len][pass...]` | `[0x02][0x00/0xFF]` |
| 0x03 | ESP_RESET | CMD | `[0x03]` | 无回复 (ESP32 会重启) |
| 0x04 | ESP_BOOT | CMD | `[0x04]` | 无回复 (进入下载模式) |
| 0x05 | WIFI_SCAN | CMD→RPY | `[0x05]` | `[0x05][count][ssid1_len][ssid1...][rssi1]...` |
| 0x10 | HEARTBEAT | 双向 | `[0x10][tick:4B BE]` | 相同格式 |

**status 字段**: 0=未连接, 1=STA已连接, 2=AP模式  
**rssi 字段**: 有符号 int8_t (dBm)

---

## 4. 开发需求

### 4.1 新增文件

| 文件 | 路径 | 说明 |
|------|------|------|
| `ehub_wifi_debug.py` | `tools/ehub_wifi_debug.py` | 新版本，支持 USB + WiFi 双模式 |
| `requirements.txt` | `tools/requirements.txt` | 更新依赖 |

> **策略**: 基于现有 `ehub_debug.py` 开发新版本 `ehub_wifi_debug.py`（保留原文件不动作备份）。新版本在现有所有功能基础上新增 WiFi 连接能力。

### 4.2 新增依赖

```
customtkinter>=5.2.0
pyserial>=3.5
zeroconf>=0.131.0      # mDNS 服务发现
```

> `zeroconf` 用于自动发现局域网中的 EHUB 设备。

### 4.3 传输层抽象

需要实现一个统一的传输层接口，使上层协议代码不关心底层是串口还是 TCP：

```python
class Transport(ABC):
    """传输层抽象基类"""
    @abstractmethod
    def connect(self) -> bool: ...
    
    @abstractmethod
    def disconnect(self) -> None: ...
    
    @abstractmethod
    def is_connected(self) -> bool: ...
    
    @abstractmethod
    def read(self, max_bytes: int = 1024) -> bytes: ...
    
    @abstractmethod
    def write(self, data: bytes) -> None: ...
    
    @abstractmethod
    def get_info(self) -> str: ...


class SerialTransport(Transport):
    """USB CDC 串口传输"""
    def __init__(self, port: str, baudrate: int = 115200):
        self._ser = serial.Serial()
        self._ser.port = port
        self._ser.baudrate = baudrate
        self._ser.timeout = 0.01  # 非阻塞读取
    
    def connect(self) -> bool:
        self._ser.open()
        return self._ser.is_open
    
    def disconnect(self):
        if self._ser.is_open:
            self._ser.close()
    
    def is_connected(self) -> bool:
        return self._ser.is_open
    
    def read(self, max_bytes=1024) -> bytes:
        return self._ser.read(min(max_bytes, self._ser.in_waiting or 1))
    
    def write(self, data: bytes):
        self._ser.write(data)
    
    def get_info(self) -> str:
        return f"USB: {self._ser.port}"


class TCPTransport(Transport):
    """WiFi TCP 传输"""
    def __init__(self, host: str, port: int = 5000):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
    
    def connect(self) -> bool:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(3.0)
        self._sock.connect((self._host, self._port))
        self._sock.settimeout(0.01)  # 非阻塞读取
        return True
    
    def disconnect(self):
        if self._sock:
            self._sock.close()
            self._sock = None
    
    def is_connected(self) -> bool:
        return self._sock is not None
    
    def read(self, max_bytes=1024) -> bytes:
        try:
            return self._sock.recv(max_bytes)
        except (socket.timeout, BlockingIOError):
            return b''
        except (ConnectionError, OSError):
            self._sock = None
            return b''
    
    def write(self, data: bytes):
        if self._sock:
            self._sock.sendall(data)
    
    def get_info(self) -> str:
        return f"WiFi: {self._host}:{self._port}"
```

### 4.4 mDNS 设备发现

```python
from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo
import socket

class EHUBDiscovery:
    """通过 mDNS 发现局域网中的 EHUB 设备"""
    
    def __init__(self):
        self._devices = []  # [(name, host, port, ip), ...]
    
    def scan(self, timeout: float = 3.0) -> list:
        """扫描局域网中的 EHUB 设备，返回设备列表"""
        self._devices = []
        zc = Zeroconf()
        browser = ServiceBrowser(zc, "_ehub._tcp.local.", self)
        time.sleep(timeout)
        zc.close()
        return self._devices.copy()
    
    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            ip = socket.inet_ntoa(info.addresses[0])
            self._devices.append({
                'name': info.server,
                'ip': ip,
                'port': info.port,
                'version': info.properties.get(b'version', b'?').decode(),
            })
    
    def remove_service(self, zc, type_, name):
        pass
    
    def update_service(self, zc, type_, name):
        pass
    
    @staticmethod
    def try_resolve_mdns(hostname: str = "ehub.local") -> str | None:
        """尝试通过 mDNS 解析主机名"""
        try:
            ip = socket.gethostbyname(hostname)
            return ip
        except socket.gaierror:
            return None
```

### 4.5 GUI 修改需求

#### 4.5.1 连接模式选择区域

在工具栏/顶部区域新增：

```
┌─────────────────────────────────────────────────────────────────┐
│  连接模式: [● USB CDC ○ WiFi TCP]                               │
│                                                                   │
│  USB 模式:   端口 [COM3 ▼]  [自动检测]  [连接/断开]            │
│  WiFi 模式:  地址 [ehub.local ▼] : [5000]  [扫描] [连接/断开]  │
│                                                                   │
│  状态: ● 已连接 - USB: COM3 @ 115200                             │
└─────────────────────────────────────────────────────────────────┘
```

| UI 元素 | 类型 | 说明 |
|---------|------|------|
| 连接模式 | RadioButton | "USB CDC" / "WiFi TCP" 二选一 |
| COM 端口 | Combobox | USB 模式下的串口列表 |
| 自动检测 | Button | USB VID/PID 自动发现 |
| WiFi 地址 | Combobox | 输入 IP 或 `ehub.local`，下拉显示扫描到的设备 |
| WiFi 端口 | Entry | 默认 5000 |
| 扫描按钮 | Button | mDNS 扫描局域网设备 |
| 连接/断开 | Button | 建立/断开连接 |
| 状态指示 | Label | 当前连接状态和方式 |

#### 4.5.2 WiFi 状态面板（新增）

在电池状态栏旁边或下方新增 WiFi 状态区域：

```
┌──────────── WiFi 状态 ────────────┐
│  模式: STA (已连接)               │
│  SSID: MyWiFi                     │
│  IP: 192.168.1.100                │
│  RSSI: -45 dBm ████████░░        │
│  [配置WiFi] [扫描] [重启ESP32]   │
└───────────────────────────────────┘
```

- 通过发送 `CH=0xE0, subcmd=0x01` 定期（每 5 秒）查询 WiFi 状态
- 仅在 WiFi 连接模式下显示此面板

#### 4.5.3 WiFi 配置对话框

点击 "配置WiFi" 按钮时弹出模态对话框：

```
┌──────────── WiFi 配置 ────────────┐
│                                    │
│  SSID: [________________] [扫描▼] │
│  密码: [________________] [👁]     │
│                                    │
│  扫描结果:                         │
│  ┌──────────────────────────────┐ │
│  │ MyWiFi       -45 dBm  🔒    │ │
│  │ Office       -60 dBm  🔒    │ │
│  │ Guest        -72 dBm        │ │
│  └──────────────────────────────┘ │
│                                    │
│      [保存并连接]  [取消]          │
└────────────────────────────────────┘
```

- 扫描通过 `CH=0xE0, subcmd=0x05` 获取
- 保存通过 `CH=0xE0, subcmd=0x02` 配置

---

## 5. 核心实现要求

### 5.1 连接管理

```python
class ConnectionManager:
    """管理设备连接（USB 或 WiFi）"""
    
    def __init__(self):
        self._transport: Transport | None = None
        self._mode: str = "usb"  # "usb" | "wifi"
        self._connected: bool = False
    
    def connect_usb(self, port: str) -> bool:
        """通过 USB CDC 连接"""
        self._transport = SerialTransport(port, 115200)
        if self._transport.connect():
            # 发送 PING 验证设备
            if self._ping():
                self._mode = "usb"
                self._connected = True
                return True
        self._transport.disconnect()
        return False
    
    def connect_wifi(self, host: str, port: int = 5000) -> bool:
        """通过 WiFi TCP 连接"""
        self._transport = TCPTransport(host, port)
        if self._transport.connect():
            if self._ping():
                self._mode = "wifi"
                self._connected = True
                return True
        self._transport.disconnect()
        return False
    
    def disconnect(self):
        if self._transport:
            self._transport.disconnect()
        self._connected = False
    
    def send_frame(self, ch: int, data: bytes):
        """发送 Bridge 命令帧"""
        frame = self._build_frame(0xAA, ch, data)
        self._transport.write(frame)
    
    def read_data(self) -> bytes:
        """读取原始数据（由帧解析器处理）"""
        return self._transport.read()
    
    def _ping(self) -> bool:
        """发送 PING 帧，验证设备"""
        self.send_frame(0xF0, bytes([0xF0, 0x00, 0, 0, 0, 0]))
        time.sleep(0.5)
        # 解析回复，检查是否包含 "EHUB"
        data = self.read_data()
        return b'EHUB' in data
    
    @property
    def mode(self) -> str:
        return self._mode
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def info(self) -> str:
        return self._transport.get_info() if self._transport else "未连接"
```

### 5.2 帧收发逻辑

帧构建和解析逻辑与现有 `ehub_debug.py` 完全一致：

```python
# 协议常量（与现有代码一致）
SOF0_CMD, SOF1, SOF0_RPY = 0xAA, 0x55, 0xBB

def build_frame(ch: int, data: bytes) -> bytes:
    """构建命令帧 (PC → 设备)"""
    length = len(data)
    len_h = (length >> 8) & 0xFF
    len_l = length & 0xFF
    crc = ch ^ len_h ^ len_l
    for b in data:
        crc ^= b
    return bytes([SOF0_CMD, SOF1, ch, len_h, len_l]) + data + bytes([crc])

def parse_frames(raw: bytes, parser_state: dict) -> list:
    """
    流式帧解析器
    parser_state 维护解析状态（跨多次调用）
    返回解析出的完整帧列表: [(ch, data), ...]
    """
    frames = []
    # ... 状态机解析，与 MCU 侧一致 ...
    return frames
```

### 5.3 接收线程

```python
class ReceiverThread(threading.Thread):
    """后台接收线程 — 从传输层读取数据，解析帧，分发到回调"""
    
    def __init__(self, connection: ConnectionManager):
        super().__init__(daemon=True)
        self._conn = connection
        self._running = False
        self._callbacks = {}  # ch -> callback_function
        self._parser_state = {}  # 帧解析状态
    
    def register_callback(self, ch: int, callback):
        """注册通道数据回调"""
        self._callbacks[ch] = callback
    
    def run(self):
        self._running = True
        while self._running:
            if not self._conn.is_connected:
                time.sleep(0.1)
                continue
            try:
                raw = self._conn.read_data()
                if raw:
                    frames = parse_frames(raw, self._parser_state)
                    for ch, data in frames:
                        if ch in self._callbacks:
                            self._callbacks[ch](data)
            except Exception:
                time.sleep(0.1)
    
    def stop(self):
        self._running = False
```

### 5.4 热插拔与自动重连

| 模式 | 检测方式 | 行为 |
|------|---------|------|
| USB | 每秒检查 COM 口是否存在 (与现有逻辑一致) | 断开时自动重连 |
| WiFi | 每 3 秒发送心跳帧 (CH=0xE0, subcmd=0x10) | 超时 10 秒无回复则断开 |

```python
def _wifi_heartbeat_check(self):
    """WiFi 模式下的心跳检测"""
    if self._mode != "wifi" or not self._connected:
        return
    
    tick = int(time.time()) & 0xFFFFFFFF
    data = bytes([0x10, (tick >> 24) & 0xFF, (tick >> 16) & 0xFF,
                  (tick >> 8) & 0xFF, tick & 0xFF])
    self.send_frame(0xE0, data)
    
    # 检查上次收到心跳回复的时间
    if time.time() - self._last_heartbeat_reply > 10.0:
        self.disconnect()
        self._on_wifi_disconnected()
```

---

## 6. 电池状态处理

与现有逻辑完全一致：

```python
# CH=0x08 BATTERY 帧接收回调
def on_battery_data(data: bytes):
    if len(data) >= 4:
        voltage_mv = (data[0] << 8) | data[1]  # 分压后 mV (2000~2900)
        percent = data[2]                        # 0~100%
        charging = data[3]                       # 0/1
        
        # 映射实际电压: 2000mV → 8.4V, 2900mV → 12.6V
        actual_v = 8.4 + (voltage_mv - 2000) / (2900 - 2000) * (12.6 - 8.4)
        
        # 更新 GUI
        update_battery_display(percent, actual_v, charging)
```

---

## 7. WiFi 状态面板实现

### 7.1 定期查询

```python
def _poll_wifi_status(self):
    """每 5 秒查询一次 WiFi 状态"""
    if self._mode == "wifi" and self._connected:
        self.send_frame(0xE0, bytes([0x01]))
    self.after(5000, self._poll_wifi_status)
```

### 7.2 WiFi 状态回调

```python
def on_wifi_ctrl_data(data: bytes):
    if len(data) < 1:
        return
    subcmd = data[0]
    
    if subcmd == 0x01 and len(data) >= 7:  # WIFI_STATUS
        status = data[1]   # 0=断开, 1=STA, 2=AP
        rssi = data[2] if data[2] < 128 else data[2] - 256  # signed
        ip = f"{data[3]}.{data[4]}.{data[5]}.{data[6]}"
        update_wifi_status_panel(status, rssi, ip)
    
    elif subcmd == 0x02:  # WIFI_CONFIG 回复
        ok = (data[1] == 0x00) if len(data) >= 2 else False
        show_config_result(ok)
    
    elif subcmd == 0x05 and len(data) >= 2:  # WIFI_SCAN 回复
        count = data[1]
        networks = []
        pos = 2
        for _ in range(count):
            if pos >= len(data): break
            ssid_len = data[pos]; pos += 1
            ssid = data[pos:pos+ssid_len].decode('utf-8', errors='replace'); pos += ssid_len
            rssi = data[pos] if data[pos] < 128 else data[pos] - 256; pos += 1
            networks.append((ssid, rssi))
        update_scan_results(networks)
    
    elif subcmd == 0x10:  # HEARTBEAT 回复
        self._last_heartbeat_reply = time.time()
```

---

## 8. GUI 布局要求

### 8.1 整体布局

```
┌── EHUB 调试工具 v2.0 ──────────────────────────────────────────────┐
│                                                                      │
│ ┌── 连接区 ──────────────────────────────────────────────────────┐  │
│ │ 模式: [● USB ○ WiFi]  [COM3/192.168.1.100:5000]  [连接] [断开] │  │
│ │ 状态: ● 已连接 via WiFi (192.168.1.100:5000)                   │  │
│ └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│ ┌── 电池 ────┐ ┌── WiFi 状态 ────────────┐                         │
│ │ ████ 85%   │ │ STA 已连接 | -45dBm     │                         │
│ │ 11.2V 充电中│ │ 192.168.1.100           │                         │
│ └────────────┘ │ [配置] [扫描] [重启ESP] │                         │
│                 └─────────────────────────┘                         │
│                                                                      │
│ ┌─ USART ─┐ ┌─ RS485 ─┐ ┌─ RS422 ─┐ ┌─ SPI ──┐ ┌─ I2C ──┐ ┌─ CAN ─┐ │
│ │         │ │         │ │         │ │        │ │        │ │       │ │
│ │ (与现有  │ │ (与现有  │ │ (与现有  │ │(与现有 │ │(与现有 │ │(与现有│ │
│ │  面板    │ │  面板    │ │  面板    │ │ 面板   │ │ 面板   │ │ 面板  │ │
│ │  完全    │ │  完全    │ │  完全    │ │ 完全   │ │ 完全   │ │ 完全  │ │
│ │  一致)   │ │  一致)   │ │  一致)   │ │ 一致)  │ │ 一致)  │ │ 一致) │ │
│ └─────────┘ └─────────┘ └─────────┘ └────────┘ └────────┘ └───────┘ │
│                                                                      │
│ ┌── 收发日志 ───────────────────────────────────────────────────┐   │
│ │ [时间] [CH] [方向] [数据]                                      │   │
│ │ ...                                                             │   │
│ └─────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.2 主题和风格

- 保持现有暗色主题 (`ctk.set_appearance_mode("dark")`)
- 蓝色色彩方案 (`ctk.set_default_color_theme("blue")`)
- WiFi 状态面板使用绿色/黄色/红色指示连接状态

---

## 9. 代码结构建议

```python
# ehub_wifi_debug.py 建议结构

"""
EHUB 调试工具 v2.0
支持 USB CDC 和 WiFi 双模式连接
"""

# ─── 导入 ──────────────────
import customtkinter as ctk
import serial
import socket
import threading
import struct
import time
from datetime import datetime
from zeroconf import ServiceBrowser, Zeroconf

# ─── 协议常量 ──────────────
SOF0_CMD = 0xAA
SOF1 = 0x55  
SOF0_RPY = 0xBB
CH = { ... }     # 与现有一致，新增 "WIFI_CTRL": 0xE0
CFG = { ... }    # 与现有一致

# ─── Transport 类 ──────────
class Transport(ABC): ...
class SerialTransport(Transport): ...
class TCPTransport(Transport): ...

# ─── 设备发现 ──────────────
class EHUBDiscovery: ...

# ─── 帧协议 ────────────────
def build_frame(ch, data): ...
def parse_frames(raw, state): ...

# ─── 连接管理 ──────────────
class ConnectionManager: ...

# ─── 接收线程 ──────────────
class ReceiverThread: ...

# ─── GUI 面板 ──────────────
class ConnectionPanel(ctk.CTkFrame): ...      # 连接模式选择
class WiFiStatusPanel(ctk.CTkFrame): ...      # WiFi 状态显示
class WiFiConfigDialog(ctk.CTkToplevel): ...  # WiFi 配置对话框
class BatteryPanel(ctk.CTkFrame): ...         # 电池状态
class BusPanel(ctk.CTkFrame): ...             # 各总线面板基类
class USARTPanel(BusPanel): ...
class RS485Panel(BusPanel): ...
class RS422Panel(BusPanel): ...
class SPIPanel(BusPanel): ...
class I2CPanel(BusPanel): ...
class CANPanel(BusPanel): ...
class LogPanel(ctk.CTkFrame): ...             # 收发日志

# ─── 主应用 ────────────────
class EHUBApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EHUB 调试工具 v2.0")
        self.geometry("1200x800")
        
        self.conn_mgr = ConnectionManager()
        self.receiver = ReceiverThread(self.conn_mgr)
        
        # 创建 GUI 面板
        self.conn_panel = ConnectionPanel(self)
        self.battery_panel = BatteryPanel(self)
        self.wifi_panel = WiFiStatusPanel(self)
        # ... 各总线面板 ...
        self.log_panel = LogPanel(self)
        
        # 注册回调
        self.receiver.register_callback(0x08, self.on_battery)
        self.receiver.register_callback(0xE0, self.on_wifi_ctrl)
        # ... 其他通道回调 ...
        
        self.receiver.start()

if __name__ == "__main__":
    app = EHUBApp()
    app.mainloop()
```

---

## 10. 测试需求

### 10.1 USB 模式（回归测试）
- [ ] 所有现有 USB 功能正常工作
- [ ] USB 设备自动发现
- [ ] 热插拔检测和自动重连
- [ ] 6 个总线面板收发正确
- [ ] 电池状态显示正常
- [ ] 运行时配置（波特率/速度/模式修改）

### 10.2 WiFi 模式
- [ ] mDNS 设备发现 (`ehub.local`)
- [ ] 手动 IP 连接
- [ ] TCP 连接建立和 PING 验证
- [ ] 所有 6 个总线通道收发正确
- [ ] 电池状态通过 WiFi 接收正常
- [ ] WiFi 状态面板显示正确（模式/RSSI/IP）
- [ ] WiFi 配置功能（扫描/设置SSID）
- [ ] 运行时配置通过 WiFi 下发
- [ ] 心跳检测和自动断开
- [ ] WiFi 断开后 GUI 状态正确更新

### 10.3 模式切换
- [ ] USB → WiFi 切换正常
- [ ] WiFi → USB 切换正常
- [ ] 切换后所有面板状态正确

### 10.4 异常情况
- [ ] WiFi 网络中断后 GUI 不卡死
- [ ] ESP32 掉电后自动断开并提示
- [ ] 无 EHUB 设备时扫描超时合理
- [ ] 大量数据发送时不阻塞 GUI

---

## 11. requirements.txt 更新

```
customtkinter>=5.2.0
pyserial>=3.5
zeroconf>=0.131.0
```

---

## 12. 汇总文档要求

开发完成后，请在 `tools/` 目录下创建 `WiFi_Bridge_上位机_开发汇总.md`，包含：

1. **新增/修改的文件清单**
2. **与原 ehub_debug.py 的主要差异**
3. **代码架构说明**（类图或模块关系）
4. **新增依赖及安装说明**
5. **使用说明**（USB 模式和 WiFi 模式的操作步骤）
6. **已知限制和待优化项**
7. **与 MCU/ESP32 的联调注意事项**
8. **截图**（如果方便的话）
