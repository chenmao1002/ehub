#ifdef _RTE_
#include "RTE_Components.h"
// STM32F407 对应的 CMSIS 设备头文件（直接替换宏，避免编译错误）
#include "stm32f4xx.h"
#else
// 若未使用 RTE，直接包含 STM32F407 设备头文件（替代原 device.h，无需额外自定义）
#include "stm32f4xx.h"
#endif

/// Processor Clock of the Cortex-M MCU used in the Debug Unit.
/// STM32F407 常用主频为 168MHz（HSE 8MHz 倍频后），若你确实用 72MHz 可保留，建议按实际配置修改
#define CPU_CLOCK               120000000U      ///< STM32F407 典型主频：168MHz（若你的硬件是 72MHz 可改回 72000000U）

/// Number of processor cycles for I/O Port write operations.
/// STM32F4 是 Cortex-M4 内核，默认需要 2 个时钟周期，保持默认
#define IO_PORT_WRITE_CYCLES    2U              ///< I/O Cycles: 2=Cortex-M4 标准，无需修改

/// Indicate that Serial Wire Debug (SWD) communication mode is available at the Debug Access Port.
#define DAP_SWD                 1               ///< SWD Mode:  1 = available, 0 = not available.

/// Indicate that JTAG communication mode is available at the Debug Port.
#define DAP_JTAG                1               ///< JTAG Mode: 1 = available, 0 = not available.

/// Configure maximum number of JTAG devices on the scan chain connected to the Debug Access Port.
#define DAP_JTAG_DEV_CNT        8U              ///< Maximum number of JTAG devices on scan chain.

/// Default communication mode on the Debug Access Port.
#define DAP_DEFAULT_PORT        1U              ///< Default JTAG/SWJ Port Mode: 1 = SWD, 2 = JTAG.

/// Default communication speed on the Debug Access Port for SWD and JTAG mode.
/// 1MHz 是安全默认值，若需更快可调整（需匹配硬件）
#define DAP_DEFAULT_SWJ_CLOCK   1000000U        ///< Default SWD/JTAG clock frequency in Hz.

/// Maximum Package Size for Command and Response data.
/// STM32F4 USB 全速 HID 推荐 64 字节，保持默认
#define DAP_PACKET_SIZE         64U             ///< Specifies Packet Size in bytes.

/// Maximum Package Buffers for Command and Response data.
#define DAP_PACKET_COUNT        4U              ///< Specifies number of packets buffered.

/// Indicate that UART Serial Wire Output (SWO) trace is available.
/// STM32F4 支持 SWO UART 模式，若需要启用可改为 1（需硬件配合）
#define SWO_UART                0               ///< SWO UART:  1 = available, 0 = not available.

/// Maximum SWO UART Baudrate.
/// 配合 168MHz 主频，最大可支持 25MHz，此处保持默认即可
#define SWO_UART_MAX_BAUDRATE   10000000U       ///< SWO UART Maximum Baudrate in Hz.

/// Indicate that Manchester Serial Wire Output (SWO) trace is available.
#define SWO_MANCHESTER          0               ///< SWO Manchester:  1 = available, 0 = not available.

/// SWO Trace Buffer Size.
#define SWO_BUFFER_SIZE         8192U           ///< SWO Trace Buffer Size in bytes (must be 2^n).

/// SWO Streaming Trace.
#define SWO_STREAM              0               ///< SWO Streaming Trace: 1 = available, 0 = not available.

/// Clock frequency of the Test Domain Timer.
/// 与 CPU 时钟保持一致（168MHz），若用 72MHz 需同步修改
#define TIMESTAMP_CLOCK         120000000U      ///< Timestamp clock in Hz (0 = timestamps not supported).

/// Debug Unit is connected to fixed Target Device.
#define TARGET_DEVICE_FIXED     0               ///< Target Device: 1 = known, 0 = unknown;

#if TARGET_DEVICE_FIXED
#define TARGET_DEVICE_VENDOR    "STMicroelectronics"  ///< STM32 厂商名称
#define TARGET_DEVICE_NAME      "STM32F407VET6"       ///< 目标芯片型号
#endif

/* 保留你的 CMSIS 编译器头文件（确保项目中存在该文件） */
#include "cmsis_compiler.h"

/** Get Vendor ID string.
\param str Pointer to buffer to store the string.
\return String length.
*/
__STATIC_INLINE uint8_t DAP_GetVendorString (char *str) {
  (void)str;
  return (0U);
}

/** Get Product ID string.
\param str Pointer to buffer to store the string.
\return String length.
*/
__STATIC_INLINE uint8_t DAP_GetProductString (char *str) {
  (void)str;
  return (0U);
}

/** Get Serial Number string.
\param str Pointer to buffer to store the string.
\return String length.
*/
__STATIC_INLINE uint8_t DAP_GetSerNumString (char *str) {
  (void)str;
  return (0U);
}

///@}

/* Private defines -----------------------------------------------------------*/
#define JTAG_TCK_Pin GPIO_PIN_10
#define JTAG_TCK_GPIO_Port GPIOB

#define JTAG_TMS_Pin GPIO_PIN_1
#define JTAG_TMS_GPIO_Port GPIOB

#define JTAG_nRESET_Pin GPIO_PIN_12
#define JTAG_nRESET_GPIO_Port GPIOB

#define JTAG_TDI_Pin GPIO_PIN_13
#define JTAG_TDI_GPIO_Port GPIOB

#define JTAG_TDO_Pin GPIO_PIN_14
#define JTAG_TDO_GPIO_Port GPIOB

#define JTAG_nTRST_Pin GPIO_PIN_15
#define JTAG_nTRST_GPIO_Port GPIOB


// Connected LED                PIN13 of GPIOC

// Target Running LED           Not available


//**************************************************************************************************
/**
\defgroup DAP_Config_PortIO_gr CMSIS-DAP Hardware I/O Pin Access
\ingroup DAP_ConfigIO_gr
@{

Standard I/O Pins of the CMSIS-DAP Hardware Debug Port support standard JTAG mode
and Serial Wire Debug (SWD) mode. In SWD mode only 2 pins are required to implement the debug
interface of a device. The following I/O Pins are provided:

JTAG I/O Pin                 | SWD I/O Pin          | CMSIS-DAP Hardware pin mode
---------------------------- | -------------------- | ---------------------------------------------
TCK: Test Clock              | SWCLK: Clock         | Output Push/Pull
TMS: Test Mode Select        | SWDIO: Data I/O      | Output Push/Pull; Input (for receiving data)
TDI: Test Data Input         |                      | Output Push/Pull
TDO: Test Data Output        |                      | Input
nTRST: Test Reset (optional) |                      | Output Open Drain with pull-up resistor
nRESET: Device Reset         | nRESET: Device Reset | Output Open Drain with pull-up resistor


DAP Hardware I/O Pin Access Functions
-------------------------------------
The various I/O Pins are accessed by functions that implement the Read, Write, Set, or Clear to
these I/O Pins.

For the SWDIO I/O Pin there are additional functions that are called in SWD I/O mode only.
This functions are provided to achieve faster I/O that is possible with some advanced GPIO
peripherals that can independently write/read a single I/O pin without affecting any other pins
of the same I/O port. The following SWDIO I/O Pin functions are provided:
 - \ref PIN_SWDIO_OUT_ENABLE to enable the output mode from the DAP hardware.
 - \ref PIN_SWDIO_OUT_DISABLE to enable the input mode to the DAP hardware.
 - \ref PIN_SWDIO_IN to read from the SWDIO I/O pin with utmost possible speed.
 - \ref PIN_SWDIO_OUT to write to the SWDIO I/O pin with utmost possible speed.
*/


// Configure DAP I/O pins ------------------------------

//   LPC-Link-II HW uses buffers for debug port pins. Therefore it is not
//   possible to disable outputs SWCLK/TCK, TDI and they are left active.
//   Only SWDIO/TMS output can be disabled but it is also left active.
//   nRESET is configured for open drain mode.

/** Setup JTAG I/O pins: TCK, TMS, TDI, TDO, nTRST, and nRESET.
Configures the DAP Hardware I/O pins for JTAG mode:
 - TCK, TMS, TDI, nTRST, nRESET to output mode and set to high level.
 - TDO to input mode.
*/
__STATIC_INLINE void PORT_JTAG_SETUP (void) {
  GPIO_InitTypeDef GPIO_InitStruct = {0};

//  HAL_GPIO_WritePin(JTAG_TCK_GPIO_Port, JTAG_TCK_Pin, GPIO_PIN_SET);
//  HAL_GPIO_WritePin(JTAG_TMS_GPIO_Port, JTAG_TMS_Pin, GPIO_PIN_SET);
//  HAL_GPIO_WritePin(JTAG_TDI_GPIO_Port, JTAG_TDI_Pin, GPIO_PIN_SET);
//  HAL_GPIO_WritePin(JTAG_nTRST_GPIO_Port, JTAG_nTRST_Pin, GPIO_PIN_SET);
//  HAL_GPIO_WritePin(JTAG_nRESET_GPIO_Port, JTAG_nRESET_Pin, GPIO_PIN_SET);
  GPIOB->BSRR = JTAG_TCK_Pin|JTAG_TMS_Pin|JTAG_TDI_Pin|JTAG_nTRST_Pin|JTAG_nRESET_Pin;

  /*Configure GPIO pins : JTAG_TCK_Pin JTAG_TMS_Pin JTAG_TDI_Pin */
  GPIO_InitStruct.Pin = JTAG_TCK_Pin|JTAG_TMS_Pin|JTAG_TDI_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : JTAG_nRESET_Pin JTAG_nTRST_Pin */
  GPIO_InitStruct.Pin = JTAG_nRESET_Pin|JTAG_nTRST_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : JTAG_TDO_Pin */
  GPIO_InitStruct.Pin = JTAG_TDO_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
}

/** Setup SWD I/O pins: SWCLK, SWDIO, and nRESET.
Configures the DAP Hardware I/O pins for Serial Wire Debug (SWD) mode:
 - SWCLK, SWDIO, nRESET to output mode and set to default high level.
 - TDI, TDO, nTRST to HighZ mode (pins are unused in SWD mode).
*/
__STATIC_INLINE void PORT_SWD_SETUP (void) {
  GPIO_InitTypeDef GPIO_InitStruct = {0};

//  HAL_GPIO_WritePin(JTAG_TCK_GPIO_Port, JTAG_TCK_Pin, GPIO_PIN_SET);
//  HAL_GPIO_WritePin(JTAG_TMS_GPIO_Port, JTAG_TMS_Pin, GPIO_PIN_SET);
//  HAL_GPIO_WritePin(JTAG_nRESET_GPIO_Port, JTAG_nRESET_Pin, GPIO_PIN_SET);
  GPIOB->BSRR = JTAG_TCK_Pin|JTAG_TMS_Pin|JTAG_nRESET_Pin;

  GPIO_InitStruct.Pin = JTAG_TMS_Pin|JTAG_TCK_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = JTAG_nRESET_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(JTAG_nRESET_GPIO_Port, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = JTAG_TDI_Pin|JTAG_TDO_Pin|JTAG_nTRST_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
}

/** Disable JTAG/SWD I/O Pins.
Disables the DAP Hardware I/O pins which configures:
 - TCK/SWCLK, TMS/SWDIO, TDI, TDO, nTRST, nRESET to High-Z mode.
*/
__STATIC_INLINE void PORT_OFF (void) {
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin = JTAG_TMS_Pin|JTAG_TCK_Pin|JTAG_TDI_Pin|
                        JTAG_TDO_Pin|JTAG_nTRST_Pin|JTAG_nRESET_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
}


// SWCLK/TCK I/O pin -------------------------------------

/** SWCLK/TCK I/O pin: Get Input.
\return Current status of the SWCLK/TCK DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_SWCLK_TCK_IN  (void) {
  return (uint32_t)(JTAG_TCK_GPIO_Port->ODR & JTAG_TCK_Pin ? 1:0);
}

/** SWCLK/TCK I/O pin: Set Output to High.
Set the SWCLK/TCK DAP hardware I/O pin to high level.
*/
__STATIC_FORCEINLINE void     PIN_SWCLK_TCK_SET (void) {
  JTAG_TCK_GPIO_Port->BSRR = JTAG_TCK_Pin;
}

/** SWCLK/TCK I/O pin: Set Output to Low.
Set the SWCLK/TCK DAP hardware I/O pin to low level.
*/
__STATIC_FORCEINLINE void     PIN_SWCLK_TCK_CLR (void) {
  JTAG_TCK_GPIO_Port->BSRR = (uint32_t)JTAG_TCK_Pin << 16U;  // 高 16 位写 1 → 复位
}


// SWDIO/TMS Pin I/O --------------------------------------

/** SWDIO/TMS I/O pin: Get Input.
\return Current status of the SWDIO/TMS DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_SWDIO_TMS_IN  (void) {
  return (uint32_t)(JTAG_TMS_GPIO_Port->ODR & JTAG_TMS_Pin ? 1:0);
}

/** SWDIO/TMS I/O pin: Set Output to High.
Set the SWDIO/TMS DAP hardware I/O pin to high level.
*/
__STATIC_FORCEINLINE void     PIN_SWDIO_TMS_SET (void) {
  JTAG_TMS_GPIO_Port->BSRR = JTAG_TMS_Pin;
}

/** SWDIO/TMS I/O pin: Set Output to Low.
Set the SWDIO/TMS DAP hardware I/O pin to low level.
*/
__STATIC_FORCEINLINE void     PIN_SWDIO_TMS_CLR (void) {
  JTAG_TMS_GPIO_Port->BSRR = (uint32_t)JTAG_TMS_Pin << 16U;  // 高 16 位写 1 → 复位
}

/** SWDIO I/O pin: Get Input (used in SWD mode only).
\return Current status of the SWDIO DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_SWDIO_IN      (void) {
  return (uint32_t)(JTAG_TMS_GPIO_Port->IDR & JTAG_TMS_Pin ? 1:0);
}

/** SWDIO I/O pin: Set Output (used in SWD mode only).
\param bit Output value for the SWDIO DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE void     PIN_SWDIO_OUT     (uint32_t bit) {
  /**
    * Important: Use only one bit (bit0) of param!
	* Sometimes the func "SWD_TransferFunction" of SW_DP.c will
	* issue "2" as param instead of "0". Zach Lee
	*/
  if ((bit & 1U) == 1) {
    JTAG_TMS_GPIO_Port->BSRR = JTAG_TMS_Pin;
  } else {
    JTAG_TMS_GPIO_Port->BSRR = (uint32_t)JTAG_TMS_Pin << 16U;  // 高 16 位写 1 → 复位
  }
}

/** SWDIO I/O pin: Switch to Output mode (used in SWD mode only).
Configure the SWDIO DAP hardware I/O pin to output mode. This function is
called prior \ref PIN_SWDIO_OUT function calls.
*/
__STATIC_FORCEINLINE void     PIN_SWDIO_OUT_ENABLE  (void) {
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin = JTAG_TMS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(JTAG_TMS_GPIO_Port, &GPIO_InitStruct);
}

/** SWDIO I/O pin: Switch to Input mode (used in SWD mode only).
Configure the SWDIO DAP hardware I/O pin to input mode. This function is
called prior \ref PIN_SWDIO_IN function calls.
*/
__STATIC_FORCEINLINE void     PIN_SWDIO_OUT_DISABLE (void) {
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin = JTAG_TMS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(JTAG_TMS_GPIO_Port, &GPIO_InitStruct);
}


// TDI Pin I/O ---------------------------------------------

/** TDI I/O pin: Get Input.
\return Current status of the TDI DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_TDI_IN  (void) {
  return (uint32_t)(JTAG_TDI_GPIO_Port->ODR & JTAG_TDI_Pin ? 1:0);
}

/** TDI I/O pin: Set Output.
\param bit Output value for the TDI DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE void     PIN_TDI_OUT (uint32_t bit) {
  if ((bit & 1U) == 1) {
    JTAG_TDI_GPIO_Port->BSRR = JTAG_TDI_Pin;
  } else {
    JTAG_TDI_GPIO_Port->BSRR   = (uint32_t)JTAG_TMS_Pin << 16U;  // 高 16 位写 1 → 复位
  }
}


// TDO Pin I/O ---------------------------------------------

/** TDO I/O pin: Get Input.
\return Current status of the TDO DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_TDO_IN  (void) {
  return (uint32_t)(JTAG_TDO_GPIO_Port->IDR & JTAG_TDO_Pin ? 1:0);
}


// nTRST Pin I/O -------------------------------------------

/** nTRST I/O pin: Get Input.
\return Current status of the nTRST DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_nTRST_IN   (void) {
  return (0U);  // Not available
}

/** nTRST I/O pin: Set Output.
\param bit JTAG TRST Test Reset pin status:
           - 0: issue a JTAG TRST Test Reset.
           - 1: release JTAG TRST Test Reset.
*/
__STATIC_FORCEINLINE void     PIN_nTRST_OUT  (uint32_t bit) {
  (void)bit;
  ;             // Not available
}

// nRESET Pin I/O------------------------------------------

/** nRESET I/O pin: Get Input.
\return Current status of the nRESET DAP hardware I/O pin.
*/
__STATIC_FORCEINLINE uint32_t PIN_nRESET_IN  (void) {
  return (uint32_t)(JTAG_nRESET_GPIO_Port->ODR & JTAG_nRESET_Pin ? 1:0);
}

/** nRESET I/O pin: Set Output.
\param bit target device hardware reset pin status:
           - 0: issue a device hardware reset.
           - 1: release device hardware reset.
*/
__STATIC_FORCEINLINE void     PIN_nRESET_OUT (uint32_t bit) {
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if ((bit & 1U) == 1) {
    JTAG_nRESET_GPIO_Port->BSRR = JTAG_nRESET_Pin;

    GPIO_InitStruct.Pin = JTAG_nRESET_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(JTAG_nRESET_GPIO_Port, &GPIO_InitStruct);
  } else {
    JTAG_nRESET_GPIO_Port->BSRR  = JTAG_nRESET_Pin<< 16U;;

    GPIO_InitStruct.Pin = JTAG_nRESET_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(JTAG_nRESET_GPIO_Port, &GPIO_InitStruct);
  }
}

///@}


//**************************************************************************************************
/**
\defgroup DAP_Config_LEDs_gr CMSIS-DAP Hardware Status LEDs
\ingroup DAP_ConfigIO_gr
@{

CMSIS-DAP Hardware may provide LEDs that indicate the status of the CMSIS-DAP Debug Unit.

It is recommended to provide the following LEDs for status indication:
 - Connect LED: is active when the DAP hardware is connected to a debugger.
 - Running LED: is active when the debugger has put the target device into running state.
*/

/** Debug Unit: Set status of Connected LED.
\param bit status of the Connect LED.
           - 1: Connect LED ON: debugger is connected to CMSIS-DAP Debug Unit.
           - 0: Connect LED OFF: debugger is not connected to CMSIS-DAP Debug Unit.
*/
__STATIC_INLINE void LED_CONNECTED_OUT (uint32_t bit) {
//  if ((bit & 1U) == 1) {
//    LED_GPIO_Port->BRR =  LED_CONNECTED_Pin;
//  } else {
//    LED_GPIO_Port->BSRR = LED_CONNECTED_Pin;
//  }
}

/** Debug Unit: Set status Target Running LED.
\param bit status of the Target Running LED.
           - 1: Target Running LED ON: program execution in target started.
           - 0: Target Running LED OFF: program execution in target stopped.
*/
__STATIC_INLINE void LED_RUNNING_OUT (uint32_t bit) {
  (void)bit;
  ;             // Not available
}

///@}


//**************************************************************************************************
/**
\defgroup DAP_Config_Timestamp_gr CMSIS-DAP Timestamp
\ingroup DAP_ConfigIO_gr
@{
Access function for Test Domain Timer.

The value of the Test Domain Timer in the Debug Unit is returned by the function \ref TIMESTAMP_GET. By
default, the DWT timer is used.  The frequency of this timer is configured with \ref TIMESTAMP_CLOCK.

*/

/** Get timestamp of Test Domain Timer.
\return Current timestamp value.
*/
__STATIC_INLINE uint32_t TIMESTAMP_GET (void) {
  return (DWT->CYCCNT);
}
///@}


//**************************************************************************************************
/**
\defgroup DAP_Config_Initialization_gr CMSIS-DAP Initialization
\ingroup DAP_ConfigIO_gr
@{

CMSIS-DAP Hardware I/O and LED Pins are initialized with the function \ref DAP_SETUP.
*/

/** Setup of the Debug Unit I/O pins and LEDs (called when Debug Unit is initialized).
This function performs the initialization of the CMSIS-DAP Hardware I/O Pins and the
Status LEDs. In detail the operation of Hardware I/O and LED pins are enabled and set:
 - I/O clock system enabled.
 - all I/O pins: input buffer enabled, output pins are set to HighZ mode.
 - for nTRST, nRESET a weak pull-up (if available) is enabled.
 - LED output pins are enabled and LEDs are turned off.
*/
__STATIC_INLINE void DAP_SETUP (void) {
  __HAL_RCC_GPIOB_CLK_ENABLE();
  PORT_JTAG_SETUP();
}

/** Reset Target Device with custom specific I/O pin or command sequence.
This function allows the optional implementation of a device specific reset sequence.
It is called when the command \ref DAP_ResetTarget and is for example required
when a device needs a time-critical unlock sequence that enables the debug port.
\return 0 = no device specific reset sequence is implemented.\n
        1 = a device specific reset sequence is implemented.
*/
__STATIC_INLINE uint8_t RESET_TARGET (void) {
  return (0U);             // change to '1' when a device reset sequence is implemented
}

///@}


//#endif /* __DAP_CONFIG_H__ */
