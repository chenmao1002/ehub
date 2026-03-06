#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define _WINSOCK_DEPRECATED_NO_WARNINGS
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cassert>
#include <vector>
#include <string>
#include <algorithm>

#pragma comment(lib, "ws2_32.lib")
