#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <Arduino.h>
#include "config.h"

// ─── 帧结构 ───
struct BridgeFrame {
    uint8_t  sof0;                    // 0xAA (CMD) 或 0xBB (RPY)
    uint8_t  ch;                      // 通道 ID
    uint16_t len;                     // 载荷长度
    uint8_t  data[BRIDGE_MAX_DATA];   // 载荷数据
    bool     valid;                   // CRC 校验结果
};

// ─── 帧解析器（流式状态机，逐字节输入）───
class FrameParser {
public:
    FrameParser();
    void reset();
    // 输入一个字节，如果解析出完整帧返回 true
    bool feed(uint8_t byte, BridgeFrame& outFrame);

private:
    enum State {
        WAIT_SOF0,
        WAIT_SOF1,
        WAIT_CH,
        WAIT_LEN_H,
        WAIT_LEN_L,
        WAIT_DATA,
        WAIT_CRC
    };

    State    _state;
    uint8_t  _sof0;
    uint8_t  _ch;
    uint16_t _len;
    uint8_t  _data[BRIDGE_MAX_DATA];
    uint16_t _dataIdx;
};

// ─── 帧构建 ───
// 构建一个完整帧到 outBuf，返回总帧长度 (6 + len)
int buildFrame(uint8_t* outBuf, uint8_t sof0, uint8_t ch,
               const uint8_t* data, uint16_t len);

// ─── CRC8 计算 (XOR) ───
uint8_t calcCRC8(uint8_t ch, uint16_t len, const uint8_t* data);

#endif // PROTOCOL_H
