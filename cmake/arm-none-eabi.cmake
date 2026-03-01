set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR ARM)

# GNU Arm Embedded Toolchain 完整路径 (含 .exe，避免含空格路径被截断)
set(TOOLCHAIN_BIN "F:/vscode/openstm32/Arm GNU Toolchain arm-none-eabi/14.3 rel1/bin")

set(CMAKE_C_COMPILER   "${TOOLCHAIN_BIN}/arm-none-eabi-gcc.exe"   CACHE FILEPATH "C compiler")
set(CMAKE_CXX_COMPILER "${TOOLCHAIN_BIN}/arm-none-eabi-g++.exe"   CACHE FILEPATH "C++ compiler")
set(CMAKE_ASM_COMPILER "${TOOLCHAIN_BIN}/arm-none-eabi-gcc.exe"   CACHE FILEPATH "ASM compiler")
set(CMAKE_AR           "${TOOLCHAIN_BIN}/arm-none-eabi-ar.exe"    CACHE FILEPATH "Archiver")
set(CMAKE_OBJCOPY      "${TOOLCHAIN_BIN}/arm-none-eabi-objcopy.exe")
set(CMAKE_OBJDUMP      "${TOOLCHAIN_BIN}/arm-none-eabi-objdump.exe")
set(CMAKE_SIZE         "${TOOLCHAIN_BIN}/arm-none-eabi-size.exe")

set(CMAKE_EXECUTABLE_SUFFIX_C   .elf)
set(CMAKE_EXECUTABLE_SUFFIX_CXX .elf)
set(CMAKE_EXECUTABLE_SUFFIX_ASM .elf)

# 防止 CMake 尝试测试编译 (交叉编译时必须)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# 查找根路径
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
