"""
EHUB 调试工具  v1.1
上位机 — CDC ↔ 总线桥接调试器
依赖: pip install customtkinter pyserial
"""

import customtkinter as ctk
import serial
import serial.tools.list_ports
import threading
import struct
import time
import queue
from datetime import datetime

# ─── 主题设置 ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ─── 协议常量 ─────────────────────────────────────────────────────────────────
SOF0_CMD, SOF1, SOF0_RPY = 0xAA, 0x55, 0xBB
CH = {
    "USART1":  0x01,
    "RS485":   0x02,
    "RS422":   0x03,
    "SPI":     0x04,
    "I2C_W":   0x05,
    "I2C_R":   0x06,
    "CAN":     0x07,
    "CONFIG":  0xF0,
}
CH_NAME = {v: k for k, v in CH.items()}

CFG_PING     = 0x00   # 设备识别 PING（iface=0xF0 param=0x00）
CFG_BAUD     = 0x01
CFG_SPI_SPD  = 0x02
CFG_SPI_MODE = 0x03
CFG_I2C_SPD  = 0x04
CFG_CAN_BAUD = 0x05

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
class SerialManager:
    def __init__(self, on_frame, on_error):
        self._on_frame = on_frame
        self._on_error  = on_error
        self._port: serial.Serial | None = None
        self._parser = FrameParser(on_frame)
        self._thread: threading.Thread | None = None
        self._alive  = False
        self.tx_count = 0
        self.rx_count = 0

    @property
    def connected(self):
        return self._port is not None and self._port.is_open

    def connect(self, portname: str, baud: int):
        self._port  = serial.Serial(portname, baud, timeout=0.05)
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._alive = False
        if self._port and self._port.is_open:
            self._port.close()

    def send(self, data: bytes):
        if not self.connected: return
        self._port.write(data)
        self.tx_count += len(data)

    def _run(self):
        _REMOVE_SIGNS = (
            "ClearCommError", "PermissionError(13", "PermissionError(5",
            "handle is invalid", "access is denied",
            "\u8bbe\u5907\u4e0d\u8bc6\u522b", "\u6ca1\u6709\u8fde\u63a5", "\u62d2\u7edd\u8bbf\u95ee",
        )
        while self._alive:
            try:
                chunk = self._port.read(256)
                if chunk:
                    self.rx_count += len(chunk)
                    self._parser.feed(chunk)
            except Exception as e:
                self._alive = False
                msg = str(e)
                is_removal = any(k.lower() in msg.lower() for k in _REMOVE_SIGNS)
                self._on_error("__REMOVED__" if is_removal else msg)
                break

# ─── 颜色 & 字体常量 ──────────────────────────────────────────────────────────
COLOR_SEND    = "#63a3f5"
COLOR_RECV    = "#5cd85c"
COLOR_CONFIG  = "#f2a93b"
COLOR_ERR     = "#f25c5c"
COLOR_TS      = "#888888"
MONO_FONT     = ("Consolas", 11)
LABEL_FONT    = ("微软雅黑", 11)
TITLE_FONT    = ("微软雅黑", 12, "bold")
PROTO_LABELS  = ["USART1", "RS485", "RS422", "SPI", "I2C", "CAN"]

# ─── 主应用 ───────────────────────────────────────────────────────────────────
class EHUBApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EHUB 调试工具  v1.1")
        self.geometry("1100x740")
        self.minsize(920, 620)
        self._serial      = SerialManager(self._on_frame, self._on_serial_error)
        self._cur_proto   = "USART1"
        self._log_q: queue.Queue = queue.Queue()
        self._auto_thread: threading.Thread | None = None
        self._build_ui()
        self._refresh_ports()
        self._poll_log()
        # 启动时自动检测，之后每秒热插拔监测
        self.after(600, self._auto_detect)
        self.after(1000, self._hotplug_watch)

    # ── UI 构建 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_topbar()
        self._build_sidebar()
        self._build_main()
        self._build_statusbar()
        self._select_proto("USART1")

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color=("#e8eaf0", "#1e2233"))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(7, weight=1)

        ctk.CTkLabel(bar, text="  EHUB 调试工具", font=("微软雅黑", 16, "bold"),
                     text_color=("#2563eb", "#63a3f5")).grid(row=0, column=0, padx=(10, 20))

        ctk.CTkLabel(bar, text="串口：", font=LABEL_FONT).grid(row=0, column=1, padx=(0, 4))
        self._port_var = ctk.StringVar()
        self._port_cb  = ctk.CTkComboBox(bar, variable=self._port_var, width=120, font=MONO_FONT)
        self._port_cb.grid(row=0, column=2, padx=(0, 4))

        ctk.CTkButton(bar, text="↺", width=30, command=self._refresh_ports,
                      font=("微软雅黑", 14)).grid(row=0, column=3, padx=(0, 6))

        # 自动检测按钮
        self._detect_btn = ctk.CTkButton(bar, text="🔍 自动检测", width=100,
                                          fg_color=("#7c3aed","#6d28d9"),
                                          hover_color=("#6d28d9","#5b21b6"),
                                          command=self._auto_detect, font=LABEL_FONT)
        self._detect_btn.grid(row=0, column=4, padx=(0, 14))

        ctk.CTkLabel(bar, text="波特率：", font=LABEL_FONT).grid(row=0, column=5, padx=(0, 4))
        self._baud_var = ctk.StringVar(value="115200")
        ctk.CTkComboBox(bar, variable=self._baud_var, width=100, font=MONO_FONT,
                        values=["9600","19200","38400","57600","115200","230400","460800","921600"]
                        ).grid(row=0, column=6, padx=(0, 14))

        self._conn_btn = ctk.CTkButton(bar, text="  连接", width=100,
                                       fg_color=("#16a34a","#15803d"),
                                       hover_color=("#15803d","#166534"),
                                       command=self._toggle_connect, font=TITLE_FONT)
        self._conn_btn.grid(row=0, column=7, padx=10, sticky="w")

        self._theme_var = ctk.StringVar(value="🌙")
        ctk.CTkButton(bar, textvariable=self._theme_var, width=36,
                      command=self._toggle_theme, font=("微软雅黑", 14)
                      ).grid(row=0, column=8, padx=(0, 10), sticky="e")

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
        card.columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="↑  发送数据", font=TITLE_FONT,
                     text_color=COLOR_SEND).grid(row=0, column=0, columnspan=4,
                                                  sticky="w", padx=10, pady=(8,4))

        ctk.CTkLabel(card, text="格式：", font=LABEL_FONT).grid(row=1, column=0, padx=10)
        self._send_mode = ctk.StringVar(value="text")
        ctk.CTkRadioButton(card, text="文本", variable=self._send_mode,
                           value="text", font=LABEL_FONT).grid(row=1, column=1, padx=4, sticky="w")
        ctk.CTkRadioButton(card, text="HEX", variable=self._send_mode,
                           value="hex",  font=LABEL_FONT).grid(row=1, column=2, padx=4, sticky="w")

        self._send_entry = ctk.CTkEntry(card, height=34, font=MONO_FONT,
                                         placeholder_text="输入文本或 HEX 字节（空格分隔），回车发送…")
        self._send_entry.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=6)
        self._send_entry.bind("<Return>", lambda _: self._do_send())

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=3, column=0, columnspan=4, sticky="ew", padx=10, pady=(0,8))
        ctk.CTkButton(btn_row, text="  发送", width=90, command=self._do_send,
                      fg_color=("#2563eb","#1d4ed8")).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_row, text="清除", width=72, fg_color=("gray70","#374151"),
                      command=lambda: self._send_entry.delete(0, "end")).pack(side="left")

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
        self._stat_tip = ctk.CTkLabel(bar, text="桥接协议 v1.1  |  插入 EHUB 设备后点击 🔍 自动检测（或等待启动自动识别）",
                     font=("微软雅黑", 11),
                     text_color=("gray50","gray50"))
        self._stat_tip.grid(row=0, column=2, sticky="w", padx=8)

    # ── CONFIG 面板渲染 ────────────────────────────────────────────────────────
    def _select_proto(self, name: str):
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

        ctk.CTkLabel(self._cfg_frame, text=f"⚙  {name} 参数配置",
                     font=TITLE_FONT, text_color=COLOR_CONFIG
                     ).grid(row=0, column=0, columnspan=6, sticky="w", padx=12, pady=(8,6))

        if name in ("USART1", "RS485", "RS422"):
            self._cfg_baud(name)
        elif name == "SPI":
            self._cfg_spi()
        elif name == "I2C":
            self._cfg_i2c()
        elif name == "CAN":
            self._cfg_can()

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
        self._cfg_widgets["spi_spd"]  = spd_var
        self._cfg_widgets["spi_mode"] = mode_var

        ctk.CTkLabel(self._cfg_frame,
                     text="ℹ  片选（CS）由外部硬件控制，固件不操作 CS 引脚",
                     font=("微软雅黑", 10), text_color="gray"
                     ).grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(0,2))

    def _cfg_i2c(self):
        spd_var  = ctk.StringVar(value="100 kHz（标准模式）")
        self._row("通信速率：", 1,
                  ctk.CTkComboBox(self._cfg_frame, variable=spd_var, width=200,
                                   values=list(I2C_SPEED_MAP.keys()), font=MONO_FONT))
        self._cfg_widgets["i2c_spd"] = spd_var

        for row, (lbl, ph, key) in enumerate([
            ("从机地址（7位十六进制）：", "0x3C", "i2c_addr"),
            ("寄存器地址（可选）：",      "0x00", "i2c_reg"),
            ("读取字节数：",              "1",    "i2c_rlen"),
        ], start=2):
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

    # ── Apply Config ──────────────────────────────────────────────────────────
    def _apply_config(self):
        if not self._serial.connected:
            self._log_append("⚠ 设备未连接", "err"); return

        name = self._cur_proto
        frames = []

        if name in ("USART1", "RS485", "RS422"):
            baud = int(self._cfg_widgets["baud"].get().replace(",",""))
            iface = CH[name]
            frames.append(build_config_frame(iface, CFG_BAUD, baud))
            self._log_append(f"[配置] {name}  波特率→{baud}", "config")

        elif name == "SPI":
            idx  = SPI_SPEED_LABELS.index(self._cfg_widgets["spi_spd"].get())
            raw_mode = self._cfg_widgets["spi_mode"].get()
            mode = int(raw_mode.split()[1])   # "模式 0 ..." → 0
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_SPD,  idx))
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_MODE, mode))
            self._log_append(f"[配置] SPI  速率索引={idx}  模式={mode}", "config")

        elif name == "I2C":
            spd = I2C_SPEED_MAP[self._cfg_widgets["i2c_spd"].get()]
            frames.append(build_config_frame(CH["I2C_W"], CFG_I2C_SPD, spd))
            self._log_append(f"[配置] I2C  速率={spd//1000} kHz", "config")

        elif name == "CAN":
            baud = CAN_BAUD_MAP[self._cfg_widgets["can_baud"].get()]
            frames.append(build_config_frame(CH["CAN"], CFG_CAN_BAUD, baud))
            self._log_append(f"[配置] CAN  波特率={baud}", "config")

        for f in frames:
            self._serial.send(f)
        self._update_stats()

    # ── Send ──────────────────────────────────────────────────────────────────
    def _do_send(self):
        if not self._serial.connected:
            self._log_append("⚠ 设备未连接", "err"); return

        raw = self._send_entry.get()
        if not raw.strip(): return

        mode = self._send_mode.get()
        name = self._cur_proto

        try:
            # build payload
            if name == "CAN":
                payload = self._build_can_payload()
            elif name == "I2C":
                payload = self._build_i2c_payload(raw, mode)
            else:
                payload = self._parse_input(raw, mode)
                ch_key  = name    # USART1 / RS485 / RS422 / SPI
        except Exception as e:
            self._log_append(f"⚠ Input error: {e}", "err"); return

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
        reg_s  = self._cfg_widgets.get("i2c_reg",  ctk.StringVar(value="")).get().strip()
        rlen_s = self._cfg_widgets.get("i2c_rlen", ctk.StringVar(value="1")).get().strip()
        data   = self._parse_input(raw, mode) if raw.strip() else b""

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
                else:
                    self._handle_frame(ch, data)
                    self._update_stats()
        except Exception:
            pass
        self.after(40, self._poll_log)

    def _handle_frame(self, ch: int, data: bytes):
        hex_str = " ".join(f"{b:02X}" for b in data)
        ch_name = CH_NAME.get(ch, f"0x{ch:02X}")

        if ch == CH["CONFIG"]:
            # 自动连接时的 PING 回复（data = [0xF0, 0x00, E, H, U, B]）
            if (len(data) >= 6 and data[0] == 0xF0 and data[1] == 0x00
                    and data[2:6] == b'EHUB'):
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
            self._serial.disconnect()
            self._conn_btn.configure(text="  连接",
                                      fg_color=("#16a34a","#15803d"),
                                      hover_color=("#15803d","#166534"))
            self._stat_conn.configure(text="○  未连接", text_color=COLOR_ERR)
            self._stat_tip.configure(text="桥接协议 v1.1  |  插入设备后点击 🔍 自动检测")
            self._log_append("已断开连接。", "err")
        else:
            port = self._port_var.get()
            if not port or port == "(无可用串口)":
                self._log_append("⚠ 未选择串口", "err"); return
            self._do_connect(port, int(self._baud_var.get()))

    def _do_connect(self, port: str, baud: int):
        """实际执行连接操作（可由自动检测或手动按钮调用）"""
        try:
            self._serial.connect(port, baud)
            self._conn_btn.configure(text="  断开",
                                      fg_color=("#dc2626","#b91c1c"),
                                      hover_color=("#b91c1c","#991b1b"))
            self._stat_conn.configure(
                text=f"●  {port}  {baud} bps", text_color=COLOR_RECV)
            self._stat_tip.configure(text=f"已连接  |  EHUB 桥接协议 v1.1")
            self._port_var.set(port)
            self._log_append(f"已连接到 {port} @ {baud} bps", "config")
        except Exception as e:
            self._log_append(f"⚠ 连接失败：{e}", "err")

    def _on_serial_error(self, msg: str):
        """串口读取线程出错 → 推送到日志队列（区分拔出与其他错误）"""
        self._log_q.put((-1, msg.encode()))
        self.after(0, self._on_disconnect_event)

    def _on_disconnect_event(self):
        self._conn_btn.configure(text="  \u8fde\u63a5",
                                  fg_color=("#16a34a","#15803d"),
                                  hover_color=("#15803d","#166534"))
        self._stat_conn.configure(text="\u25cb  \u672a\u8fde\u63a5", text_color=COLOR_ERR)
        self._stat_tip.configure(text="\u8bbe\u5907\u5df2\u79fb\u9664  |  \u91cd\u65b0\u63d2\u5165\u540e\u5c06\u81ea\u52a8\u8fde\u63a5")

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_cb.configure(values=ports if ports else ["(无可用串口)"])
        if ports:
            self._port_var.set(ports[0])

    # ── 自动检测 ──────────────────────────────────────────────────────────────
    def _auto_detect(self):
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
        self._stat_tx.configure(text=f"发送:  {self._serial.tx_count} B")
        self._stat_rx.configure(text=f"接收:  {self._serial.rx_count} B")
        self._stat_err.configure(text=f"错误: {self._errors}")

    def _hotplug_watch(self):
        """每秒静默检测 EHUB 设备插入，断开状态下自动重连。"""
        if not self._serial.connected:
            port = find_ehub_port()
            if port:
                self._log_append(f"\u26a1 EHUB \u8bbe\u5907\u91cd\u65b0\u63d2\u5165\uff1a{port}\uff0c\u6b63\u5728\u8fde\u63a5\u2026", "config")
                self._do_connect(port, PROBE_BAUD)
        self.after(1000, self._hotplug_watch)

    def _toggle_theme(self):
        mode = ctk.get_appearance_mode()
        new  = "light" if mode == "Dark" else "dark"
        ctk.set_appearance_mode(new)
        self._theme_var.set("☀" if new == "light" else "🌙")


if __name__ == "__main__":
    app = EHUBApp()
    app.mainloop()
