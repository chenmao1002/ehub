#include "ehub_boot.h"

#include "main.h"

#include "stm32f4xx_hal.h"

typedef void (*pFunction)(void);

static void Boot_BoardPowerInit(void)
{
    GPIO_InitTypeDef gpioInit = {0};

    __HAL_RCC_GPIOD_CLK_ENABLE();
    __HAL_RCC_GPIOE_CLK_ENABLE();

    HAL_GPIO_WritePin(PWR_EN_GPIO_Port, PWR_EN_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(USB_S_GPIO_Port, USB_S_Pin, GPIO_PIN_SET);

    gpioInit.Mode = GPIO_MODE_OUTPUT_PP;
    gpioInit.Pull = GPIO_NOPULL;
    gpioInit.Speed = GPIO_SPEED_FREQ_LOW;

    gpioInit.Pin = PWR_EN_Pin;
    HAL_GPIO_Init(PWR_EN_GPIO_Port, &gpioInit);

    gpioInit.Pin = USB_S_Pin;
    HAL_GPIO_Init(USB_S_GPIO_Port, &gpioInit);
}

static uint8_t Boot_ManifestReady(const EHUB_BootManifest *manifest)
{
    if (manifest == NULL) {
        return 0U;
    }

    return (manifest->magic == EHUB_MANIFEST_MAGIC) &&
           (manifest->state == EHUB_MANIFEST_STATE_READY) &&
           (manifest->image_size > 0U) &&
           (manifest->image_size <= EHUB_APP_MAX_SIZE) &&
           (manifest->image_size <= EHUB_STAGING_MAX_SIZE);
}

static HAL_StatusTypeDef Boot_WriteBytes(uint32_t address, const uint8_t *data, uint32_t len)
{
    HAL_StatusTypeDef status = HAL_OK;

    for (uint32_t idx = 0U; idx < len; idx++) {
        status = HAL_FLASH_Program(FLASH_TYPEPROGRAM_BYTE, address + idx, data[idx]);
        if (status != HAL_OK) {
            break;
        }
    }

    return status;
}

static HAL_StatusTypeDef Boot_InstallStagedImage(const EHUB_BootManifest *manifest)
{
    FLASH_EraseInitTypeDef eraseInit = {0};
    uint32_t sectorError = 0U;
    HAL_StatusTypeDef status;
    const uint8_t *src = (const uint8_t *)EHUB_STAGING_START_ADDR;

    HAL_FLASH_Unlock();

    eraseInit.TypeErase = FLASH_TYPEERASE_SECTORS;
    eraseInit.VoltageRange = FLASH_VOLTAGE_RANGE_3;
    eraseInit.Sector = FLASH_SECTOR_4;
    eraseInit.NbSectors = 2U;
    status = HAL_FLASHEx_Erase(&eraseInit, &sectorError);
    if (status == HAL_OK) {
        status = Boot_WriteBytes(EHUB_APP_START_ADDR, src, manifest->image_size);
    }

    if ((status == HAL_OK) &&
        (EHUB_Boot_Crc32((const void *)EHUB_APP_START_ADDR, manifest->image_size) == manifest->image_crc32)) {
        uint32_t zero = 0U;
        (void)HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, EHUB_MANIFEST_ADDR, zero);
    } else {
        status = HAL_ERROR;
    }

    HAL_FLASH_Lock();
    return status;
}

static void Boot_JumpToApplication(void)
{
    const uint32_t appStack = *(const uint32_t *)EHUB_APP_START_ADDR;
    const uint32_t appReset = *(const uint32_t *)(EHUB_APP_START_ADDR + 4U);
    pFunction jump = (pFunction)appReset;

    __disable_irq();
    SysTick->CTRL = 0U;
    SysTick->LOAD = 0U;
    SysTick->VAL = 0U;
    HAL_DeInit();

    for (uint32_t irqIndex = 0U; irqIndex < 8U; irqIndex++) {
        NVIC->ICER[irqIndex] = 0xFFFFFFFFU;
        NVIC->ICPR[irqIndex] = 0xFFFFFFFFU;
    }

    SCB->VTOR = EHUB_APP_START_ADDR;
    __set_CONTROL(0U);
    __set_MSP(appStack);
    __DSB();
    __ISB();
    __enable_irq();
    jump();
}

int main(void)
{
    HAL_Init();
    Boot_BoardPowerInit();

    if (Boot_ManifestReady(EHUB_BOOT_MANIFEST)) {
        (void)Boot_InstallStagedImage(EHUB_BOOT_MANIFEST);
    }

    if (EHUB_Boot_IsValidApp(EHUB_APP_START_ADDR)) {
        Boot_JumpToApplication();
    }

    while (1) {
    }
}