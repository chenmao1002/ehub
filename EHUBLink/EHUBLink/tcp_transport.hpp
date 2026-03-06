#pragma once
#include "pch.h"

/*
 * TcpTransport — Blocking Winsock2 TCP transport with OpenOCD frame protocol
 *
 * Frame format (OpenOCD DAP TCP protocol):
 *   Send: [0x44 0x41 0x50 0x00] [len_LE16] [0x01] [0x00] [payload...]
 *   Recv: [0x44 0x41 0x50 0x00] [len_LE16] [0x02] [0x00] [payload...]
 *
 * Each ocd_cmd() call corresponds to exactly ONE send+recv cycle.
 * TCP fragmentation is handled by recv_exact() with a leftover buffer.
 */
class TcpTransport
{
public:
    TcpTransport() : m_sock(INVALID_SOCKET) {}

    ~TcpTransport() { disconnect(); }

    bool connect(const char* host, uint16_t port)
    {
        disconnect();

        WSADATA wsa;
        WSAStartup(MAKEWORD(2, 2), &wsa);

        m_sock = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (m_sock == INVALID_SOCKET) return false;

        // TCP_NODELAY — disable Nagle for low latency
        int flag = 1;
        ::setsockopt(m_sock, IPPROTO_TCP, TCP_NODELAY,
                     reinterpret_cast<const char*>(&flag), sizeof(flag));

        // Resolve host (supports both hostname and IP string)
        struct addrinfo hints{}, *res = nullptr;
        hints.ai_family   = AF_INET;
        hints.ai_socktype = SOCK_STREAM;
        char port_str[8];
        _snprintf_s(port_str, sizeof(port_str), "%u", port);
        if (::getaddrinfo(host, port_str, &hints, &res) != 0) {
            ::closesocket(m_sock);
            m_sock = INVALID_SOCKET;
            return false;
        }

        int rc = ::connect(m_sock, res->ai_addr, (int)res->ai_addrlen);
        ::freeaddrinfo(res);
        if (rc == SOCKET_ERROR) {
            ::closesocket(m_sock);
            m_sock = INVALID_SOCKET;
            return false;
        }

        // 10-second socket timeout
        DWORD timeout_ms = 10000;
        ::setsockopt(m_sock, SOL_SOCKET, SO_RCVTIMEO,
                     reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));
        ::setsockopt(m_sock, SOL_SOCKET, SO_SNDTIMEO,
                     reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));

        m_leftover.clear();
        return true;
    }

    void disconnect()
    {
        if (m_sock != INVALID_SOCKET) {
            ::closesocket(m_sock);
            m_sock = INVALID_SOCKET;
        }
        m_leftover.clear();
    }

    bool connected() const { return m_sock != INVALID_SOCKET; }

    /*
     * ocd_cmd — send one CMSIS-DAP command wrapped in an OCD frame,
     *            receive the OCD response frame, return payload bytes.
     * Thread-safety: caller must hold g_cs.
     */
    bool ocd_cmd(const uint8_t* payload, uint16_t len, std::vector<uint8_t>& resp)
    {
        if (m_sock == INVALID_SOCKET) return false;

        // ── Build and send OCD CMD frame ──────────────────────────────
        uint8_t hdr[8];
        hdr[0] = 'D'; hdr[1] = 'A'; hdr[2] = 'P'; hdr[3] = '\0';
        hdr[4] = static_cast<uint8_t>(len & 0xFF);
        hdr[5] = static_cast<uint8_t>((len >> 8) & 0xFF);
        hdr[6] = 0x01;  // type = CMD
        hdr[7] = 0x00;

        if (!send_all(hdr, 8))           return false;
        if (len > 0 && !send_all(payload, len)) return false;

        // ── Receive OCD RSP frame header ──────────────────────────────
        uint8_t rhdr[8];
        if (!recv_exact(rhdr, 8)) return false;

        // Validate signature
        if (rhdr[0] != 'D' || rhdr[1] != 'A' || rhdr[2] != 'P' || rhdr[3] != '\0') {
            disconnect();
            return false;
        }
        // type must be 0x02 (RSP)
        if (rhdr[6] != 0x02) {
            disconnect();
            return false;
        }

        uint16_t rlen = static_cast<uint16_t>(rhdr[4]) |
                        (static_cast<uint16_t>(rhdr[5]) << 8);

        resp.resize(rlen);
        if (rlen > 0 && !recv_exact(resp.data(), rlen)) {
            disconnect();
            return false;
        }
        return true;
    }

private:
    SOCKET              m_sock;
    std::vector<uint8_t> m_leftover;   // unconsumed bytes from previous recv

    // Send exactly 'n' bytes, handling partial writes
    bool send_all(const uint8_t* data, int n)
    {
        while (n > 0) {
            int sent = ::send(m_sock, reinterpret_cast<const char*>(data), n, 0);
            if (sent <= 0) return false;
            data += sent;
            n    -= sent;
        }
        return true;
    }

    // Receive exactly 'n' bytes; uses leftover buffer to handle TCP fragmentation
    bool recv_exact(uint8_t* dst, int n)
    {
        // First drain any leftover bytes from previous recv
        int from_leftover = (std::min)(n, static_cast<int>(m_leftover.size()));
        if (from_leftover > 0) {
            memcpy(dst, m_leftover.data(), from_leftover);
            m_leftover.erase(m_leftover.begin(), m_leftover.begin() + from_leftover);
            dst += from_leftover;
            n   -= from_leftover;
        }

        while (n > 0) {
            uint8_t tmp[4096];
            int got = ::recv(m_sock, reinterpret_cast<char*>(tmp),
                             (std::min)(n + static_cast<int>(m_leftover.size()), (int)sizeof(tmp)), 0);
            if (got <= 0) return false;

            int copy = (std::min)(got, n);
            memcpy(dst, tmp, copy);
            dst += copy;
            n   -= copy;

            // Save any extra bytes
            if (got > copy) {
                m_leftover.insert(m_leftover.end(), tmp + copy, tmp + got);
            }
        }
        return true;
    }
};
