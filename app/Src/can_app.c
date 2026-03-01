/**
 * @file    can_app.c
 * @brief   CAN1 bridge
 *
 * PC → Device frame payload layout  (channel = BRIDGE_CH_CAN):
 *   data[0..3] = CAN ID big-endian (11-bit ID ≤ 0x7FF → standard,
 *                                   29-bit ID  > 0x7FF → extended)
 *   data[4]    = DLC (0–8)
 *   data[5..X] = payload bytes (X = 5 + DLC – 1)
 *
 * Device → PC frame payload layout  (same structure):
 *   Same encoding as above plus:
 *   data[4] bit7 set (0x80) when the received frame is extended-ID.
 *
 * Note: CAN_SHDN_Pin (PD2) controls the CAN-bus transceiver power-down.
 *       Setting it LOW enables the transceiver (active-low SHDN).
 */

#include "usb_app.h"
#include "can.h"
#include "main.h"
#include <string.h>

/* -------------------------------------------------------------------------
 * Bridge_CAN_Init
 * Configure an accept-all filter, start CAN, enable FIFO0 interrupt.
 * ------------------------------------------------------------------------- */
void Bridge_CAN_Init(void)
{
    /* Enable CAN transceiver (CAN_SHDN active-low) */
    HAL_GPIO_WritePin(CAN_SHDN_GPIO_Port, CAN_SHDN_Pin, GPIO_PIN_RESET);

    /* Accept-all filter on FIFO0 */
    CAN_FilterTypeDef f = {0};
    f.FilterBank           = 0U;
    f.FilterMode           = CAN_FILTERMODE_IDMASK;
    f.FilterScale          = CAN_FILTERSCALE_32BIT;
    f.FilterIdHigh         = 0x0000U;
    f.FilterIdLow          = 0x0000U;
    f.FilterMaskIdHigh     = 0x0000U;
    f.FilterMaskIdLow      = 0x0000U;
    f.FilterFIFOAssignment = CAN_RX_FIFO0;
    f.FilterActivation     = ENABLE;
    HAL_CAN_ConfigFilter(&hcan1, &f);

    HAL_CAN_Start(&hcan1);
    HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING);
}

/* -------------------------------------------------------------------------
 * Bridge_CAN_Send
 * Payload: [ID:4BE][DLC:1][data:DLC]
 * ------------------------------------------------------------------------- */
void Bridge_CAN_Send(const uint8_t *data, uint16_t len)
{
    if (data == NULL || len < 5U) { return; }

    uint32_t can_id = ((uint32_t)data[0] << 24U)
                    | ((uint32_t)data[1] << 16U)
                    | ((uint32_t)data[2] <<  8U)
                    |  (uint32_t)data[3];
    uint8_t dlc = data[4];
    if (dlc > 8U) { dlc = 8U; }
    if (len < (uint16_t)(5U + dlc)) { return; }

    CAN_TxHeaderTypeDef hdr = {0};
    if (can_id <= 0x7FFU) {
        hdr.StdId = can_id;
        hdr.IDE   = CAN_ID_STD;
    } else {
        hdr.ExtId = can_id;
        hdr.IDE   = CAN_ID_EXT;
    }
    hdr.RTR = CAN_RTR_DATA;
    hdr.DLC = dlc;

    uint32_t mailbox;
    HAL_CAN_AddTxMessage(&hcan1, &hdr, (uint8_t *)&data[5], &mailbox);
}

/* -------------------------------------------------------------------------
 * HAL_CAN_RxFifo0MsgPendingCallback
 * Received CAN frame → bridge queue → Bridge_Task → CDC
 * ------------------------------------------------------------------------- */
void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan)
{
    CAN_RxHeaderTypeDef rxhdr;
    uint8_t rx_data[8U];

    while (HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO0, &rxhdr, rx_data) == HAL_OK)
    {
        BridgeMsg_t msg;
        msg.ch = BRIDGE_CH_CAN;

        uint32_t id = (rxhdr.IDE == CAN_ID_STD) ? rxhdr.StdId : rxhdr.ExtId;
        msg.buf[0] = (uint8_t)(id >> 24U);
        msg.buf[1] = (uint8_t)(id >> 16U);
        msg.buf[2] = (uint8_t)(id >>  8U);
        msg.buf[3] = (uint8_t)(id        );
        /* Mark extended-ID frames with bit7 of the DLC byte */
        msg.buf[4] = (rxhdr.IDE == CAN_ID_EXT)
                     ? (uint8_t)(rxhdr.DLC | 0x80U)
                     : (uint8_t) rxhdr.DLC;
        memcpy(&msg.buf[5], rx_data, rxhdr.DLC);
        msg.len = (uint16_t)(5U + rxhdr.DLC);

        osMessageQueuePut(bridge_rx_queue, &msg, 0U, 0U);
    }
}

/* -------------------------------------------------------------------------
 * Bridge_CAN_Config
 * BRIDGE_CFG_CAN_BAUD : 125000 / 250000 / 500000 / 1000000
 * APB1 = 42 MHz, total TQ = 14  (SJW=1, BS1=11, BS2=2)
 * Prescaler = APB1 / (baud * 14)
 * ------------------------------------------------------------------------- */
typedef struct { uint32_t baud; uint32_t pre; } CanBaudEntry_t;
static const CanBaudEntry_t s_can_baud_table[] = {
    { 1000000U,  3U },
    {  500000U,  6U },
    {  250000U, 12U },
    {  125000U, 24U },
};

void Bridge_CAN_Config(uint8_t param, uint32_t value)
{
    if (param != BRIDGE_CFG_CAN_BAUD) { return; }
    uint32_t pre = 0U;
    for (uint8_t i = 0U; i < 4U; i++) {
        if (s_can_baud_table[i].baud == value) { pre = s_can_baud_table[i].pre; break; }
    }
    if (pre == 0U) { return; }   /* unsupported baud rate */

    HAL_CAN_Stop(&hcan1);
    HAL_CAN_DeInit(&hcan1);
    hcan1.Init.Prescaler         = pre;
    hcan1.Init.Mode              = CAN_MODE_NORMAL;
    hcan1.Init.SyncJumpWidth     = CAN_SJW_1TQ;
    hcan1.Init.TimeSeg1          = CAN_BS1_11TQ;
    hcan1.Init.TimeSeg2          = CAN_BS2_2TQ;
    hcan1.Init.TimeTriggeredMode = DISABLE;
    hcan1.Init.AutoBusOff        = DISABLE;
    hcan1.Init.AutoWakeUp        = DISABLE;
    hcan1.Init.AutoRetransmission = ENABLE;
    hcan1.Init.ReceiveFifoLocked  = DISABLE;
    hcan1.Init.TransmitFifoPriority = DISABLE;
    HAL_CAN_Init(&hcan1);

    /* Re-apply accept-all filter */
    CAN_FilterTypeDef f = {0};
    f.FilterBank           = 0U;
    f.FilterMode           = CAN_FILTERMODE_IDMASK;
    f.FilterScale          = CAN_FILTERSCALE_32BIT;
    f.FilterFIFOAssignment = CAN_RX_FIFO0;
    f.FilterActivation     = ENABLE;
    HAL_CAN_ConfigFilter(&hcan1, &f);
    HAL_CAN_Start(&hcan1);
    HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING);
}
