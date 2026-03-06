#!/usr/bin/env python3
"""Parse ESP32 debug counter raw hex from 0xF0 response."""
import struct, sys

raw_hex = 'f082000000820000000000000000000000000082000000000000000000000002000001000000000000080000'
d = bytes.fromhex(raw_hex)

# skip subcmd byte 0xF0
vals = struct.unpack_from('<7I', d, 1)
names = ['dapTcpRead','dapUartTx','dapUartRx','dapTcpSend','dapTimeout','uartBytesRx','uartFramesRx']
for n, v in zip(names, vals):
    print(f'  {n:20s} = {v}')

pos = 1 + 28
v16 = struct.unpack_from('<H', d, pos)[0]; pos += 2
print(f'  lastDapCmdLen      = {v16}')
cmd_bytes = d[pos:pos+8]; pos += 8
print(f'  lastDapCmd         = {cmd_bytes.hex()}')
v16 = struct.unpack_from('<H', d, pos)[0]; pos += 2
print(f'  lastBridgeTxLen    = {v16}')
tx_bytes = d[pos:pos+min(16, len(d)-pos)]
print(f'  lastBridgeTx       = {tx_bytes.hex()}')
