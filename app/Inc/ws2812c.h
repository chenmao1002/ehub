#ifndef __WS2812C_H
#define __WS2812C_H

#include "stm32f4xx_hal.h"

#define LED_NUM         7       // 级联LED数量
#define TIM_PRESCALER   0       // 定时器不分频 → 60MHz时钟
#define PWM_PERIOD      75     // PWM周期=75×8.333ns=1.25μs（WS2812C码元总时长）
#define CODE0_HIGH      24      // 0码高电平：48×8.333ns≈0.4μs（要求0.3~0.5μs）
#define CODE1_HIGH      48      // 1码高电平：96×8.333ns≈0.8μs（要求0.6~0.9μs）
#define RESET_TIME      50      // 复位信号≥50μs（低电平）

// WS2812C颜色格式：GRB（绿色→红色→蓝色，必须遵循）
typedef struct {
    uint8_t G;  // 绿色通道（0~255）
    uint8_t R;  // 红色通道（0~255）
    uint8_t B;  // 蓝色通道（0~255）
} WS2812C_ColorTypeDef;

// 全局变量：存储每个LED的颜色数据
extern WS2812C_ColorTypeDef WS2812C_LED_Buf[LED_NUM];

// 函数声明
void WS2812C_Init(void);                  // 初始化（GPIO+TIM+DMA）
void WS2812C_Update(void);                // 刷新LED显示（发送所有数据）
void WS2812C_SetSingleColor(uint8_t idx, uint8_t r, uint8_t g, uint8_t b); // 设置单个LED颜色
void WS2812C_SetAllColor(uint8_t r, uint8_t g, uint8_t b); // 设置所有LED同色
void WS2812C_ClearAll(void);              // 熄灭所有LED
void WS2812C_RainbowEffect(void);         // 彩虹渐变效果（示例）
//void Error_Handler(void);                  // 错误处理

#endif

