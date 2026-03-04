/**
  ******************************************************************************
  * @file    usbd_customhid.c
  * @author  MCD Application Team
  * @brief   This file provides the CUSTOM_HID core functions.
  *
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2015 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  * @verbatim
  *
  *          ===================================================================
  *                                CUSTOM_HID Class  Description
  *          ===================================================================
  *           This module manages the CUSTOM_HID class V1.11 following the "Device Class Definition
  *           for Human Interface Devices (CUSTOM_HID) Version 1.11 Jun 27, 2001".
  *           This driver implements the following aspects of the specification:
  *             - The Boot Interface Subclass
  *             - Usage Page : Generic Desktop
  *             - Usage : Vendor
  *             - Collection : Application
  *
  * @note     In HS mode and when the DMA is used, all variables and data structures
  *           dealing with the DMA during the transaction process should be 32-bit aligned.
  *
  *
  *  @endverbatim
  *
  ******************************************************************************
  */

/* BSPDependencies
- "stm32xxxxx_{eval}{discovery}{nucleo_144}.c"
- "stm32xxxxx_{eval}{discovery}_io.c"
EndBSPDependencies */

/* Includes ------------------------------------------------------------------*/
#include "usbd_customhid.h"
#include "usbd_ctlreq.h"


/** @addtogroup STM32_USB_DEVICE_LIBRARY
  * @{
  */


/** @defgroup USBD_CUSTOM_HID
  * @brief usbd core module
  * @{
  */

/** @defgroup USBD_CUSTOM_HID_Private_TypesDefinitions
  * @{
  */
/**
  * @}
  */


/** @defgroup USBD_CUSTOM_HID_Private_Defines
  * @{
  */

/**
  * @}
  */


/** @defgroup USBD_CUSTOM_HID_Private_Macros
  * @{
  */
/**
  * @}
  */
/** @defgroup USBD_CUSTOM_HID_Private_FunctionPrototypes
  * @{
  */

static uint8_t USBD_CUSTOM_HID_Init(USBD_HandleTypeDef *pdev, uint8_t cfgidx);
static uint8_t USBD_CUSTOM_HID_DeInit(USBD_HandleTypeDef *pdev, uint8_t cfgidx);
static uint8_t USBD_CUSTOM_HID_Setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req);

static uint8_t USBD_CUSTOM_HID_DataIn(USBD_HandleTypeDef *pdev, uint8_t epnum);
static uint8_t USBD_CUSTOM_HID_DataOut(USBD_HandleTypeDef *pdev, uint8_t epnum);
static uint8_t USBD_CUSTOM_HID_EP0_RxReady(USBD_HandleTypeDef  *pdev);
#ifndef USE_USBD_COMPOSITE
static uint8_t *USBD_CUSTOM_HID_GetFSCfgDesc(uint16_t *length);
static uint8_t *USBD_CUSTOM_HID_GetHSCfgDesc(uint16_t *length);
static uint8_t *USBD_CUSTOM_HID_GetOtherSpeedCfgDesc(uint16_t *length);
static uint8_t *USBD_CUSTOM_HID_GetDeviceQualifierDesc(uint16_t *length);
#endif /* USE_USBD_COMPOSITE  */
/**
  * @}
  */

/** @defgroup USBD_CUSTOM_HID_Private_Variables
  * @{
  */

USBD_ClassTypeDef  USBD_CUSTOM_HID =
{
  USBD_CUSTOM_HID_Init,
  USBD_CUSTOM_HID_DeInit,
  USBD_CUSTOM_HID_Setup,
  NULL, /*EP0_TxSent*/
  USBD_CUSTOM_HID_EP0_RxReady, /*EP0_RxReady*/ /* STATUS STAGE IN */
  USBD_CUSTOM_HID_DataIn, /*DataIn*/
  USBD_CUSTOM_HID_DataOut,
  NULL, /*SOF */
  NULL,
  NULL,
#ifdef USE_USBD_COMPOSITE
  NULL,
  NULL,
  NULL,
  NULL,
#else
  USBD_CUSTOM_HID_GetHSCfgDesc,
  USBD_CUSTOM_HID_GetFSCfgDesc,
  USBD_CUSTOM_HID_GetOtherSpeedCfgDesc,
  USBD_CUSTOM_HID_GetDeviceQualifierDesc,
#endif /* USE_USBD_COMPOSITE  */
};

#ifndef USE_USBD_COMPOSITE
/* USB CUSTOM_HID+CDC Composite Configuration Descriptor (107 bytes)
 * Interface 0: HID  (CMSIS-DAP)
 * Interface 1: CDC  Communications Interface (ACM, Notification EP)
 * Interface 2: CDC  Data Interface (Bulk IN/OUT)
 */
__ALIGN_BEGIN static uint8_t USBD_CUSTOM_HID_CfgDesc[USB_CUSTOM_HID_CONFIG_DESC_SIZ] __ALIGN_END =
{
  /* ---------- Configuration Descriptor (9 bytes) ---------- */
  0x09,                                               /* bLength */
  USB_DESC_TYPE_CONFIGURATION,                        /* bDescriptorType */
  LOBYTE(USB_CUSTOM_HID_CONFIG_DESC_SIZ),             /* wTotalLength lo */
  HIBYTE(USB_CUSTOM_HID_CONFIG_DESC_SIZ),             /* wTotalLength hi */
  0x03,                                               /* bNumInterfaces: HID + CDC_Comm + CDC_Data */
  0x01,                                               /* bConfigurationValue */
  0x00,                                               /* iConfiguration */
#if (USBD_SELF_POWERED == 1U)
  0xC0,                                               /* bmAttributes: self powered */
#else
  0x80,                                               /* bmAttributes: bus powered */
#endif /* USBD_SELF_POWERED */
  USBD_MAX_POWER,                                     /* MaxPower */

  /* ---------- Interface 0: HID (9 bytes, offset 9) ---------- */
  0x09,                                               /* bLength */
  USB_DESC_TYPE_INTERFACE,                            /* bDescriptorType */
  0x00,                                               /* bInterfaceNumber */
  0x00,                                               /* bAlternateSetting */
  0x02,                                               /* bNumEndpoints */
  0x03,                                               /* bInterfaceClass: HID */
  0x00,                                               /* bInterfaceSubClass */
  0x00,                                               /* bInterfaceProtocol */
  0x00,                                               /* iInterface */

  /* HID Class Descriptor (9 bytes, offset 18) */
  0x09,                                               /* bLength */
  CUSTOM_HID_DESCRIPTOR_TYPE,                         /* bDescriptorType */
  0x11, 0x01,                                         /* bcdHID */
  0x00,                                               /* bCountryCode */
  0x01,                                               /* bNumDescriptors */
  0x22,                                               /* bDescriptorType: Report */
  LOBYTE(USBD_CUSTOM_HID_REPORT_DESC_SIZE),           /* wItemLength lo */
  HIBYTE(USBD_CUSTOM_HID_REPORT_DESC_SIZE),           /* wItemLength hi */

  /* HID EP IN (7 bytes, offset 27) */
  0x07,                                               /* bLength */
  USB_DESC_TYPE_ENDPOINT,                             /* bDescriptorType */
  CUSTOM_HID_EPIN_ADDR,                               /* bEndpointAddress */
  0x03,                                               /* bmAttributes: Interrupt */
  LOBYTE(CUSTOM_HID_EPIN_SIZE),                       /* wMaxPacketSize lo */
  HIBYTE(CUSTOM_HID_EPIN_SIZE),                       /* wMaxPacketSize hi */
  CUSTOM_HID_FS_BINTERVAL,                            /* bInterval */

  /* HID EP OUT (7 bytes, offset 34) */
  0x07,                                               /* bLength */
  USB_DESC_TYPE_ENDPOINT,                             /* bDescriptorType */
  CUSTOM_HID_EPOUT_ADDR,                              /* bEndpointAddress */
  0x03,                                               /* bmAttributes: Interrupt */
  LOBYTE(CUSTOM_HID_EPOUT_SIZE),                      /* wMaxPacketSize lo */
  HIBYTE(CUSTOM_HID_EPOUT_SIZE),                      /* wMaxPacketSize hi */
  CUSTOM_HID_FS_BINTERVAL,                            /* bInterval */
  /* offset 41 */

  /* ---------- IAD: Interface Association Descriptor (8 bytes, offset 41) ---------- */
  0x08,                                               /* bLength */
  0x0B,                                               /* bDescriptorType: IAD */
  0x01,                                               /* bFirstInterface: 1 */
  0x02,                                               /* bInterfaceCount: 2 (CDC comm + data) */
  0x02,                                               /* bFunctionClass: CDC */
  0x02,                                               /* bFunctionSubClass: ACM */
  0x01,                                               /* bFunctionProtocol: AT commands */
  0x00,                                               /* iFunction */
  /* offset 49 */

  /* ---------- Interface 1: CDC Communications (9 bytes, offset 49) ---------- */
  0x09,                                               /* bLength */
  USB_DESC_TYPE_INTERFACE,                            /* bDescriptorType */
  0x01,                                               /* bInterfaceNumber: 1 */
  0x00,                                               /* bAlternateSetting */
  0x01,                                               /* bNumEndpoints: 1 (Notification) */
  0x02,                                               /* bInterfaceClass: CDC */
  0x02,                                               /* bInterfaceSubClass: ACM */
  0x01,                                               /* bInterfaceProtocol: AT commands */
  0x00,                                               /* iInterface */
  /* offset 58 */

  /* CDC Header Functional Descriptor (5 bytes, offset 58) */
  0x05, 0x24, 0x00, 0x10, 0x01,
  /* CDC Call Management Functional Descriptor (5 bytes, offset 63) */
  0x05, 0x24, 0x01, 0x00, 0x02,
  /* CDC ACM Functional Descriptor (4 bytes, offset 68) */
  0x04, 0x24, 0x02, 0x02,
  /* CDC Union Functional Descriptor (5 bytes, offset 72) */
  0x05, 0x24, 0x06, 0x01, 0x02,
  /* offset 77 */

  /* CDC Notification EP IN (Interrupt, 7 bytes, offset 77) */
  0x07,                                               /* bLength */
  USB_DESC_TYPE_ENDPOINT,                             /* bDescriptorType */
  CDC_CMD_EP_ADDR,                                    /* bEndpointAddress: 0x82 */
  0x03,                                               /* bmAttributes: Interrupt */
  LOBYTE(CDC_CMD_EP_SIZE),                            /* wMaxPacketSize lo */
  HIBYTE(CDC_CMD_EP_SIZE),                            /* wMaxPacketSize hi */
  0x10,                                               /* bInterval */
  /* offset 84 */

  /* ---------- Interface 2: CDC Data (9 bytes, offset 84) ---------- */
  0x09,                                               /* bLength */
  USB_DESC_TYPE_INTERFACE,                            /* bDescriptorType */
  0x02,                                               /* bInterfaceNumber: 2 */
  0x00,                                               /* bAlternateSetting */
  0x02,                                               /* bNumEndpoints */
  0x0A,                                               /* bInterfaceClass: CDC Data */
  0x00,                                               /* bInterfaceSubClass */
  0x00,                                               /* bInterfaceProtocol */
  0x00,                                               /* iInterface */
  /* offset 93 */

  /* CDC Data EP OUT (Bulk, 7 bytes, offset 93) */
  0x07,                                               /* bLength */
  USB_DESC_TYPE_ENDPOINT,                             /* bDescriptorType */
  CDC_OUT_EP_ADDR,                                    /* bEndpointAddress: 0x03 */
  0x02,                                               /* bmAttributes: Bulk */
  LOBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),                /* wMaxPacketSize lo */
  HIBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),                /* wMaxPacketSize hi */
  0x00,                                               /* bInterval */

  /* CDC Data EP IN (Bulk, 7 bytes, offset 100) */
  0x07,                                               /* bLength */
  USB_DESC_TYPE_ENDPOINT,                             /* bDescriptorType */
  CDC_IN_EP_ADDR,                                     /* bEndpointAddress: 0x83 */
  0x02,                                               /* bmAttributes: Bulk */
  LOBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),                /* wMaxPacketSize lo */
  HIBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),                /* wMaxPacketSize hi */
  0x00,                                               /* bInterval */
  /* offset 107 */
};
#endif /* USE_USBD_COMPOSITE  */

/* USB CUSTOM_HID device Configuration Descriptor */
__ALIGN_BEGIN static uint8_t USBD_CUSTOM_HID_Desc[USB_CUSTOM_HID_DESC_SIZ] __ALIGN_END =
{
  /* 18 */
  0x09,                                               /* bLength: CUSTOM_HID Descriptor size */
  CUSTOM_HID_DESCRIPTOR_TYPE,                         /* bDescriptorType: CUSTOM_HID */
  0x11,                                               /* bCUSTOM_HIDUSTOM_HID: CUSTOM_HID Class Spec release number */
  0x01,
  0x00,                                               /* bCountryCode: Hardware target country */
  0x01,                                               /* bNumDescriptors: Number of CUSTOM_HID class descriptors
                                                         to follow */
  0x22,                                               /* bDescriptorType */
  LOBYTE(USBD_CUSTOM_HID_REPORT_DESC_SIZE),                   /* wItemLength: Total length of Report descriptor */
  HIBYTE(USBD_CUSTOM_HID_REPORT_DESC_SIZE),
};

#ifndef USE_USBD_COMPOSITE
/* USB Standard Device Descriptor */
__ALIGN_BEGIN static uint8_t USBD_CUSTOM_HID_DeviceQualifierDesc[USB_LEN_DEV_QUALIFIER_DESC] __ALIGN_END =
{
  USB_LEN_DEV_QUALIFIER_DESC,
  USB_DESC_TYPE_DEVICE_QUALIFIER,
  0x00,
  0x02,
  0x00,
  0x00,
  0x00,
  0x40,
  0x01,
  0x00,
};
#endif /* USE_USBD_COMPOSITE  */

static uint8_t CUSTOMHIDInEpAdd = CUSTOM_HID_EPIN_ADDR;
static uint8_t CUSTOMHIDOutEpAdd = CUSTOM_HID_EPOUT_ADDR;
/**
  * @}
  */

/** @defgroup USBD_CUSTOM_HID_Private_Functions
  * @{
  */

/**
  * @brief  USBD_CUSTOM_HID_Init
  *         Initialize the CUSTOM_HID interface
  * @param  pdev: device instance
  * @param  cfgidx: Configuration index
  * @retval status
  */
static uint8_t USBD_CUSTOM_HID_Init(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  UNUSED(cfgidx);
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid;

  hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)USBD_malloc(sizeof(USBD_CUSTOM_HID_ComposeHandleTypeDef));

  if (hhid == NULL)
  {
    pdev->pClassDataCmsit[pdev->classId] = NULL;
    return (uint8_t)USBD_EMEM;
  }

  pdev->pClassDataCmsit[pdev->classId] = (void *)hhid;
  pdev->pClassData = pdev->pClassDataCmsit[pdev->classId];

#ifdef USE_USBD_COMPOSITE
  /* Get the Endpoints addresses allocated for this class instance */
  CUSTOMHIDInEpAdd = USBD_CoreGetEPAdd(pdev, USBD_EP_IN, USBD_EP_TYPE_INTR, (uint8_t)pdev->classId);
  CUSTOMHIDOutEpAdd = USBD_CoreGetEPAdd(pdev, USBD_EP_OUT, USBD_EP_TYPE_INTR, (uint8_t)pdev->classId);
#endif /* USE_USBD_COMPOSITE */

  if (pdev->dev_speed == USBD_SPEED_HIGH)
  {
    pdev->ep_in[CUSTOMHIDInEpAdd & 0xFU].bInterval = CUSTOM_HID_HS_BINTERVAL;
    pdev->ep_out[CUSTOMHIDOutEpAdd & 0xFU].bInterval = CUSTOM_HID_HS_BINTERVAL;
  }
  else   /* LOW and FULL-speed endpoints */
  {
    pdev->ep_in[CUSTOMHIDInEpAdd & 0xFU].bInterval = CUSTOM_HID_FS_BINTERVAL;
    pdev->ep_out[CUSTOMHIDOutEpAdd & 0xFU].bInterval = CUSTOM_HID_FS_BINTERVAL;
  }

  /* Open HID EP IN */
  (void)USBD_LL_OpenEP(pdev, CUSTOMHIDInEpAdd, USBD_EP_TYPE_INTR, CUSTOM_HID_EPIN_SIZE);
  pdev->ep_in[CUSTOMHIDInEpAdd & 0xFU].is_used = 1U;

  /* Open HID EP OUT */
  (void)USBD_LL_OpenEP(pdev, CUSTOMHIDOutEpAdd, USBD_EP_TYPE_INTR, CUSTOM_HID_EPOUT_SIZE);
  pdev->ep_out[CUSTOMHIDOutEpAdd & 0xFU].is_used = 1U;

  /* Open CDC Notification EP (Interrupt IN) */
  (void)USBD_LL_OpenEP(pdev, CDC_CMD_EP_ADDR, USBD_EP_TYPE_INTR, CDC_CMD_EP_SIZE);
  pdev->ep_in[CDC_CMD_EP_ADDR & 0xFU].is_used = 1U;

  /* Open CDC Data EP IN (Bulk) */
  (void)USBD_LL_OpenEP(pdev, CDC_IN_EP_ADDR, USBD_EP_TYPE_BULK, CDC_DATA_FS_MAX_PACKET_SIZE);
  pdev->ep_in[CDC_IN_EP_ADDR & 0xFU].is_used = 1U;

  /* Open CDC Data EP OUT (Bulk) */
  (void)USBD_LL_OpenEP(pdev, CDC_OUT_EP_ADDR, USBD_EP_TYPE_BULK, CDC_DATA_FS_MAX_PACKET_SIZE);
  pdev->ep_out[CDC_OUT_EP_ADDR & 0xFU].is_used = 1U;

  hhid->state = CUSTOM_HID_IDLE;

  ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->Init();

#ifndef USBD_CUSTOMHID_OUT_PREPARE_RECEIVE_DISABLED
  /* Prepare HID Out endpoint to receive 1st packet */
  (void)USBD_LL_PrepareReceive(pdev, CUSTOMHIDOutEpAdd, hhid->Report_buf,
                               USBD_CUSTOMHID_OUTREPORT_BUF_SIZE);
#endif /* USBD_CUSTOMHID_OUT_PREPARE_RECEIVE_DISABLED */

  /* Prepare CDC Out endpoint to receive 1st packet */
  (void)USBD_LL_PrepareReceive(pdev, CDC_OUT_EP_ADDR, hhid->cdc_rx_buf,
                               CDC_DATA_FS_MAX_PACKET_SIZE);

  return (uint8_t)USBD_OK;
}

/**
  * @brief  USBD_CUSTOM_HID_Init
  *         DeInitialize the CUSTOM_HID layer
  * @param  pdev: device instance
  * @param  cfgidx: Configuration index
  * @retval status
  */
static uint8_t USBD_CUSTOM_HID_DeInit(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  UNUSED(cfgidx);

#ifdef USE_USBD_COMPOSITE
  /* Get the Endpoints addresses allocated for this class instance */
  CUSTOMHIDInEpAdd = USBD_CoreGetEPAdd(pdev, USBD_EP_IN, USBD_EP_TYPE_INTR, (uint8_t)pdev->classId);
  CUSTOMHIDOutEpAdd = USBD_CoreGetEPAdd(pdev, USBD_EP_OUT, USBD_EP_TYPE_INTR, (uint8_t)pdev->classId);
#endif /* USE_USBD_COMPOSITE */

  /* Close HID EP IN */
  (void)USBD_LL_CloseEP(pdev, CUSTOMHIDInEpAdd);
  pdev->ep_in[CUSTOMHIDInEpAdd & 0xFU].is_used = 0U;
  pdev->ep_in[CUSTOMHIDInEpAdd & 0xFU].bInterval = 0U;

  /* Close HID EP OUT */
  (void)USBD_LL_CloseEP(pdev, CUSTOMHIDOutEpAdd);
  pdev->ep_out[CUSTOMHIDOutEpAdd & 0xFU].is_used = 0U;
  pdev->ep_out[CUSTOMHIDOutEpAdd & 0xFU].bInterval = 0U;

  /* Close CDC endpoints */
  (void)USBD_LL_CloseEP(pdev, CDC_CMD_EP_ADDR);
  pdev->ep_in[CDC_CMD_EP_ADDR & 0xFU].is_used = 0U;

  (void)USBD_LL_CloseEP(pdev, CDC_IN_EP_ADDR);
  pdev->ep_in[CDC_IN_EP_ADDR & 0xFU].is_used = 0U;

  (void)USBD_LL_CloseEP(pdev, CDC_OUT_EP_ADDR);
  pdev->ep_out[CDC_OUT_EP_ADDR & 0xFU].is_used = 0U;

  /* Free allocated memory */
  if (pdev->pClassDataCmsit[pdev->classId] != NULL)
  {
    ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->DeInit();
    USBD_free(pdev->pClassDataCmsit[pdev->classId]);
    pdev->pClassDataCmsit[pdev->classId] = NULL;
    pdev->pClassData = NULL;
  }

  return (uint8_t)USBD_OK;
}

/**
  * @brief  USBD_CUSTOM_HID_Setup
  *         Handle the CUSTOM_HID specific requests
  * @param  pdev: instance
  * @param  req: usb requests
  * @retval status
  */
static uint8_t USBD_CUSTOM_HID_Setup(USBD_HandleTypeDef *pdev,
                                     USBD_SetupReqTypedef *req)
{
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];
  uint16_t len = 0U;
#ifdef USBD_CUSTOMHID_CTRL_REQ_GET_REPORT_ENABLED
  uint16_t ReportLength = 0U;
#endif /* USBD_CUSTOMHID_CTRL_REQ_GET_REPORT_ENABLED */
  uint8_t  *pbuf = NULL;
  uint16_t status_info = 0U;
  USBD_StatusTypeDef ret = USBD_OK;

  if (hhid == NULL)
  {
    return (uint8_t)USBD_FAIL;
  }

  switch (req->bmRequest & USB_REQ_TYPE_MASK)
  {
    case USB_REQ_TYPE_CLASS:
      switch (req->bRequest)
      {
        case CUSTOM_HID_REQ_SET_PROTOCOL:
          hhid->Protocol = (uint8_t)(req->wValue);
          break;

        case CUSTOM_HID_REQ_GET_PROTOCOL:
          (void)USBD_CtlSendData(pdev, (uint8_t *)&hhid->Protocol, 1U);
          break;

        case CUSTOM_HID_REQ_SET_IDLE:
          hhid->IdleState = (uint8_t)(req->wValue >> 8);
          break;

        case CUSTOM_HID_REQ_GET_IDLE:
          (void)USBD_CtlSendData(pdev, (uint8_t *)&hhid->IdleState, 1U);
          break;

        case CUSTOM_HID_REQ_SET_REPORT:
#ifdef USBD_CUSTOMHID_CTRL_REQ_COMPLETE_CALLBACK_ENABLED
          if (((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->CtrlReqComplete != NULL)
          {
            ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->CtrlReqComplete(req->bRequest,
                                                                                            req->wLength);
          }
#endif /* USBD_CUSTOMHID_CTRL_REQ_COMPLETE_CALLBACK_ENABLED */
#ifndef USBD_CUSTOMHID_EP0_OUT_PREPARE_RECEIVE_DISABLED
          if (req->wLength > USBD_CUSTOMHID_OUTREPORT_BUF_SIZE)
          {
            USBD_CtlError(pdev, req);
            return USBD_FAIL;
          }
          hhid->IsReportAvailable = 1U;
          (void)USBD_CtlPrepareRx(pdev, hhid->Report_buf, req->wLength);
#endif /* USBD_CUSTOMHID_EP0_OUT_PREPARE_RECEIVE_DISABLED */
          break;
#ifdef USBD_CUSTOMHID_CTRL_REQ_GET_REPORT_ENABLED
        case CUSTOM_HID_REQ_GET_REPORT:
          if (((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->GetReport != NULL)
          {
            ReportLength = req->wLength;
            pbuf = ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->GetReport(&ReportLength);
          }
          if ((pbuf != NULL) && (ReportLength != 0U))
          {
            len = MIN(ReportLength, req->wLength);
            (void)USBD_CtlSendData(pdev, pbuf, len);
          }
          else
          {
#ifdef USBD_CUSTOMHID_CTRL_REQ_COMPLETE_CALLBACK_ENABLED
            if (((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->CtrlReqComplete != NULL)
            {
              ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->CtrlReqComplete(req->bRequest,
                                                                                              req->wLength);
            }
            else
            {
              USBD_CtlError(pdev, req);
            }
#else
            USBD_CtlError(pdev, req);
#endif /* USBD_CUSTOMHID_CTRL_REQ_COMPLETE_CALLBACK_ENABLED */
          }
          break;
#endif /* USBD_CUSTOMHID_CTRL_REQ_GET_REPORT_ENABLED */

        /* --- CDC-ACM class requests (wIndex selects CDC communication interface 1) --- */
        case 0x20U: /* CDC SET_LINE_CODING */
          hhid->is_linecoding_set = 1U;
          (void)USBD_CtlPrepareRx(pdev, hhid->linecoding, MIN(req->wLength, 7U));
          break;

        case 0x21U: /* CDC GET_LINE_CODING */
          (void)USBD_CtlSendData(pdev, hhid->linecoding, MIN(req->wLength, 7U));
          break;

        case 0x22U: /* CDC SET_CONTROL_LINE_STATE */
          hhid->control_line_state = req->wValue;
          /* NOTE: We intentionally do NOT forward DTR/RTS to ESP32 BOOT/EN here.
           * When the host opens the COM port, it asserts both DTR=1 and RTS=1,
           * which would hold ESP32 in reset (EN LOW).  The passthrough entry
           * sequence already puts ESP32 into bootloader mode, so auto-reset
           * via DTR/RTS is not needed (esptool uses --before no_reset). */
          break;

        default:
          USBD_CtlError(pdev, req);
          ret = USBD_FAIL;
          break;
      }
      break;

    case USB_REQ_TYPE_STANDARD:
      switch (req->bRequest)
      {
        case USB_REQ_GET_STATUS:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            (void)USBD_CtlSendData(pdev, (uint8_t *)&status_info, 2U);
          }
          else
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        case USB_REQ_GET_DESCRIPTOR:
          if ((req->wValue >> 8) == CUSTOM_HID_REPORT_DESC)
          {
            len = MIN(USBD_CUSTOM_HID_REPORT_DESC_SIZE, req->wLength);
            pbuf = ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->pReport;
          }
          else
          {
            if ((req->wValue >> 8) == CUSTOM_HID_DESCRIPTOR_TYPE)
            {
              pbuf = USBD_CUSTOM_HID_Desc;
              len = MIN(USB_CUSTOM_HID_DESC_SIZ, req->wLength);
            }
          }

          if (pbuf != NULL)
          {
            (void)USBD_CtlSendData(pdev, pbuf, len);
          }
          else
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        case USB_REQ_GET_INTERFACE:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            (void)USBD_CtlSendData(pdev, (uint8_t *)&hhid->AltSetting, 1U);
          }
          else
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        case USB_REQ_SET_INTERFACE:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            hhid->AltSetting = (uint8_t)(req->wValue);
          }
          else
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        case USB_REQ_CLEAR_FEATURE:
          break;

        default:
          USBD_CtlError(pdev, req);
          ret = USBD_FAIL;
          break;
      }
      break;

    default:
      USBD_CtlError(pdev, req);
      ret = USBD_FAIL;
      break;
  }
  return (uint8_t)ret;
}

/**
  * @brief  USBD_CUSTOM_HID_SendReport
  *         Send CUSTOM_HID Report
  * @param  pdev: device instance
  * @param  buff: pointer to report
  * @param  ClassId: The Class ID
  * @retval status
  */
#ifdef USE_USBD_COMPOSITE
uint8_t USBD_CUSTOM_HID_SendReport(USBD_HandleTypeDef *pdev,
                                   uint8_t *report, uint16_t len, uint8_t ClassId)
{
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[ClassId];
#else
uint8_t USBD_CUSTOM_HID_SendReport(USBD_HandleTypeDef *pdev,
                                   uint8_t *report, uint16_t len)
{
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];
#endif /* USE_USBD_COMPOSITE */

  if (hhid == NULL)
  {
    return (uint8_t)USBD_FAIL;
  }

#ifdef USE_USBD_COMPOSITE
  /* Get Endpoint IN address allocated for this class instance */
  CUSTOMHIDInEpAdd = USBD_CoreGetEPAdd(pdev, USBD_EP_IN, USBD_EP_TYPE_INTR, ClassId);
#endif /* USE_USBD_COMPOSITE */

  if (pdev->dev_state == USBD_STATE_CONFIGURED)
  {
    if (hhid->state == CUSTOM_HID_IDLE)
    {
      hhid->state = CUSTOM_HID_BUSY;
      (void)USBD_LL_Transmit(pdev, CUSTOMHIDInEpAdd, report, len);
    }
    else
    {
      return (uint8_t)USBD_BUSY;
    }
  }
  return (uint8_t)USBD_OK;
}
#ifndef USE_USBD_COMPOSITE
/**
  * @brief  USBD_CUSTOM_HID_GetFSCfgDesc
  *         return FS configuration descriptor
  * @param  speed : current device speed
  * @param  length : pointer data length
  * @retval pointer to descriptor buffer
  */
static uint8_t *USBD_CUSTOM_HID_GetFSCfgDesc(uint16_t *length)
{
  USBD_EpDescTypeDef *pEpInDesc = USBD_GetEpDesc(USBD_CUSTOM_HID_CfgDesc, CUSTOM_HID_EPIN_ADDR);
  USBD_EpDescTypeDef *pEpOutDesc = USBD_GetEpDesc(USBD_CUSTOM_HID_CfgDesc, CUSTOM_HID_EPOUT_ADDR);

  if (pEpInDesc != NULL)
  {
    pEpInDesc->wMaxPacketSize = CUSTOM_HID_EPIN_SIZE;
    pEpInDesc->bInterval = CUSTOM_HID_FS_BINTERVAL;
  }

  if (pEpOutDesc != NULL)
  {
    pEpOutDesc->wMaxPacketSize = CUSTOM_HID_EPOUT_SIZE;
    pEpOutDesc->bInterval = CUSTOM_HID_FS_BINTERVAL;
  }

  *length = (uint16_t)sizeof(USBD_CUSTOM_HID_CfgDesc);
  return USBD_CUSTOM_HID_CfgDesc;
}

/**
  * @brief  USBD_CUSTOM_HID_GetHSCfgDesc
  *         return HS configuration descriptor
  * @param  speed : current device speed
  * @param  length : pointer data length
  * @retval pointer to descriptor buffer
  */
static uint8_t *USBD_CUSTOM_HID_GetHSCfgDesc(uint16_t *length)
{
  USBD_EpDescTypeDef *pEpInDesc = USBD_GetEpDesc(USBD_CUSTOM_HID_CfgDesc, CUSTOM_HID_EPIN_ADDR);
  USBD_EpDescTypeDef *pEpOutDesc = USBD_GetEpDesc(USBD_CUSTOM_HID_CfgDesc, CUSTOM_HID_EPOUT_ADDR);

  if (pEpInDesc != NULL)
  {
    pEpInDesc->wMaxPacketSize = CUSTOM_HID_EPIN_SIZE;
    pEpInDesc->bInterval = CUSTOM_HID_HS_BINTERVAL;
  }

  if (pEpOutDesc != NULL)
  {
    pEpOutDesc->wMaxPacketSize = CUSTOM_HID_EPOUT_SIZE;
    pEpOutDesc->bInterval = CUSTOM_HID_HS_BINTERVAL;
  }

  *length = (uint16_t)sizeof(USBD_CUSTOM_HID_CfgDesc);
  return USBD_CUSTOM_HID_CfgDesc;
}

/**
  * @brief  USBD_CUSTOM_HID_GetOtherSpeedCfgDesc
  *         return other speed configuration descriptor
  * @param  speed : current device speed
  * @param  length : pointer data length
  * @retval pointer to descriptor buffer
  */
static uint8_t *USBD_CUSTOM_HID_GetOtherSpeedCfgDesc(uint16_t *length)
{
  USBD_EpDescTypeDef *pEpInDesc = USBD_GetEpDesc(USBD_CUSTOM_HID_CfgDesc, CUSTOM_HID_EPIN_ADDR);
  USBD_EpDescTypeDef *pEpOutDesc = USBD_GetEpDesc(USBD_CUSTOM_HID_CfgDesc, CUSTOM_HID_EPOUT_ADDR);

  if (pEpInDesc != NULL)
  {
    pEpInDesc->wMaxPacketSize = CUSTOM_HID_EPIN_SIZE;
    pEpInDesc->bInterval = CUSTOM_HID_FS_BINTERVAL;
  }

  if (pEpOutDesc != NULL)
  {
    pEpOutDesc->wMaxPacketSize = CUSTOM_HID_EPOUT_SIZE;
    pEpOutDesc->bInterval = CUSTOM_HID_FS_BINTERVAL;
  }

  *length = (uint16_t)sizeof(USBD_CUSTOM_HID_CfgDesc);
  return USBD_CUSTOM_HID_CfgDesc;
}
#endif /* USE_USBD_COMPOSITE  */

/**
  * @brief  USBD_CUSTOM_HID_DataIn
  *         handle data IN Stage
  * @param  pdev: device instance
  * @param  epnum: endpoint index
  * @retval status
  */
	/* USER CODE BEGIN USBD_CUSTOM_HID_DataIn 0 */
extern void USBD_InEvent(void);
extern void CDC_TxCplt(void);
/* USER CODE END USBD_CUSTOM_HID_DataIn 0 */
static uint8_t USBD_CUSTOM_HID_DataIn(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  if (epnum == (CDC_IN_EP_ADDR & 0x0FU))
  {
    /* CDC Bulk IN complete: release TX busy flag */
    CDC_TxCplt();
  }
  else
  {
    /* HID Interrupt IN complete */
    ((USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[pdev->classId])->state = CUSTOM_HID_IDLE;
	  /* USER CODE BEGIN USBD_CUSTOM_HID_DataIn 0 */
    USBD_InEvent();
    /* USER CODE END USBD_CUSTOM_HID_DataIn 0 */
  }
  return (uint8_t)USBD_OK;
}

/**
  * @brief  USBD_CUSTOM_HID_DataOut
  *         handle data OUT Stage
  * @param  pdev: device instance
  * @param  epnum: endpoint index
  * @retval status
  */
static uint8_t USBD_CUSTOM_HID_DataOut(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid;

  if (pdev->pClassDataCmsit[pdev->classId] == NULL)
  {
    return (uint8_t)USBD_FAIL;
  }

  hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];

  if (epnum == (CDC_OUT_EP_ADDR & 0x0FU))
  {
    /* CDC data received from host: forward to UART */
    uint32_t rxlen = USBD_LL_GetRxDataSize(pdev, epnum);
    extern void CDC_Receive_FS(uint8_t *Buf, uint32_t Len);
    CDC_Receive_FS(hhid->cdc_rx_buf, rxlen);

    /* Passthrough flow control: if c2u ring is nearly full, DON'T re-arm
     * the OUT endpoint — the USB host will NAK.  The passthrough task
     * re-arms the endpoint once the ring drains below 50%.             */
    extern uint8_t WiFi_Bridge_IsPassthrough(void);
    extern uint8_t WiFi_Passthrough_C2URingNearlyFull(void);
    extern void    WiFi_Passthrough_SetCDCPaused(void);
    if (WiFi_Bridge_IsPassthrough() && WiFi_Passthrough_C2URingNearlyFull()) {
        WiFi_Passthrough_SetCDCPaused();
        /* Don't call PrepareReceive — endpoint will NAK host */
    } else {
        /* Re-arm CDC OUT endpoint */
        (void)USBD_LL_PrepareReceive(pdev, CDC_OUT_EP_ADDR, hhid->cdc_rx_buf,
                                     CDC_DATA_FS_MAX_PACKET_SIZE);
    }
  }
  else
  {
    /* HID data received from host */
#ifdef USBD_CUSTOMHID_REPORT_BUFFER_EVENT_ENABLED
    ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->OutEvent(hhid->Report_buf);
#else
    ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->OutEvent(hhid->Report_buf[0],
                                                                             hhid->Report_buf[1]);
#endif /* USBD_CUSTOMHID_REPORT_BUFFER_EVENT_ENABLED */
  }

  return (uint8_t)USBD_OK;
}


/**
  * @brief  USBD_CUSTOM_HID_ReceivePacket
  *         prepare OUT Endpoint for reception
  * @param  pdev: device instance
  * @retval status
  */
uint8_t USBD_CUSTOM_HID_ReceivePacket(USBD_HandleTypeDef *pdev)
{
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid;

  if (pdev->pClassDataCmsit[pdev->classId] == NULL)
  {
    return (uint8_t)USBD_FAIL;
  }

#ifdef USE_USBD_COMPOSITE
  /* Get OUT Endpoint address allocated for this class instance */
  CUSTOMHIDOutEpAdd = USBD_CoreGetEPAdd(pdev, USBD_EP_OUT, USBD_EP_TYPE_INTR, (uint8_t)pdev->classId);
#endif /* USE_USBD_COMPOSITE */

  hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];

  /* Resume USB Out process */
  (void)USBD_LL_PrepareReceive(pdev, CUSTOMHIDOutEpAdd, hhid->Report_buf,
                               USBD_CUSTOMHID_OUTREPORT_BUF_SIZE);

  return (uint8_t)USBD_OK;
}


/**
  * @brief  USBD_CUSTOM_HID_EP0_RxReady
  *         Handles control request data.
  * @param  pdev: device instance
  * @retval status
  */
static uint8_t USBD_CUSTOM_HID_EP0_RxReady(USBD_HandleTypeDef *pdev)
{
  USBD_CUSTOM_HID_ComposeHandleTypeDef *hhid = (USBD_CUSTOM_HID_ComposeHandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];

  if (hhid == NULL)
  {
    return (uint8_t)USBD_FAIL;
  }

  if (hhid->IsReportAvailable == 1U)
  {
#ifdef USBD_CUSTOMHID_REPORT_BUFFER_EVENT_ENABLED
    ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->OutEvent(hhid->Report_buf);
#else
    ((USBD_CUSTOM_HID_ItfTypeDef *)pdev->pUserData[pdev->classId])->OutEvent(hhid->Report_buf[0],
                                                                             hhid->Report_buf[1]);
#endif /* USBD_CUSTOMHID_REPORT_BUFFER_EVENT_ENABLED */
    hhid->IsReportAvailable = 0U;
  }

  /* Handle CDC SET_LINE_CODING data phase completion */
  if (hhid->is_linecoding_set == 1U)
  {
    hhid->is_linecoding_set = 0U;
    /* linecoding[0..3]: dwDTERate, [4]: bCharFormat, [5]: bParityType, [6]: bDataBits */
    extern void CDC_SetLineCoding_Callback(uint8_t *linecoding);
    CDC_SetLineCoding_Callback(hhid->linecoding);
  }

  return (uint8_t)USBD_OK;
}

#ifndef USE_USBD_COMPOSITE
/**
  * @brief  DeviceQualifierDescriptor
  *         return Device Qualifier descriptor
  * @param  length : pointer data length
  * @retval pointer to descriptor buffer
  */
static uint8_t *USBD_CUSTOM_HID_GetDeviceQualifierDesc(uint16_t *length)
{
  *length = (uint16_t)sizeof(USBD_CUSTOM_HID_DeviceQualifierDesc);

  return USBD_CUSTOM_HID_DeviceQualifierDesc;
}
#endif /* USE_USBD_COMPOSITE  */
/**
  * @brief  USBD_CUSTOM_HID_RegisterInterface
  * @param  pdev: device instance
  * @param  fops: CUSTOMHID Interface callback
  * @retval status
  */
uint8_t USBD_CUSTOM_HID_RegisterInterface(USBD_HandleTypeDef *pdev,
                                          USBD_CUSTOM_HID_ItfTypeDef *fops)
{
  if (fops == NULL)
  {
    return (uint8_t)USBD_FAIL;
  }

  pdev->pUserData[pdev->classId] = fops;

  return (uint8_t)USBD_OK;
}
/**
  * @}
  */


/**
  * @}
  */


/**
  * @}
  */

