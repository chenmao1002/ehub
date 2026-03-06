"""
EHUB 调试工具  v2.0
上位机 — USB CDC / WiFi TCP 双模式桥接调试器
依赖: pip install customtkinter pyserial zeroconf
"""

import customtkinter as ctk
import serial
import serial.tools.list_ports
import threading
import struct
import time
import queue
import socket
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime

try:
    from zeroconf import ServiceBrowser, Zeroconf
except Exception:
    ServiceBrowser = None
    Zeroconf = None

# ─── 主题设置 ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ─── 协议常量 ─────────────────────────────────────────────────────────────────
SOF0_CMD, SOF1, SOF0_RPY = 0xAA, 0x55, 0xBB
CH = {
    "USART":   0x01,
    "RS485":   0x02,
    "RS422":   0x03,
    "SPI":     0x04,
    "I2C_W":   0x05,
    "I2C_R":   0x06,
    "CAN":     0x07,
    "BATTERY": 0x08,
    "DAP":     0xD0,
    "WIFI_CTRL": 0xE0,
    "CONFIG":  0xF0,
}
CH_NAME = {v: k for k, v in CH.items()}

CFG_PING     = 0x00   # 设备识别 PING（iface=0xF0 param=0x00）
CFG_BAUD     = 0x01
CFG_SPI_SPD  = 0x02
CFG_SPI_MODE = 0x03
CFG_I2C_SPD  = 0x04
CFG_CAN_BAUD = 0x05
CFG_SPI_ROLE = 0x06
CFG_I2C_ROLE = 0x07
CFG_I2C_OWN  = 0x08

PROBE_BAUD   = 115200
PROBE_MAGIC  = b'EHUB'  # 设备 PING 回复中必须包含的标识

# EHUB 设备 USB 标识（VID=0x0D28 ARM Ltd / PID=0x0204 CMSIS-DAP 复合设备）
EHUB_VID = 0x0D28
EHUB_PID = 0x0204


def find_ehub_port() -> str | None:
    """通过 USB VID/PID 直接定位 EHUB 设备的 COM 口，不依赖固件应答。"""
    for p in serial.tools.list_ports.comports():
        if p.vid == EHUB_VID and p.pid == EHUB_PID:
            return p.device
    return None

SPI_SPEED_LABELS = [
    "42 MHz  (÷2)",
    "21 MHz  (÷4)",
    "10.5 MHz (÷8)",
    "5.25 MHz (÷16)",
    "2.63 MHz (÷32)",
    "1.31 MHz (÷64)",
    "656 kHz  (÷128)",
    "328 kHz  (÷256)",
]
CAN_BAUD_MAP = {
    "1 Mbps (1000 kbps)":  1000000,
    "500 kbps":            500000,
    "250 kbps":            250000,
    "125 kbps":            125000,
}
I2C_SPEED_MAP = {
    "100 kHz（标准模式）": 100000,
    "400 kHz（快速模式）": 400000,
}
SPI_ROLE_MAP = {
    "主机模式（Master）": 0,
    "从机模式（Slave）": 1,
}
I2C_ROLE_MAP = {
    "主机模式（Master）": 0,
    "从机模式（Slave）": 1,
}

# ─── 设备探测（自动连接用） ────────────────────────────────────────────────────
def probe_port(portname: str, baud: int = PROBE_BAUD, timeout: float = 1.2) -> bool:
    """向指定串口发送 PING 帧，收到含 'EHUB' 的回复则判定为目标设备（可选验证）。"""
    try:
        with serial.Serial(portname, baud,
                           timeout=0.1,
                           write_timeout=1.0,
                           dsrdtr=False,
                           rtscts=False) as s:
            time.sleep(0.12)
            s.reset_input_buffer()
            ping = build_frame(CH["CONFIG"], bytes([0xF0, CFG_PING, 0, 0, 0, 0]))
            s.write(ping)
            s.flush()
            deadline = time.time() + timeout
            buf = bytearray()
            while time.time() < deadline:
                chunk = s.read(128)
                if chunk:
                    buf.extend(chunk)
                    if b'\xBB\x55\xF0' in buf and PROBE_MAGIC in buf:
                        return True
                else:
                    time.sleep(0.02)
            return False
    except Exception:
        return False

# ─── 协议编解码 ───────────────────────────────────────────────────────────────
def _crc8(ch_byte, data: bytes) -> int:
    crc = ch_byte
    hi  = (len(data) >> 8) & 0xFF
    lo  = len(data) & 0xFF
    crc ^= hi ^ lo
    for b in data:
        crc ^= b
    return crc & 0xFF

def build_frame(ch: int, data: bytes) -> bytes:
    """构建 PC→设备 命令帧"""
    length = len(data)
    header = bytes([SOF0_CMD, SOF1, ch, (length >> 8) & 0xFF, length & 0xFF])
    crc    = _crc8(ch, data)
    return header + data + bytes([crc])

def build_config_frame(iface: int, param: int, value: int) -> bytes:
    """构建 CONFIG 帧 (6字节 payload)"""
    payload = bytes([iface, param]) + struct.pack(">I", value)
    return build_frame(CH["CONFIG"], payload)

def build_ping_frame() -> bytes:
    """构建设备识别 PING 帧"""
    return build_frame(CH["CONFIG"], bytes([0xF0, CFG_PING, 0, 0, 0, 0]))

class FrameParser:
    """状态机解析设备→PC 回复帧"""
    _PS_SOF0, _PS_SOF1, _PS_CH, _PS_LEN_H, _PS_LEN_L, _PS_DATA, _PS_CRC = range(7)

    def __init__(self, cb):
        self._cb  = cb   # callback(ch, data)
        self._state = self._PS_SOF0
        self._ch    = 0
        self._len   = 0
        self._idx   = 0
        self._buf   = bytearray()
        self._crc   = 0

    def feed(self, raw: bytes):
        for b in raw:
            s = self._state
            if s == self._PS_SOF0:
                if b == SOF0_RPY: self._state = self._PS_SOF1
            elif s == self._PS_SOF1:
                self._state = self._PS_CH if b == SOF1 else self._PS_SOF0
            elif s == self._PS_CH:
                self._ch    = b
                self._crc   = b
                self._state = self._PS_LEN_H
            elif s == self._PS_LEN_H:
                self._len  = b << 8
                self._crc ^= b
                self._state = self._PS_LEN_L
            elif s == self._PS_LEN_L:
                self._len |= b
                self._crc ^= b
                self._buf  = bytearray()
                self._idx  = 0
                self._state = self._PS_DATA if 0 < self._len <= 256 else self._PS_SOF0
            elif s == self._PS_DATA:
                self._buf.append(b)
                self._crc ^= b
                self._idx += 1
                if self._idx >= self._len:
                    self._state = self._PS_CRC
            elif s == self._PS_CRC:
                if b == self._crc:
                    self._cb(self._ch, bytes(self._buf))
                self._state = self._PS_SOF0

# ─── 串口管理 ─────────────────────────────────────────────────────────────────
class Transport(ABC):
    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def read(self, max_bytes: int = 1024) -> bytes:
        ...

    @abstractmethod
    def write(self, data: bytes) -> None:
        ...

    @abstractmethod
    def get_info(self) -> str:
        ...


class SerialTransport(Transport):
    def __init__(self, port: str, baudrate: int = 115200):
        self._ser = serial.Serial()
        self._ser.port = port
        self._ser.baudrate = baudrate
        self._ser.timeout = 0.01

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
    def __init__(self, host: str, port: int = 5000):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None

    def connect(self) -> bool:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(3.0)
        self._sock.connect((self._host, self._port))
        self._sock.settimeout(0.01)
        return True

    def disconnect(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def is_connected(self) -> bool:
        return self._sock is not None

    def read(self, max_bytes=1024) -> bytes:
        if not self._sock:
            return b""
        try:
            return self._sock.recv(max_bytes)
        except (socket.timeout, BlockingIOError):
            return b""
        except (ConnectionError, OSError):
            self._sock = None
            return b""

    def write(self, data: bytes):
        if self._sock:
            self._sock.sendall(data)

    def get_info(self) -> str:
        return f"WiFi: {self._host}:{self._port}"


class EHUBDiscovery:
    def __init__(self):
        self._devices = []

    def scan(self, timeout: float = 2.5) -> list:
        self._devices = []
        if ServiceBrowser is None or Zeroconf is None:
            return []
        zc = Zeroconf()
        try:
            ServiceBrowser(zc, "_ehub._tcp.local.", self)
            time.sleep(timeout)
            return self._devices.copy()
        finally:
            zc.close()

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if not info or not info.addresses:
            return
        ip = socket.inet_ntoa(info.addresses[0])
        self._devices.append({
            "name": info.server or name,
            "ip": ip,
            "port": info.port,
            "display": f"{ip}:{info.port}",
        })

    def remove_service(self, zc, type_, name):
        return

    def update_service(self, zc, type_, name):
        return

    @staticmethod
    def try_resolve_mdns(hostname: str = "ehub.local") -> str | None:
        try:
            return socket.gethostbyname(hostname)
        except socket.gaierror:
            return None


class ConnectionManager:
    def __init__(self, on_frame, on_error):
        self._on_frame = on_frame
        self._on_error  = on_error
        self._transport: Transport | None = None
        self._mode = "usb"
        self._info = ""
        self._parser = FrameParser(on_frame)
        self._thread: threading.Thread | None = None
        self._alive  = False
        self.tx_count = 0
        self.rx_count = 0

    @property
    def connected(self):
        return self._alive and self._transport is not None and self._transport.is_connected()

    @property
    def mode(self):
        return self._mode

    @property
    def info(self):
        return self._info

    def connect(self, portname: str, baud: int):
        self.connect_usb(portname, baud)

    def connect_usb(self, portname: str, baud: int = 115200):
        self.disconnect()
        self._transport = SerialTransport(portname, baud)
        self._transport.connect()
        self._mode = "usb"
        self._info = self._transport.get_info()
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def connect_wifi(self, host: str, port: int = 5000):
        self.disconnect()
        self._transport = TCPTransport(host, port)
        self._transport.connect()
        self._mode = "wifi"
        self._info = self._transport.get_info()
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._alive = False
        if self._transport:
            self._transport.disconnect()
        self._transport = None
        self._info = ""

    def send(self, data: bytes):
        if not self.connected: return
        self._transport.write(data)
        self.tx_count += len(data)

    def send_silent(self, data: bytes):
        """发送数据但不计入 tx 统计（用于后台心跳/状态查询）"""
        if not self.connected: return
        self._transport.write(data)

    def _run(self):
        _REMOVE_SIGNS = (
            "ClearCommError", "PermissionError(13", "PermissionError(5",
            "handle is invalid", "access is denied",
            "\u8bbe\u5907\u4e0d\u8bc6\u522b", "\u6ca1\u6709\u8fde\u63a5", "\u62d2\u7edd\u8bbf\u95ee",
        )
        while self._alive:
            try:
                chunk = self._transport.read(256) if self._transport else b""
                if chunk:
                    self.rx_count += len(chunk)
                    self._parser.feed(chunk)
            except Exception as e:
                self._alive = False
                msg = str(e)
                is_removal = any(k.lower() in msg.lower() for k in _REMOVE_SIGNS)
                self._on_error("__REMOVED__" if is_removal else msg)
                break


SerialManager = ConnectionManager

# ─── EHUBLink 安装辅助 ────────────────────────────────────────────────────────
def _find_keil_path() -> str:
    """尝试自动找到 Keil MDK 安装根目录（含 UV4/UV4.exe）"""
    # 1. 读取注册表
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\Keil\Products\MDK")
        path_val, _ = winreg.QueryValueEx(key, "Path")
        winreg.CloseKey(key)
        # Path 一般指向 ARM\ 子目录，取其父目录即 Keil 根
        candidate = os.path.dirname(path_val.rstrip("\\/"))
        if os.path.exists(os.path.join(candidate, "UV4", "UV4.exe")):
            return candidate
    except Exception:
        pass
    # 2. 尝试常见盘符/目录名
    for drive in ("C", "D", "E", "F"):
        for name in ("Keil_v5", "Keil", "keil_v5", "keil"):
            p = f"{drive}:\\{name}"
            if os.path.exists(os.path.join(p, "UV4", "UV4.exe")):
                return p
    return ""


def _do_install_ehublink(keil_path: str, dll_src: str,
                         dap_host: str, dap_port: int):
    """将 EHUBLink.dll 安装为 elaphureRddi.dll 并写入调试配置。
    返回 (success: bool, message: str)。
    """
    uv4_dir = os.path.join(keil_path, "UV4")
    if not os.path.exists(os.path.join(uv4_dir, "UV4.exe")):
        return False, f"✗ 无效的 Keil 路径，{uv4_dir} 中未找到 UV4.exe"
    if not os.path.exists(dll_src):
        return False, f"✗ 未找到 EHUBLink.dll：{dll_src}"

    target = os.path.join(uv4_dir, "elaphureRddi.dll")

    # 备份旧 DLL
    if os.path.exists(target):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(uv4_dir, "EHUBLink_backup")
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(target, os.path.join(backup_dir, f"elaphureRddi_{stamp}.dll"))

    # 复制 DLL
    shutil.copy2(dll_src, target)

    # 写入 ehublink.cfg（調试器地址）
    cfg_path = os.path.join(uv4_dir, "ehublink.cfg")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(f"# EHUBLink configuration\nhost={dap_host}\nport={dap_port}\n")

    return True, (f"✓ 安装成功！\n"
                  f"  DLL → {target}\n"
                  f"  调试地址: {dap_host}:{dap_port}")


# ─── 颜色 & 字体常量 ──────────────────────────────────────────────────────────
COLOR_SEND    = "#63a3f5"
COLOR_RECV    = "#5cd85c"
COLOR_CONFIG  = "#f2a93b"
COLOR_ERR     = "#f25c5c"
COLOR_TS      = "#888888"
MONO_FONT     = ("Consolas", 11)
LABEL_FONT    = ("微软雅黑", 11)
TITLE_FONT    = ("微软雅黑", 12, "bold")
PROTO_LABELS  = ["USART", "RS485", "RS422", "SPI", "I2C", "CAN", "TCP", "UDP"]

# ─── OpenOCD 运行时路径 ────────────────────────────────────────────────────────
_OPENOCD_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openocd")
_OPENOCD_EXE     = os.path.join(_OPENOCD_DIR, "openocd.exe")
_OPENOCD_SCRIPTS = os.path.join(_OPENOCD_DIR, "scripts")

OCD_TARGET_MAP = {
    "STM32F1x  (F103/F1xx)": "stm32f1x",
    "STM32F2x  (F205/F2xx)": "stm32f2x",
    "STM32F3x  (F303/F3xx)": "stm32f3x",
    "STM32F4x  (F407/F4xx)": "stm32f4x",
    "STM32F7x  (F746/F7xx)": "stm32f7x",
    "STM32H7x  (H743/H7xx)": "stm32h7x",
    "STM32F0x  (F030/F0xx)": "stm32f0x",
    "STM32L4x  (L476/L4xx)": "stm32l4x",
    "STM32G0x  (G071/G0xx)": "stm32g0x",
    "STM32G4x  (G431/G4xx)": "stm32g4x",
    "STM32L0x  (L031/L0xx)": "stm32l0",
    "STM32L1x  (L151/L1xx)": "stm32l1",
    "STM32L5x  (L552/L5xx)": "stm32l5x",
    "STM32U0x  (U031/U0xx)": "stm32u0x",
    "STM32U5x  (U585/U5xx)": "stm32u5x",
    "STM32WBx  (WB55/WBxx)": "stm32wbx",
    "STM32WLx  (WL55/WLxx)": "stm32wlx",
}
OCD_TRANSPORT_MAP = {
    "SWD": "swd",
    "JTAG": "jtag",
}
OCD_SPEED_LABELS = ["100", "500", "1000", "2000", "4000", "8000"]

# ─── 主应用 ───────────────────────────────────────────────────────────────────
class EHUBApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EHUB 调试工具  v2.0 — USB/WiFi 双模式")
        self.geometry("1220x780")
        self.minsize(920, 620)
        self._serial      = SerialManager(self._on_frame, self._on_serial_error)
        self._wifi_discovery = EHUBDiscovery()
        self._cur_proto   = "USART"
        self._log_q: queue.Queue = queue.Queue()
        self._auto_thread: threading.Thread | None = None
        self._auto_connect = True   # False = 手动断开后禁止自动重连，点击自动检测后恢复
        self._wifi_last_heartbeat_reply = 0.0
        self._wifi_tick = 0
        self._wifi_scan_results: list[tuple[str, int]] = []
        self._last_ping_ok = 0.0
        self._auto_send_enabled = False
        self._auto_send_job = None
        self._pc_tcp_sock: socket.socket | None = None
        self._pc_tcp_peer: tuple[str, int] | None = None
        self._extra_tx_count = 0
        self._extra_rx_count = 0
        # ── OpenOCD 相关状态 ─────────────────────────────────────────────
        self._openocd_proc: subprocess.Popen | None = None
        self._ocd_start_btn: ctk.CTkButton | None = None
        self._ocd_stop_btn:  ctk.CTkButton | None = None
        self._ocd_pid_lbl:   ctk.CTkLabel  | None = None
        self._dbg_keil_status_lbl: ctk.CTkLabel | None = None
        # 持久化变量（调试器面板重建后保留值）
        self._ocd_host_var   = ctk.StringVar(value="ehub.local")
        self._ocd_port_var   = ctk.StringVar(value="6000")
        self._ocd_target_var = ctk.StringVar(value=list(OCD_TARGET_MAP.keys())[0])
        self._ocd_transport_var = ctk.StringVar(value="SWD")
        self._ocd_speed_var  = ctk.StringVar(value="1000")
        self._dbg_keil_path_var = ctk.StringVar(value="")
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_ports()
        self._poll_log()
        # 启动时自动检测，之后每秒热插拔监测
        self.after(600, self._auto_detect)
        self.after(1000, self._hotplug_watch)
        self.after(3000, self._wifi_heartbeat_check)
        self.after(5000, self._poll_wifi_status)

    # ── UI 构建 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_topbar()
        self._build_sidebar()
        self._build_main()
        self._build_statusbar()
        self._select_proto("USART")

    def _build_topbar(self):
        # ── 外层横条 ──
        bar = ctk.CTkFrame(self, corner_radius=0, fg_color=("#e8eaf0", "#1e2233"))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(0, weight=1)

        # ── 第一行：标题 | 模式选择 | 连接按钮 | 电池 | 主题 ──────────────
        row1 = ctk.CTkFrame(bar, fg_color="transparent", height=46)
        row1.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        row1.columnconfigure(4, weight=1)  # 中间弹性列

        ctk.CTkLabel(row1, text="  EHUB 调试工具", font=("微软雅黑", 16, "bold"),
                     text_color=("#2563eb", "#63a3f5")
                     ).grid(row=0, column=0, padx=(4, 20), sticky="w")

        ctk.CTkLabel(row1, text="连接模式：", font=LABEL_FONT
                     ).grid(row=0, column=1, padx=(0, 4), sticky="w")
        self._conn_mode = ctk.StringVar(value="usb")
        ctk.CTkRadioButton(row1, text="USB CDC", variable=self._conn_mode,
                           value="usb", command=self._on_mode_change,
                           font=LABEL_FONT).grid(row=0, column=2, padx=(0, 8), sticky="w")
        ctk.CTkRadioButton(row1, text="WiFi TCP", variable=self._conn_mode,
                           value="wifi", command=self._on_mode_change,
                           font=LABEL_FONT).grid(row=0, column=3, padx=(0, 18), sticky="w")

        # 弹性列 4 撑开中间空间

        self._conn_btn = ctk.CTkButton(row1, text="  连接", width=110,
                                       fg_color=("#16a34a", "#15803d"),
                                       hover_color=("#15803d", "#166534"),
                                       command=self._toggle_connect, font=TITLE_FONT)
        self._conn_btn.grid(row=0, column=5, padx=(0, 12), sticky="e")

        # WiFi 连接状态（仅 WiFi 模式显示，与连接按钮同行）
        self._wifi_conn_lbl = ctk.CTkLabel(row1, text="", font=MONO_FONT,
                                           text_color=("#64748b", "#a0a0a0"),
                                           anchor="w", width=160)
        # 初始不显示，由 _on_mode_change 控制

        # 电池简要状态
        bat_bar = ctk.CTkFrame(row1, fg_color="transparent")
        bat_bar.grid(row=0, column=7, padx=(0, 8), sticky="e")
        self._bat_icon = ctk.CTkLabel(bat_bar, text="🔋", font=("Segoe UI Emoji", 14), anchor="w")
        self._bat_icon.pack(side="left", padx=(4, 4))
        self._bat_pct_lbl = ctk.CTkLabel(bat_bar, text="电量: ---%", font=MONO_FONT,
                                         text_color="#a0a0a0", anchor="w")
        self._bat_pct_lbl.pack(side="left", padx=(0, 8))
        self._bat_volt_lbl = ctk.CTkLabel(bat_bar, text="电压: --- V", font=MONO_FONT,
                                          text_color="#a0a0a0", anchor="w")
        self._bat_volt_lbl.pack(side="left", padx=(0, 8))
        self._bat_chg_lbl = ctk.CTkLabel(bat_bar, text="充电: ---", font=MONO_FONT,
                                         text_color="#a0a0a0", anchor="w")
        self._bat_chg_lbl.pack(side="left")

        self._theme_var = ctk.StringVar(value="🌙")
        ctk.CTkButton(row1, textvariable=self._theme_var, width=36,
                      command=self._toggle_theme, font=("微软雅黑", 14)
                      ).grid(row=0, column=8, padx=(0, 6), sticky="e")

        # ── 第二行：USB 子帧 / WiFi 子帧（互斥显示）───────────────────────
        row2 = ctk.CTkFrame(bar, fg_color="transparent", height=40)
        row2.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        row2.columnconfigure(99, weight=1)  # 末尾弹性列

        # -- USB 子帧 --
        self._usb_frame = ctk.CTkFrame(row2, fg_color="transparent")
        ctk.CTkLabel(self._usb_frame, text="串口：", font=LABEL_FONT
                     ).pack(side="left", padx=(0, 4))
        self._port_var = ctk.StringVar()
        self._port_cb = ctk.CTkComboBox(self._usb_frame, variable=self._port_var,
                                        width=120, font=MONO_FONT)
        self._port_cb.pack(side="left", padx=(0, 4))
        self._refresh_btn = ctk.CTkButton(self._usb_frame, text="↺", width=30,
                                          command=self._refresh_ports,
                                          font=("微软雅黑", 14))
        self._refresh_btn.pack(side="left", padx=(0, 8))
        self._detect_btn = ctk.CTkButton(self._usb_frame, text="🔍 自动检测", width=106,
                                         fg_color=("#7c3aed", "#6d28d9"),
                                         hover_color=("#6d28d9", "#5b21b6"),
                                         command=self._auto_detect, font=LABEL_FONT)
        self._detect_btn.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(self._usb_frame, text="波特率：", font=LABEL_FONT
                     ).pack(side="left", padx=(0, 4))
        self._baud_var = ctk.StringVar(value="115200")
        self._baud_cb = ctk.CTkComboBox(
            self._usb_frame, variable=self._baud_var, width=110, font=MONO_FONT,
            values=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self._baud_cb.pack(side="left")

        # -- WiFi 子帧 --
        self._wifi_frame = ctk.CTkFrame(row2, fg_color="transparent")
        ctk.CTkLabel(self._wifi_frame, text="地址：", font=LABEL_FONT
                     ).pack(side="left", padx=(0, 4))
        self._wifi_host_var = ctk.StringVar(value="ehub.local")
        self._wifi_host_cb = ctk.CTkComboBox(self._wifi_frame, variable=self._wifi_host_var,
                                             width=170, font=MONO_FONT,
                                             values=["ehub.local"])
        self._wifi_host_cb.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(self._wifi_frame, text=":", font=LABEL_FONT
                     ).pack(side="left")
        self._wifi_port_var = ctk.StringVar(value="5000")
        self._wifi_port_entry = ctk.CTkEntry(self._wifi_frame,
                                             textvariable=self._wifi_port_var,
                                             width=70, font=MONO_FONT)
        self._wifi_port_entry.pack(side="left", padx=(2, 10))
        self._wifi_scan_btn = ctk.CTkButton(self._wifi_frame, text="扫描", width=72,
                                            command=self._scan_wifi_devices,
                                            font=LABEL_FONT)
        self._wifi_scan_btn.pack(side="left", padx=(0, 12))
        self._wifi_cfg_btn = ctk.CTkButton(
            self._wifi_frame, text="配置WiFi", width=90,
            command=self._open_wifi_config_dialog,
            fg_color=("#0e7490", "#155e75"), hover_color=("#155e75", "#164e63"),
            font=LABEL_FONT)
        self._wifi_cfg_btn.pack(side="left", padx=(0, 8))
        self._esp_reset_btn = ctk.CTkButton(
            self._wifi_frame, text="重启ESP32", width=90,
            command=self._send_esp_reset,
            fg_color=("#374151", "#374151"), hover_color=("#1f2937", "#111827"),
            font=LABEL_FONT)
        self._esp_reset_btn.pack(side="left", padx=(0, 16))
        # WiFi IP + RSSI 状态（第二行右侧）
        self._wifi_ip_rssi_lbl = ctk.CTkLabel(self._wifi_frame, text="IP: ---.---.---.---  RSSI: -- dBm",
                                              font=MONO_FONT,
                                              text_color=("#64748b", "#a0a0a0"), anchor="w")
        self._wifi_ip_rssi_lbl.pack(side="left", padx=(0, 4))

        self._on_mode_change()

    def _on_mode_change(self):
        is_usb = self._conn_mode.get() == "usb"
        # 切换显示子帧
        if is_usb:
            self._wifi_frame.grid_forget()
            self._usb_frame.grid(row=0, column=0, sticky="w")
            self._wifi_conn_lbl.grid_forget()
        else:
            self._usb_frame.grid_forget()
            self._wifi_frame.grid(row=0, column=0, sticky="w")
            self._wifi_conn_lbl.grid(row=0, column=4, padx=(4, 8), sticky="e")

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=158, corner_radius=0, fg_color=("#d1d5e8","#161b2e"))
        sb.grid(row=1, column=0, sticky="nsew", padx=0)
        sb.grid_propagate(False)

        ctk.CTkLabel(sb, text="通信协议", font=("微软雅黑", 13, "bold"),
                     text_color=("#475569","#94a3b8")).pack(pady=(18, 8))

        self._proto_btns: dict[str, ctk.CTkButton] = {}
        for name in PROTO_LABELS:
            btn = ctk.CTkButton(sb, text=name, width=130, height=36,
                                anchor="w", font=TITLE_FONT,
                                fg_color="transparent",
                                text_color=("#1e293b","#e2e8f0"),
                                hover_color=("#c7d0eb","#1e2a45"),
                                command=lambda n=name: self._select_proto(n),
                                corner_radius=8)
            btn.pack(pady=3, padx=12)
            self._proto_btns[name] = btn

        # ── 分隔线 + 调试器安装快捷按钮 ──────────────────────────────
        ctk.CTkFrame(sb, height=1, fg_color=("gray60", "gray30")
                     ).pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(sb, text="调试器", font=("微软雅黑", 11, "bold"),
                     text_color=("#475569", "#94a3b8")).pack(pady=(0, 4))
        self._dbg_btn = ctk.CTkButton(sb, text="🔧 配置调试器", width=130, height=36,
                      anchor="w", font=TITLE_FONT,
                      fg_color="transparent",
                      text_color=("#1e293b", "#e2e8f0"),
                      hover_color=("#c7d0eb", "#1e2a45"),
                      command=self._select_debugger,
                      corner_radius=8)
        self._dbg_btn.pack(pady=3, padx=12)

        sb_bot = ctk.CTkFrame(sb, fg_color="transparent")
        sb_bot.pack(side="bottom", pady=14, padx=10)
        self._stat_tx  = ctk.CTkLabel(sb_bot, text="发送:  0 B", font=MONO_FONT,
                                       text_color=COLOR_SEND, anchor="w")
        self._stat_rx  = ctk.CTkLabel(sb_bot, text="接收:  0 B", font=MONO_FONT,
                                       text_color=COLOR_RECV, anchor="w")
        self._stat_err = ctk.CTkLabel(sb_bot, text="错误: 0",    font=MONO_FONT,
                                       text_color=COLOR_ERR,  anchor="w")
        for lbl in (self._stat_tx, self._stat_rx, self._stat_err):
            lbl.pack(anchor="w")
        self._errors = 0
        

    def _build_main(self):
        self._main_frame = ctk.CTkFrame(self, corner_radius=0,
                                         fg_color=("#f1f4fb","#111827"))
        self._main_frame.grid(row=1, column=1, sticky="nsew", padx=0)
        self._main_frame.columnconfigure(0, weight=1)
        self._main_frame.rowconfigure(1, weight=1)

        self._cfg_frame = ctk.CTkFrame(self._main_frame, corner_radius=10,
                                        fg_color=("#e2e8f4","#1a2236"))
        self._cfg_frame.grid(row=0, column=0, sticky="ew", padx=14, pady=(12,6))
        self._cfg_frame.columnconfigure(0, weight=1)
        self._cfg_widgets: dict = {}

        split = ctk.CTkFrame(self._main_frame, corner_radius=0, fg_color="transparent")
        split.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0,6))
        split.columnconfigure(0, weight=1)
        split.rowconfigure(0, weight=0)
        split.rowconfigure(1, weight=1)

        self._build_send_panel(split)
        self._build_log_panel(split)

    def _build_send_panel(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=("#e2e8f4","#1a2236"))
        card.grid(row=0, column=0, sticky="ew", pady=(0,6))
        # col0: 左侧内容, col1: 弹性间距, col2: 右侧对齐列
        card.columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="↑  发送数据", font=TITLE_FONT,
                     text_color=COLOR_SEND).grid(row=0, column=0, columnspan=3,
                                                  sticky="w", padx=10, pady=(8,4))

        # --- 格式行：左侧 "格式：文本"  右侧 "HEX" ---
        fmt_left = ctk.CTkFrame(card, fg_color="transparent")
        fmt_left.grid(row=1, column=0, columnspan=2, sticky="w", padx=10)
        ctk.CTkLabel(fmt_left, text="格式：", font=LABEL_FONT).pack(side="left")
        self._send_mode = ctk.StringVar(value="text")
        ctk.CTkRadioButton(fmt_left, text="文本", variable=self._send_mode,
                           value="text", font=LABEL_FONT).pack(side="left", padx=(2, 4))
        ctk.CTkRadioButton(card, text="HEX", variable=self._send_mode,
                           value="hex",  font=LABEL_FONT
                           ).grid(row=1, column=2, sticky="e", padx=10)

        # --- 输入框 ---
        self._send_entry = ctk.CTkEntry(card, height=34, font=MONO_FONT,
                                         placeholder_text="输入文本或 HEX 字节（空格分隔），回车发送…")
        self._send_entry.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=6)
        self._send_entry.bind("<Return>", lambda _: self._do_send())

        # --- 按钮行：左侧 "发送 清除"  右侧 "追加换行" ---
        btn_left = ctk.CTkFrame(card, fg_color="transparent")
        btn_left.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0,8))
        ctk.CTkButton(btn_left, text="  发送", width=90, command=self._do_send,
                      fg_color=("#2563eb","#1d4ed8")).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_left, text="清除", width=72, fg_color=("gray70","#374151"),
                      command=lambda: self._send_entry.delete(0, "end")).pack(side="left")
        self._auto_send_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(btn_left, text="自动发送", variable=self._auto_send_var,
                        command=self._on_auto_send_toggle,
                        font=LABEL_FONT, width=80).pack(side="left", padx=(10, 4))
        ctk.CTkLabel(btn_left, text="周期(ms)：", font=LABEL_FONT).pack(side="left", padx=(2, 2))
        self._auto_interval_var = ctk.StringVar(value="1000")
        self._auto_interval_entry = ctk.CTkEntry(
            btn_left, textvariable=self._auto_interval_var, width=70, font=MONO_FONT)
        self._auto_interval_entry.pack(side="left", padx=(0, 0))
        self._append_newline = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(card, text="追加换行", variable=self._append_newline,
                        font=LABEL_FONT, width=40
                        ).grid(row=3, column=2, sticky="e", padx=36, pady=(0,16))

    def _build_log_panel(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=("#e2e8f4","#1a2236"))
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8,2))
        ctk.CTkLabel(hdr, text="↓  接收日志", font=TITLE_FONT,
                     text_color=COLOR_RECV).pack(side="left")
        ctk.CTkButton(hdr, text="保存", width=60, fg_color=("gray60","#374151"),
                      command=self._save_log, height=26).pack(side="right", padx=(4,0))
        ctk.CTkButton(hdr, text="清空", width=60, fg_color=("gray60","#374151"),
                      command=self._clear_log, height=26).pack(side="right")

        self._log = ctk.CTkTextbox(card, font=MONO_FONT, wrap="none",
                                    fg_color=("#f8fafc","#0d1117"), corner_radius=6)
        self._log.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0,8))
        self._log.tag_config("ts",     foreground=COLOR_TS)
        self._log.tag_config("send",   foreground=COLOR_SEND)
        self._log.tag_config("recv",   foreground=COLOR_RECV)
        self._log.tag_config("config", foreground=COLOR_CONFIG)
        self._log.tag_config("err",    foreground=COLOR_ERR)
        self._log.configure(state="disabled")

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=26, corner_radius=0,
                            fg_color=("#d1d5e8","#161b2e"))
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(2, weight=1)
        self._stat_conn = ctk.CTkLabel(bar, text="○  未连接",
                                        font=("微软雅黑", 11),
                                        text_color=COLOR_ERR)
        self._stat_conn.grid(row=0, column=0, padx=12)
        ctk.CTkLabel(bar, text="│", font=("微软雅黑", 11),
                     text_color=("gray50","gray40")).grid(row=0, column=1)
        self._stat_tip = ctk.CTkLabel(bar, text="桥接协议 v2.0  |  可选择 USB CDC 或 WiFi TCP 连接",
                     font=("微软雅黑", 11),
                     text_color=("gray50","gray50"))
        self._stat_tip.grid(row=0, column=2, sticky="w", padx=8)

    # ── CONFIG 面板渲染 ────────────────────────────────────────────────────────
    def _select_proto(self, name: str):
        if name != "TCP":
            self._close_pc_tcp_socket()
        self._cur_proto = name
        for n, btn in self._proto_btns.items():
            btn.configure(
                fg_color=("#b6c1e0","#1e3a5f") if n == name else "transparent",
                text_color=("#1e293b","#ffffff") if n == name else ("#1e293b","#e2e8f0"),
            )
        self._render_config(name)

    def _render_config(self, name: str):
        for w in self._cfg_frame.winfo_children():
            w.destroy()
        self._cfg_widgets.clear()

        _title = "🔧  配置调试器" if name == "DEBUGGER" else f"⚙  {name} 参数配置"
        ctk.CTkLabel(self._cfg_frame, text=_title,
                     font=TITLE_FONT, text_color=COLOR_CONFIG
                     ).grid(row=0, column=0, columnspan=6, sticky="w", padx=12, pady=(8,6))

        if name in ("USART", "RS485", "RS422"):
            self._cfg_baud(name)
        elif name == "SPI":
            self._cfg_spi()
        elif name == "I2C":
            self._cfg_i2c()
        elif name == "CAN":
            self._cfg_can()
        elif name in ("TCP", "UDP"):
            self._cfg_tcp_udp(name)
        elif name == "DEBUGGER":
            self._cfg_debugger()
            return   # 调试器面板自带按钮，无需"应用配置"

        ctk.CTkButton(self._cfg_frame, text="应用配置", width=110,
                      fg_color=("#d97706","#b45309"),
                      hover_color=("#b45309","#92400e"),
                      command=self._apply_config, font=TITLE_FONT
                      ).grid(row=10, column=0, columnspan=6, padx=12, pady=(4,10), sticky="w")

    def _row(self, text: str, row: int, widget: ctk.CTkBaseClass):
        ctk.CTkLabel(self._cfg_frame, text=text, font=LABEL_FONT
                     ).grid(row=row, column=0, sticky="w", padx=12, pady=3)
        widget.grid(row=row, column=1, sticky="w", padx=(0,20), pady=3)

    def _cfg_baud(self, name: str):
        var = ctk.StringVar(value="115200")
        cb  = ctk.CTkComboBox(self._cfg_frame, variable=var, width=160,
                               values=["9600","19200","38400","57600","115200",
                                       "230400","460800","921600"],
                               font=MONO_FONT)
        self._row("波特率：", 1, cb)
        self._cfg_widgets["baud"] = var

    def _cfg_spi(self):
        spd_var  = ctk.StringVar(value=SPI_SPEED_LABELS[2])
        mode_var = ctk.StringVar(value="模式 0 (CPOL=0 CPHA=0)")
        role_var = ctk.StringVar(value="主机模式（Master）")
        ctk.CTkComboBox(self._cfg_frame, variable=spd_var, width=200,
                         values=SPI_SPEED_LABELS, font=MONO_FONT
                         ).grid(row=1, column=1, sticky="w", padx=(0,20), pady=3)
        ctk.CTkLabel(self._cfg_frame, text="通信速率：", font=LABEL_FONT
                     ).grid(row=1, column=0, sticky="w", padx=12, pady=3)
        modes = ["模式 0 (CPOL=0 CPHA=0)","模式 1 (CPOL=0 CPHA=1)",
                 "模式 2 (CPOL=1 CPHA=0)","模式 3 (CPOL=1 CPHA=1)"]
        ctk.CTkComboBox(self._cfg_frame, variable=mode_var, width=200,
                         values=modes, font=MONO_FONT
                         ).grid(row=2, column=1, sticky="w", padx=(0,20), pady=3)
        ctk.CTkLabel(self._cfg_frame, text="时钟模式：", font=LABEL_FONT
                     ).grid(row=2, column=0, sticky="w", padx=12, pady=3)
        ctk.CTkComboBox(self._cfg_frame, variable=role_var, width=200,
                         values=list(SPI_ROLE_MAP.keys()), font=MONO_FONT
                         ).grid(row=3, column=1, sticky="w", padx=(0,20), pady=3)
        ctk.CTkLabel(self._cfg_frame, text="主从模式：", font=LABEL_FONT
                     ).grid(row=3, column=0, sticky="w", padx=12, pady=3)
        self._cfg_widgets["spi_spd"]  = spd_var
        self._cfg_widgets["spi_mode"] = mode_var
        self._cfg_widgets["spi_role"] = role_var

        ctk.CTkLabel(self._cfg_frame,
                     text="ℹ  片选（CS）由外部硬件控制，固件不操作 CS 引脚",
                     font=("微软雅黑", 10), text_color="gray"
                     ).grid(row=4, column=0, columnspan=4, sticky="w", padx=12, pady=(0,2))

    def _cfg_i2c(self):
        spd_var  = ctk.StringVar(value="100 kHz（标准模式）")
        role_var = ctk.StringVar(value="主机模式（Master）")
        self._row("通信速率：", 1,
                  ctk.CTkComboBox(self._cfg_frame, variable=spd_var, width=200,
                                   values=list(I2C_SPEED_MAP.keys()), font=MONO_FONT))
        self._row("主从模式：", 2,
                  ctk.CTkComboBox(self._cfg_frame, variable=role_var, width=200,
                                   values=list(I2C_ROLE_MAP.keys()), font=MONO_FONT))
        self._cfg_widgets["i2c_spd"] = spd_var
        self._cfg_widgets["i2c_role"] = role_var

        for row, (lbl, ph, key) in enumerate([
            ("设备地址（7位十六进制）：", "0x3C", "i2c_addr"),
            ("寄存器地址（可选）：",      "0x00", "i2c_reg"),
            ("读取字节数：",              "1",    "i2c_rlen"),
        ], start=3):
            var = ctk.StringVar(value="")
            e   = ctk.CTkEntry(self._cfg_frame, placeholder_text=ph,
                                textvariable=var, width=130, font=MONO_FONT)
            ctk.CTkLabel(self._cfg_frame, text=lbl, font=LABEL_FONT
                         ).grid(row=row, column=0, sticky="w", padx=12, pady=3)
            e.grid(row=row, column=1, sticky="w", padx=(0,20), pady=3)
            self._cfg_widgets[key] = var

    def _cfg_can(self):
        baud_var = ctk.StringVar(value="500 kbps")
        self._row("CAN 波特率：", 1,
                  ctk.CTkComboBox(self._cfg_frame, variable=baud_var,
                                   width=180, values=list(CAN_BAUD_MAP.keys()), font=MONO_FONT))
        ide_var = ctk.StringVar(value="标准帧 11 位")
        self._row("帧类型：", 2,
                  ctk.CTkComboBox(self._cfg_frame, variable=ide_var,
                                   width=180, values=["标准帧 11 位","扩展帧 29 位"], font=MONO_FONT))
        id_var = ctk.StringVar(value="0x123")
        self._row("CAN ID（十六进制）：", 3,
                  ctk.CTkEntry(self._cfg_frame, textvariable=id_var, width=110, font=MONO_FONT))
        self._cfg_widgets.update(can_baud=baud_var, can_ide=ide_var, can_id=id_var)

    def _cfg_tcp_udp(self, name: str):
        host_var = ctk.StringVar(value="127.0.0.1")
        port_var = ctk.StringVar(value="9000" if name == "TCP" else "9001")
        local_port_var = ctk.StringVar(value="0")
        timeout_var = ctk.StringVar(value="0.2")

        self._row("目标地址：", 1,
                  ctk.CTkEntry(self._cfg_frame, textvariable=host_var, width=220, font=MONO_FONT))
        self._row("目标端口：", 2,
                  ctk.CTkEntry(self._cfg_frame, textvariable=port_var, width=120, font=MONO_FONT))
        if name == "UDP":
            self._row("本地端口(0随机)：", 3,
                      ctk.CTkEntry(self._cfg_frame, textvariable=local_port_var, width=120, font=MONO_FONT))
        self._row("接收超时(秒)：", 4,
                  ctk.CTkEntry(self._cfg_frame, textvariable=timeout_var, width=120, font=MONO_FONT))

        self._cfg_widgets["net_host"] = host_var
        self._cfg_widgets["net_port"] = port_var
        self._cfg_widgets["net_local_port"] = local_port_var
        self._cfg_widgets["net_timeout"] = timeout_var

    # ── Apply Config ──────────────────────────────────────────────────────────
    def _apply_config(self):
        if not self._serial.connected:
            self._log_append("⚠ 设备未连接", "err"); return

        name = self._cur_proto
        frames = []

        if name in ("USART", "RS485", "RS422"):
            baud = int(self._cfg_widgets["baud"].get().replace(",",""))
            iface = CH[name]
            frames.append(build_config_frame(iface, CFG_BAUD, baud))
            self._log_append(f"[配置] {name}  波特率→{baud}", "config")

        elif name == "SPI":
            idx  = SPI_SPEED_LABELS.index(self._cfg_widgets["spi_spd"].get())
            raw_mode = self._cfg_widgets["spi_mode"].get()
            mode = int(raw_mode.split()[1])   # "模式 0 ..." → 0
            role = SPI_ROLE_MAP[self._cfg_widgets["spi_role"].get()]
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_SPD,  idx))
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_MODE, mode))
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_ROLE, role))
            self._log_append(f"[配置] SPI  速率索引={idx}  模式={mode}  角色={'主机' if role == 0 else '从机'}", "config")

        elif name == "I2C":
            spd = I2C_SPEED_MAP[self._cfg_widgets["i2c_spd"].get()]
            role = I2C_ROLE_MAP[self._cfg_widgets["i2c_role"].get()]
            addr = int(self._cfg_widgets.get("i2c_addr", ctk.StringVar(value="0x3C")).get(), 16) & 0x7F
            frames.append(build_config_frame(CH["I2C_W"], CFG_I2C_SPD, spd))
            frames.append(build_config_frame(CH["I2C_W"], CFG_I2C_ROLE, role))
            frames.append(build_config_frame(CH["I2C_W"], CFG_I2C_OWN,  addr))
            self._log_append(f"[配置] I2C  速率={spd//1000} kHz  角色={'主机' if role == 0 else '从机'}  本机地址=0x{addr:02X}", "config")

        elif name == "CAN":
            baud = CAN_BAUD_MAP[self._cfg_widgets["can_baud"].get()]
            frames.append(build_config_frame(CH["CAN"], CFG_CAN_BAUD, baud))
            self._log_append(f"[配置] CAN  波特率={baud}", "config")

        for f in frames:
            self._serial.send(f)
        self._update_stats()

    # ── Send ──────────────────────────────────────────────────────────────────
    def _do_send(self, silent: bool = False) -> bool:
        name = self._cur_proto
        if name not in ("TCP", "UDP") and not self._serial.connected:
            if not silent:
                self._log_append("⚠ 设备未连接", "err")
            return False

        raw = self._send_entry.get()
        if not raw.strip():
            return False

        mode = self._send_mode.get()

        if name in ("TCP", "UDP"):
            try:
                payload = self._parse_input(raw, mode)
                if self._append_newline.get() and mode == "text":
                    payload += b"\r\n"
                recv_data = self._send_pc_socket(name, payload)
                hex_str = " ".join(f"{b:02X}" for b in payload)
                self._log_append(f"→ [{name}]  {hex_str}", "send")
                if recv_data:
                    recv_hex = " ".join(f"{b:02X}" for b in recv_data)
                    try:
                        recv_txt = recv_data.decode("utf-8", errors="replace").replace("\r", "").replace("\n", "↵")
                    except Exception:
                        recv_txt = ""
                    line = f"← [{name}]  {recv_hex}"
                    if recv_txt and recv_txt.isprintable():
                        line += '    “' + recv_txt + '”'
                    self._log_append(line, "recv")
            except Exception as e:
                if not silent:
                    self._log_append(f"⚠ {name} 发送失败: {e}", "err")
                return False
            self._update_stats()
            return True

        try:
            # build payload
            if name == "CAN":
                payload = self._build_can_payload()
            elif name == "I2C":
                payload = self._build_i2c_payload(raw, mode)
            else:
                payload = self._parse_input(raw, mode)
                if self._append_newline.get() and mode == "text":
                    payload += b"\r\n"
                ch_key  = name    # USART / RS485 / RS422 / SPI
        except Exception as e:
            if not silent:
                self._log_append(f"⚠ Input error: {e}", "err")
            return False

        if name not in ("CAN", "I2C"):
            ch_key = name
            frame  = build_frame(CH[ch_key], payload)
        elif name == "I2C":
            ch_str, frame = payload
            ch_key = ch_str
        else:
            frame  = payload
            ch_key = "CAN"

        self._serial.send(frame)
        hex_str = " ".join(f"{b:02X}" for b in (frame[5:-1] if len(frame) > 6 else frame))
        self._log_append(f"→ [{ch_key}]  {hex_str}", "send")
        self._update_stats()
        return True

    def _send_pc_socket(self, proto: str, payload: bytes) -> bytes:
        host = self._cfg_widgets.get("net_host", ctk.StringVar(value="127.0.0.1")).get().strip() or "127.0.0.1"
        port_s = self._cfg_widgets.get("net_port", ctk.StringVar(value="9000")).get().strip()
        timeout_s = self._cfg_widgets.get("net_timeout", ctk.StringVar(value="0.2")).get().strip() or "0.2"
        local_port_s = self._cfg_widgets.get("net_local_port", ctk.StringVar(value="0")).get().strip() or "0"

        port = int(port_s)
        if port <= 0 or port > 65535:
            raise ValueError("端口范围应为 1~65535")
        timeout = max(0.05, float(timeout_s))

        if proto == "TCP":
            sock = self._ensure_pc_tcp_socket(host, port, timeout)
            sock.sendall(payload)
            self._extra_tx_count += len(payload)
            sock.settimeout(timeout)
            try:
                data = sock.recv(2048)
            except socket.timeout:
                data = b""
            self._extra_rx_count += len(data)
            return data

        # UDP
        local_port = int(local_port_s)
        if local_port < 0 or local_port > 65535:
            raise ValueError("本地端口范围应为 0~65535")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            if local_port > 0:
                sock.bind(("0.0.0.0", local_port))
            sock.sendto(payload, (host, port))
            self._extra_tx_count += len(payload)
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                data = b""
            self._extra_rx_count += len(data)
            return data

    def _ensure_pc_tcp_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        peer = (host, port)
        if self._pc_tcp_sock is not None and self._pc_tcp_peer == peer:
            return self._pc_tcp_sock
        self._close_pc_tcp_socket()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(peer)
        self._pc_tcp_sock = sock
        self._pc_tcp_peer = peer
        return sock

    def _close_pc_tcp_socket(self):
        if self._pc_tcp_sock is not None:
            try:
                self._pc_tcp_sock.close()
            except Exception:
                pass
        self._pc_tcp_sock = None
        self._pc_tcp_peer = None

    def _on_auto_send_toggle(self):
        if not self._auto_send_var.get():
            self._stop_auto_send("ℹ 自动发送已停止")
            return
        try:
            interval_ms = int(self._auto_interval_var.get().strip())
            if interval_ms < 20:
                raise ValueError
        except Exception:
            self._log_append("⚠ 自动发送周期无效（最小 20ms）", "err")
            self._auto_send_var.set(False)
            return
        if not self._send_entry.get().strip():
            self._log_append("⚠ 请先输入发送内容", "err")
            self._auto_send_var.set(False)
            return
        self._auto_send_enabled = True
        self._log_append(f"ℹ 自动发送已启动，周期 {interval_ms} ms", "config")
        self._schedule_auto_send()

    def _schedule_auto_send(self):
        if not self._auto_send_enabled:
            return
        try:
            interval_ms = max(20, int(self._auto_interval_var.get().strip()))
        except Exception:
            interval_ms = 1000
        self._auto_send_job = self.after(interval_ms, self._auto_send_tick)

    def _auto_send_tick(self):
        if not self._auto_send_enabled:
            return
        ok = self._do_send(silent=True)
        if not ok and self._cur_proto not in ("TCP", "UDP"):
            self._stop_auto_send("⚠ 自动发送已停止：设备未连接或参数错误")
            return
        self._schedule_auto_send()

    def _stop_auto_send(self, log_text: str | None = None):
        self._auto_send_enabled = False
        if self._auto_send_job is not None:
            try:
                self.after_cancel(self._auto_send_job)
            except Exception:
                pass
        self._auto_send_job = None
        self._auto_send_var.set(False)
        if log_text:
            self._log_append(log_text, "config")

    def _parse_input(self, raw: str, mode: str) -> bytes:
        if mode == "hex":
            tokens = raw.replace(",","").split()
            return bytes(int(t, 16) for t in tokens)
        else:
            return raw.encode("utf-8")

    def _build_can_payload(self) -> bytes:
        can_id  = int(self._cfg_widgets["can_id"].get(), 16)
        ide     = 1 if "29" in self._cfg_widgets["can_ide"].get() else 0  # 扩展帧 29 位
        raw     = self._send_entry.get().strip()
        mode    = self._send_mode.get()
        data    = self._parse_input(raw, mode)[:8]
        dlc     = len(data)
        id_be   = struct.pack(">I", can_id)
        dlc_byte= (dlc | 0x80) if ide else dlc
        return build_frame(CH["CAN"], id_be + bytes([dlc_byte]) + data)

    def _build_i2c_payload(self, raw: str, mode: str):
        addr_s = self._cfg_widgets.get("i2c_addr", ctk.StringVar(value="0x3C")).get()
        addr   = int(addr_s, 16) & 0x7F
        role_s = self._cfg_widgets.get("i2c_role", ctk.StringVar(value="主机模式（Master）")).get()
        is_slave = I2C_ROLE_MAP.get(role_s, 0) == 1
        reg_s  = self._cfg_widgets.get("i2c_reg",  ctk.StringVar(value="")).get().strip()
        rlen_s = self._cfg_widgets.get("i2c_rlen", ctk.StringVar(value="1")).get().strip()
        data   = self._parse_input(raw, mode) if raw.strip() else b""

        if is_slave:
            if len(data) == 0:
                raise ValueError("I2C 从机模式下请输入应答数据（HEX或文本）")
            payload = data[:128]
            return ("I2C_W", build_frame(CH["I2C_W"], payload))

        needs_read = (rlen_s not in ("", "0"))

        if needs_read:
            rlen = int(rlen_s)
            reg  = int(reg_s, 16) if reg_s else None
            payload = bytes([addr, rlen]) + (bytes([reg]) if reg is not None else b"")
            return ("I2C_R", build_frame(CH["I2C_R"], payload))
        else:
            reg  = int(reg_s, 16) if reg_s else None
            payload = bytes([addr]) + (bytes([reg]) if reg is not None else b"") + data
            return ("I2C_W", build_frame(CH["I2C_W"], payload))

    # ── Frame 接收 ─────────────────────────────────────────────────────────────
    def _on_frame(self, ch: int, data: bytes):
        """在串口读取线程中回调 — 只入队，不操作 Tk"""
        self._log_q.put((ch, data))

    def _poll_log(self):
        try:
            while not self._log_q.empty():
                ch, data = self._log_q.get_nowait()
                if ch == -1:
                    text = data.decode(errors='replace')
                    if text == "__REMOVED__":
                        self._log_append("\u26a1 \u8bbe\u5907\u5df2\u79fb\u9664", "config")
                    else:
                        self._log_append(f"\u26a0 \u4e32\u53e3\u9519\u8bef\uff1a{text}", "err")
                    self._update_stats()
                elif ch == -2:
                    text = data.decode(errors="replace")
                    self._log_append(f"[OpenOCD] {text}", "config")
                else:
                    self._handle_frame(ch, data)
                    self._update_stats()
        except Exception:
            pass
        self.after(40, self._poll_log)

    def _handle_frame(self, ch: int, data: bytes):
        hex_str = " ".join(f"{b:02X}" for b in data)
        ch_name = CH_NAME.get(ch, f"0x{ch:02X}")

        if ch == CH["BATTERY"]:
            self._handle_battery(data)
            return

        if ch == CH["WIFI_CTRL"]:
            self._handle_wifi_ctrl(data)
            return

        if ch == CH["CONFIG"]:
            # 自动连接时的 PING 回复（data = [0xF0, 0x00, E, H, U, B]）
            if (len(data) >= 6 and data[0] == 0xF0 and data[1] == 0x00
                    and data[2:6] == b'EHUB'):
                self._last_ping_ok = time.time()
                self._log_append("← [设备识别]  EHUB 设备已确认 ✓", "config")
                return
            status = "成功" if len(data) >= 2 and data[1] == 0x00 else "失败"
            target = CH_NAME.get(data[0], f"0x{data[0]:02X}") if data else "?"
            self._log_append(f"← [配置回复/{target}]  {status}", "config")
        else:
            try:
                text = data.decode("utf-8", errors="replace")
                text = text[:80].replace("\r", "").replace("\n", "↵")
            except Exception:
                text = ""
            line = f"← [{ch_name}]  {hex_str}"
            if text.isprintable() and len(text) > 0:
                line += '    \u201c' + text + '\u201d'
            self._log_append(line, "recv")

    def _handle_wifi_ctrl(self, data: bytes):
        if not data:
            return
        subcmd = data[0]
        if subcmd == 0x01 and len(data) >= 7:
            status = data[1]
            rssi = data[2] if data[2] < 128 else data[2] - 256
            ip = f"{data[3]}.{data[4]}.{data[5]}.{data[6]}"
            status_map = {0: "未连接", 1: "STA已连接", 2: "AP模式"}
            st = status_map.get(status, f"未知({status})")
            color = "#22c55e" if status == 1 else ("#eab308" if status == 2 else "#ef4444")
            # Row1 显示连接状态，Row2 显示 IP + RSSI
            self._wifi_conn_lbl.configure(text=f"WiFi: {st}", text_color=color)
            self._wifi_ip_rssi_lbl.configure(text=f"IP: {ip}  RSSI: {rssi} dBm", text_color=color)
            # 后台轮询状态，不写入接收日志；且不计入 rx 字节统计
            self._serial.rx_count = max(0, self._serial.rx_count - (6 + len(data)))
        elif subcmd == 0x02:
            ok = len(data) >= 2 and data[1] == 0x00
            self._log_append("← [WIFI_CONFIG]  成功" if ok else "← [WIFI_CONFIG]  失败", "config" if ok else "err")
        elif subcmd == 0x05 and len(data) >= 2:
            count = data[1]
            pos = 2
            nets = []
            for _ in range(count):
                if pos >= len(data):
                    break
                ssid_len = data[pos]
                pos += 1
                if pos + ssid_len > len(data):
                    break
                ssid = data[pos:pos+ssid_len].decode("utf-8", errors="replace")
                pos += ssid_len
                if pos >= len(data):
                    break
                rssi = data[pos] if data[pos] < 128 else data[pos] - 256
                pos += 1
                nets.append((ssid, rssi))
            self._wifi_scan_results = nets
            brief = ", ".join(f"{s}({r})" for s, r in nets[:5]) if nets else "无"
            self._log_append(f"← [WIFI_SCAN]  {len(nets)} 个: {brief}", "recv")
        elif subcmd == 0x10:
            self._wifi_last_heartbeat_reply = time.time()
        else:
            hex_str = " ".join(f"{b:02X}" for b in data)
            self._log_append(f"← [WIFI_CTRL]  {hex_str}", "recv")

    # ── Battery 解析 ─────────────────────────────────────────────────────────
    def _handle_battery(self, data: bytes):
        """解析 BRIDGE_CH_BATTERY (0x08) 帧：[V_H][V_L][pct][charging]"""
        if len(data) < 4:
            return
        # 电池上报帧不计入 rx 统计字节
        self._serial.rx_count = max(0, self._serial.rx_count - (6 + len(data)))
        voltage_mv = (data[0] << 8) | data[1]
        # 设备上报的是分压后的电压（mV），经分压后大约落在 2000-2900 mV
        # 实际对应电池电压范围为 8400-12600 mV（即 8.4V - 12.6V，4S 电池）
        reported_pct = data[2]
        charging   = data[3]
        # 校准映射参数（以 mV 为单位）
        MEAS_MIN = 2000
        MEAS_MAX = 2900
        ACT_MIN  = 8400
        ACT_MAX  = 12600

        # 将分压后测得的电压映射回实际电池电压（线性插值并限幅）
        if voltage_mv <= MEAS_MIN:
            actual_mv = ACT_MIN
        elif voltage_mv >= MEAS_MAX:
            actual_mv = ACT_MAX
        else:
            actual_mv = int((voltage_mv - MEAS_MIN) * (ACT_MAX - ACT_MIN) / (MEAS_MAX - MEAS_MIN) + ACT_MIN)

        # 根据映射后的实际电压计算百分比（0-100%），并优先使用映射计算值
        pct = int((actual_mv - ACT_MIN) * 100 / (ACT_MAX - ACT_MIN))
        pct = max(0, min(100, pct))

        # 颜色与图标显示
        if pct > 60:
            color = "#22c55e"
        elif pct > 20:
            color = "#eab308"
        else:
            color = "#ef4444"

        chg_text  = "⚡ 充电中" if charging else "🔌 未充电"
        chg_color = "#22d3ee" if charging else "#a0a0a0"

        if charging:
            icon = "🔋⚡"
        elif pct > 75:
            icon = "🔋"
        elif pct > 50:
            icon = "🔋"
        elif pct > 25:
            icon = "🪫"
        else:
            icon = "🪫"

        self._bat_icon.configure(text=icon)
        self._bat_pct_lbl.configure(text=f"电量: {pct}%", text_color=color)
        # 仅显示映射后的实际电压（单位：V，保留两位小数）
        self._bat_volt_lbl.configure(text=f"电压: {actual_mv/1000:.2f} V", text_color="#94a3b8")
        # 保留设备原始上报的百分比供参考（可在需要时改为显示）
        self._bat_chg_lbl.configure(text=f"充电: {chg_text}", text_color=chg_color)

    # ── Log helpers ───────────────────────────────────────────────────────────
    def _log_append(self, text: str, tag: str = "recv"):
        ts  = datetime.now().strftime("%H:%M:%S.%f")[:12]
        self._log.configure(state="normal")
        self._log.insert("end", f"{ts}  ", "ts")
        self._log.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _save_log(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            content = self._log.get("1.0", "end")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    # ── Serial helpers ────────────────────────────────────────────────────────
    def _toggle_connect(self):
        if self._serial.connected:
            self._auto_connect = False   # 手动断开 → 禁止自动重连
            self._serial.disconnect()
            self._close_pc_tcp_socket()
            self._conn_btn.configure(text="  连接",
                                      fg_color=("#16a34a","#15803d"),
                                      hover_color=("#15803d","#166534"))
            self._stat_conn.configure(text="○  未连接", text_color=COLOR_ERR)
            self._stat_tip.configure(text="已手动断开  |  点击 🔍 自动检测可重新启用自动连接")
            self._log_append("已手动断开连接。自动重连已暂停，点击 🔍 自动检测可恢复。", "config")
        else:
            if self._conn_mode.get() == "usb":
                port = self._port_var.get()
                if not port or port == "(无可用串口)":
                    self._log_append("⚠ 未选择串口", "err"); return
                self._do_connect(port, int(self._baud_var.get()))
            else:
                host = self._wifi_host_var.get().strip() or "ehub.local"
                if host == "ehub.local":
                    host = EHUBDiscovery.try_resolve_mdns("ehub.local") or host
                try:
                    port = int(self._wifi_port_var.get().strip() or "5000")
                except ValueError:
                    self._log_append("⚠ WiFi 端口无效", "err"); return
                self._do_wifi_connect(host, port)

    def _do_connect(self, port: str, baud: int):
        """实际执行连接操作（可由自动检测或手动按钮调用）"""
        try:
            self._serial.connect_usb(port, baud)
            # PING 验证（失败只警告，不强制断开，保留原 v1.1 行为）
            if not self._ping_check():
                self._log_append("⚠ PING 未收到 EHUB 应答，请确认固件版本", "err")
            self._conn_btn.configure(text="  断开",
                                      fg_color=("#dc2626","#b91c1c"),
                                      hover_color=("#b91c1c","#991b1b"))
            self._stat_conn.configure(
                text=f"●  {port}  {baud} bps", text_color=COLOR_RECV)
            self._stat_tip.configure(text=f"已连接  |  USB 模式 EHUB 桥接协议")
            self._port_var.set(port)
            self._log_append(f"已连接到 {port} @ {baud} bps", "config")
        except Exception as e:
            self._log_append(f"⚠ 连接失败：{e}", "err")

    def _do_wifi_connect(self, host: str, port: int):
        try:
            self._serial.connect_wifi(host, port)
            self._wifi_last_heartbeat_reply = time.time()
            # PING 验证（失败只警告，不强制断开）
            if not self._ping_check():
                self._log_append("⚠ PING 未收到 EHUB 应答，请确认固件版本", "err")
            self._conn_btn.configure(text="  断开",
                                      fg_color=("#dc2626","#b91c1c"),
                                      hover_color=("#b91c1c","#991b1b"))
            self._stat_conn.configure(text=f"●  WiFi {host}:{port}", text_color=COLOR_RECV)
            self._stat_tip.configure(text="已连接  |  WiFi TCP 模式 EHUB 桥接协议")
            self._log_append(f"已连接到 WiFi {host}:{port}", "config")
            self._send_wifi_ctrl(bytes([0x01]))
        except Exception as e:
            self._log_append(f"⚠ WiFi 连接失败：{e}", "err")

    def _ping_check(self, timeout: float = 1.0) -> bool:
        before = self._last_ping_ok
        self._serial.send(build_ping_frame())
        end_t = time.time() + timeout
        while time.time() < end_t:
            self.update_idletasks()
            self.update()
            if self._last_ping_ok > before:
                return True
            time.sleep(0.03)
        return False

    def _send_wifi_ctrl(self, payload: bytes):
        if not self._serial.connected:
            return
        frame = build_frame(CH["WIFI_CTRL"], payload)
        self._serial.send(frame)
        self._update_stats()

    def _on_serial_error(self, msg: str):
        """串口读取线程出错 → 推送到日志队列（区分拔出与其他错误）"""
        self._log_q.put((-1, msg.encode()))
        self.after(0, self._on_disconnect_event)

    def _on_disconnect_event(self):
        # 确保端口对象被干净关闭，使 connected 返回 False，热插拔监测才能重连
        try:
            self._serial.disconnect()
        except Exception:
            pass
        self._conn_btn.configure(text="  连接",
                                  fg_color=("#16a34a","#15803d"),
                                  hover_color=("#15803d","#166534"))
        self._stat_conn.configure(text="○  未连接", text_color=COLOR_ERR)
        self._stat_tip.configure(text="连接已断开  |  USB 可自动重连，WiFi 请检查网络")

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_cb.configure(values=ports if ports else ["(无可用串口)"])
        if ports:
            self._port_var.set(ports[0])

    # ── 自动检测 ──────────────────────────────────────────────────────────────
    def _auto_detect(self):
        if self._conn_mode.get() != "usb":
            self._log_append("ℹ 当前为 WiFi 模式，USB 自动检测已跳过", "config")
            return
        self._auto_connect = True   # 点击自动检测 → 重新开启自动重连
        if self._serial.connected:
            self._log_append("ℹ 已连接，无需自动检测", "config"); return
        if self._auto_thread and self._auto_thread.is_alive():
            return

        # ── 第一步：VID/PID 快速识别 ──────────────────────────────────────
        port = find_ehub_port()
        if port:
            self._log_append(f"✓ 通过 USB 描述符找到 EHUB 设备：{port}，正在连接…", "config")
            self._do_connect(port, PROBE_BAUD)
            return

        # ── 如果 VID/PID 未能识别，退回到 PING 扫描 ──────────────────────
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            self._log_append("⚠ 未检测到任何串口，请检查 USB 连接", "err"); return
        self._detect_btn.configure(state="disabled", text="检测中…")
        self._stat_tip.configure(text=f"正在扫描 {len(ports)} 个串口（PING 模式）…")
        self._log_append(f"VID/PID 未匹配，启动 PING 扫描，共 {len(ports)} 个串口…", "config")
        self._auto_thread = threading.Thread(
            target=self._probe_worker, args=(ports,), daemon=True)
        self._auto_thread.start()

    def _probe_worker(self, ports: list):
        found_port = None
        baud = PROBE_BAUD
        for port in ports:
            self.after(0, lambda p=port: self._stat_tip.configure(
                text=f"正在检测 {p}…"))
            self.after(0, lambda p=port: self._log_append(
                f"  → {p}  发送 PING…", "config"))
            ok = probe_port(port, baud)
            self.after(0, lambda p=port, r=ok: self._log_append(
                f"  ← {p}  {'✓ EHUB 应答' if r else '✗ 无应答'}", "config"))
            if ok:
                found_port = port
                break

        # 回到 Tk 主线程更新 UI
        self.after(0, lambda: self._probe_done(found_port, baud))

    def _probe_done(self, found_port, baud: int):
        self._detect_btn.configure(state="normal", text="🔍 自动检测")
        if found_port:
            self._log_append(f"✓ 检测到 EHUB 设备：{found_port}，正在连接…", "config")
            self._do_connect(found_port, baud)
        else:
            self._log_append("✗ 未检测到 EHUB 设备，请检查 USB 连接或手动选择串口", "err")
            self._stat_tip.configure(text="未找到 EHUB 设备  |  可手动选择串口后点击连接")

    def _update_stats(self):
        tx_total = self._serial.tx_count + self._extra_tx_count
        rx_total = self._serial.rx_count + self._extra_rx_count
        self._stat_tx.configure(text=f"发送:  {tx_total} B")
        self._stat_rx.configure(text=f"接收:  {rx_total} B")
        self._stat_err.configure(text=f"错误: {self._errors}")

    def _hotplug_watch(self):
        """每秒静默检测 EHUB 设备插入，断开状态下自动重连（仅限 _auto_connect=True）。"""
        if self._conn_mode.get() == "usb" and self._auto_connect and not self._serial.connected:
            port = find_ehub_port()
            if port:
                self._log_append(f"⚡ EHUB 设备重新插入：{port}，正在连接…", "config")
                self._do_connect(port, PROBE_BAUD)
        self.after(1000, self._hotplug_watch)

    def _poll_wifi_status(self):
        if self._conn_mode.get() == "wifi" and self._serial.connected and self._serial.mode == "wifi":
            # 后台查询，静默发送不计 tx 字节
            self._serial.send_silent(build_frame(CH["WIFI_CTRL"], bytes([0x01])))
        self.after(5000, self._poll_wifi_status)

    def _wifi_heartbeat_check(self):
        if self._serial.connected and self._serial.mode == "wifi":
            self._wifi_tick = (self._wifi_tick + 1) & 0xFFFFFFFF
            tick = self._wifi_tick
            payload = bytes([0x10, (tick >> 24) & 0xFF, (tick >> 16) & 0xFF, (tick >> 8) & 0xFF, tick & 0xFF])
            # 心跳静默发送不计 tx 字节
            self._serial.send_silent(build_frame(CH["WIFI_CTRL"], payload))
            if self._wifi_last_heartbeat_reply > 0 and (time.time() - self._wifi_last_heartbeat_reply) > 10.0:
                self._log_append("⚠ WiFi 心跳超时，连接已断开", "err")
                self._on_disconnect_event()
        self.after(3000, self._wifi_heartbeat_check)

    def _scan_wifi_devices(self):
        if ServiceBrowser is None or Zeroconf is None:
            self._log_append("⚠ 未安装 zeroconf，无法进行 mDNS 扫描（pip install zeroconf）", "err")
            return
        self._wifi_scan_btn.configure(state="disabled", text="扫描中…")
        self._log_append("正在扫描局域网 EHUB 设备（mDNS）…", "config")
        def _do_scan():
            devs = self._wifi_discovery.scan(timeout=2.5)
            self.after(0, lambda: self._scan_wifi_done(devs))
        threading.Thread(target=_do_scan, daemon=True).start()

    def _scan_wifi_done(self, devices: list):
        self._wifi_scan_btn.configure(state="normal", text="扫描")
        vals = ["ehub.local"]
        for d in devices:
            vals.append(d["ip"])
        uniq_vals = list(dict.fromkeys(vals))
        self._wifi_host_cb.configure(values=uniq_vals)
        if len(uniq_vals) > 1:
            self._wifi_host_var.set(uniq_vals[1])
        self._log_append(f"WiFi 扫描完成：发现 {max(0, len(uniq_vals)-1)} 台 EHUB 设备", "config")

    def _send_esp_reset(self):
        if not (self._serial.connected and self._serial.mode == "wifi"):
            self._log_append("⚠ 请先以 WiFi 模式连接设备", "err")
            return
        self._send_wifi_ctrl(bytes([0x03]))
        self._log_append("→ [WIFI_CTRL] ESP32 重启命令已发送", "config")

    def _open_wifi_config_dialog(self):
        if not (self._serial.connected and self._serial.mode == "wifi"):
            self._log_append("⚠ 请先以 WiFi 模式连接后再配置", "err")
            return
        dlg = ctk.CTkToplevel(self)
        dlg.title("WiFi 配置")
        dlg.geometry("440x320")
        dlg.grab_set()

        ssid_var = ctk.StringVar(value="")
        pwd_var = ctk.StringVar(value="")
        ctk.CTkLabel(dlg, text="SSID:", font=LABEL_FONT).pack(anchor="w", padx=14, pady=(14, 2))
        ssid_entry = ctk.CTkEntry(dlg, textvariable=ssid_var, width=380, font=MONO_FONT)
        ssid_entry.pack(anchor="w", padx=14)
        ctk.CTkLabel(dlg, text="密码:", font=LABEL_FONT).pack(anchor="w", padx=14, pady=(8, 2))
        pwd_entry = ctk.CTkEntry(dlg, textvariable=pwd_var, width=380, font=MONO_FONT, show="*")
        pwd_entry.pack(anchor="w", padx=14)

        result_box = ctk.CTkTextbox(dlg, width=380, height=150, font=MONO_FONT)
        result_box.pack(padx=14, pady=10)

        def fill_scan_results():
            self._send_wifi_ctrl(bytes([0x05]))
            self.after(600, lambda: self._render_wifi_scan_result_box(result_box, ssid_var))

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkButton(btns, text="扫描", width=90, command=fill_scan_results).pack(side="left")
        ctk.CTkButton(btns, text="保存并连接", width=110,
                      command=lambda: self._apply_wifi_config(ssid_var.get(), pwd_var.get(), dlg)
                      ).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="取消", width=90, command=dlg.destroy).pack(side="right")

        fill_scan_results()

    def _render_wifi_scan_result_box(self, box: ctk.CTkTextbox, ssid_var: ctk.StringVar):
        box.configure(state="normal")
        box.delete("1.0", "end")
        if not self._wifi_scan_results:
            box.insert("end", "未发现网络\n")
        else:
            for ssid, rssi in sorted(self._wifi_scan_results, key=lambda x: x[1], reverse=True):
                box.insert("end", f"{ssid:<24} {rssi:>4} dBm\n")
            ssid_var.set(self._wifi_scan_results[0][0])
        box.configure(state="disabled")

    def _apply_wifi_config(self, ssid: str, password: str, dialog):
        try:
            ssid_b = ssid.encode("utf-8")
            pwd_b = password.encode("utf-8")
            if len(ssid_b) > 32 or len(pwd_b) > 64:
                raise ValueError("SSID 或密码长度超限")
            payload = bytes([0x02, len(ssid_b)]) + ssid_b + bytes([len(pwd_b)]) + pwd_b
            self._send_wifi_ctrl(payload)
            self._log_append(f"→ [WIFI_CONFIG] SSID={ssid}", "config")
            dialog.destroy()
        except Exception as e:
            self._log_append(f"⚠ WiFi 配置失败：{e}", "err")

    def _toggle_theme(self):
        mode = ctk.get_appearance_mode()
        new  = "light" if mode == "Dark" else "dark"
        ctk.set_appearance_mode(new)
        self._theme_var.set("☀" if new == "light" else "🌙")

    def _on_close(self):
        """窗口关闭时自动停止 OpenOCD"""
        if self._openocd_proc and self._openocd_proc.poll() is None:
            self._openocd_proc.terminate()
            try:
                self._openocd_proc.wait(timeout=2)
            except Exception:
                pass
        self.destroy()

    # ── 调试器选择（内联面板） ─────────────────────────────────────────────────
    def _select_debugger(self):
        for btn in self._proto_btns.values():
            btn.configure(fg_color="transparent",
                          text_color=("#1e293b", "#e2e8f0"))
        self._dbg_btn.configure(fg_color=("#b6c1e0", "#1e3a5f"),
                                text_color=("#1e293b", "#ffffff"))
        self._cur_proto = "DEBUGGER"
        self._render_config("DEBUGGER")

    # ── 配置调试器 内联面板 ────────────────────────────────────────────────────
    def _cfg_debugger(self):
        """在 _cfg_frame 内构建双列调试器配置面板（Keil安装 + OpenOCD启停）"""
        fr = self._cfg_frame

        # 容器框，跨满 cfg_frame 全部列
        wrap = ctk.CTkFrame(fr, fg_color="transparent")
        wrap.grid(row=1, column=0, columnspan=6, sticky="ew", padx=0, pady=(0, 6))
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=1)

        # ══════════════════ 左列: Keil 调试器安装 ══════════════════
        keil_card = ctk.CTkFrame(wrap, corner_radius=8,
                                  fg_color=("#d4d9ee", "#141d30"))
        keil_card.grid(row=0, column=0, sticky="nsew", padx=(4, 3))
        keil_card.columnconfigure(1, weight=1)

        ctk.CTkLabel(keil_card, text="🔑 Keil 调试器安装", font=TITLE_FONT,
                     text_color=COLOR_CONFIG
                     ).grid(row=0, column=0, columnspan=3, sticky="w",
                            padx=10, pady=(8, 4))

        ctk.CTkLabel(keil_card, text="Keil 路径：", font=LABEL_FONT
                     ).grid(row=1, column=0, sticky="w", padx=10, pady=3)
        ctk.CTkEntry(keil_card, textvariable=self._dbg_keil_path_var,
                     font=MONO_FONT
                     ).grid(row=1, column=1, sticky="ew", padx=(0, 3), pady=3)

        def _browse():
            from tkinter import filedialog
            p = filedialog.askdirectory(title="选择 Keil MDK 安装目录（含 UV4 文件夹）")
            if p:
                self._dbg_keil_path_var.set(p.replace("/", "\\"))

        ctk.CTkButton(keil_card, text="浏览", width=52, command=_browse,
                      font=LABEL_FONT
                      ).grid(row=1, column=2, padx=(0, 10), pady=3)

        def _auto_keil():
            p = _find_keil_path()
            if p:
                self._dbg_keil_path_var.set(p)
                if self._dbg_keil_status_lbl:
                    self._dbg_keil_status_lbl.configure(
                        text=f"✓ 自动检测到：{p}", text_color="#22c55e")
            else:
                if self._dbg_keil_status_lbl:
                    self._dbg_keil_status_lbl.configure(
                        text="✗ 未检测到 Keil MDK，请手动选择", text_color=COLOR_ERR)

        ctk.CTkButton(keil_card, text="🔍 自动检测 Keil 路径", height=30,
                      command=_auto_keil,
                      fg_color=("#7c3aed", "#6d28d9"),
                      hover_color=("#6d28d9", "#5b21b6"),
                      font=LABEL_FONT
                      ).grid(row=2, column=0, columnspan=3, padx=10,
                             pady=(0, 4), sticky="ew")

        # DLL 来源信息
        _script_dir  = os.path.dirname(os.path.abspath(__file__))
        _project_dir = os.path.dirname(_script_dir)
        _dll_candidates = [
            os.path.join(_project_dir, "EHUBLink", "EHUBLink", "bin", "Release", "EHUBLink.dll"),
            os.path.join(_project_dir, "EHUBLink", "bin", "Release", "EHUBLink.dll"),
        ]
        _dll_src = next((p for p in _dll_candidates if os.path.exists(p)), "")
        ctk.CTkLabel(keil_card,
                     text=(f"DLL: {os.path.basename(_dll_src)}  ({os.path.dirname(_dll_src)})"
                           if _dll_src else "✗ 未找到 EHUBLink.dll（请先编译项目）"),
                     font=("微软雅黑", 10),
                     text_color=("gray40" if _dll_src else COLOR_ERR),
                     anchor="w", wraplength=260
                     ).grid(row=3, column=0, columnspan=3, sticky="w",
                            padx=10, pady=(0, 4))

        def _do_install():
            kp = self._dbg_keil_path_var.get().strip()
            if not kp:
                if self._dbg_keil_status_lbl:
                    self._dbg_keil_status_lbl.configure(
                        text="✗ 请先指定 Keil 安装路径", text_color=COLOR_ERR)
                return
            if not _dll_src:
                if self._dbg_keil_status_lbl:
                    self._dbg_keil_status_lbl.configure(
                        text="✗ 未找到 EHUBLink.dll", text_color=COLOR_ERR)
                return
            _install_btn.configure(state="disabled", text="安装中…")
            def _run():
                try:
                    ok, msg = _do_install_ehublink(
                        kp, _dll_src,
                        self._ocd_host_var.get().strip() or "ehub.local",
                        int(self._ocd_port_var.get().strip() or "6000"))
                    if self._dbg_keil_status_lbl:
                        self.after(0, lambda m=msg, s=ok: self._dbg_keil_status_lbl.configure(
                            text=m[:80], text_color="#22c55e" if s else COLOR_ERR))
                    if ok:
                        self.after(0, lambda: self._log_append(
                            f"[调试器] EHUBLink 已安装到 Keil：{kp}", "config"))
                except Exception as e:
                    if self._dbg_keil_status_lbl:
                        self.after(0, lambda ex=e: self._dbg_keil_status_lbl.configure(
                            text=f"✗ 安装失败：{ex}", text_color=COLOR_ERR))
                finally:
                    self.after(0, lambda: _install_btn.configure(
                        state="normal", text="⚡ 一键安装 EHUBLink"))
            threading.Thread(target=_run, daemon=True).start()

        _install_btn = ctk.CTkButton(
            keil_card, text="⚡ 一键安装 EHUBLink", height=34,
            fg_color=("#2563eb", "#1d4ed8"),
            hover_color=("#1d4ed8", "#1e40af"),
            font=("微软雅黑", 12, "bold"),
            command=_do_install)
        _install_btn.grid(row=4, column=0, columnspan=3, sticky="ew",
                          padx=10, pady=(0, 4))

        self._dbg_keil_status_lbl = ctk.CTkLabel(
            keil_card, text="", font=("微软雅黑", 10),
            text_color="#22c55e", anchor="w", wraplength=260)
        self._dbg_keil_status_lbl.grid(row=5, column=0, columnspan=3,
                                        sticky="w", padx=10, pady=(0, 10))

        # 首次显示时自动检测 Keil 路径
        if not self._dbg_keil_path_var.get():
            _auto_keil()

        # ══════════════════ 右列: OpenOCD DAP TCP 服务 ══════════════════
        ocd_card = ctk.CTkFrame(wrap, corner_radius=8,
                                 fg_color=("#d4d9ee", "#141d30"))
        ocd_card.grid(row=0, column=1, sticky="nsew", padx=(3, 4))
        ocd_card.columnconfigure(1, weight=1)

        ctk.CTkLabel(ocd_card, text="▶ OpenOCD DAP TCP 服务", font=TITLE_FONT,
                     text_color=COLOR_CONFIG
                     ).grid(row=0, column=0, columnspan=4, sticky="w",
                            padx=10, pady=(8, 4))

        ctk.CTkLabel(ocd_card, text="EHUB 主机：", font=LABEL_FONT
                     ).grid(row=1, column=0, sticky="w", padx=10, pady=3)
        ctk.CTkEntry(ocd_card, textvariable=self._ocd_host_var,
                     width=130, font=MONO_FONT
                     ).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=3)
        ctk.CTkLabel(ocd_card, text="端口：", font=LABEL_FONT
                     ).grid(row=1, column=2, sticky="w", padx=(4, 2), pady=3)
        ctk.CTkEntry(ocd_card, textvariable=self._ocd_port_var,
                     width=68, font=MONO_FONT
                     ).grid(row=1, column=3, sticky="w", padx=(0, 10), pady=3)

        ctk.CTkLabel(ocd_card, text="目标芯片：", font=LABEL_FONT
                     ).grid(row=2, column=0, sticky="w", padx=10, pady=3)
        ctk.CTkComboBox(ocd_card, variable=self._ocd_target_var,
                        values=list(OCD_TARGET_MAP.keys()),
                        width=220, font=MONO_FONT
                        ).grid(row=2, column=1, columnspan=3, sticky="w",
                               padx=(0, 10), pady=3)

        ctk.CTkLabel(ocd_card, text="调试方式：", font=LABEL_FONT
                 ).grid(row=3, column=0, sticky="w", padx=10, pady=3)
        ctk.CTkComboBox(ocd_card, variable=self._ocd_transport_var,
                values=list(OCD_TRANSPORT_MAP.keys()), width=90, font=MONO_FONT
                ).grid(row=3, column=1, sticky="w", padx=(0, 6), pady=3)

        ctk.CTkLabel(ocd_card, text="适配器速率(kHz)：", font=LABEL_FONT
                 ).grid(row=4, column=0, sticky="w", padx=10, pady=3)
        ctk.CTkComboBox(ocd_card, variable=self._ocd_speed_var,
                        values=OCD_SPEED_LABELS, width=90, font=MONO_FONT
                ).grid(row=4, column=1, sticky="w", padx=(0, 6), pady=3)

        ocd_avail = os.path.exists(_OPENOCD_EXE)
        if not ocd_avail:
            ctk.CTkLabel(ocd_card, text=f"⚠ 未找到 openocd.exe：{_OPENOCD_EXE}",
                         font=("微软雅黑", 10), text_color=COLOR_ERR, anchor="w"
                         ).grid(row=4, column=0, columnspan=4, sticky="w",
                                padx=10, pady=(0, 4))

        btn_row = ctk.CTkFrame(ocd_card, fg_color="transparent")
        btn_row.grid(row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 4))

        _already_running = (self._openocd_proc is not None and
                            self._openocd_proc.poll() is None)
        self._ocd_start_btn = ctk.CTkButton(
            btn_row, text="▶ 启动 OpenOCD", width=130, height=34,
            fg_color=("#16a34a", "#15803d"),
            hover_color=("#15803d", "#166534"),
            font=TITLE_FONT,
            state="disabled" if (_already_running or not ocd_avail) else "normal",
            command=self._start_openocd)
        self._ocd_start_btn.pack(side="left", padx=(0, 6))

        self._ocd_stop_btn = ctk.CTkButton(
            btn_row, text="■ 停止", width=72, height=34,
            fg_color=("#dc2626", "#b91c1c"),
            hover_color=("#b91c1c", "#991b1b"),
            font=TITLE_FONT,
            state="normal" if _already_running else "disabled",
            command=self._stop_openocd)
        self._ocd_stop_btn.pack(side="left", padx=(0, 10))

        _pid_text = f"PID: {self._openocd_proc.pid}" if _already_running else "PID: --"
        self._ocd_pid_lbl = ctk.CTkLabel(
            btn_row, text=_pid_text, font=MONO_FONT, text_color="#94a3b8")
        self._ocd_pid_lbl.pack(side="left")

        _status_text  = "▶ OpenOCD 运行中" if _already_running else "■ OpenOCD 未运行"
        _status_color = "#22c55e" if _already_running else "#94a3b8"
        ctk.CTkLabel(ocd_card, text=_status_text, font=("微软雅黑", 11),
                     text_color=_status_color, anchor="w"
                     ).grid(row=6, column=0, columnspan=4, sticky="w",
                            padx=10, pady=(0, 10))

    # ── OpenOCD 启动 / 停止 ───────────────────────────────────────────────────
    def _start_openocd(self):
        if self._openocd_proc and self._openocd_proc.poll() is None:
            self._log_append("⚠ OpenOCD 已在运行中", "err")
            return
        if not os.path.exists(_OPENOCD_EXE):
            self._log_append(f"✗ 未找到 OpenOCD：{_OPENOCD_EXE}", "err")
            return
        host   = self._ocd_host_var.get().strip()  or "ehub.local"
        port   = self._ocd_port_var.get().strip()  or "6000"
        speed  = self._ocd_speed_var.get().strip() or "1000"
        target = OCD_TARGET_MAP.get(self._ocd_target_var.get(), "stm32f1x")
        transport = OCD_TRANSPORT_MAP.get(self._ocd_transport_var.get(), "swd")
        cmd = [
            _OPENOCD_EXE, "-s", _OPENOCD_SCRIPTS,
            "-c", "adapter driver cmsis-dap",
            "-c", "cmsis-dap backend tcp",
            "-c", f"cmsis-dap tcp host {host}",
            "-c", f"cmsis-dap tcp port {port}",
            "-c", f"transport select {transport}",
            "-c", f"source [find target/{target}.cfg]",
            "-c", f"adapter speed {speed}",
            "-c", "reset_config none",
            "-c", "cortex_m reset_config sysresetreq",
        ]
        try:
            self._openocd_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                cwd=_OPENOCD_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            pid = self._openocd_proc.pid
            self._log_append(
                f"▶ OpenOCD 已启动  PID={pid}  目标={target}  方式={transport.upper()}  {host}:{port}", "config")
            if self._ocd_pid_lbl:   self._ocd_pid_lbl.configure(text=f"PID: {pid}")
            if self._ocd_start_btn: self._ocd_start_btn.configure(state="disabled")
            if self._ocd_stop_btn:  self._ocd_stop_btn.configure(state="normal")
            threading.Thread(target=self._read_openocd_output, daemon=True).start()
        except Exception as e:
            self._log_append(f"✗ OpenOCD 启动失败: {e}", "err")

    def _stop_openocd(self):
        if self._openocd_proc and self._openocd_proc.poll() is None:
            self._openocd_proc.terminate()
            self._log_append("■ OpenOCD 停止命令已发送", "config")
        else:
            self._log_append("ℹ OpenOCD 未在运行", "config")
            self._openocd_proc = None

    def _read_openocd_output(self):
        proc = self._openocd_proc
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                if line:
                    self._log_q.put((-2, line.encode("utf-8", errors="replace")))
        except Exception:
            pass
        finally:
            self.after(0, self._on_openocd_exit)

    def _on_openocd_exit(self):
        ret = self._openocd_proc.returncode if self._openocd_proc else None
        self._log_append(f"■ OpenOCD 已退出 (ret={ret})", "config")
        self._openocd_proc = None
        try:
            if self._ocd_pid_lbl:   self._ocd_pid_lbl.configure(text="PID: --")
            if self._ocd_start_btn: self._ocd_start_btn.configure(state="normal")
            if self._ocd_stop_btn:  self._ocd_stop_btn.configure(state="disabled")
        except Exception:
            pass


if __name__ == "__main__":
    app = EHUBApp()
    app.mainloop()
