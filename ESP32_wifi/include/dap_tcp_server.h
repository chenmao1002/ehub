/**
 * @file    dap_tcp_server.h
 * @brief   CMSIS-DAP over TCP — supports both OpenOCD and elaphureLink
 *
 * Two TCP servers:
 *   1. Port 6000 (DAP_TCP_PORT)     — OpenOCD cmsis-dap tcp protocol
 *      8-byte header: [4-byte signature "DAP\0" = 0x00504144 LE]
 *                     [2-byte LE payload length]
 *                     [1-byte type: 0x01=req, 0x02=rsp]
 *                     [1-byte reserved = 0x00]
 *
 *   2. Port 3240 (ELAPHURELINK_PORT) — elaphureLink Proxy Protocol
 *      12-byte handshake (ESP32-local), then raw CMSIS-DAP commands.
 *      See: https://github.com/windowsair/elaphureLink/blob/master/docs/proxy_protocol.md
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
    bool     _elHandshakeDone;

    // OpenOCD: state machine for 8-byte header
    //   Header: [4B signature][2B LE length][1B type][1B reserved]
    static constexpr uint32_t DAP_SIGNATURE = 0x00504144; // "DAP\0"
    static constexpr uint8_t  DAP_TYPE_REQ  = 0x01;
    static constexpr uint8_t  DAP_TYPE_RSP  = 0x02;
    static constexpr uint8_t  HEADER_SIZE   = 8;

    enum ReadState { ST_HDR, ST_DATA };
    ReadState _state;
    uint8_t   _hdrBuf[8];
    uint8_t   _hdrIdx;
    uint16_t  _expectLen;
    uint8_t   _cmdBuf[DAP_TCP_MAX_PACKET];
    uint16_t  _cmdIdx;

    void resetParser();
    bool readOpenOCD(uint8_t* buf, uint16_t* len);
    bool readElaphureLink(uint8_t* buf, uint16_t* len);
};

#endif // DAP_TCP_SERVER_H
