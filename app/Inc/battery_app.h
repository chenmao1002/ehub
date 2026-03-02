/**
 * @file    battery_app.h
 * @brief   Battery voltage monitoring & charging detection
 *
 * Hardware: PB0 → ADC1_IN8
 *   Full-charge threshold  : ≥ 2.9 V  → 100 %
 *   Empty threshold        : ≤ 2.0 V  →   0 %
 *   Charging detection     : EMA-smoothed voltage rising → charging
 */

#ifndef __BATTERY_APP_H__
#define __BATTERY_APP_H__

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* ---- 可调参数 ----------------------------------------------------------- */
#define BAT_VREF_MV          3300U    /* ADC 参考电压 (mV) */
#define BAT_ADC_RESOLUTION   4095U    /* 12-bit ADC 最大值 */
#define BAT_FULL_MV          2900U    /* 满电电压 (mV) */
#define BAT_EMPTY_MV         2000U    /* 空电电压 (mV) */
#define BAT_SAMPLE_PERIOD_MS 2000U    /* 采样周期 2 s（≤ 3 s 要求） */
#define BAT_EMA_ALPHA        30U      /* EMA 系数 α/100 (0.30)，越大跟踪越快 */
#define BAT_CHARGE_THRESH_MV 5U       /* 两次 EMA 差值 > 此值视为充电中（提高灵敏度） */
#define BAT_MULTI_SAMPLE     8U       /* 单次采样取多次平均 */

/* ---- 电池状态结构体 ----------------------------------------------------- */
typedef struct {
    uint16_t voltage_mv;   /* 当前 EMA 平滑电压 (mV) */
    uint8_t  percent;      /* 百分比 0-100 */
    uint8_t  charging;     /* 1 = 充电中, 0 = 未充电 */
} BatteryStatus_t;

/* ---- 公开 API ----------------------------------------------------------- */

/**
 * @brief  获取最新电池状态（ISR-safe，只读 volatile 结构体）
 */
const BatteryStatus_t *Battery_GetStatus(void);

/**
 * @brief  FreeRTOS 任务入口 — 由 freertos.c 启动
 */
void StartBatteryTask(void *argument);

#ifdef __cplusplus
}
#endif

#endif /* __BATTERY_APP_H__ */
