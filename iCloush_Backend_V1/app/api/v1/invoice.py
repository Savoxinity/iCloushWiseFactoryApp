"""
发票路由 — Phase 3A 基础 + Phase 3C 自动销账集成
═══════════════════════════════════════════════════
核心功能：
  1. 发票OCR上传识别
  2. 发票列表/详情
  3. 发票核验
  4. Phase 3C: 上传发票后自动触发欠票销账

接口清单：
  POST /upload          上传发票图片并OCR识别
  GET  /list            发票列表
  GET  /{id}            发票详情
  POST /{id}/verify     发票核验
"""
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import User
from app.models.finance import Invoice, MissingInvoiceLedger

router = APIRouter()


# ═══════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════

class InvoiceUploadRequest(BaseModel):
    """发票上传（OCR识别结果）"""
    image_url: str = Field(..., description="发票图片URL")
    # OCR 识别字段（前端OCR后传入）
    invoice_type: Optional[str] = Field(default=None, description="发票类型")
    invoice_code: Optional[str] = Field(default=None, description="发票代码")
    invoice_number: Optional[str] = Field(default=None, description="发票号码")
    invoice_date: Optional[str] = Field(default=None, description="开票日期 YYYY-MM-DD")
    check_code: Optional[str] = Field(default=None, description="校验码")
    buyer_name: Optional[str] = Field(default=None, description="购方名称")
    buyer_tax_id: Optional[str] = Field(default=None, description="购方税号")
    seller_name: Optional[str] = Field(default=None, description="销方名称")
    seller_tax_id: Optional[str] = Field(default=None, description="销方税号")
    pre_tax_amount: Optional[float] = Field(default=None, description="不含税金额")
    tax_amount: Optional[float] = Field(default=None, description="税额")
    total_amount: Optional[float] = Field(default=None, description="价税合计")
    remark: Optional[str] = Field(default=None, description="备注")
    ocr_raw_json: Optional[dict] = Field(default=None, description="OCR原始JSON")
    business_type: Optional[str] = Field(default=None, description="业务分类")


class InvoiceVerifyRequest(BaseModel):
    """发票核验"""
    verify_result: str = Field(..., description="核验结果: verified/failed/duplicate")
    verify_result_json: Optional[dict] = Field(default=None, description="核验详情JSON")


# ═══════════════════════════════════════════════════
# 上传发票
# ═══════════════════════════════════════════════════

@router.post("/upload")
async def upload_invoice(
    req: InvoiceUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    上传发票（OCR识别后存储）
    Phase 3C: 上传成功后自动触发欠票销账匹配
    """
    # 解析日期
    invoice_date = None
    if req.invoice_date:
        try:
            invoice_date = date.fromisoformat(req.invoice_date)
        except ValueError:
            pass

    invoice = Invoice(
        user_id=current_user.id,
        invoice_type=req.invoice_type,
        invoice_code=req.invoice_code,
        invoice_number=req.invoice_number,
        invoice_date=invoice_date,
        check_code=req.check_code,
        buyer_name=req.buyer_name,
        buyer_tax_id=req.buyer_tax_id,
        seller_name=req.seller_name,
        seller_tax_id=req.seller_tax_id,
        pre_tax_amount=Decimal(str(req.pre_tax_amount)) if req.pre_tax_amount else None,
        tax_amount=Decimal(str(req.tax_amount)) if req.tax_amount else None,
        total_amount=Decimal(str(req.total_amount)) if req.total_amount else None,
        remark=req.remark,
        image_url=req.image_url,
        ocr_raw_json=req.ocr_raw_json,
        verify_status="pending",
        business_type=req.business_type,
    )
    db.add(invoice)
    await db.flush()

    # ── Phase 3C: 自动销账匹配 ──
    auto_resolved = []
    if invoice.total_amount:
        # 查找该员工的未核销欠票
        missing_result = await db.execute(
            select(MissingInvoiceLedger).where(
                and_(
                    MissingInvoiceLedger.responsible_user_id == current_user.id,
                    MissingInvoiceLedger.status.in_(["pending", "reminded"]),
                )
            ).order_by(MissingInvoiceLedger.trade_date.desc())
        )
        pending_records = missing_result.scalars().all()

        now = datetime.now(timezone.utc)
        inv_amount = float(invoice.total_amount)

        for record in pending_records:
            record_amount = float(record.amount)
            if record_amount > 0:
                diff_pct = abs(inv_amount - record_amount) / record_amount
                if diff_pct <= 0.05:
                    # 金额匹配（±5%容差）→ 自动销账
                    record.status = "received"
                    record.matched_invoice_id = invoice.id
                    record.resolved_at = now
                    record.resolved_by = current_user.id
                    auto_resolved.append({
                        "missing_invoice_id": record.id,
                        "item_name": record.item_name,
                        "amount": record_amount,
                    })
                    break  # 一张发票只匹配一条欠票

    await db.flush()

    response_data = _serialize_invoice(invoice)
    if auto_resolved:
        response_data["auto_resolved"] = auto_resolved

    return {
        "code": 200,
        "message": "发票上传成功" + (f"，自动核销 {len(auto_resolved)} 条欠票" if auto_resolved else ""),
        "data": response_data,
    }


# ═══════════════════════════════════════════════════
# 发票列表
# ═══════════════════════════════════════════════════

@router.get("/list")
async def list_invoices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发票列表（员工看自己的，管理员看全部）"""
    query = select(Invoice)

    if current_user.role < 5:
        query = query.where(Invoice.user_id == current_user.id)

    # 总数
    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar() or 0

    query = query.order_by(Invoice.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    invoices = result.scalars().all()

    return {
        "code": 200,
        "data": [_serialize_invoice(inv) for inv in invoices],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ═══════════════════════════════════════════════════
# 发票详情
# ═══════════════════════════════════════════════════

@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发票详情"""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")
    if invoice.user_id != current_user.id and current_user.role < 5:
        raise HTTPException(status_code=403, detail="无权查看")
    return {"code": 200, "data": _serialize_invoice(invoice)}


# ═══════════════════════════════════════════════════
# 发票核验
# ═══════════════════════════════════════════════════

@router.post("/{invoice_id}/verify")
async def verify_invoice(
    invoice_id: int,
    req: InvoiceVerifyRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """发票核验（管理员操作）"""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")

    if req.verify_result not in ("verified", "failed", "duplicate"):
        raise HTTPException(status_code=422, detail="核验结果必须为 verified/failed/duplicate")

    invoice.verify_status = req.verify_result
    invoice.verify_result_json = req.verify_result_json
    await db.flush()

    return {
        "code": 200,
        "message": "核验完成",
        "data": _serialize_invoice(invoice),
    }


# ═══════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════

def _serialize_invoice(inv: Invoice) -> dict:
    VERIFY_LABELS = {
        "pending": "待核验",
        "verifying": "核验中",
        "verified": "已核验",
        "failed": "核验失败",
        "duplicate": "重复发票",
    }
    return {
        "id": inv.id,
        "user_id": inv.user_id,
        "invoice_type": inv.invoice_type,
        "invoice_code": inv.invoice_code,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "check_code": inv.check_code,
        "buyer_name": inv.buyer_name,
        "buyer_tax_id": inv.buyer_tax_id,
        "seller_name": inv.seller_name,
        "seller_tax_id": inv.seller_tax_id,
        "pre_tax_amount": float(inv.pre_tax_amount) if inv.pre_tax_amount else None,
        "tax_amount": float(inv.tax_amount) if inv.tax_amount else None,
        "total_amount": float(inv.total_amount) if inv.total_amount else None,
        "remark": inv.remark,
        "image_url": inv.image_url,
        "verify_status": inv.verify_status,
        "verify_status_label": VERIFY_LABELS.get(inv.verify_status, "未知"),
        "business_type": inv.business_type,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }
