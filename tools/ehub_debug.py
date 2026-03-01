"""
EHUB Debug Tool  v1.0
上位机调试工具 — CDC ↔ Bus Bridge
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

CFG_BAUD      = 0x01
CFG_SPI_SPD   = 0x02
CFG_SPI_MODE  = 0x03
CFG_I2C_SPD   = 0x04
CFG_CAN_BAUD  = 0x05

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
    "1 Mbps":   1000000,
    "500 kbps": 500000,
    "250 kbps": 250000,
    "125 kbps": 125000,
}
I2C_SPEED_MAP = {
    "100 kHz (Standard)": 100000,
    "400 kHz (Fast)":     400000,
}

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
        while self._alive:
            try:
                chunk = self._port.read(256)
                if chunk:
                    self.rx_count += len(chunk)
                    self._parser.feed(chunk)
            except Exception as e:
                self._alive = False
                self._on_error(str(e))
                break

# ─── 颜色 & 字体常量 ──────────────────────────────────────────────────────────
COLOR_SEND    = "#63a3f5"
COLOR_RECV    = "#5cd85c"
COLOR_CONFIG  = "#f2a93b"
COLOR_ERR     = "#f25c5c"
COLOR_TS      = "#888888"
MONO_FONT     = ("Consolas", 11)
LABEL_FONT    = ("Segoe UI", 11)
TITLE_FONT    = ("Segoe UI Semibold", 12)
PROTO_LABELS  = ["USART1", "RS485", "RS422", "SPI", "I2C", "CAN"]

# ─── 主应用 ───────────────────────────────────────────────────────────────────
class EHUBApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EHUB Debug Tool  v1.0")
        self.geometry("1050x720")
        self.minsize(900, 600)
        self._serial  = SerialManager(self._on_frame, self._on_serial_error)
        self._cur_proto = "USART1"
        self._log_q: queue.Queue = queue.Queue()
        self._build_ui()
        self._refresh_ports()
        self._poll_log()

    # ── UI 构建 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_topbar()
        self._build_sidebar()
        self._build_main()
        self._build_statusbar()

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color=("#e8eaf0", "#1e2233"))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(6, weight=1)

        ctk.CTkLabel(bar, text="  EHUB Debug Tool", font=("Segoe UI Semibold", 16),
                     text_color=("#2563eb", "#63a3f5")).grid(row=0, column=0, padx=(10, 20))

        ctk.CTkLabel(bar, text="Port:", font=LABEL_FONT).grid(row=0, column=1, padx=(0, 4))
        self._port_var = ctk.StringVar()
        self._port_cb  = ctk.CTkComboBox(bar, variable=self._port_var, width=120, font=MONO_FONT)
        self._port_cb.grid(row=0, column=2, padx=(0, 4))

        ctk.CTkButton(bar, text="↺", width=30, command=self._refresh_ports,
                      font=("Segoe UI", 14)).grid(row=0, column=3, padx=(0, 10))

        ctk.CTkLabel(bar, text="Baud:", font=LABEL_FONT).grid(row=0, column=4, padx=(0, 4))
        self._baud_var = ctk.StringVar(value="115200")
        ctk.CTkComboBox(bar, variable=self._baud_var, width=100, font=MONO_FONT,
                        values=["9600","19200","38400","57600","115200","230400","460800","921600"]
                        ).grid(row=0, column=5, padx=(0, 14))

        self._conn_btn = ctk.CTkButton(bar, text="  Connect", width=110,
                                       fg_color=("#16a34a","#15803d"),
                                       hover_color=("#15803d","#166534"),
                                       command=self._toggle_connect, font=TITLE_FONT)
        self._conn_btn.grid(row=0, column=6, padx=10, sticky="w")

        # theme toggle
        self._theme_var = ctk.StringVar(value="🌙")
        ctk.CTkButton(bar, textvariable=self._theme_var, width=36,
                      command=self._toggle_theme, font=("Segoe UI", 14)
                      ).grid(row=0, column=7, padx=(0, 10), sticky="e")

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=150, corner_radius=0, fg_color=("#d1d5e8","#161b2e"))
        sb.grid(row=1, column=0, sticky="nsew", padx=0)
        sb.grid_propagate(False)

        ctk.CTkLabel(sb, text="Protocol", font=("Segoe UI Semibold", 13),
                     text_color=("#475569","#94a3b8")).pack(pady=(18, 8))

        self._proto_btns: dict[str, ctk.CTkButton] = {}
        for name in PROTO_LABELS:
            btn = ctk.CTkButton(sb, text=name, width=120, height=36,
                                anchor="w", font=TITLE_FONT,
                                fg_color="transparent",
                                text_color=("#1e293b","#e2e8f0"),
                                hover_color=("#c7d0eb","#1e2a45"),
                                command=lambda n=name: self._select_proto(n),
                                corner_radius=8)
            btn.pack(pady=3, padx=12)
            self._proto_btns[name] = btn

        # stat labels
        sb_bot = ctk.CTkFrame(sb, fg_color="transparent")
        sb_bot.pack(side="bottom", pady=14, padx=10)
        self._stat_tx  = ctk.CTkLabel(sb_bot, text="TX:  0 B", font=MONO_FONT,
                                       text_color=COLOR_SEND, anchor="w")
        self._stat_rx  = ctk.CTkLabel(sb_bot, text="RX:  0 B", font=MONO_FONT,
                                       text_color=COLOR_RECV, anchor="w")
        self._stat_err = ctk.CTkLabel(sb_bot, text="ERR: 0",   font=MONO_FONT,
                                       text_color=COLOR_ERR,  anchor="w")
        for lbl in (self._stat_tx, self._stat_rx, self._stat_err):
            lbl.pack(anchor="w")
        self._errors = 0

        self._select_proto("USART1")

    def _build_main(self):
        self._main_frame = ctk.CTkFrame(self, corner_radius=0,
                                         fg_color=("#f1f4fb","#111827"))
        self._main_frame.grid(row=1, column=1, sticky="nsew", padx=0)
        self._main_frame.columnconfigure(0, weight=1)
        self._main_frame.rowconfigure(1, weight=1)

        # ── config card ──────────────────────────────────────────────────────
        self._cfg_frame = ctk.CTkFrame(self._main_frame, corner_radius=10,
                                        fg_color=("#e2e8f4","#1a2236"))
        self._cfg_frame.grid(row=0, column=0, sticky="ew", padx=14, pady=(12,6))
        self._cfg_frame.columnconfigure(0, weight=1)
        self._cfg_widgets: dict = {}

        # ── bottom splitter (send + log) ──────────────────────────────────────
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

        ctk.CTkLabel(card, text="↑  Send", font=TITLE_FONT,
                     text_color=COLOR_SEND).grid(row=0, column=0, columnspan=4,
                                                  sticky="w", padx=10, pady=(8,4))

        ctk.CTkLabel(card, text="Mode:", font=LABEL_FONT).grid(row=1, column=0, padx=10)
        self._send_mode = ctk.StringVar(value="text")
        ctk.CTkRadioButton(card, text="Text", variable=self._send_mode,
                           value="text", font=LABEL_FONT).grid(row=1, column=1, padx=4, sticky="w")
        ctk.CTkRadioButton(card, text="HEX",  variable=self._send_mode,
                           value="hex",  font=LABEL_FONT).grid(row=1, column=2, padx=4, sticky="w")

        self._send_entry = ctk.CTkEntry(card, height=34, font=MONO_FONT,
                                         placeholder_text="Enter text or hex bytes …")
        self._send_entry.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=6)
        self._send_entry.bind("<Return>", lambda _: self._do_send())

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=3, column=0, columnspan=4, sticky="ew", padx=10, pady=(0,8))
        ctk.CTkButton(btn_row, text="  Send", width=90, command=self._do_send,
                      fg_color=("#2563eb","#1d4ed8")).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_row, text="Clear", width=72, fg_color=("gray70","#374151"),
                      command=lambda: self._send_entry.delete(0, "end")).pack(side="left")

    def _build_log_panel(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=("#e2e8f4","#1a2236"))
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8,2))
        ctk.CTkLabel(hdr, text="↓  Receive Log", font=TITLE_FONT,
                     text_color=COLOR_RECV).pack(side="left")
        ctk.CTkButton(hdr, text="Save", width=60, fg_color=("gray60","#374151"),
                      command=self._save_log, height=26).pack(side="right", padx=(4,0))
        ctk.CTkButton(hdr, text="Clear", width=60, fg_color=("gray60","#374151"),
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
        self._stat_conn = ctk.CTkLabel(bar, text="○ Disconnected",
                                        font=("Segoe UI", 11),
                                        text_color=COLOR_ERR)
        self._stat_conn.grid(row=0, column=0, padx=12)
        ctk.CTkLabel(bar, text="│", font=("Segoe UI", 11),
                     text_color=("gray50","gray40")).grid(row=0, column=1)
        ctk.CTkLabel(bar, text="Bridge Protocol v1.0",
                     font=("Segoe UI", 11),
                     text_color=("gray50","gray50")).grid(row=0, column=2, sticky="w", padx=8)

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

        ctk.CTkLabel(self._cfg_frame, text=f"⚙  {name} Configuration",
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

        ctk.CTkButton(self._cfg_frame, text="Apply Config", width=120,
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
        self._row("Baud Rate:", 1, cb)
        self._cfg_widgets["baud"] = var

    def _cfg_spi(self):
        spd_var  = ctk.StringVar(value=SPI_SPEED_LABELS[2])
        mode_var = ctk.StringVar(value="Mode 0 (CPOL=0 CPHA=0)")
        ctk.CTkComboBox(self._cfg_frame, variable=spd_var, width=200,
                         values=SPI_SPEED_LABELS, font=MONO_FONT
                         ).grid(row=1, column=1, sticky="w", padx=(0,20), pady=3)
        ctk.CTkLabel(self._cfg_frame, text="Speed:", font=LABEL_FONT
                     ).grid(row=1, column=0, sticky="w", padx=12, pady=3)
        modes = ["Mode 0 (CPOL=0 CPHA=0)","Mode 1 (CPOL=0 CPHA=1)",
                 "Mode 2 (CPOL=1 CPHA=0)","Mode 3 (CPOL=1 CPHA=1)"]
        ctk.CTkComboBox(self._cfg_frame, variable=mode_var, width=200,
                         values=modes, font=MONO_FONT
                         ).grid(row=2, column=1, sticky="w", padx=(0,20), pady=3)
        ctk.CTkLabel(self._cfg_frame, text="Mode:", font=LABEL_FONT
                     ).grid(row=2, column=0, sticky="w", padx=12, pady=3)
        self._cfg_widgets["spi_spd"]  = spd_var
        self._cfg_widgets["spi_mode"] = mode_var

        # extra SPI-specific I/O params shown for reference
        ctk.CTkLabel(self._cfg_frame,
                     text="ℹ  CS pin is controlled externally (not by firmware)",
                     font=("Segoe UI", 10), text_color="gray"
                     ).grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(0,2))

    def _cfg_i2c(self):
        spd_var  = ctk.StringVar(value="100 kHz (Standard)")
        self._row("Speed:", 1,
                  ctk.CTkComboBox(self._cfg_frame, variable=spd_var, width=200,
                                   values=list(I2C_SPEED_MAP.keys()), font=MONO_FONT))
        self._cfg_widgets["i2c_spd"] = spd_var

        # extra fields for I2C operation
        for row, (lbl, ph, key) in enumerate([
            ("Slave Addr (7-bit hex):", "0x3C", "i2c_addr"),
            ("Reg Addr (hex, opt):",    "0x00", "i2c_reg"),
            ("Read Len (bytes):",       "1",    "i2c_rlen"),
        ], start=2):
            var = ctk.StringVar(value="")
            e   = ctk.CTkEntry(self._cfg_frame, placeholder_text=ph,
                                textvariable=var, width=120, font=MONO_FONT)
            ctk.CTkLabel(self._cfg_frame, text=lbl, font=LABEL_FONT
                         ).grid(row=row, column=0, sticky="w", padx=12, pady=3)
            e.grid(row=row, column=1, sticky="w", padx=(0,20), pady=3)
            self._cfg_widgets[key] = var

    def _cfg_can(self):
        baud_var = ctk.StringVar(value="500 kbps")
        self._row("CAN Baud:", 1,
                  ctk.CTkComboBox(self._cfg_frame, variable=baud_var,
                                   width=160, values=list(CAN_BAUD_MAP.keys()), font=MONO_FONT))
        ide_var = ctk.StringVar(value="Standard 11-bit")
        self._row("Frame Type:", 2,
                  ctk.CTkComboBox(self._cfg_frame, variable=ide_var,
                                   width=180, values=["Standard 11-bit","Extended 29-bit"], font=MONO_FONT))
        id_var = ctk.StringVar(value="0x123")
        self._row("CAN ID (hex):", 3,
                  ctk.CTkEntry(self._cfg_frame, textvariable=id_var, width=110, font=MONO_FONT))
        self._cfg_widgets.update(can_baud=baud_var, can_ide=ide_var, can_id=id_var)

    # ── Apply Config ──────────────────────────────────────────────────────────
    def _apply_config(self):
        if not self._serial.connected:
            self._log_append("⚠ Not connected", "err"); return

        name = self._cur_proto
        frames = []

        if name in ("USART1", "RS485", "RS422"):
            baud = int(self._cfg_widgets["baud"].get().replace(",",""))
            iface = CH[name]
            frames.append(build_config_frame(iface, CFG_BAUD, baud))
            self._log_append(f"[Config] {name}  baud→{baud}", "config")

        elif name == "SPI":
            idx  = SPI_SPEED_LABELS.index(self._cfg_widgets["spi_spd"].get())
            mode = int(self._cfg_widgets["spi_mode"].get().split()[1])
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_SPD,  idx))
            frames.append(build_config_frame(CH["SPI"], CFG_SPI_MODE, mode))
            self._log_append(f"[Config] SPI  speed_idx={idx}  mode={mode}", "config")

        elif name == "I2C":
            spd = I2C_SPEED_MAP[self._cfg_widgets["i2c_spd"].get()]
            frames.append(build_config_frame(CH["I2C_W"], CFG_I2C_SPD, spd))
            self._log_append(f"[Config] I2C  speed={spd//1000} kHz", "config")

        elif name == "CAN":
            baud = CAN_BAUD_MAP[self._cfg_widgets["can_baud"].get()]
            frames.append(build_config_frame(CH["CAN"], CFG_CAN_BAUD, baud))
            self._log_append(f"[Config] CAN  baud={baud}", "config")

        for f in frames:
            self._serial.send(f)
        self._update_stats()

    # ── Send ──────────────────────────────────────────────────────────────────
    def _do_send(self):
        if not self._serial.connected:
            self._log_append("⚠ Not connected", "err"); return

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
            ch_str, frame = payload   # returns (ch_key, frame)
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
        ide     = 1 if "29" in self._cfg_widgets["can_ide"].get() else 0
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
                self._handle_frame(ch, data)
                self._update_stats()
        except Exception:
            pass
        self.after(40, self._poll_log)

    def _handle_frame(self, ch: int, data: bytes):
        hex_str = " ".join(f"{b:02X}" for b in data)
        ch_name = CH_NAME.get(ch, f"0x{ch:02X}")

        if ch == CH["CONFIG"]:
            status = "OK" if len(data) >= 2 and data[1] == 0 else "FAIL"
            target = CH_NAME.get(data[0], f"0x{data[0]:02X}") if data else "?"
            self._log_append(f"← [CONFIG/{target}]  {status}", "config")
        else:
            # try ASCII decode for display
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
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if path:
            content = self._log.get("1.0", "end")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    # ── Serial helpers ────────────────────────────────────────────────────────
    def _toggle_connect(self):
        if self._serial.connected:
            self._serial.disconnect()
            self._conn_btn.configure(text="  Connect",
                                      fg_color=("#16a34a","#15803d"),
                                      hover_color=("#15803d","#166534"))
            self._stat_conn.configure(text="○ Disconnected", text_color=COLOR_ERR)
            self._log_append("Disconnected.", "err")
        else:
            port = self._port_var.get()
            if not port:
                self._log_append("⚠ No port selected", "err"); return
            try:
                baud = int(self._baud_var.get().replace(",",""))
                self._serial.connect(port, baud)
                self._conn_btn.configure(text="  Disconnect",
                                          fg_color=("#dc2626","#b91c1c"),
                                          hover_color=("#b91c1c","#991b1b"))
                self._stat_conn.configure(
                    text=f"● {port}  {baud}", text_color=COLOR_RECV)
                self._log_append(f"Connected to {port} @ {baud}", "config")
            except Exception as e:
                self._log_append(f"⚠ {e}", "err")

    def _on_serial_error(self, msg: str):
        self._log_q.put((-1, msg.encode()))

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_cb.configure(values=ports if ports else ["(none)"])
        if ports:
            self._port_var.set(ports[0])

    def _update_stats(self):
        self._stat_tx.configure(text=f"TX:  {self._serial.tx_count} B")
        self._stat_rx.configure(text=f"RX:  {self._serial.rx_count} B")
        self._stat_err.configure(text=f"ERR: {self._errors}")

    def _toggle_theme(self):
        mode = ctk.get_appearance_mode()
        new  = "light" if mode == "Dark" else "dark"
        ctk.set_appearance_mode(new)
        self._theme_var.set("☀" if new == "light" else "🌙")


if __name__ == "__main__":
    app = EHUBApp()
    app.mainloop()
