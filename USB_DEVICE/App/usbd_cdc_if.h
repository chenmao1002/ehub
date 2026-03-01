#ifndef __USBD_CDC_IF_H__
#define __USBD_CDC_IF_H__

#include <stdint.h>

#ifdef __cplusplus
 extern "C" {
#endif

/**
 * @brief  Send data to PC serial assistant (USB CDC IN endpoint).
 * @param  Buf  Data buffer pointer
 * @param  Len  Number of bytes
 * @retval USBD_OK / USBD_BUSY / USBD_FAIL
 */
uint8_t CDC_Transmit_FS(uint8_t *Buf, uint16_t Len);

/**
 * @brief  CDC TX complete callback (internal, called by USB stack).
 */
void CDC_TxCplt(void);

/**
 * @brief  Callback when PC sends data to device via serial assistant.
 *         Defined as __weak — override in your application.
 * @param  Buf  Received data
 * @param  Len  Length in bytes
 */
void CDC_Receive_FS(uint8_t *Buf, uint32_t Len);

#ifdef __cplusplus
 }
#endif

#endif /* __USBD_CDC_IF_H__ */
