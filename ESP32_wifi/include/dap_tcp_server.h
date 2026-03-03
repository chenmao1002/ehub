/**
 * @file    dap_tcp_server.h
 * @brief   CMSIS-DAP over TCP — supports both OpenOCD and elaphureLink
 *
 * Two TCP servers:
 *   1. Port 6000 (DAP_TCP_PORT)     — OpenOCD cmsis-dap tcp protocol
 *      Send/Recv: [4-byte LE uint32 length][DAP data]
 *
 *   2. Port 3240 (ELAPHURELINK_PORT) — elaphureLink protocol
 *      Handshake: 12-byte packet starting with 0x8a 0x65 0x6c
 *      After handshake: raw DAP data (no length header)
 *
 * ESP32 does NOT execute DAP commands — it wraps them in Bridge protocol
 * frames (CH=0xD0) and forwards to MCU via UART. MCU responses are routed
 * back to the active TCP client.
 */

#ifndef DAP_TCP_SERVER_H
#define DAP_TCP_SERVER_H

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"

/**
 * @brief  Protocol type for the DAP TCP connection
 */
enum DAPProtocol {
    DAP_PROTO_NONE = 0,
    DAP_PROTO_OPENOCD,       // 4-byte LE length header
    DAP_PROTO_ELAPHURELINK   // 12-byte handshake + raw data
};

class DAPTCPServer {
public:
    DAPTCPServer();
    void begin();                    // Start both servers
    void loop();                     // Accept connections, manage state
    bool hasClient();                // Any DAP client connected?
    DAPProtocol activeProtocol();    // Which protocol is active
    void disconnect();
    IPAddress clientIP();

    /**
     * @brief  Non-blocking read of a complete DAP command from TCP client.
     * @param  buf   Output buffer for DAP command bytes
     * @param  len   Output: actual command length
     * @return true  if a complete command was received
     */
    bool readCommand(uint8_t* buf, uint16_t* len);

    /**
     * @brief  Send DAP response back to TCP client (auto-selects protocol format).
     * @param  buf   DAP response data
     * @param  len   Response length
     */
    void sendResponse(const uint8_t* buf, uint16_t len);

private:
    // Two TCP servers
    WiFiServer* _serverOCD;          // Port 6000 — OpenOCD
    WiFiServer* _serverEL;           // Port 3240 — elaphureLink

    WiFiClient  _client;
    DAPProtocol _protocol;
    bool        _connected;

    // elaphureLink handshake state
    bool _elHandshakeDone;

    // OpenOCD: state machine for 4-byte length prefix
    enum ReadState { ST_LEN, ST_DATA };
    ReadState _state;
    uint8_t   _lenBuf[4];
    uint8_t   _lenIdx;
    uint32_t  _expectLen;
    uint8_t   _cmdBuf[DAP_TCP_MAX_PACKET];
    uint16_t  _cmdIdx;

    void resetParser();
    bool readOpenOCD(uint8_t* buf, uint16_t* len);
    bool readElaphureLink(uint8_t* buf, uint16_t* len);
};

#endif // DAP_TCP_SERVER_H
