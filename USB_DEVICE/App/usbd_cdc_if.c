#include "usbd_cdc_if.h"
#include "usbd_customhid.h"
#include "usb_device.h"
#include "stm32f4xx_hal.h"

extern USBD_HandleTypeDef hUsbDeviceFS;

/* -----------------------------------------------------------------------
 * Internal TX busy flag.
 * Set to 1 when a USB CDC IN transfer is in progress.
 * Cleared automatically in CDC_TxCplt() when the transfer completes.
 * ----------------------------------------------------------------------- */
static volatile uint8_t cdc_tx_busy = 0U;

/* -----------------------------------------------------------------------
 * CDC_Transmit_FS
 *
 * Send data from device to PC serial assistant.
 * Buf must remain valid until CDC_TxCplt() is called (i.e. do not use
 * a local stack buffer unless you block-wait for completion).
 *
 * Returns:
 *   USBD_OK   – transfer started
 *   USBD_BUSY – previous transfer still in progress, call again later
 *   USBD_FAIL – USB not enumerated / configured
 * ----------------------------------------------------------------------- */
uint8_t CDC_Transmit_FS(uint8_t *Buf, uint16_t Len)
{
  if (Len == 0U)                                        { return USBD_OK;   }
  if (hUsbDeviceFS.dev_state != USBD_STATE_CONFIGURED)  { return USBD_FAIL; }
  if (cdc_tx_busy)                                      { return USBD_BUSY; }

  cdc_tx_busy = 1U;
  USBD_LL_Transmit(&hUsbDeviceFS, CDC_IN_EP_ADDR, Buf, (uint32_t)Len);
  return USBD_OK;
}

/* -----------------------------------------------------------------------
 * CDC_TxCplt
 *
 * Called automatically by the USB stack (via USBD_CUSTOM_HID_DataIn)
 * when a CDC IN transfer finishes.  Releases the busy flag so that
 * the next call to CDC_Transmit_FS() can proceed.
 * ----------------------------------------------------------------------- */
void CDC_TxCplt(void)
{
  cdc_tx_busy = 0U;
}

/* -----------------------------------------------------------------------
 * CDC_Receive_FS  (weak – override in your application)
 *
 * Called when the PC serial assistant sends data to the device.
 * The default implementation does nothing; define your own version
 * anywhere in the project to handle incoming bytes.
 *
 * Example (in main.c or app layer):
 *
 *   void CDC_Receive_FS(uint8_t *Buf, uint32_t Len)
 *   {
 *       // echo back to PC
 *       while (CDC_Transmit_FS(Buf, Len) == USBD_BUSY);
 *   }
 * ----------------------------------------------------------------------- */
__weak void CDC_Receive_FS(uint8_t *Buf, uint32_t Len)
{
  UNUSED(Buf);
  UNUSED(Len);
}
