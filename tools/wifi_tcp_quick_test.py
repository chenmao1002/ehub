#!/usr/bin/env python3
"""Quick WiFi DAP_TCP read speed test."""
import subprocess, os, tempfile, time

CUSTOM_OCD = r"C:\Users\MC\Desktop\wifidap\openocd\src\openocd.exe"
CUSTOM_SCRIPTS = r"C:\Users\MC\Desktop\wifidap\openocd\tcl"

CFG = """\
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

TCL = """\
init
halt
set t0 [ms]
mem2array a32 32 0x08000000 1024
set t1 [ms]
echo "RESULT_READ_4KB: [expr {$t1 - $t0}] ms"
set t2 [ms]
mem2array b32 32 0x08000000 4096
set t3 [ms]
echo "RESULT_READ_16KB: [expr {$t3 - $t2}] ms"
echo "RESULT_SP: [format 0x%08X $a32(0)]"
echo "RESULT_PC: [format 0x%08X $a32(1)]"
shutdown
"""

def main():
    cfg_path = os.path.join(tempfile.gettempdir(), "wifi_tcp_test.cfg")
    tcl_path = os.path.join(tempfile.gettempdir(), "wifi_tcp_test.tcl")
    with open(cfg_path, 'w') as f: f.write(CFG)
    with open(tcl_path, 'w') as f: f.write(TCL)

    print("Starting WiFi DAP_TCP test...")
    t0 = time.time()
    try:
        r = subprocess.run(
            [CUSTOM_OCD, "-s", CUSTOM_SCRIPTS, "-f", cfg_path, "-f", tcl_path],
            capture_output=True, text=True, timeout=120
        )
        elapsed = time.time() - t0
        print(f"Completed in {elapsed:.1f}s, returncode={r.returncode}")
        
        combined = r.stdout + "\n" + r.stderr
        for line in combined.split('\n'):
            line = line.strip()
            if any(kw in line for kw in ['RESULT_', 'DPIDR', 'Cortex', 'Error', 'failed', 'CMD_']):
                print(f"  {line}")
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {time.time()-t0:.1f}s")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    main()
