#include "pch.h"
#include "tcp_transport.hpp"

/*
 * dllmain.cpp — Global state, config loading, DLL entry
 */

// ──────────────────────────────────────────────────────────────────────────
// Global state
// ──────────────────────────────────────────────────────────────────────────
TcpTransport    g_tcp;
CRITICAL_SECTION g_cs;          // guards g_tcp
HMODULE         g_hmod = NULL;  // our own DLL handle (for finding cfg file)

// Config (read from ehublink.cfg next to the DLL)
char     g_cfg_host[256] = "ehub.local";
uint16_t g_cfg_port      = 6000;

// Device info — filled at connect time via DAP_Info commands
char g_product_name[160]     = "CMSIS-DAP EHUB";
char g_serial_number[160]    = "EHUB-001";
char g_firmware_version[20]  = "1.0.0";
uint32_t g_capabilities      = 0x01;  // SWD capable

// Session state
int      g_rddi_handle     = -1;
int      g_debug_clock     = 1000000;   // 1 MHz default
bool     g_is_swd          = true;
bool     g_device_ready    = false;
uint32_t g_detected_dpidr  = 0;         // DPIDR from last DetectNumberOfDAPs

// ──────────────────────────────────────────────────────────────────────────
// Debug log — writes to %TEMP%\ehublink.log and OutputDebugString
//   Helps diagnose WiFi communication failures during flash download.
// ──────────────────────────────────────────────────────────────────────────
void ehub_log(const char* fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, ap);
    va_end(ap);

    OutputDebugStringA("[EHUBLink] ");
    OutputDebugStringA(buf);
    OutputDebugStringA("\n");

    // Also write to file for persistent capture
    char log_path[MAX_PATH] = {};
    GetTempPathA(MAX_PATH, log_path);
    strncat_s(log_path, sizeof(log_path), "ehublink.log", _TRUNCATE);

    FILE* fp = nullptr;
    if (fopen_s(&fp, log_path, "a") == 0 && fp) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        fprintf(fp, "[%02d:%02d:%02d.%03d] %s\n",
                st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, buf);
        fclose(fp);
    }
}

// ──────────────────────────────────────────────────────────────────────────
// Config loader — reads ehublink.cfg from DLL directory
//   host=ehub.local
//   port=6000
// ──────────────────────────────────────────────────────────────────────────
static void load_config()
{
    wchar_t dll_path[MAX_PATH] = {};
    if (!GetModuleFileNameW(g_hmod, dll_path, MAX_PATH)) return;

    // Replace filename with "ehublink.cfg"
    wchar_t* last_sep = wcsrchr(dll_path, L'\\');
    if (!last_sep) return;
    wcscpy_s(last_sep + 1, MAX_PATH - (last_sep - dll_path + 1), L"ehublink.cfg");

    FILE* fp = nullptr;
    if (_wfopen_s(&fp, dll_path, L"r") != 0 || !fp) return;

    char line[512];
    while (fgets(line, sizeof(line), fp)) {
        // Strip trailing newline/CR
        char* nl = strpbrk(line, "\r\n");
        if (nl) *nl = '\0';

        char* eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        const char* key = line;
        const char* val = eq + 1;

        if (_stricmp(key, "host") == 0) {
            strncpy_s(g_cfg_host, sizeof(g_cfg_host), val, _TRUNCATE);
        } else if (_stricmp(key, "port") == 0) {
            g_cfg_port = static_cast<uint16_t>(atoi(val));
        }
    }
    fclose(fp);
}

// ──────────────────────────────────────────────────────────────────────────
// connect_and_fetch_info — TCP connect + DAP_Info(ProductName/Serial/FW)
// Called from RDDI_Open under g_cs.
// ──────────────────────────────────────────────────────────────────────────
static bool dap_info_query(uint8_t info_id, char* out_buf, int buf_size)
{
    uint8_t cmd[2] = { 0x00, info_id };
    std::vector<uint8_t> resp;
    if (!g_tcp.ocd_cmd(cmd, 2, resp)) return false;
    if (resp.size() < 2) return false;
    if (resp[0] != 0x00) return false;

    int data_len = resp[1];
    if (data_len <= 0) return false;

    int copy_len = (std::min)(data_len, buf_size - 1);
    memcpy(out_buf, resp.data() + 2, copy_len);
    out_buf[copy_len] = '\0';
    return true;
}

bool connect_and_fetch_info()
{
    if (!g_tcp.connect(g_cfg_host, g_cfg_port)) return false;

    // Query device info
    dap_info_query(0x02, g_product_name,    sizeof(g_product_name));    // Product Name
    dap_info_query(0x03, g_serial_number,   sizeof(g_serial_number));   // Serial Number
    dap_info_query(0x04, g_firmware_version,sizeof(g_firmware_version));// FW Version

    // Capabilities
    uint8_t caps_cmd[2] = { 0x00, 0xF0 };
    std::vector<uint8_t> caps_resp;
    if (g_tcp.ocd_cmd(caps_cmd, 2, caps_resp) && caps_resp.size() >= 3) {
        g_capabilities = caps_resp[2];
    }

    g_device_ready = true;
    return true;
}

// ──────────────────────────────────────────────────────────────────────────
// DllMain
// ──────────────────────────────────────────────────────────────────────────
BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID /*reserved*/)
{
    switch (reason)
    {
    case DLL_PROCESS_ATTACH:
        g_hmod = hModule;
        DisableThreadLibraryCalls(hModule);
        InitializeCriticalSection(&g_cs);
        load_config();
        break;

    case DLL_PROCESS_DETACH:
        g_tcp.disconnect();
        DeleteCriticalSection(&g_cs);
        WSACleanup();
        break;
    }
    return TRUE;
}
