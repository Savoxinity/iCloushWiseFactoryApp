"""
iCloush 智慧工厂 — 腾讯云发票 OCR & 核验服务
═══════════════════════════════════════════════════
Phase 3A: 发票识别与真伪核验

依赖：
  pip install tencentcloud-sdk-python-ocr

环境变量：
  TENCENT_SECRET_ID   腾讯云 API 密钥 ID
  TENCENT_SECRET_KEY  腾讯云 API 密钥 Key
"""
import json
import logging
import base64
from datetime import datetime
from typing import Optional, Dict, Any

from app.core.config import settings

logger = logging.getLogger("icloush.ocr")


# ═══════════════════════════════════════════════════
# 腾讯云 SDK 初始化
# ═══════════════════════════════════════════════════

def _get_ocr_client():
    """获取腾讯云 OCR 客户端实例"""
    try:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.ocr.v20181119 import ocr_client

        cred = credential.Credential(
            settings.TENCENT_SECRET_ID,
            settings.TENCENT_SECRET_KEY,
        )
        http_profile = HttpProfile()
        http_profile.endpoint = "ocr.tencentcloudapi.com"
        http_profile.reqMethod = "POST"

        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile

        client = ocr_client.OcrClient(cred, "ap-shanghai", client_profile)
        return client
    except Exception as e:
        logger.error(f"腾讯云 OCR 客户端初始化失败: {e}")
        raise


# ═══════════════════════════════════════════════════
# 发票 OCR 识别
# ═══════════════════════════════════════════════════

async def recognize_invoice(image_url: Optional[str] = None,
                            image_base64: Optional[str] = None) -> Dict[str, Any]:
    """
    调用腾讯云 VatInvoiceOCR 识别发票

    参数:
        image_url:    图片 URL（与 image_base64 二选一）
        image_base64: 图片 Base64 编码

    返回:
        {
            "success": True/False,
            "invoice_type": "增值税专用发票" / "增值税普通发票" / ...,
            "data": { ... 结构化字段 ... },
            "raw": { ... 原始 OCR 响应 ... },
            "error": None / "错误信息"
        }
    """
    try:
        from tencentcloud.ocr.v20181119 import models as ocr_models

        client = _get_ocr_client()
        req = ocr_models.VatInvoiceOCRRequest()

        params = {}
        if image_url:
            params["ImageUrl"] = image_url
        elif image_base64:
            params["ImageBase64"] = image_base64
        else:
            return {"success": False, "error": "需要提供 image_url 或 image_base64"}

        req.from_json_string(json.dumps(params))
        resp = client.VatInvoiceOCR(req)
        raw = json.loads(resp.to_json_string())

        # 解析结构化数据
        parsed = _parse_ocr_result(raw)
        parsed["raw"] = raw
        parsed["success"] = True
        parsed["error"] = None

        logger.info(f"发票 OCR 识别成功: type={parsed.get('invoice_type')}, "
                     f"number={parsed.get('data', {}).get('invoice_number')}")
        return parsed

    except Exception as e:
        logger.error(f"发票 OCR 识别失败: {e}")
        return {
            "success": False,
            "invoice_type": None,
            "data": {},
            "raw": {},
            "error": str(e),
        }


def _parse_ocr_result(raw: dict) -> dict:
    """
    将腾讯云 VatInvoiceOCR 原始返回解析为统一结构

    腾讯云返回的 VatInvoiceInfos 是一个列表，每项包含:
      Name: 字段名（如"发票号码"、"合计金额"等）
      Value: 字段值
    """
    items = raw.get("VatInvoiceInfos", [])
    invoice_type = raw.get("Type", "")

    # 构建字段映射
    field_map = {}
    for item in items:
        field_map[item.get("Name", "")] = item.get("Value", "")

    # 统一提取
    data = {
        "invoice_code": field_map.get("发票代码", ""),
        "invoice_number": field_map.get("发票号码", ""),
        "invoice_date": _parse_date(field_map.get("开票日期", "")),
        "check_code": field_map.get("校验码", "")[-6:] if field_map.get("校验码") else "",
        "buyer_name": field_map.get("购买方名称", "") or field_map.get("购方名称", ""),
        "buyer_tax_id": field_map.get("购买方识别号", "") or field_map.get("购方纳税人识别号", ""),
        "seller_name": field_map.get("销售方名称", "") or field_map.get("销方名称", ""),
        "seller_tax_id": field_map.get("销售方识别号", "") or field_map.get("销方纳税人识别号", ""),
        "pre_tax_amount": _parse_amount(field_map.get("合计金额", "")),
        "tax_amount": _parse_amount(field_map.get("合计税额", "")),
        "total_amount": _parse_amount(
            field_map.get("价税合计", "") or field_map.get("小写金额", "")
        ),
        "remark": field_map.get("备注", ""),
    }

    return {
        "invoice_type": _normalize_invoice_type(invoice_type),
        "data": data,
    }


def _normalize_invoice_type(raw_type: str) -> str:
    """将腾讯云返回的发票类型归一化"""
    type_map = {
        "增值税专用发票": "special_vat",
        "增值税普通发票": "general_vat",
        "增值税电子专用发票": "special_vat",
        "增值税电子普通发票": "general_vat",
        "全电发票（专用发票）": "special_vat",
        "全电发票（普通发票）": "general_vat",
        "卷式发票": "general_vat",
        "区块链发票": "general_vat",
        "机动车销售统一发票": "special_vat",
    }
    for key, val in type_map.items():
        if key in raw_type:
            return val
    return "general_vat"


def _parse_date(date_str: str) -> Optional[str]:
    """解析各种日期格式为 YYYY-MM-DD"""
    if not date_str:
        return None
    # 常见格式：2026年03月15日 / 2026-03-15 / 20260315
    date_str = date_str.replace("年", "-").replace("月", "-").replace("日", "").strip()
    try:
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str


def _parse_amount(amount_str: str) -> Optional[float]:
    """解析金额字符串"""
    if not amount_str:
        return None
    # 去掉 ¥ ￥ 符号和空格
    cleaned = amount_str.replace("¥", "").replace("￥", "").replace(",", "").replace(" ", "").strip()
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════
# 发票真伪核验
# ═══════════════════════════════════════════════════

async def verify_invoice(
    invoice_code: str,
    invoice_number: str,
    invoice_date: str,
    total_amount: str,
    check_code: str = "",
) -> Dict[str, Any]:
    """
    调用腾讯云 VatInvoiceVerify 核验发票真伪

    参数:
        invoice_code:   发票代码
        invoice_number: 发票号码
        invoice_date:   开票日期 YYYY-MM-DD
        total_amount:   价税合计金额
        check_code:     校验码后6位（普票必填）

    返回:
        {
            "success": True/False,
            "verified": True/False,
            "data": { ... 核验详情 ... },
            "error": None / "错误信息"
        }
    """
    try:
        from tencentcloud.ocr.v20181119 import models as ocr_models

        client = _get_ocr_client()
        req = ocr_models.VatInvoiceVerifyNewRequest()

        params = {
            "InvoiceCode": invoice_code,
            "InvoiceNo": invoice_number,
            "InvoiceDate": invoice_date,
            "Additional": total_amount,
        }
        if check_code:
            params["CheckCode"] = check_code

        req.from_json_string(json.dumps(params))
        resp = client.VatInvoiceVerifyNew(req)
        raw = json.loads(resp.to_json_string())

        # 核验通过
        invoice_info = raw.get("Invoice", {})
        verified = bool(invoice_info)

        logger.info(f"发票核验完成: number={invoice_number}, verified={verified}")
        return {
            "success": True,
            "verified": verified,
            "data": invoice_info,
            "error": None,
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"发票核验失败: {error_msg}")

        # 腾讯云返回的错误码判断
        is_fake = "不一致" in error_msg or "查无此票" in error_msg
        return {
            "success": True,  # 调用成功，但核验不通过
            "verified": not is_fake,
            "data": {},
            "error": error_msg if is_fake else None,
        }


# ═══════════════════════════════════════════════════
# 图片转 Base64 工具
# ═══════════════════════════════════════════════════

async def image_file_to_base64(file_bytes: bytes) -> str:
    """将图片文件字节转为 Base64 字符串"""
    return base64.b64encode(file_bytes).decode("utf-8")
