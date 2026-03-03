/**
 * @file    battery_app.c
 * @brief   Battery voltage monitoring task — ADC1 CH8 (PB0)
 *
 * Algorithm
 * ─────────
 * 1. Software-triggered single-conversion on ADC1 CH8 (already initialised
 *    by CubeMX MX_ADC1_Init()).
 * 2. Take BAT_MULTI_SAMPLE readings and average to suppress noise.
 * 3. Convert raw ADC → mV, then apply an exponential moving average (EMA).
 * 4. Map voltage linearly  2.0 V → 0 %  …  2.9 V → 100 %.
 * 5. Detect charging: if EMA is rising by more than BAT_CHARGE_THRESH_MV
 *    between two consecutive cycles → charging = 1;
 *    if EMA falls or stays flat → charging = 0.
 * 6. Every cycle, push a 4-byte status frame to the PC via bridge
 *    channel BRIDGE_CH_BATTERY (0x08).
 *    Payload: [voltage_mV_H][voltage_mV_L][percent][charging]
 */

#include "battery_app.h"
#include "adc.h"
#include "usb_app.h"
#include "cmsis_os.h"

/* ---- 内部状态 ----------------------------------------------------------- */
static volatile BatteryStatus_t s_bat = { .voltage_mv = 0, .percent = 0, .charging = 0 };

/* ---- 公开 API ----------------------------------------------------------- */
const BatteryStatus_t *Battery_GetStatus(void)
{
    return (const BatteryStatus_t *)&s_bat;
}

/* ---- 内部工具函数 ------------------------------------------------------- */

/**
 * @brief  执行一次 ADC1 软件触发转换并返回原始值
 */
static uint32_t ADC1_ReadOnce(void)
{
    HAL_ADC_Start(&hadc1);
    if (HAL_ADC_PollForConversion(&hadc1, 10U) == HAL_OK)
    {
        return HAL_ADC_GetValue(&hadc1);
    }
    return 0U;
}

/**
 * @brief  采集 BAT_MULTI_SAMPLE 次取平均，返回 mV
 */
static uint16_t ADC1_ReadAverageMV(void)
{
    uint32_t sum = 0U;
    for (uint8_t i = 0U; i < BAT_MULTI_SAMPLE; i++)
    {
        sum += ADC1_ReadOnce();
    }
    uint32_t avg = sum / BAT_MULTI_SAMPLE;
    /* 转换为 mV: voltage = avg / 4095 * 3300 */
    return (uint16_t)((avg * BAT_VREF_MV) / BAT_ADC_RESOLUTION);
}

/**
 * @brief  将 mV 映射到 0-100% (线性插值)
 */
static uint8_t Voltage2Percent(uint16_t mv)
{
    if (mv >= BAT_FULL_MV)  return 100U;
    if (mv <= BAT_EMPTY_MV) return 0U;
    return (uint8_t)(((uint32_t)(mv - BAT_EMPTY_MV) * 100U) / (BAT_FULL_MV - BAT_EMPTY_MV));
}

/* ---- FreeRTOS 任务 ------------------------------------------------------ */

void StartBatteryTask(void *argument)
{
    (void)argument;

    /* 首次采样初始化 EMA */
    uint32_t ema_mv = ADC1_ReadAverageMV();
    uint32_t prev_ema = ema_mv;

    /* 充电检测需要连续几个周期上升才确认充电，防止单次抖动 */
    uint8_t  rising_cnt = 0U;
    uint8_t  falling_cnt = 0U;
    uint8_t  charging = 0U;

    for (;;)
    {
        osDelay(BAT_SAMPLE_PERIOD_MS);

        /* 1. 采样并做 EMA 平滑 */
        uint16_t raw_mv = ADC1_ReadAverageMV();
        ema_mv = (BAT_EMA_ALPHA * (uint32_t)raw_mv
                + (100U - BAT_EMA_ALPHA) * ema_mv) / 100U;

        /* 2. 充电检测（基于 EMA 变化趋势） */
        int32_t delta = (int32_t)ema_mv - (int32_t)prev_ema;

        if (delta > (int32_t)BAT_CHARGE_THRESH_MV)
        {
            /* 电压上升 → 可能在充电 */
            rising_cnt++;
            falling_cnt = 0U;
            if (rising_cnt >= 1U)   /* 连续 1 个周期上升即确认（提高灵敏度） */
            {
                charging = 1U;
            }
        }
        else if (delta < -(int32_t)BAT_CHARGE_THRESH_MV)
        {
            /* 电压下降 → 停止充电 */
            falling_cnt++;
            rising_cnt = 0U;
            if (falling_cnt >= 2U)
            {
                charging = 0U;
            }
        }
        else
        {
            /* 电压平稳 — 维持当前充电状态，慢慢衰减计数 */
            if (rising_cnt > 0U) rising_cnt--;
            if (falling_cnt > 0U) falling_cnt--;
        }

        prev_ema = ema_mv;

        /* 3. 更新全局状态 */
        uint8_t pct = Voltage2Percent((uint16_t)ema_mv);
        s_bat.voltage_mv = (uint16_t)ema_mv;
        s_bat.percent    = pct;
        s_bat.charging   = charging;

        /* 4. 通过 Bridge 上报到 PC
         *    payload: [voltage_mV_H][voltage_mV_L][percent][charging]
         */
        uint8_t payload[4];
        payload[0] = (uint8_t)(ema_mv >> 8U);
        payload[1] = (uint8_t)(ema_mv & 0xFFU);
        payload[2] = pct;
        payload[3] = charging;
        Bridge_SendToAll(BRIDGE_CH_BATTERY, payload, 4U);
    }
}
