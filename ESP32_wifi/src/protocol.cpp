#include "protocol.h"

// ═══════════════════════════════════════════════════════════════
// CRC8 计算 — XOR(CH, LEN_H, LEN_L, DATA[0..LEN-1])
// ═══════════════════════════════════════════════════════════════
uint8_t calcCRC8(uint8_t ch, uint16_t len, const uint8_t* data) {
    uint8_t crc = ch;
    crc ^= (uint8_t)(len >> 8);    // LEN_H
    crc ^= (uint8_t)(len & 0xFF);  // LEN_L
    for (uint16_t i = 0; i < len; i++) {
        crc ^= data[i];
    }
    return crc;
}

// ═══════════════════════════════════════════════════════════════
// 帧构建
// ═══════════════════════════════════════════════════════════════
int buildFrame(uint8_t* outBuf, uint8_t sof0, uint8_t ch,
               const uint8_t* data, uint16_t len) {
    outBuf[0] = sof0;
    outBuf[1] = BRIDGE_SOF1;
    outBuf[2] = ch;
    outBuf[3] = (uint8_t)(len >> 8);    // LEN_H
    outBuf[4] = (uint8_t)(len & 0xFF);  // LEN_L
    if (data && len > 0) {
        memcpy(&outBuf[5], data, len);
    }
    outBuf[5 + len] = calcCRC8(ch, len, data);
    return 6 + len;  // SOF0 + SOF1 + CH + LEN_H + LEN_L + DATA + CRC
}

// ═══════════════════════════════════════════════════════════════
// 帧解析器 — 流式状态机
// ═══════════════════════════════════════════════════════════════
FrameParser::FrameParser() {
    reset();
}

void FrameParser::reset() {
    _state   = WAIT_SOF0;
    _sof0    = 0;
    _ch      = 0;
    _len     = 0;
    _dataIdx = 0;
}

bool FrameParser::feed(uint8_t byte, BridgeFrame& outFrame) {
    switch (_state) {
        case WAIT_SOF0:
            if (byte == BRIDGE_SOF0_CMD || byte == BRIDGE_SOF0_RPY) {
                _sof0 = byte;
                _state = WAIT_SOF1;
            }
            break;

        case WAIT_SOF1:
            if (byte == BRIDGE_SOF1) {
                _state = WAIT_CH;
            } else {
                // 不是有效帧头，重新检测
                // 但当前字节可能是新的 SOF0
                if (byte == BRIDGE_SOF0_CMD || byte == BRIDGE_SOF0_RPY) {
                    _sof0 = byte;
                    _state = WAIT_SOF1;
                } else {
                    reset();
                }
            }
            break;

        case WAIT_CH:
            _ch = byte;
            _state = WAIT_LEN_H;
            break;

        case WAIT_LEN_H:
            _len = (uint16_t)byte << 8;
            _state = WAIT_LEN_L;
            break;

        case WAIT_LEN_L:
            _len |= byte;
            _dataIdx = 0;
            if (_len > BRIDGE_MAX_DATA) {
                // 帧太长，丢弃，重置
                reset();
            } else if (_len == 0) {
                _state = WAIT_CRC;
            } else {
                _state = WAIT_DATA;
            }
            break;

        case WAIT_DATA:
            _data[_dataIdx++] = byte;
            if (_dataIdx >= _len) {
                _state = WAIT_CRC;
            }
            break;

        case WAIT_CRC: {
            uint8_t expectedCRC = calcCRC8(_ch, _len, _data);
            outFrame.sof0  = _sof0;
            outFrame.ch    = _ch;
            outFrame.len   = _len;
            memcpy(outFrame.data, _data, _len);
            outFrame.valid = (byte == expectedCRC);
            reset();
            return true;  // 完整帧已解析
        }
    }
    return false;
}
