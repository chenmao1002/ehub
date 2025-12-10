/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
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

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define USB_S_Pin GPIO_PIN_2
#define USB_S_GPIO_Port GPIOE
#define ESP_BOOT_Pin GPIO_PIN_1
#define ESP_BOOT_GPIO_Port GPIOC
#define ESP_EN_Pin GPIO_PIN_2
#define ESP_EN_GPIO_Port GPIOC
#define BOOT_IO_Pin GPIO_PIN_10
#define BOOT_IO_GPIO_Port GPIOE
#define NSET_IO_Pin GPIO_PIN_11
#define NSET_IO_GPIO_Port GPIOE
#define RS485_TX_EN_Pin GPIO_PIN_10
#define RS485_TX_EN_GPIO_Port GPIOD
#define EXT_RESET_Pin GPIO_PIN_12
#define EXT_RESET_GPIO_Port GPIOD
#define PWR_EN_Pin GPIO_PIN_13
#define PWR_EN_GPIO_Port GPIOD
#define EXT_TDI_Pin GPIO_PIN_15
#define EXT_TDI_GPIO_Port GPIOD
#define EXT_TDO_SWO_Pin GPIO_PIN_6
#define EXT_TDO_SWO_GPIO_Port GPIOC
#define EXT_TC_KCLK_Pin GPIO_PIN_7
#define EXT_TC_KCLK_GPIO_Port GPIOC
#define EXT_TMS_DIO_Pin GPIO_PIN_8
#define EXT_TMS_DIO_GPIO_Port GPIOC
#define STM_DP_UP_Pin GPIO_PIN_9
#define STM_DP_UP_GPIO_Port GPIOC
#define CAN_SHDN_Pin GPIO_PIN_2
#define CAN_SHDN_GPIO_Port GPIOD

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
