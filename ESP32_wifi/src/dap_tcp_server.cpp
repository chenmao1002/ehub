/**
 * @file    dap_tcp_server.cpp
 * @brief   CMSIS-DAP over TCP — dual protocol server
 *
 * Two independent TCP servers:
 *   Port 6000: OpenOCD cmsis-dap tcp — 8-byte header protocol
 *              [4B signature 0x00504144][2B LE length][1B type][1B reserved]
 *   Port 3240: elaphureLink Proxy Protocol
 *              12-byte handshake (handled locally on ESP32),
 *              then raw CMSIS-DAP commands without any framing.
 *              See: https://github.com/windowsair/elaphureLink/blob/master/docs/proxy_protocol.md
 *
 * The ESP32 does NOT process DAP commands. It wraps them in Bridge protocol
 * frames (CH=0xD0) and forwards to the MCU via UART. MCU executes the DAP
 * command and sends the response back, which is then forwarded to the TCP client.
 */

#include "dap_tcp_server.h"

DAPTCPServer::DAPTCPServer()
    : _serverOCD(nullptr)
    , _serverEL(nullptr)
    , _protocol(DAP_PROTO_NONE)
    , _connected(false)
    , _elHandshakeDone(false)
    , _state(ST_HDR)
    , _hdrIdx(0)
    , _expectLen(0)
    , _cmdIdx(0)
{
}

void DAPTCPServer::resetParser() {
    _state = ST_HDR;
    _hdrIdx = 0;
    _expectLen = 0;
    _cmdIdx = 0;
    _elHandshakeDone = false;
}

void DAPTCPServer::begin() {
    // OpenOCD server (port 6000)
    _serverOCD = new WiFiServer(DAP_TCP_PORT);
    _serverOCD->begin();
    _serverOCD->setNoDelay(true);

    // elaphureLink server (port 3240)
    _serverEL = new WiFiServer(ELAPHURELINK_PORT);
    _serverEL->begin();
    _serverEL->setNoDelay(true);
}

void DAPTCPServer::loop() {
    // Check OpenOCD server for new connections
    if (_serverOCD) {
        WiFiClient newClient = _serverOCD->available();
        if (newClient) {
            if (_connected && _client.connected()) {
                _client.stop();
            }
            _client = newClient;
            _client.setNoDelay(true);
            _connected = true;
            _protocol = DAP_PROTO_OPENOCD;
            resetParser();
        }
    }

    // Check elaphureLink server for new connections
    if (_serverEL) {
        WiFiClient newClient = _serverEL->available();
        if (newClient) {
            if (_connected && _client.connected()) {
                _client.stop();
            }
            _client = newClient;
            _client.setNoDelay(true);
            _connected = true;
            _protocol = DAP_PROTO_ELAPHURELINK;
            resetParser();
        }
    }

    // Check for disconnection
    if (_connected && !_client.connected()) {
        _client.stop();
        _connected = false;
        _protocol = DAP_PROTO_NONE;
        resetParser();
    }
}

bool DAPTCPServer::hasClient() {
    return _connected && _client.connected();
}

DAPProtocol DAPTCPServer::activeProtocol() {
    return _protocol;
}

void DAPTCPServer::disconnect() {
    if (_connected) {
        _client.stop();
        _connected = false;
    }
    _protocol = DAP_PROTO_NONE;
    resetParser();
}

IPAddress DAPTCPServer::clientIP() {
    if (hasClient()) return _client.remoteIP();
    return IPAddress(0, 0, 0, 0);
}

// ─── OpenOCD protocol: 8-byte header [sig][len][type][rsv] + data ───
bool DAPTCPServer::readOpenOCD(uint8_t* buf, uint16_t* len) {
    while (_client.available()) {
        uint8_t b = _client.read();

        switch (_state) {
        case ST_HDR:
            _hdrBuf[_hdrIdx++] = b;
            if (_hdrIdx >= HEADER_SIZE) {
                // Parse header
                uint32_t sig = (uint32_t)_hdrBuf[0]
                             | ((uint32_t)_hdrBuf[1] << 8)
                             | ((uint32_t)_hdrBuf[2] << 16)
                             | ((uint32_t)_hdrBuf[3] << 24);
                _expectLen = (uint16_t)_hdrBuf[4]
                           | ((uint16_t)_hdrBuf[5] << 8);
                uint8_t pktType = _hdrBuf[6];
                // _hdrBuf[7] = reserved

                if (sig != DAP_SIGNATURE || pktType != DAP_TYPE_REQ
                    || _expectLen == 0 || _expectLen > DAP_TCP_MAX_PACKET) {
                    // Invalid header — reset
                    _hdrIdx = 0;
                    continue;
                }
                _cmdIdx = 0;
                _state = ST_DATA;
            }
            break;

        case ST_DATA:
            _cmdBuf[_cmdIdx++] = b;
            if (_cmdIdx >= _expectLen) {
                memcpy(buf, _cmdBuf, _expectLen);
                *len = _expectLen;
                _state = ST_HDR;
                _hdrIdx = 0;
                return true;
            }
            break;
        }
    }
    return false;
}

// ─── elaphureLink Proxy Protocol ───
// Handshake: 12 bytes REQ_HANDSHAKE / RES_HANDSHAKE (ESP32 handles locally)
//   [0..3]  0x8a656c70  — elaphureLink identifier (big-endian)
//   [4..7]  0x00000000  — command code: handshake
//   [8..11] version     — client/server version
// After handshake: raw CMSIS-DAP commands, no framing, no padding.
// Each TCP write = one complete DAP command or response.
bool DAPTCPServer::readElaphureLink(uint8_t* buf, uint16_t* len) {
    int avail = _client.available();
    if (avail <= 0) return false;

    // ── Phase 1: Handshake ──
    if (!_elHandshakeDone) {
        // Need at least 12 bytes for a valid handshake
        if (avail < 12) return false;

        uint8_t hsBuf[12];
        _client.readBytes(hsBuf, 12);

        // Check elaphureLink identifier: 0x8a 0x65 0x6c 0x70
        if (hsBuf[0] == 0x8a && hsBuf[1] == 0x65 &&
            hsBuf[2] == 0x6c && hsBuf[3] == 0x70) {
            // RES_HANDSHAKE: same identifier + cmd=0 + fw_version
            uint8_t resp[12] = {
                0x8a, 0x65, 0x6c, 0x70,   // elaphureLink identifier
                0x00, 0x00, 0x00, 0x00,   // command: handshake
                0x00, 0x02, 0x00, 0x00    // firmware version: 2.0.0
            };
            _client.write(resp, 12);
            _client.flush();
            _elHandshakeDone = true;
            return false;  // Handshake done, no DAP data yet
        }

        // Not a handshake — treat first 12 bytes as DAP command data
        _elHandshakeDone = true;
        memcpy(buf, hsBuf, 12);
        // Also read any remaining data that arrived with this segment
        int extra = _client.available();
        if (extra > 0 && extra <= (int)DAP_TCP_MAX_PACKET - 12) {
            int r = _client.readBytes(buf + 12, extra);
            *len = (uint16_t)(12 + r);
        } else {
            *len = 12;
        }
        return true;
    }

    // ── Phase 2: Raw CMSIS-DAP commands ──
    // Read all available bytes as one DAP command.
    // With TCP_NODELAY, each client write() arrives as one TCP segment.
    int toRead = (avail > (int)DAP_TCP_MAX_PACKET) ? (int)DAP_TCP_MAX_PACKET : avail;
    int n = _client.readBytes(buf, toRead);
    if (n > 0) {
        *len = (uint16_t)n;
        return true;
    }
    return false;
}

bool DAPTCPServer::readCommand(uint8_t* buf, uint16_t* len) {
    if (!hasClient()) return false;

    switch (_protocol) {
    case DAP_PROTO_OPENOCD:
        return readOpenOCD(buf, len);
    case DAP_PROTO_ELAPHURELINK:
        return readElaphureLink(buf, len);
    default:
        return false;
    }
}

void DAPTCPServer::sendResponse(const uint8_t* buf, uint16_t len) {
    if (!hasClient() || len == 0) return;

    switch (_protocol) {
    case DAP_PROTO_OPENOCD:
    {
        // OpenOCD: send 8-byte header + data as SINGLE write to avoid TCP fragmentation
        // [4B signature][2B LE length][1B type=0x02][1B reserved=0x00][payload]
        uint8_t pkt[8 + DAP_TCP_MAX_PACKET];
        pkt[0] = 0x44; // 'D'
        pkt[1] = 0x41; // 'A'
        pkt[2] = 0x50; // 'P'
        pkt[3] = 0x00; // '\0'
        pkt[4] = (uint8_t)(len & 0xFF);
        pkt[5] = (uint8_t)((len >> 8) & 0xFF);
        pkt[6] = DAP_TYPE_RSP; // 0x02
        pkt[7] = 0x00;         // reserved
        memcpy(pkt + 8, buf, len);
        _client.write(pkt, 8 + len);
        _client.flush();
        break;
    }
    case DAP_PROTO_ELAPHURELINK:
    {
        // elaphureLink: raw DAP response, no framing, no padding
        _client.write(buf, len);
        _client.flush();
        break;
    }
    default:
        break;
    }
}
