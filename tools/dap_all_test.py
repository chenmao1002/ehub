#!/usr/bin/env python3
"""
EHUB DAP Speed Test — tests all three DAP modes (wired, DAP_TCP, elaphureLink)
against STM32F103 target.

Usage: python dap_all_test.py
"""
import subprocess
import time
import os
import sys
import tempfile

XPACK_OCD = r"F:/vscode/openstm32/xpack-openocd/xpack-openocd-0.12.0-4/bin/openocd.exe"
XPACK_SCRIPTS = r"F:/vscode/openstm32/xpack-openocd/xpack-openocd-0.12.0-4/openocd/scripts"
CUSTOM_OCD = r"C:\Users\MC\Desktop\wifidap\openocd\src\openocd.exe"
CUSTOM_SCRIPTS = r"C:\Users\MC\Desktop\wifidap\openocd\tcl"
HEX_FILE = r"C:/Users/MC/Desktop/wifidap/stm32f103_test/MDK-ARM/stm32f103_test/stm32f103_test.hex"

def run_openocd(ocd_exe, ocd_scripts, cfg_content, tcl_content, timeout=30):
    """Run OpenOCD with config + Tcl script files, return output string."""
    cfg_path = os.path.join(tempfile.gettempdir(), "dap_test.cfg")
    tcl_path = os.path.join(tempfile.gettempdir(), "dap_test.tcl")
    with open(cfg_path, 'w') as f:
        f.write(cfg_content)
    with open(tcl_path, 'w') as f:
        f.write(tcl_content)
    cmd = [ocd_exe, "-s", ocd_scripts, "-f", cfg_path, "-f", tcl_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout + "\n" + r.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {e}"


WIRED_CFG = """\
source [find interface/cmsis-dap.cfg]
cmsis-dap vid_pid 0x0D28 0x0204
cmsis-dap backend hid
transport select swd
set CHIPNAME stm32f1x
source [find target/stm32f1x.cfg]
adapter speed 1000
reset_config none
cortex_m reset_config sysresetreq
"""

WIFI_TCP_CFG = """\
adapter driver cmsis-dap
cmsis-dap backend tcp
cmsis-dap tcp host 192.168.227.100
cmsis-dap tcp port 6000
cmsis-dap tcp min_timeout 500
transport select swd
set CHIPNAME stm32f1x
source [find target/stm32f1x.cfg]
adapter speed 1000
reset_config none
cortex_m reset_config sysresetreq
"""

READ_SPEED_TCL = """\
init
halt

# 4KB read
set t0 [ms]
mem2array a32 32 0x08000000 1024
set t1 [ms]
echo "RESULT_READ_4KB: [expr {$t1 - $t0}] ms"

# 16KB read
set t2 [ms]
mem2array b32 32 0x08000000 4096
set t3 [ms]
echo "RESULT_READ_16KB: [expr {$t3 - $t2}] ms"

# Vector table check
echo "RESULT_SP: [format 0x%08X $a32(0)]"
echo "RESULT_PC: [format 0x%08X $a32(1)]"

shutdown
"""

FLASH_TCL = f"""\
init
halt
stm32f1x mass_erase 0
set t0 [ms]
flash write_image {HEX_FILE}
set t1 [ms]
echo "RESULT_FLASH_WRITE: [expr {{$t1 - $t0}}] ms"
set t2 [ms]
verify_image {HEX_FILE}
set t3 [ms]
echo "RESULT_FLASH_VERIFY: [expr {{$t3 - $t2}}] ms"
reset
shutdown
"""


def extract_results(output):
    """Parse RESULT_ lines from OpenOCD output."""
    results = {}
    for line in output.split('\n'):
        if 'RESULT_' in line:
            parts = line.strip().split('RESULT_', 1)[1]
            key, _, val = parts.partition(':')
            results[key.strip()] = val.strip()
        if 'DPIDR' in line:
            results['DPIDR'] = line.strip()
        if 'Cortex' in line and 'detected' in line:
            results['CPU'] = line.strip()
        if 'Error' in line:
            results.setdefault('errors', []).append(line.strip())
    return results


def test_wired():
    print("=" * 60)
    print("  TEST 1: 有线 DAP (USB HID)")
    print("=" * 60)
    
    print("\n[读内存测速]")
    out = run_openocd(XPACK_OCD, XPACK_SCRIPTS, WIRED_CFG, READ_SPEED_TCL)
    r = extract_results(out)
    
    if 'DPIDR' in r:
        print(f"  ✓ {r['DPIDR']}")
    else:
        print("  ✗ 连接失败")
        for line in out.strip().split('\n')[-10:]:
            print(f"    {line}")
        return None
    
    if 'CPU' in r:
        print(f"  ✓ {r['CPU']}")
    for key in ['READ_4KB', 'READ_16KB', 'SP', 'PC']:
        if key in r:
            print(f"  → {key}: {r[key]}")
    for e in r.get('errors', []):
        if 'reset' not in e.lower():
            print(f"  ✗ {e}")
    
    res = {}
    if 'READ_4KB' in r:
        ms = float(r['READ_4KB'].split()[0])
        res['4KB_ms'] = ms
        res['4KB_KBs'] = 4.0 / (ms / 1000)
    if 'READ_16KB' in r:
        ms = float(r['READ_16KB'].split()[0])
        res['16KB_ms'] = ms
        res['16KB_KBs'] = 16.0 / (ms / 1000)
    return res


def test_wifi_tcp():
    print("\n" + "=" * 60)
    print("  TEST 2: WiFi DAP_TCP (OpenOCD TCP, port 6000)")
    print("=" * 60)
    
    if not os.path.exists(CUSTOM_OCD):
        print(f"  ✗ 找不到 TCP OpenOCD: {CUSTOM_OCD}")
        return None
    
    print("\n[读内存测速]")
    out = run_openocd(CUSTOM_OCD, CUSTOM_SCRIPTS, WIFI_TCP_CFG, READ_SPEED_TCL, timeout=120)
    r = extract_results(out)
    
    if 'DPIDR' in r:
        print(f"  ✓ {r['DPIDR']}")
    else:
        print("  ✗ 连接失败")
        for line in out.strip().split('\n')[-10:]:
            print(f"    {line}")
        return None
    
    if 'CPU' in r:
        print(f"  ✓ {r['CPU']}")
    for key in ['READ_4KB', 'READ_16KB', 'SP', 'PC']:
        if key in r:
            print(f"  → {key}: {r[key]}")
    for e in r.get('errors', []):
        print(f"  ✗ {e}")
    
    res = {}
    if 'READ_4KB' in r:
        ms = float(r['READ_4KB'].split()[0])
        res['4KB_ms'] = ms
        res['4KB_KBs'] = 4.0 / (ms / 1000)
    if 'READ_16KB' in r:
        ms = float(r['READ_16KB'].split()[0])
        res['16KB_ms'] = ms
        res['16KB_KBs'] = 16.0 / (ms / 1000)
    return res


def test_elaphurelink():
    import socket
    import struct
    
    print("\n" + "=" * 60)
    print("  TEST 3: elaphureLink (TCP port 3240)")
    print("=" * 60)
    
    HOST = "192.168.227.100"
    PORT = 3240
    TIMEOUT = 5.0
    
    def send_dap(sock, cmd):
        sock.sendall(bytes(cmd))
        try:
            return sock.recv(2048)
        except socket.timeout:
            return None
    
    def dap_transfer(sock, idx, cnt, *ops):
        cmd = [0x05, idx, cnt]
        for op in ops:
            cmd.extend(op)
        return send_dap(sock, cmd)
    
    def read_dp(sock, addr):
        req = (addr & 0x0C) | 0x02
        resp = dap_transfer(sock, 0, 1, [req])
        if resp and len(resp) >= 7 and resp[2] == 0x01:
            return struct.unpack_from('<I', resp, 3)[0]
        return None
    
    def write_dp(sock, addr, val):
        req = (addr & 0x0C) | 0x00
        data = list(struct.pack('<I', val))
        resp = dap_transfer(sock, 0, 1, [req] + data)
        return resp and len(resp) >= 3 and resp[2] == 0x01
    
    def write_ap(sock, addr, val):
        req = (addr & 0x0C) | 0x01
        data = list(struct.pack('<I', val))
        resp = dap_transfer(sock, 0, 1, [req] + data)
        return resp and len(resp) >= 3 and resp[2] == 0x01
    
    def read_block(sock, addr, nwords):
        """Read nwords using DAP_TransferBlock."""
        write_ap(sock, 0x04, addr)  # TAR
        cmd = [0x06, 0x00]
        cmd += list(struct.pack('<H', nwords))
        cmd += [0x0F]  # AP read DRW (A[3:2]=11, RnW=1, APnDP=1)
        resp = send_dap(sock, cmd)
        if resp is None or len(resp) < 4:
            return None
        cnt = struct.unpack_from('<H', resp, 1)[0]
        status = resp[3]
        if status != 0x01:
            return None
        words = []
        for i in range(cnt):
            if 4 + i*4 + 4 <= len(resp):
                words.append(struct.unpack_from('<I', resp, 4 + i*4)[0])
        return words
    
    def read_mem32(sock, addr, total_words):
        """Read total_words in batches of 64."""
        # Setup AP
        write_dp(sock, 0x08, 0x00000000)  # SELECT AP0 bank0
        write_ap(sock, 0x00, 0x23000012)  # CSW: 32-bit, auto-inc
        
        all_words = []
        batch = 64
        off = 0
        while off < total_words:
            n = min(batch, total_words - off)
            w = read_block(sock, addr + off * 4, n)
            if w is None:
                return None
            all_words.extend(w)
            off += len(w)
            if len(w) < n:
                return None  # short read
        return all_words
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((HOST, PORT))
        
        # Handshake
        hs = bytes([0x8a, 0x65, 0x6c, 0x70, 0, 0, 0, 0, 1, 0, 0, 0])
        s.sendall(hs)
        hr = s.recv(12)
        if len(hr) == 12 and hr[0] == 0x8a:
            print("  ✓ 握手成功")
        else:
            print(f"  ✗ 握手失败: {hr.hex() if hr else 'empty'}")
            s.close()
            return False
        
        # Connect SWD
        r = send_dap(s, [0x02, 0x01])
        if r and r[1] == 0x01:
            print("  ✓ DAP_Connect SWD")
        else:
            print(f"  ✗ DAP_Connect 失败: {r.hex() if r else 'timeout'}")
            s.close()
            return False
        
        # Clock
        r = send_dap(s, struct.pack('<BI', 0x11, 1000000))
        print(f"  → Clock: {r.hex() if r else 'timeout'}")
        r = send_dap(s, [0x13, 0x00])  # SWD configure
        print(f"  → SWD_Config: {r.hex() if r else 'timeout'}")
        
        # JTAG-to-SWD sequence
        r = send_dap(s, [0x12, 51] + [0xFF]*6 + [0x03])
        print(f"  → SWJ_Seq(51): {r.hex() if r else 'timeout'}")
        r = send_dap(s, [0x12, 16, 0x9E, 0xE7])
        print(f"  → SWJ_Seq(16): {r.hex() if r else 'timeout'}")
        r = send_dap(s, [0x12, 51] + [0xFF]*6 + [0x03])
        print(f"  → SWJ_Seq(51): {r.hex() if r else 'timeout'}")
        r = send_dap(s, [0x12, 8, 0x00])
        print(f"  → SWJ_Seq(8): {r.hex() if r else 'timeout'}")
        
        # DPIDR — use DAP_Transfer: read DP reg 0 (DPIDR)
        # Request byte: A[3:2]=00, RnW=1, APnDP=0 → 0x02
        r = send_dap(s, [0x05, 0x00, 0x01, 0x02])
        print(f"  → DPIDR raw: {r.hex() if r else 'timeout'}")
        dpidr = None
        if r and len(r) >= 7 and r[2] == 0x01:
            dpidr = struct.unpack_from('<I', r, 3)[0]
        if dpidr:
            print(f"  ✓ DPIDR = 0x{dpidr:08X}")
        else:
            print("  ✗ DPIDR 读取失败")
            s.close()
            return False
        
        # Power up
        write_dp(s, 0x04, 0x54000000)
        write_dp(s, 0x08, 0x00000000)
        write_dp(s, 0x04, 0x50000000)
        time.sleep(0.1)
        ctrl = read_dp(s, 0x04)
        if ctrl:
            print(f"  ✓ CTRL/STAT = 0x{ctrl:08X}")
        
        # Basic read
        print("\n[验证读取]")
        words4 = read_mem32(s, 0x08000000, 4)
        if words4 and len(words4) >= 2:
            print(f"  ✓ SP = 0x{words4[0]:08X}, PC = 0x{words4[1]:08X}")
        else:
            print(f"  ✗ 基本读取失败")
            s.close()
            return False
        
        # Speed test
        print("\n[读速度测试]")
        res = {}
        
        # 4KB = 1024 words
        t0 = time.perf_counter()
        d4k = read_mem32(s, 0x08000000, 1024)
        t1 = time.perf_counter()
        if d4k and len(d4k) == 1024:
            dt = (t1 - t0) * 1000
            spd = 4.0 / (t1 - t0)
            res['4KB_ms'] = dt
            res['4KB_KBs'] = spd
            print(f"  → READ 4KB: {dt:.0f} ms ({spd:.1f} KB/s)")
        else:
            got = len(d4k) if d4k else 0
            print(f"  ✗ 4KB 读取失败 ({got} words)")
        
        # 16KB = 4096 words
        t2 = time.perf_counter()
        d16k = read_mem32(s, 0x08000000, 4096)
        t3 = time.perf_counter()
        if d16k and len(d16k) == 4096:
            dt2 = (t3 - t2) * 1000
            spd2 = 16.0 / (t3 - t2)
            res['16KB_ms'] = dt2
            res['16KB_KBs'] = spd2
            print(f"  → READ 16KB: {dt2:.0f} ms ({spd2:.1f} KB/s)")
        else:
            got = len(d16k) if d16k else 0
            print(f"  ✗ 16KB 读取失败 ({got} words)")
        
        s.close()
        return res
        
    except socket.timeout:
        print("  ✗ 超时")
        return None
    except ConnectionRefusedError:
        print("  ✗ 连接被拒绝")
        return None
    except Exception as e:
        print(f"  ✗ 异常: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       EHUB DAP 三模式 功能 + 速率测试                  ║")
    print("║  目标: STM32F103C8T6 (SWD, 无 nRST)                   ║")
    print("╚══════════════════════════════════════════════════════════╝\n")
    
    results = {}
    
    results['有线 USB HID'] = test_wired()
    time.sleep(2)
    results['WiFi DAP_TCP'] = test_wifi_tcp()
    time.sleep(2)
    results['elaphureLink'] = test_elaphurelink()
    
    print("\n" + "=" * 60)
    print("  ╔════════════════════════════════════════════════╗")
    print("  ║              测试结果汇总                     ║")
    print("  ╚════════════════════════════════════════════════╝")
    hdr = f"  {'模式':<18s} {'4KB(ms)':<10s} {'KB/s':<10s} {'16KB(ms)':<10s} {'KB/s':<10s}"
    print(hdr)
    print(f"  {'-'*56}")
    for mode, r in results.items():
        if r is None:
            print(f"  {mode:<18s} {'✗ 连接失败':^46s}")
        elif not r:
            print(f"  {mode:<18s} {'✓ 连接成功 (无速度数据)':^46s}")
        else:
            a = f"{r['4KB_ms']:.0f}" if '4KB_ms' in r else 'N/A'
            b = f"{r['4KB_KBs']:.1f}" if '4KB_KBs' in r else 'N/A'
            c = f"{r['16KB_ms']:.0f}" if '16KB_ms' in r else 'N/A'
            d = f"{r['16KB_KBs']:.1f}" if '16KB_KBs' in r else 'N/A'
            print(f"  {mode:<18s} {a:<10s} {b:<10s} {c:<10s} {d:<10s}")
    print("=" * 60)

if __name__ == '__main__':
    main()
