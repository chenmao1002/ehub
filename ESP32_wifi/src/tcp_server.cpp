#include "tcp_server.h"

TCPBridgeServer::TCPBridgeServer()
    : _server(nullptr)
    , _clientConnected(false)
{
}

void TCPBridgeServer::begin(uint16_t port) {
    _server = new WiFiServer(port);
    _server->begin();
    _server->setNoDelay(true);
}

void TCPBridgeServer::loop() {
    if (!_server) return;

    // 检查新连接
    WiFiClient newClient = _server->available();
    if (newClient) {
        // 仅允许 1 个连接，新连接到来时踢掉旧连接
        if (_clientConnected && _client.connected()) {
            _client.stop();
        }
        _client = newClient;
        _client.setNoDelay(true);
        _clientConnected = true;
    }

    // 检测当前客户端是否断开
    if (_clientConnected && !_client.connected()) {
        _client.stop();
        _clientConnected = false;
    }
}

bool TCPBridgeServer::hasClient() {
    return _clientConnected && _client.connected();
}

int TCPBridgeServer::available() {
    if (!hasClient()) return 0;
    return _client.available();
}

int TCPBridgeServer::read(uint8_t* buf, int maxLen) {
    if (!hasClient()) return 0;
    int avail = _client.available();
    if (avail <= 0) return 0;
    int toRead = (avail < maxLen) ? avail : maxLen;
    return _client.read(buf, toRead);
}

void TCPBridgeServer::write(const uint8_t* buf, int len) {
    if (!hasClient()) return;
    _client.write(buf, len);
}

void TCPBridgeServer::disconnect() {
    if (_clientConnected) {
        _client.stop();
        _clientConnected = false;
    }
}

IPAddress TCPBridgeServer::clientIP() {
    if (hasClient()) {
        return _client.remoteIP();
    }
    return IPAddress(0, 0, 0, 0);
}
