#include "ws2812c.h"
//#include "delay.h"  // 需实现delay_us/delay_ms（基于HAL_Delay或SysTick）
#include "tim.h"

// 全局变量定义
WS2812C_ColorTypeDef WS2812C_LED_Buf[LED_NUM] = {0};  // 初始全黑
static uint16_t WS2812C_DmaBuf[LED_NUM * 24] = {0};   // DMA缓冲区：LED_NUM×24个占空比

// 定时器和DMA句柄（F4 HAL库标准）
extern TIM_HandleTypeDef htim4;
extern DMA_HandleTypeDef hdma_tim4_ch3;
volatile uint8_t ws2812_done = 0;

void HAL_DMA_XferCpltCallback(DMA_HandleTypeDef *hdma) {
    if (hdma == &hdma_tim4_ch3) {
        __HAL_TIM_DISABLE_DMA(&htim4, TIM_DMA_CC3);
        HAL_TIM_PWM_Stop(&htim4, TIM_CHANNEL_3);
        ws2812_done = 1;  // 设置完成标志
    }
}
/******************************************************************
 * 函数名：WS2812C_Init
 * 功能：统一初始化，初始熄灭所有LED
 ******************************************************************/
void WS2812C_Init(void) {
		HAL_TIM_PWM_Start(&htim4, TIM_CHANNEL_3);// 启动PWM输出
    WS2812C_ClearAll();
}

void WS2812C_Update(void) {
    uint32_t led_idx, bit_idx;
    uint32_t dma_buf_idx = 0;
    uint8_t g, r, b;

    // 填充DMA缓冲区：GRB格式，高位→低位
    for (led_idx = 0; led_idx < LED_NUM; led_idx++) {
        g = WS2812C_LED_Buf[led_idx].G;
        r = WS2812C_LED_Buf[led_idx].R;
        b = WS2812C_LED_Buf[led_idx].B;

        // G
        for (bit_idx = 0; bit_idx < 8; bit_idx++) {
            WS2812C_DmaBuf[dma_buf_idx++] =
                (g & (0x80 >> bit_idx)) ? CODE1_HIGH : CODE0_HIGH;
        }
        // R
        for (bit_idx = 0; bit_idx < 8; bit_idx++) {
            WS2812C_DmaBuf[dma_buf_idx++] =
                (r & (0x80 >> bit_idx)) ? CODE1_HIGH : CODE0_HIGH;
        }
        // B
        for (bit_idx = 0; bit_idx < 8; bit_idx++) {
            WS2812C_DmaBuf[dma_buf_idx++] =
                (b & (0x80 >> bit_idx)) ? CODE1_HIGH : CODE0_HIGH;
        }
    }

		// 1) 启动 PWM 输出（确认 TIM 与通道）
    HAL_TIM_PWM_Start(&htim4, TIM_CHANNEL_3);

    // 2) 启动 DMA（返回值检查用于 debug）
    if (HAL_DMA_Start_IT(&hdma_tim4_ch3,
                         (uint32_t)WS2812C_DmaBuf,
                         (uint32_t)&TIM4->CCR3,
                         LED_NUM * 24) != HAL_OK) {
        Error_Handler(); // 或者在串口打印错误
    }

    // 3) 使能 TIM4 CH3 的 DMA 请求
    __HAL_TIM_ENABLE_DMA(&htim4, TIM_DMA_CC3);
		// 等待 DMA 完成（通过标志，不轮询 TCIF）
//    while(ws2812_done == 0) {
//        __NOP(); // 可以做低功耗或其他任务
//    }
    // 4) 等待复位时间（Data传送完后需要至少50us低电平）
//    HAL_Delay(5); // 1ms OK
    // 发送复位信号
    HAL_Delay(2);
		__HAL_TIM_DISABLE_DMA(&htim4, TIM_DMA_CC3);
        HAL_TIM_PWM_Stop(&htim4, TIM_CHANNEL_3);
}


/******************************************************************
 * 以下函数无修改，直接复用
 ******************************************************************/
void WS2812C_SetSingleColor(uint8_t idx, uint8_t r, uint8_t g, uint8_t b) {
    if (idx >= LED_NUM) return;
    WS2812C_LED_Buf[idx].R = r;
    WS2812C_LED_Buf[idx].G = g;
    WS2812C_LED_Buf[idx].B = b;
}

void WS2812C_SetAllColor(uint8_t r, uint8_t g, uint8_t b) {
    for (uint8_t i = 0; i < LED_NUM; i++) {
        WS2812C_SetSingleColor(i, r, g, b);
    }
}

void WS2812C_ClearAll(void) {
    WS2812C_SetAllColor(0, 0, 0);
    WS2812C_Update();
	HAL_Delay(20);
}

void WS2812C_RainbowEffect(void) {
    static uint8_t hue = 0;
    uint8_t r, g, b;
    
    for (uint8_t i = 0; i < LED_NUM; i++) {
        uint16_t h = (hue + i * 3) % 180;
        if (h < 60) {
            r = 204; g = (h * 204) / 60; b = 0;
        } else if (h < 120) {
            r = 204 - (h - 60) * 204 / 60; g = 204; b = 0;
        } else {
            r = 0; g = 204 - (h - 120) * 204 / 60; b = (h - 120) * 204 / 60;
        }
        WS2812C_SetSingleColor(i, r, g, b);
    }
    WS2812C_Update();
    hue = (hue + 1) % 180;
    HAL_Delay(20);
}

///******************************************************************
// * DMA传输完成中断服务函数（无修改）
// ******************************************************************/
//void HAL_DMA_XferCpltCallback(DMA_HandleTypeDef *hdma) {
//    if (hdma == &hdma_tim4_ch3) {
//        __HAL_TIM_DISABLE_DMA(&htim4, TIM_DMA_CC3);
//        HAL_TIM_PWM_Stop(&htim4, TIM_CHANNEL_3);
//        // 清 FLAG 一般 HAL 已处理，但你也可以显式清理
//        __HAL_DMA_CLEAR_FLAG(&hdma_tim4_ch3, DMA_FLAG_TCIF3_7); // optional
//    }
//}


