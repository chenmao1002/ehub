"""Write WiFi read test pointing to proxy port 6001."""
import os, tempfile

d = tempfile.gettempdir()

with open(os.path.join(d, 'wifi_proxy.cfg'), 'w', encoding='utf-8', newline='\n') as f:
    f.write("""adapter driver cmsis-dap
cmsis-dap backend tcp
cmsis-dap tcp host 127.0.0.1
cmsis-dap tcp port 6001
cmsis-dap tcp min_timeout 5000
transport select swd
set CHIPNAME stm32f1x
source [find target/stm32f1x.cfg]
adapter speed 1000
reset_config none
cortex_m reset_config sysresetreq
""")

with open(os.path.join(d, 'wifi_proxy.tcl'), 'w', encoding='utf-8', newline='\n') as f:
    f.write("""init
halt
mem2array a32 32 0x08000000 256
echo "RESULT: 256 words read OK"
shutdown
""")

print(f"Written proxy config (port 6001) to {d}")
