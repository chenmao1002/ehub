"""Write WiFi read test with longer OpenOCD timeout."""
import os, tempfile

d = tempfile.gettempdir()

with open(os.path.join(d, 'wifi_read.cfg'), 'w', encoding='utf-8', newline='\n') as f:
    f.write("""adapter driver cmsis-dap
cmsis-dap backend tcp
cmsis-dap tcp host 192.168.227.100
cmsis-dap tcp port 6000
cmsis-dap tcp min_timeout 5000
transport select swd
set CHIPNAME stm32f1x
source [find target/stm32f1x.cfg]
adapter speed 1000
reset_config none
cortex_m reset_config sysresetreq
""")

with open(os.path.join(d, 'wifi_read.tcl'), 'w', encoding='utf-8', newline='\n') as f:
    f.write("""init
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
""")

print(f"Written with min_timeout=5000 to {d}")
