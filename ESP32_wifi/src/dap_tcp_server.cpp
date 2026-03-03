/**
 * @file    dap_tcp_server.cpp
 * @brief   CMSIS-DAP over TCP server implementation
 *
 * This server listens on DAP_TCP_PORT (default 6000) and speaks the standard
 * CMSIS-DAP TCP protocol:
 *   Client → Server: [4-byte LE length][DAP_command_bytes]
 *   Server → Client: [4-byte LE length][DAP_response_bytes]
 *
 * The ESP32 does NOT process DAP commands. It wraps them in Bridge protocol
 * frames (CH=0xD0) and forwards to the MCU via UART. MCU executes the DAP
 * command and sends the response back, which is then forwarded to the TCP client.
 */

#include "dap_tcp_server.h"

DAPTCPServer::DAPTCPServer()
    : _server(nullptr)
    , _connected(false)
    , _state(ST_LEN)
    , _lenIdx(0)
    , _expectLen(0)
    , _cmdIdx(0)
{
}

void DAPTCPServer::begin(uint16_t port) {
    _server = new WiFiServer(port);
    _server->begin();
    _server->setNoDelay(true);
}

void DAPTCPServer::loop() {
    if (!_server) return;

    WiFiClient newClient = _server->available();
    if (newClient) {
        // Only allow one DAP client at a time
        if (_connected && _client.connected()) {
            _client.stop();
        }
        _client = newClient;
        _client.setNoDelay(true);
        _connected = true;

        // Reset parser state for new connection
        _state = ST_LEN;
        _lenIdx = 0;
        _expectLen = 0;
        _cmdIdx = 0;
    }

    if (_connected && !_client.connected()) {
        _client.stop();
        _connected = false;
        _state = ST_LEN;
        _lenIdx = 0;
    }
}

bool DAPTCPServer::hasClient() {
    return _connected && _client.connected();
}

void DAPTCPServer::disconnect() {
    if (_connected) {
        _client.stop();
        _connected = false;
    }
    _state = ST_LEN;
    _lenIdx = 0;
}

IPAddress DAPTCPServer::clientIP() {
    if (hasClient()) return _client.remoteIP();
    return IPAddress(0, 0, 0, 0);
}

bool DAPTCPServer::readCommand(uint8_t* buf, uint16_t* len) {
    if (!hasClient()) return false;

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
                    // Invalid length — reset
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
                // Complete DAP command received
                memcpy(buf, _cmdBuf, _expectLen);
                *len = (uint16_t)_expectLen;

                // Reset for next command
                _state = ST_LEN;
                _lenIdx = 0;
                return true;
            }
            break;
        }
    }
    return false;
}

void DAPTCPServer::sendResponse(const uint8_t* buf, uint16_t len) {
    if (!hasClient()) return;

    // Send 4-byte LE length header
    uint8_t header[4];
    header[0] = (uint8_t)(len & 0xFF);
    header[1] = (uint8_t)((len >> 8) & 0xFF);
    header[2] = 0;
    header[3] = 0;

    _client.write(header, 4);
    _client.write(buf, len);
    _client.flush();
}
