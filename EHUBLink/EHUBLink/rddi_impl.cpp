#include "pch.h"
#include "tcp_transport.hpp"

// ARM RDDI headers (from elaphureLink-master\common\)
#include "..\..\elaphureLink-master\common\rddi.h"
#include "..\..\elaphureLink-master\common\rddi_dap.h"
#include "..\..\elaphureLink-master\common\rddi_dap_cmsis.h"
#include "..\..\elaphureLink-master\common\dap.hpp"

/*
 * rddi_impl.cpp — All ARM RDDI exported functions
 *
 * Architecture:
 *   Keil calls RDDI functions → we build CMSIS-DAP commands → ocd_cmd() →
 *   EHUB ESP32 (port 6000, OpenOCD TCP framing) → EHUB MCU SWD → target
 *
 * Each ocd_cmd() is one send+recv cycle; TCP framing ensures no sync loss.
 */

// ──────────────────────────────────────────────────────────────────────────
// External globals (declared in dllmain.cpp)
// ──────────────────────────────────────────────────────────────────────────
extern TcpTransport     g_tcp;
extern CRITICAL_SECTION g_cs;
extern char             g_product_name[160];
extern char             g_serial_number[160];
extern char             g_firmware_version[20];
extern uint32_t         g_capabilities;
extern int              g_rddi_handle;
extern int              g_debug_clock;
extern bool             g_is_swd;
extern bool             g_device_ready;
extern uint32_t         g_detected_dpidr;
extern bool             connect_and_fetch_info();
extern void             ehub_log(const char* fmt, ...);

// ── Error-code helpers ────────────────────────────────────────────────────
// RDDI_FAILED / RDDI_INTERNAL_ERROR both map to rddi::RDDI_DAP_ERROR (0x2000)
// inside SWD_CheckStatus, which bypasses EU14 conversion → "Unknown Error".
//
// Returning RDDI_DAP_OPERATION_TIMEOUT / RDDI_DAP_DP_STICKY_ERR instead makes
// SWD_CheckStatus abort+retry properly and return RDDI_DAP_ERROR_MEMORY(0x2005),
// which then gets converted to EU14 "Cannot access Memory" by SWD.cpp line 1790.
// ─────────────────────────────────────────────────────────────────────────
static inline int tcp_fail(const char* caller)
{
    ehub_log("%s: TCP/socket failed — WiFi comm error?", caller);
    return RDDI_DAP_OPERATION_TIMEOUT;   // handled by SWD_CheckStatus → EU14
}
static inline int ack_fail(const char* caller, int ack)
{
    ehub_log("%s: bad DAP ack=0x%02x", caller, ack);
    return RDDI_DAP_DP_STICKY_ERR;       // handled by SWD_CheckStatus → EU14
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS-DAP register address map (from elaphureLink)
//   Indices 0-3  → DP regs  (APnDP=0):  A=00,01,10,11 → 0x00,0x04,0x08,0x0C
//   Indices 4-7  → AP regs  (APnDP=1):  A=00,01,10,11 → 0x01,0x05,0x09,0x0D
// ──────────────────────────────────────────────────────────────────────────
static const uint8_t k_reg_map[] = {
    0x00, 0x04, 0x08, 0x0C,   // DP_0x0 … DP_0xC
    0x01, 0x05, 0x09, 0x0D,   // AP_0x0 … AP_0xC
};
static_assert(sizeof(k_reg_map) == 8, "");

// ──────────────────────────────────────────────────────────────────────────
// DAP response parsing helpers
// ──────────────────────────────────────────────────────────────────────────

/*
 * parse_transfer_resp — parse a DAP_Transfer (0x05) or
 *   ExecuteCommands-wrapped (0x7F) response.
 *
 * Walk sub-command responses until we find 0x05 (Transfer),
 * verify transfer_count (if >= 0), fill read_data[], return ack.
 */
static int parse_transfer_resp(const std::vector<uint8_t>& b,
                                int read_count,
                                int* read_data,
                                int  transfer_count_expected = -1)
{
    if (b.empty()) return (int)DAP_RES_ERROR;
    const uint8_t* p   = b.data();
    const uint8_t* end = p + b.size();

    if (*p == 0x7F) {
        // ExecuteCommands: [0x7F][n_cmds][sub_resp1][sub_resp2]...
        if (p + 2 > end) return (int)DAP_RES_ERROR;
        // int n_cmds = p[1];  // not used explicitly — we walk until ID_DAP_Transfer
        p += 2;

        // Walk sub-responses (each is 2 bytes for non-Transfer commands)
        while (p < end && *p != ID_DAP_Transfer) {
            p += 2;   // Disconnect, Connect, SWJ_Clock, TransferConfigure,
                      // SWD_Configure, SWJ_Sequence all have 2-byte responses
        }
    }

    if (p + 3 > end || *p != ID_DAP_Transfer) return (int)DAP_RES_ERROR;
    p++;                          // skip cmd id

    int actual_count = *p++;
    int ack          = *p++;

    if (transfer_count_expected >= 0 && actual_count != transfer_count_expected)
        return (int)DAP_RES_FAULT;

    if (ack != DAP_RES_OK) return ack;

    // Copy read words
    for (int i = 0; i < read_count; i++) {
        if (p + 4 > end) return (int)DAP_RES_ERROR;
        memcpy(&read_data[i], p, 4);
        p += 4;
    }
    return ack;
}

/*
 * parse_transfer_block_resp — parse a DAP_TransferBlock (0x06) response.
 */
static int parse_transfer_block_resp(const std::vector<uint8_t>& b,
                                      int expected_count,
                                      int* data_out)
{
    if (b.size() < 4) {
        ehub_log("parse_TransferBlock: short resp size=%d", (int)b.size());
        return (int)DAP_RES_ERROR;
    }
    if (b[0] != ID_DAP_TransferBlock) {
        ehub_log("parse_TransferBlock: bad cmd_id=0x%02x (expected 0x06), size=%d, bytes=%02x %02x %02x %02x",
                 b[0], (int)b.size(), b[0],
                 b.size()>1?b[1]:0, b.size()>2?b[2]:0, b.size()>3?b[3]:0);
        return (int)DAP_RES_ERROR;
    }

    int actual_count = static_cast<int>(b[1]) | (static_cast<int>(b[2]) << 8);
    int ack          = b[3];

    if (ack != DAP_RES_OK) {
        ehub_log("parse_TransferBlock: ack=0x%02x actual_count=%d expected=%d", ack, actual_count, expected_count);
        return ack;
    }
    if (actual_count != expected_count) {
        ehub_log("parse_TransferBlock: count mismatch actual=%d expected=%d ack=%d", actual_count, expected_count, ack);
        return (int)DAP_RES_FAULT;
    }
    // For WRITE operations data_out is nullptr; response is only 4 bytes (no data payload).
    // Only validate and copy the data payload for READ operations (data_out != nullptr).
    if (data_out) {
        if ((int)b.size() < 4 + expected_count * 4) {
            ehub_log("parse_TransferBlock: read resp too short size=%d expected=%d", (int)b.size(), 4 + expected_count * 4);
            return (int)DAP_RES_ERROR;
        }
        memcpy(data_out, b.data() + 4, expected_count * 4);
    }
    return ack;
}

// ──────────────────────────────────────────────────────────────────────────
// Convenience: lock-guarded ocd_cmd
// ──────────────────────────────────────────────────────────────────────────
static bool tcp_cmd(const std::vector<uint8_t>& cmd, std::vector<uint8_t>& resp)
{
    EnterCriticalSection(&g_cs);
    bool ok = g_tcp.ocd_cmd(cmd.data(), static_cast<uint16_t>(cmd.size()), resp);
    LeaveCriticalSection(&g_cs);
    return ok;
}

// ──────────────────────────────────────────────────────────────────────────
// RDDI core functions
// ──────────────────────────────────────────────────────────────────────────

RDDI_FUNC int RDDI_Open(RDDIHandle* pHandle, const void* /*pDetails*/)
{
    if (g_rddi_handle != -1) return RDDI_TOOMANYCONNECTIONS;
    if (!pHandle)             return RDDI_BADARG;

    // Connect and fetch device info
    EnterCriticalSection(&g_cs);
    bool ok = connect_and_fetch_info();
    LeaveCriticalSection(&g_cs);

    if (!ok) return RDDI_FAILED;

    g_rddi_handle = 1;
    *pHandle      = 1;
    return RDDI_SUCCESS;
}

RDDI_FUNC int RDDI_Close(RDDIHandle handle)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;

    EnterCriticalSection(&g_cs);
    g_tcp.disconnect();
    g_device_ready = false;
    LeaveCriticalSection(&g_cs);

    g_rddi_handle = -1;
    return RDDI_SUCCESS;
}

RDDI_FUNC int RDDI_GetLastError(int* /*pError*/, char* pDetails, size_t detailsLen)
{
    if (pDetails && detailsLen > 0) pDetails[0] = '\0';
    return RDDI_SUCCESS;
}

RDDI_FUNC void RDDI_SetLogCallback(RDDIHandle, RDDILogCallback, void*, int) {}

// ──────────────────────────────────────────────────────────────────────────
// DAP core functions
// ──────────────────────────────────────────────────────────────────────────

RDDI_FUNC int DAP_GetInterfaceVersion(const RDDIHandle, int* version)
{
    if (version) *version = 1;
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_Configure(const RDDIHandle handle, const char* /*configFileName*/)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_Connect(const RDDIHandle handle, RDDI_DAP_CONN_DETAILS* /*pConnDetails*/)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_Disconnect(const RDDIHandle /*handle*/)
{
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_GetSupportedOptimisationLevel(const RDDIHandle, int* level)
{
    if (level) *level = 0;
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_GetNumberOfDAPs(const RDDIHandle, int* n)
{
    if (n) *n = 1;
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_GetDAPIDList(const RDDIHandle, int* arr, size_t sz)
{
    if (arr && sz >= 1) arr[0] = 0;
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// Single register read (DAP_Transfer read)
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int DAP_ReadReg(const RDDIHandle handle, const int DAP_ID,
                           const int regID, int* value)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;
    if (!value)                   return RDDI_BADARG;

    const uint16_t reg_low  = regID & 0xFFFF;
    if (reg_low >= 8) return RDDI_BADARG;

    uint8_t req = k_reg_map[reg_low] | 0x02;  // read bit

    std::vector<uint8_t> cmd = {
        ID_DAP_Transfer,
        static_cast<uint8_t>(DAP_ID),
        0x01,   // transfer count
        req
    };

    std::vector<uint8_t> resp;
    if (!tcp_cmd(cmd, resp)) return tcp_fail("DAP_ReadReg");

    int ack = parse_transfer_resp(resp, 1, value, 1);
    if (ack == DAP_RES_FAULT)  return RDDI_DAP_DP_STICKY_ERR;
    if (ack != DAP_RES_OK)     return ack_fail("DAP_ReadReg", ack);
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// Single register write (DAP_Transfer write, or DAP_WriteABORT)
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int DAP_WriteReg(const RDDIHandle handle, const int DAP_ID,
                            const int regID, const int value)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;

    const uint16_t reg_low = regID & 0xFFFF;
    if (reg_low >= 8 && reg_low != DAP_REG_DP_ABORT) return RDDI_BADARG;

    const uint8_t* data = reinterpret_cast<const uint8_t*>(&value);

    // ABORT register → use DAP_WriteABORT (0x08)
    if (reg_low == DAP_REG_DP_ABORT) {
        std::vector<uint8_t> cmd = {
            ID_DAP_WriteABORT,
            static_cast<uint8_t>(DAP_ID),
            data[0], data[1], data[2], data[3]
        };
        std::vector<uint8_t> resp;
        if (!tcp_cmd(cmd, resp)) return tcp_fail("DAP_WriteReg:ABORT");
        if (resp.size() < 2 || resp[1] != 0x00) return ack_fail("DAP_WriteReg:ABORT", resp.size() >= 2 ? resp[1] : -1);
        return RDDI_SUCCESS;
    }

    uint8_t req = k_reg_map[reg_low];  // write: no read bit

    std::vector<uint8_t> cmd = {
        ID_DAP_Transfer,
        static_cast<uint8_t>(DAP_ID),
        0x01,   // transfer count
        req,
        data[0], data[1], data[2], data[3]
    };

    std::vector<uint8_t> resp;
    if (!tcp_cmd(cmd, resp)) return tcp_fail("DAP_WriteReg");

    int ack = parse_transfer_resp(resp, 0, nullptr, 1);
    if (ack == DAP_RES_FAULT) return RDDI_DAP_DP_STICKY_ERR;
    if (ack != DAP_RES_OK)    return ack_fail("DAP_WriteReg", ack);
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// Bulk register access — mirrors elaphureLink's DAP_RegAccessBlock exactly
// but replaces shared-memory IPC with direct tcp_cmd().
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int DAP_RegAccessBlock(const RDDIHandle handle, const int DAP_ID,
                                  const int numRegs,
                                  const int* regIDArray, int* dataArray)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;

    // Indices of reads, in command order (for result mapping)
    std::vector<int> read_reg_index_array;

    // ── Initial command array (plain DAP_Transfer) ────────────────────
    constexpr int XFER_IDX  = 2;   // [0x05][idx][->count<-]...
    constexpr int XFER_INIT = 3;   // initial size

    std::vector<uint8_t> dap_cmd = {
        ID_DAP_Transfer, static_cast<uint8_t>(DAP_ID), 0x00
    };

    // ── Helper: build ExecCmds+TransferConfigure+Transfer header ──────
    auto set_cmd_with_retry = [&](uint16_t retry_count) {
        const uint8_t* pr = reinterpret_cast<const uint8_t*>(&retry_count);
        dap_cmd = {
            ID_DAP_ExecuteCommands, 0x02,
            ID_DAP_TransferConfigure,
            0x00, pr[0], pr[1], pr[0], pr[1],
            ID_DAP_Transfer, static_cast<uint8_t>(DAP_ID), 0x00
        };
    };

    constexpr int EXEC_XFER_IDX  = 0x0A;
    constexpr int EXEC_INIT      = 11;

    // ── Helper: send dap_cmd, parse response ─────────────────────────
    // Returns 0 on success, RDDI error code on failure.
    auto send_and_parse = [&](int transfer_count, int read_count) -> int {
        std::vector<uint8_t> resp;
        if (!tcp_cmd(dap_cmd, resp)) return tcp_fail("DAP_RegAccessBlock");

        std::vector<int> read_vals(read_count);
        int ack = parse_transfer_resp(resp,
                                       read_count,
                                       read_count > 0 ? read_vals.data() : nullptr,
                                       transfer_count);

        if (ack == DAP_RES_FAULT)  return RDDI_DAP_DP_STICKY_ERR;
        if (ack != DAP_RES_OK)     return ack_fail("DAP_RegAccessBlock", ack);

        // Map read values back to caller's dataArray
        for (int j = 0; j < read_count; j++)
            dataArray[read_reg_index_array[j]] = read_vals[j];

        return 0;
    };

    int i = 0, ret = 0;

    while (i <= numRegs) {
        int xfer_count      = 0;
        int read_count      = 0;
        read_reg_index_array.clear();

        for (; i < numRegs; i++) {
            const int      rid    = regIDArray[i];
            const uint16_t rh     = rid >> 16;
            const uint16_t rl     = rid & 0xFFFF;

            if (rl == DAP_REG_MATCH_RETRY) break;

            xfer_count++;

            if (rl == DAP_REG_MATCH_MASK) {
                // Write match mask
                const uint8_t* pv = reinterpret_cast<const uint8_t*>(&dataArray[i]);
                dap_cmd.push_back(0x20);
                dap_cmd.insert(dap_cmd.end(), pv, pv + 4);

            } else if (rh == (DAP_REG_RnW | DAP_REG_WaitForValue) >> 16) {
                // Value-match read
                const uint8_t* pv = reinterpret_cast<const uint8_t*>(&dataArray[i]);
                dap_cmd.push_back(k_reg_map[rl] | 0x12);  // Value_Match | RnW
                dap_cmd.insert(dap_cmd.end(), pv, pv + 4);

            } else if (rh & (DAP_REG_RnW >> 16)) {
                // Read
                read_count++;
                read_reg_index_array.push_back(i);
                dap_cmd.push_back(k_reg_map[rl] | 0x02);

            } else {
                // Write
                const uint8_t* pv = reinterpret_cast<const uint8_t*>(&dataArray[i]);
                dap_cmd.push_back(k_reg_map[rl]);
                dap_cmd.insert(dap_cmd.end(), pv, pv + 4);
            }
        }

        if (i < numRegs) {
            // Hit a MATCH_RETRY separator
            if (dap_cmd[0] == ID_DAP_Transfer && (int)dap_cmd.size() == XFER_INIT) {
                // Nothing to send before this MATCH_RETRY — just reset
                ;
            } else if (dap_cmd[0] == ID_DAP_ExecuteCommands && (int)dap_cmd.size() == EXEC_INIT) {
                // Only TransferConfigure needs sending (no Transfer data yet)
                dap_cmd[1] = 0x01;
                dap_cmd.resize(8);   // ExecCmds + TransferConfigure only
                if ((ret = send_and_parse(0, 0)) != 0) return ret;
            } else if (dap_cmd[0] == ID_DAP_Transfer) {
                dap_cmd[XFER_IDX] = static_cast<uint8_t>(xfer_count);
                if ((ret = send_and_parse(xfer_count, read_count)) != 0) return ret;
            } else {
                dap_cmd[EXEC_XFER_IDX] = static_cast<uint8_t>(xfer_count);
                if ((ret = send_and_parse(xfer_count, read_count)) != 0) return ret;
            }
            set_cmd_with_retry(static_cast<uint16_t>(dataArray[i]));

        } else {
            // End of array — send whatever we have
            if (dap_cmd[0] == ID_DAP_Transfer) {
                dap_cmd[XFER_IDX] = static_cast<uint8_t>(xfer_count);
            } else {
                if ((int)dap_cmd.size() == EXEC_INIT) {
                    dap_cmd[1] = 0x01;
                    dap_cmd.resize(8);
                } else {
                    dap_cmd[1]           = 0x02;
                    dap_cmd[EXEC_XFER_IDX] = static_cast<uint8_t>(xfer_count);
                }
            }
            if ((ret = send_and_parse(xfer_count, read_count)) != 0) return ret;
        }

        i++;
    }

    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_RegWriteBlock(const RDDIHandle, const int, const int,
                                 const int*, const int*)
{ return 8204; }

RDDI_FUNC int DAP_RegReadBlock(const RDDIHandle, const int, const int,
                                const int*, int*)
{ return 8204; }

// ──────────────────────────────────────────────────────────────────────────
// Bulk write (DAP_TransferBlock write) — e.g. flash programming
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int DAP_RegWriteRepeat(const RDDIHandle handle, const int DAP_ID,
                                  const int numRepeats,
                                  const int regID, const int* dataArray)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;

    const uint16_t rl = regID & 0xFFFF;
    if (rl >= 8) return RDDI_BADARG;

    uint8_t req = k_reg_map[rl];  // write

    // Max words per TCP frame to stay within EHUB's packet limit (≈260 words)
    constexpr int MAX_PER_CHUNK = 248;

    for (int i = 0; i < numRepeats; i += MAX_PER_CHUNK) {
        int16_t count = static_cast<int16_t>(
            std::min(MAX_PER_CHUNK, numRepeats - i));
        const uint8_t* pc = reinterpret_cast<const uint8_t*>(&count);

        std::vector<uint8_t> cmd = {
            ID_DAP_TransferBlock,
            static_cast<uint8_t>(DAP_ID),
            pc[0], pc[1],   // count LE16
            req
        };
        // Append data words
        const uint8_t* src = reinterpret_cast<const uint8_t*>(&dataArray[i]);
        cmd.insert(cmd.end(), src, src + count * 4);

        std::vector<uint8_t> resp;
        if (!tcp_cmd(cmd, resp)) return tcp_fail("DAP_RegWriteRepeat");

        int ack = parse_transfer_block_resp(resp, count, nullptr);
        if (ack != DAP_RES_OK) return ack_fail("DAP_RegWriteRepeat", ack);
    }
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// Bulk read (DAP_TransferBlock read) — e.g. memory read
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int DAP_RegReadRepeat(const RDDIHandle handle, const int DAP_ID,
                                 const int numRepeats,
                                 const int regID, int* dataArray)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;

    const uint16_t rl = regID & 0xFFFF;
    if (rl >= 8) return RDDI_BADARG;

    uint8_t req = k_reg_map[rl] | 0x02;  // read
    constexpr int MAX_PER_CHUNK = 248;

    for (int i = 0; i < numRepeats; i += MAX_PER_CHUNK) {
        int16_t count = static_cast<int16_t>(
            std::min(MAX_PER_CHUNK, numRepeats - i));
        const uint8_t* pc = reinterpret_cast<const uint8_t*>(&count);

        std::vector<uint8_t> cmd = {
            ID_DAP_TransferBlock,
            static_cast<uint8_t>(DAP_ID),
            pc[0], pc[1],
            req
        };

        std::vector<uint8_t> resp;
        if (!tcp_cmd(cmd, resp)) return tcp_fail("DAP_RegReadRepeat");

        int ack = parse_transfer_block_resp(resp, count, &dataArray[i]);
        if (ack != DAP_RES_OK) return ack_fail("DAP_RegReadRepeat", ack);
    }
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_RegReadWaitForValue(const RDDIHandle, const int, const int,
                                       const int, const int*, const int*)
{ return 8204; }

RDDI_FUNC int DAP_Target(const RDDIHandle, const char*, char* resp, const int resp_len)
{
    if (resp && resp_len > 0) resp[0] = '\0';
    return RDDI_SUCCESS;
}

RDDI_FUNC int DAP_DefineSequence(const RDDIHandle, const int, void*) { return 8204; }
RDDI_FUNC int DAP_RunSequence(const RDDIHandle, const int, void*, void*) { return 8204; }

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP interface detection / identification
// ──────────────────────────────────────────────────────────────────────────

RDDI_FUNC int CMSIS_DAP_Detect(const RDDIHandle handle, int* noOfIFs)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (noOfIFs) *noOfIFs = 1;
    return RDDI_SUCCESS;
}

RDDI_FUNC int CMSIS_DAP_Identify(const RDDIHandle handle, int ifNo,
                                   int idNo, char* str, const int len)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!str || len <= 0)         return RDDI_BADARG;
    (void)ifNo;

    switch (idNo) {
    case RDDI_CMSIS_DAP_ID_PRODUCT:  strncpy_s(str, len, g_product_name,    _TRUNCATE); break;
    case RDDI_CMSIS_DAP_ID_SER_NUM:  strncpy_s(str, len, g_serial_number,   _TRUNCATE); break;
    case RDDI_CMSIS_DAP_ID_FW_VER:   strncpy_s(str, len, g_firmware_version,_TRUNCATE); break;
    default:
        if (len > 0) str[0] = '\0';
        break;
    }
    return RDDI_SUCCESS;
}

RDDI_FUNC int CMSIS_DAP_GetGUID(const RDDIHandle handle, int /*ifNo*/,
                                  char* str, const int len)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (str && len > 0) strncpy_s(str, len, "EHUBLink", _TRUNCATE);
    return RDDI_SUCCESS;
}

RDDI_FUNC int CMSIS_DAP_Capabilities(const RDDIHandle handle, int /*ifNo*/,
                                       int* cap_info)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (cap_info) *cap_info = INFO_CAPS_SWD;
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP_ConfigureInterface — parse "Port=SW;Clock=10000000;..."
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_ConfigureInterface(const RDDIHandle handle,
                                             int /*ifNo*/, char* str)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!str) return RDDI_SUCCESS;

    const char* p = str;
    char key[64]={}, val[256]={};
    int k=0, v=0, st=0;

    while (*p) {
        if (st == 0) {         // parsing key
            if (*p == '=')      { key[k]='\0'; st=1; k=0; }
            else if (k<62)      key[k++] = *p;
        } else {               // parsing value
            if (*p == ';') {
                val[v]='\0';
                // Apply setting
                if (_stricmp(key,"Port")  == 0) g_is_swd = (_stricmp(val,"SW") == 0);
                if (_stricmp(key,"Clock") == 0) g_debug_clock = atoi(val);
                k=v=0; st=0; memset(key,0,sizeof(key)); memset(val,0,sizeof(val));
            } else if (v<254)  val[v++] = *p;
        }
        p++;
    }
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP_ConfigureDAP — parse "SWJSwitch=E79E" etc. (nothing actionable yet)
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_ConfigureDAP(const RDDIHandle handle, const char* /*str*/)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP_DetectNumberOfDAPs — full SWD init + DPIDR read
// Uses same ExecuteCommands sequence as elaphureLink.
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_DetectNumberOfDAPs(const RDDIHandle handle, int* noOfDAPs)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;
    if (!g_is_swd)                return RDDI_FAILED;  // JTAG not implemented

    int clock = g_debug_clock;
    const uint8_t* pc = reinterpret_cast<const uint8_t*>(&clock);

    // ExecuteCommands wrapping 10 sub-commands:
    //   Disconnect → Connect(SWD) → SWJ_Clock → TransferConfigure →
    //   SWD_Configure → SWJ_Seq×4 → Transfer(DPIDR)
    std::vector<uint8_t> cmd = {
        0x7F, 0x0A,                                               // ExecuteCommands, 10
        0x03,                                                     // Disconnect
        0x02, 0x01,                                               // Connect SWD
        0x11, pc[0], pc[1], pc[2], pc[3],                        // SWJ_Clock (LE32)
        0x04, 0x00, 0x64, 0x00, 0x00, 0x00,                      // TransferConfigure
        0x13, 0x00,                                               // SWD_Configure
        0x12, 0x33, 0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,          // SWJ_Seq 51b reset
        0x12, 0x10, 0x9E, 0xE7,                                   // SWJ_Seq 16b JTAG→SWD
        0x12, 0x33, 0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,          // SWJ_Seq 51b reset
        0x12, 0x08, 0x00,                                         // SWJ_Seq 8b idle
        0x05, 0x00, 0x01, 0x02,                                   // Transfer: read DPIDR
    };

    std::vector<uint8_t> resp;
    if (!tcp_cmd(cmd, resp)) return tcp_fail("DetectNumberOfDAPs:init");

    // Parse response: walk sub-responses to find Transfer at end
    int dpidr_val = 0;
    int ack = parse_transfer_resp(resp, 1, &dpidr_val, 1);
    if (ack != DAP_RES_OK) return ack_fail("DetectNumberOfDAPs:DPIDR", ack);

    // Save DPIDR for DetectDAPIDList
    g_detected_dpidr = (uint32_t)dpidr_val;

    // Second pass: re-read DPIDR to verify stability
    std::vector<uint8_t> cmd2 = {
        0x7F, 0x02,
        0x12, 0x08, 0x00,       // SWJ_Seq 8b idle
        0x05, 0x00, 0x01, 0x02, // Transfer: read DPIDR
    };
    std::vector<uint8_t> resp2;
    if (!tcp_cmd(cmd2, resp2)) return tcp_fail("DetectNumberOfDAPs:verify");

    int dpidr2 = 0;
    ack = parse_transfer_resp(resp2, 1, &dpidr2, 1);
    if (ack != DAP_RES_OK) return ack_fail("DetectNumberOfDAPs:verify", ack);
    if (dpidr_val != dpidr2) { ehub_log("DetectNumberOfDAPs: DPIDR mismatch 0x%08X vs 0x%08X", dpidr_val, dpidr2); return RDDI_DAP_DP_STICKY_ERR; }

    if (noOfDAPs) *noOfDAPs = 1;
    return RDDI_SUCCESS;
}

RDDI_FUNC int CMSIS_DAP_DetectDAPIDList(const RDDIHandle handle,
                                         int* DAP_ID_Array, size_t sizeOfArray)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (DAP_ID_Array && sizeOfArray >= 1)
        DAP_ID_Array[0] = (int)g_detected_dpidr;
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP_Commands — pass-through for single raw CMSIS-DAP commands
//   (elaphureLink only implements DAP_ResetTarget here)
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_Commands(const RDDIHandle handle, int num,
                                  unsigned char** request, int* req_len,
                                  unsigned char** response, int* resp_len)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (num != 1) return 8204;

    std::vector<uint8_t> cmd(request[0], request[0] + req_len[0]);
    std::vector<uint8_t> resp;
    if (!tcp_cmd(cmd, resp)) return tcp_fail("CMSIS_DAP_Commands");

    int copy = (std::min)(static_cast<int>(resp.size()), resp_len[0]);
    memcpy(response[0], resp.data(), copy);
    resp_len[0] = copy;
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP_SWJ_Sequence — send SWJ bit sequence
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_SWJ_Sequence(const RDDIHandle handle,
                                       int num, unsigned char* request)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;

    int nbytes = (num + 7) / 8;
    std::vector<uint8_t> cmd = { 0x12, static_cast<uint8_t>(num) };
    cmd.insert(cmd.end(), request, request + nbytes);

    std::vector<uint8_t> resp;
    if (!tcp_cmd(cmd, resp)) return tcp_fail("SWJ_Sequence");
    if (resp.size() < 2 || resp[1] != 0x00) return ack_fail("SWJ_Sequence", resp.size() >= 2 ? resp[1] : -1);
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// CMSIS_DAP_SWJ_Pins — read/write SWJ pin state
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_SWJ_Pins(const RDDIHandle handle,
                                   unsigned char pinselect, unsigned char pinout,
                                   int* res, int wait)
{
    if (handle != g_rddi_handle) return RDDI_INVHANDLE;
    if (!g_device_ready)          return RDDI_FAILED;

    const uint8_t* pw = reinterpret_cast<const uint8_t*>(&wait);
    std::vector<uint8_t> cmd = { 0x10, pinout, pinselect, pw[0], pw[1], pw[2], pw[3] };

    std::vector<uint8_t> resp;
    if (!tcp_cmd(cmd, resp)) return tcp_fail("SWJ_Pins");
    if (resp.size() >= 2 && res) *res = resp[1];
    return RDDI_SUCCESS;
}

// ──────────────────────────────────────────────────────────────────────────
// Stubs — functions Keil may call but behave benignly if returning 8204
// ──────────────────────────────────────────────────────────────────────────
RDDI_FUNC int CMSIS_DAP_Disconnect()                  { return 8204; }
RDDI_FUNC int DAP_SetCommTimeout()                    { return 8204; }
RDDI_FUNC int CMSIS_DAP_GetInterfaceVersion()         { return 8204; }
RDDI_FUNC int CMSIS_DAP_ResetDAP()                    { return 8204; }
RDDI_FUNC int CMSIS_DAP_JTAG_Sequence()               { return 8204; }
RDDI_FUNC int CMSIS_DAP_Atomic_Result()               { return RDDI_SUCCESS; }
RDDI_FUNC int CMSIS_DAP_Atomic_Control()              { return RDDI_SUCCESS; }
RDDI_FUNC int CMSIS_DAP_WriteABORT()                  { return 8204; }
RDDI_FUNC int CMSIS_DAP_JTAG_GetIDCODEs()             { return 8204; }
RDDI_FUNC int CMSIS_DAP_JTAG_GetIRLengths()           { return 8204; }
RDDI_FUNC int CMSIS_DAP_Delay()                       { return RDDI_SUCCESS; }
RDDI_FUNC int CMSIS_DAP_SWJ_Clock()                   { return 8204; }
RDDI_FUNC int CMSIS_DAP_ConfigureDebugger()           { return RDDI_SUCCESS; }
RDDI_FUNC int CMSIS_DAP_GetBoardInfo()                { return 8204; }
RDDI_FUNC int CMSIS_DAP_GetDebugDevices()             { return 8204; }
