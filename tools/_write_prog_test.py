"""Write OpenOCD config/tcl for progressive read size test."""
import os, tempfile

d = tempfile.gettempdir()

with open(os.path.join(d, 'wifi_read.cfg'), 'w', encoding='utf-8', newline='\n') as f:
    f.write("""adapter driver cmsis-dap
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
""")

# Progressive read test: try 64, 128, 256, 512, 1024 words
with open(os.path.join(d, 'wifi_read.tcl'), 'w', encoding='utf-8', newline='\n') as f:
    f.write("""init
halt

echo "=== Progressive read size test ==="

set t0 [ms]
mem2array r64 32 0x08000000 64
set t1 [ms]
echo "RESULT_256B: [expr {$t1 - $t0}] ms (64 words) OK"

set t2 [ms]
mem2array r128 32 0x08000000 128
set t3 [ms]
echo "RESULT_512B: [expr {$t3 - $t2}] ms (128 words) OK"

set t4 [ms]
mem2array r256 32 0x08000000 256
set t5 [ms]
echo "RESULT_1KB: [expr {$t5 - $t4}] ms (256 words) OK"

set t6 [ms]
mem2array r512 32 0x08000000 512
set t7 [ms]
echo "RESULT_2KB: [expr {$t7 - $t6}] ms (512 words) OK"

set t8 [ms]
mem2array r1024 32 0x08000000 1024
set t9 [ms]
echo "RESULT_4KB: [expr {$t9 - $t8}] ms (1024 words) OK"

shutdown
""")

print(f"Written progressive read test to {d}")
