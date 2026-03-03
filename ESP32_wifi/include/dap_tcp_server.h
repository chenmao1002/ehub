/**
 * @file    dap_tcp_server.h
 * @brief   CMSIS-DAP over TCP server for ESP32
 *
 * Implements the standard CMSIS-DAP TCP protocol used by OpenOCD (cmsis-dap backend tcp)
 * and elaphureLink. The protocol is:
 *   Send:  [4-byte LE uint32 length][DAP command bytes]
 *   Recv:  [4-byte LE uint32 length][DAP response bytes]
 *
 * ESP32 does NOT execute DAP commands — it transparently bridges them to MCU
 * via the Bridge protocol (CH = 0xD0), and forwards MCU responses back to TCP.
 */

#ifndef DAP_TCP_SERVER_H
#define DAP_TCP_SERVER_H

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"

class DAPTCPServer {
public:
    DAPTCPServer();
    void begin(uint16_t port = DAP_TCP_PORT);
    void loop();                     // Accept new connections, manage state
    bool hasClient();
    void disconnect();
    IPAddress clientIP();

    /**
     * @brief  Non-blocking read of a complete DAP command from TCP client.
     *         Handles the 4-byte LE length header internally.
     * @param  buf   Output buffer for DAP command bytes
     * @param  len   Output: actual command length
     * @return true  if a complete command was received
     */
    bool readCommand(uint8_t* buf, uint16_t* len);

    /**
     * @brief  Send DAP response back to TCP client with 4-byte LE length header.
     * @param  buf   DAP response data
     * @param  len   Response length
     */
    void sendResponse(const uint8_t* buf, uint16_t len);

private:
    WiFiServer* _server;
    WiFiClient  _client;
    bool        _connected;

    // State machine for parsing 4-byte length prefix + payload
    enum ReadState { ST_LEN, ST_DATA };
    ReadState _state;
    uint8_t   _lenBuf[4];
    uint8_t   _lenIdx;
    uint32_t  _expectLen;
    uint8_t   _cmdBuf[DAP_TCP_MAX_PACKET];
    uint16_t  _cmdIdx;
};

#endif // DAP_TCP_SERVER_H
