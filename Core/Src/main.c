/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "cmsis_os.h"
#include "adc.h"
#include "can.h"
#include "dma.h"
#include "i2c.h"
#include "spi.h"
#include "tim.h"
#include "usart.h"
#include "usb_device.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
# include "ws2812c.h"
#include "usbd_custom_hid_if.h"
# include "dap.h"
# include "dap_config.h"
# include "dap_app.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
#define HID_REPORT_INPUT            0x81
#define HID_REPORT_OUTPUT           0x91
#define HID_REPORT_FEATURE          0xB1

#define USBD_HID_REQ_EP_CTRL        0x01
#define USBD_HID_REQ_PERIOD_UPDATE  0x02
#define USBD_HID_REQ_EP_INT         0x03
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */
static volatile uint16_t USB_RequestIndexI;     // Request  Index In
static volatile uint16_t USB_RequestIndexO;     // Request  Index Out
static volatile uint16_t USB_RequestCountI;     // Request  Count In
static volatile uint16_t USB_RequestCountO;     // Request  Count Out

static volatile uint16_t USB_ResponseIndexI;    // Response Index In
static volatile uint16_t USB_ResponseIndexO;    // Response Index Out
static volatile uint16_t USB_ResponseCountI;    // Response Count In
static volatile uint16_t USB_ResponseCountO;    // Response Count Out
static volatile uint8_t  USB_ResponseIdle;      // Response Idle  Flag

static uint8_t  USB_Request [DAP_PACKET_COUNT][DAP_PACKET_SIZE];  // Request  Buffer
static uint8_t  USB_Response[DAP_PACKET_COUNT][DAP_PACKET_SIZE];  // Response Buffer

	extern USBD_HandleTypeDef hUsbDeviceFS;
/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

//int32_t USBD_HID0_GetReport (uint8_t rtype, uint8_t req, uint8_t rid, uint8_t *buf) {
//  (void)rid;

//  switch (rtype) {
//    case HID_REPORT_INPUT:
//      switch (req) {
//        case USBD_HID_REQ_EP_CTRL:        // Explicit USB Host request via Control OUT Endpoint
//        case USBD_HID_REQ_PERIOD_UPDATE:  // Periodic USB Host request via Interrupt OUT Endpoint
//          break;
//        case USBD_HID_REQ_EP_INT:         // Called after USBD_HID_GetReportTrigger to signal data obtained.
//          if (USB_ResponseCountI != USB_ResponseCountO) {
//            // Load data from response buffer to be sent back
//            memcpy(buf, USB_Response[USB_ResponseIndexO], DAP_PACKET_SIZE);
//            USB_ResponseIndexO++;
//            if (USB_ResponseIndexO == DAP_PACKET_COUNT) {
//              USB_ResponseIndexO = 0U;
//            }
//            USB_ResponseCountO++;
//            return ((int32_t)DAP_PACKET_SIZE);
//          } else {
//            USB_ResponseIdle = 1U;
//          }
//          break;
//      }
//      break;
//    case HID_REPORT_FEATURE:
//      break;
//  }
//  return (0);
//}
//uint8_t USBD_HID0_SetReport (uint8_t rtype, uint8_t req, uint8_t rid, const uint8_t *buf, int32_t len) {
//  (void)req;
//  (void)rid;

//  switch (rtype) {
//    case HID_REPORT_OUTPUT:
//      if (len == 0) {
//        break;
//      }
//      if (buf[0] == ID_DAP_TransferAbort) {
//        DAP_TransferAbort = 1U;
//        break;
//      }
//      if ((uint16_t)(USB_RequestCountI - USB_RequestCountO) == DAP_PACKET_COUNT) {
//        osThreadFlagsSet(DAP_ThreadId, 0x80U);
//        break;  // Discard packet when buffer is full
//      }
//      // Store received data into request buffer
//      memcpy(USB_Request[USB_RequestIndexI], buf, (uint32_t)len);
//      USB_RequestIndexI++;
//      if (USB_RequestIndexI == DAP_PACKET_COUNT) {
//        USB_RequestIndexI = 0U;
//      }
//      USB_RequestCountI++;
//      osThreadFlagsSet(DAP_ThreadId, 0x01U);
//      break;
//    case HID_REPORT_FEATURE:
//      break;
//  }
//  return 1;
//}

//void USBD_HID0_Initialize (void) {
//  // Initialize variables
//  USB_RequestIndexI  = 0U;
//  USB_RequestIndexO  = 0U;
//  USB_RequestCountI  = 0U;
//  USB_RequestCountO  = 0U;
//  USB_ResponseIndexI = 0U;
//  USB_ResponseIndexO = 0U;
//  USB_ResponseCountI = 0U;
//  USB_ResponseCountO = 0U;
//  USB_ResponseIdle   = 1U;
//}

//void USBD_InEvent(void)
//{
//  int32_t len;

//  USBD_CUSTOM_HID_HandleTypeDef *hhid = (USBD_CUSTOM_HID_HandleTypeDef *)hUsbDeviceFS.pClassData;
//  if ((len=USBD_HID0_GetReport(HID_REPORT_INPUT, USBD_HID_REQ_EP_INT, 0, hhid->Report_buf)) > 0)
//  {
//    USBD_CUSTOM_HID_SendReport(&hUsbDeviceFS, hhid->Report_buf, len);
//  }
//}

//void USBD_OutEvent(void)
//{
//  USBD_CUSTOM_HID_HandleTypeDef *hhid = (USBD_CUSTOM_HID_HandleTypeDef *)hUsbDeviceFS.pClassData;
//  USBD_HID0_SetReport(HID_REPORT_OUTPUT, 0, 0, hhid->Report_buf, USBD_CUSTOMHID_OUTREPORT_BUF_SIZE);
//}
int32_t USBD_HID0_GetReport (uint8_t rtype, uint8_t req, uint8_t rid, uint8_t *buf) {
  (void)rid;

  switch (rtype) {
    case HID_REPORT_INPUT:
      switch (req) {
        case USBD_HID_REQ_EP_CTRL:        // Explicit USB Host request via Control OUT Endpoint
        case USBD_HID_REQ_PERIOD_UPDATE:  // Periodic USB Host request via Interrupt OUT Endpoint
          break;
        case USBD_HID_REQ_EP_INT:         // Called after USBD_HID_GetReportTrigger to signal data obtained.
          if (USB_ResponseCountI != USB_ResponseCountO) {
            // Load data from response buffer to be sent back
            memcpy(buf, USB_Response[USB_ResponseIndexO], DAP_PACKET_SIZE);
            USB_ResponseIndexO++;
            if (USB_ResponseIndexO == DAP_PACKET_COUNT) {
              USB_ResponseIndexO = 0U;
            }
            USB_ResponseCountO++;
            return ((int32_t)DAP_PACKET_SIZE);
          } else {
            USB_ResponseIdle = 1U;
          }
          break;
      }
      break;
    case HID_REPORT_FEATURE:
      break;
  }
  return (0);
}

uint8_t USBD_HID0_SetReport (uint8_t rtype, uint8_t req, uint8_t rid, const uint8_t *buf, int32_t len) {
  (void)req;
  (void)rid;

  switch (rtype) {
    case HID_REPORT_OUTPUT:
      if (len == 0) {
        break;
      }
      if (buf[0] == ID_DAP_TransferAbort) {
        DAP_TransferAbort = 1U;
        break;
      }
      if ((uint16_t)(USB_RequestCountI - USB_RequestCountO) == DAP_PACKET_COUNT) {
        break;  // Discard packet when buffer is full
      }
      // Store received data into request buffer
      memcpy(USB_Request[USB_RequestIndexI], buf, (uint32_t)len);
      USB_RequestIndexI++;
      if (USB_RequestIndexI == DAP_PACKET_COUNT) {
        USB_RequestIndexI = 0U;
      }
      USB_RequestCountI++;
      break;
    case HID_REPORT_FEATURE:
      break;
  }
  return 1;
}

void USBD_HID0_Initialize (void) {
  // Initialize variables
  USB_RequestIndexI  = 0U;
  USB_RequestIndexO  = 0U;
  USB_RequestCountI  = 0U;
  USB_RequestCountO  = 0U;
  USB_ResponseIndexI = 0U;
  USB_ResponseIndexO = 0U;
  USB_ResponseCountI = 0U;
  USB_ResponseCountO = 0U;
  USB_ResponseIdle   = 1U;
}

void USBD_InEvent(void)
{
  int32_t len;

  USBD_CUSTOM_HID_HandleTypeDef *hhid = (USBD_CUSTOM_HID_HandleTypeDef *)hUsbDeviceFS.pClassData;
  if ((len=USBD_HID0_GetReport(HID_REPORT_INPUT, USBD_HID_REQ_EP_INT, 0, hhid->Report_buf)) > 0)
  {
    USBD_CUSTOM_HID_SendReport(&hUsbDeviceFS, hhid->Report_buf, len);
  }
}

void USBD_OutEvent(void)
{
  USBD_CUSTOM_HID_HandleTypeDef *hhid = (USBD_CUSTOM_HID_HandleTypeDef *)hUsbDeviceFS.pClassData;
  USBD_HID0_SetReport(HID_REPORT_OUTPUT, 0, 0, hhid->Report_buf, USBD_CUSTOMHID_OUTREPORT_BUF_SIZE);
}
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
void MX_FREERTOS_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_ADC1_Init();
  MX_CAN1_Init();
  MX_ADC2_Init();
  MX_I2C1_Init();
  MX_I2C2_Init();
  MX_SPI1_Init();
  MX_USART2_UART_Init();
  MX_USART3_UART_Init();
  MX_TIM1_Init();
  MX_UART4_Init();
  MX_USART1_UART_Init();
  MX_TIM4_Init();
  /* USER CODE BEGIN 2 */
	HAL_GPIO_WritePin(GPIOE, USB_S_Pin|BOOT_IO_Pin|NSET_IO_Pin, GPIO_PIN_SET);
	HAL_Delay(50);
	WS2812C_Init();        // 初始化WS2812C
	MX_USB_DEVICE_Init();

	DAP_Setup(); 
	uint32_t flags;
  uint32_t n;
	USBD_HID0_Initialize();
	WS2812C_SetSingleColor(1,25,0,0);
		WS2812C_Update();
		HAL_Delay(1000);
	while(1){
		uint8_t tx_buf[5] = "00000";

		USBD_CUSTOM_HID_SendReport(&hUsbDeviceFS, tx_buf, 2);
		
		
		
		  for (;;) {
    // Directly process the USB request queue
		while (USB_RequestCountI != USB_RequestCountO) {
			// Handle Queue Commands
			uint32_t n = USB_RequestIndexO;
			while (USB_Request[n][0] == ID_DAP_QueueCommands) {
				USB_Request[n][0] = ID_DAP_ExecuteCommands;
				n++;
				if (n == DAP_PACKET_COUNT) {
					n = 0U;
				}
				if (n == USB_RequestIndexI) {
					break;
				}
			}

			// Execute DAP Command (process request and prepare response)
			DAP_ExecuteCommand(USB_Request[USB_RequestIndexO], USB_Response[USB_ResponseIndexI]);

			// Update Request Index and Count
			USB_RequestIndexO++;
			if (USB_RequestIndexO == DAP_PACKET_COUNT) {
				USB_RequestIndexO = 0U;
			}
      USB_RequestCountO++;

			// Update Response Index and Count
			USB_ResponseIndexI++;
			if (USB_ResponseIndexI == DAP_PACKET_COUNT) {
				USB_ResponseIndexI = 0U;
			}
			USB_ResponseCountI++;

			// Check if response data is idle and ready to be sent back
			if (USB_ResponseIdle) {
				if (USB_ResponseCountI != USB_ResponseCountO) {
					// Load data from response buffer to be sent back
					uint32_t n = USB_ResponseIndexO++;
					if (USB_ResponseIndexO == DAP_PACKET_COUNT) {
						USB_ResponseIndexO = 0U;
					}
					USB_ResponseCountO++;
					USB_ResponseIdle = 0U;

					// Send response via USB HID
					USBD_CUSTOM_HID_SendReport(&hUsbDeviceFS, USB_Response[n], DAP_PACKET_SIZE);
				}
			}
		}
  }

	
	}
  /* USER CODE END 2 */

  /* Init scheduler */
  osKernelInitialize();

  /* Call init function for freertos objects (in cmsis_os2.c) */
  MX_FREERTOS_Init();

  /* Start scheduler */
  osKernelStart();

  /* We should never get here as control is now taken by the scheduler */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
		
		
		
		
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 15;
  RCC_OscInitStruct.PLL.PLLN = 144;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 5;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  Period elapsed callback in non blocking mode
  * @note   This function is called  when TIM2 interrupt took place, inside
  * HAL_TIM_IRQHandler(). It makes a direct call to HAL_IncTick() to increment
  * a global variable "uwTick" used as application time base.
  * @param  htim : TIM handle
  * @retval None
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  /* USER CODE BEGIN Callback 0 */

  /* USER CODE END Callback 0 */
  if (htim->Instance == TIM2)
  {
    HAL_IncTick();
  }
  /* USER CODE BEGIN Callback 1 */

  /* USER CODE END Callback 1 */
}

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
