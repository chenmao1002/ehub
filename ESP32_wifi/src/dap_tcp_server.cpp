/**
 * @file    dap_tcp_server.cpp
 * @brief   CMSIS-DAP over TCP — dual protocol server
 *
 * Two independent TCP servers:
 *   Port 6000: OpenOCD cmsis-dap tcp — [4-byte LE length][DAP data]
 *   Port 3240: elaphureLink — 12-byte handshake, then raw DAP data
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
    , _state(ST_LEN)
    , _lenIdx(0)
    , _expectLen(0)
    , _cmdIdx(0)
{
}

void DAPTCPServer::resetParser() {
    _state = ST_LEN;
    _lenIdx = 0;
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

// ─── OpenOCD protocol: [4-byte LE length][data] ───
bool DAPTCPServer::readOpenOCD(uint8_t* buf, uint16_t* len) {
    while (_client.available()) {
        uint8_t b = _client.read();

        switch (_state) {
        case ST_LEN:
            _lenBuf[_lenIdx++] = b;
            if (_lenIdx >= 4) {
                _expectLen = (uint32_t)_lenBuf[0]
                           | ((uint32_t)_lenBuf[1] << 8)
                           | ((uint32_t)_lenBuf[2] << 16)
                           | ((uint32_t)_lenBuf[3] << 24);

                if (_expectLen == 0 || _expectLen > DAP_TCP_MAX_PACKET) {
                    _lenIdx = 0;
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
                *len = (uint16_t)_expectLen;
                _state = ST_LEN;
                _lenIdx = 0;
                return true;
            }
            break;
        }
    }
    return false;
}

// ─── elaphureLink protocol: 12-byte handshake, then raw DAP data ───
bool DAPTCPServer::readElaphureLink(uint8_t* buf, uint16_t* len) {
    if (!_client.available()) return false;

    // Phase 1: Handshake detection
    if (!_elHandshakeDone) {
        // Read available data
        int avail = _client.available();
        if (avail < 12) return false;  // Wait for full handshake

        uint8_t hsBuf[12];
        _client.readBytes(hsBuf, 12);

        // Check elaphureLink handshake signature: 0x8a 0x65 0x6c
        if (hsBuf[0] == 0x8a && hsBuf[1] == 0x65 && hsBuf[2] == 0x6c) {
            // Respond to handshake: modify bytes [8..11] = {0,0,0,1}
            hsBuf[8] = 0;
            hsBuf[9] = 0;
            hsBuf[10] = 0;
            hsBuf[11] = 1;
            _client.write(hsBuf, 12);
            _client.flush();
            _elHandshakeDone = true;
            return false;  // Handshake done, no DAP data yet
        } else {
            // Not a valid handshake — treat as raw data anyway
            _elHandshakeDone = true;
            memcpy(buf, hsBuf, 12);
            *len = 12;
            return true;
        }
    }

    // Phase 2: After handshake — raw DAP data
    // elaphureLink sends DAP commands as raw bytes,
    // we read all available data as one command
    int avail = _client.available();
    if (avail <= 0) return false;

    int toRead = (avail > DAP_TCP_MAX_PACKET) ? DAP_TCP_MAX_PACKET : avail;
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
        // OpenOCD: send 4-byte LE length header + data
        uint8_t header[4];
        header[0] = (uint8_t)(len & 0xFF);
        header[1] = (uint8_t)((len >> 8) & 0xFF);
        header[2] = 0;
        header[3] = 0;
        _client.write(header, 4);
        _client.write(buf, len);
        _client.flush();
        break;
    }
    case DAP_PROTO_ELAPHURELINK:
    {
        // elaphureLink: send raw DAP response data (no header)
        _client.write(buf, len);
        _client.flush();
        break;
    }
    default:
        break;
    }
}
