"""
iCloush 智慧工厂 — 发票与报销数据模型
═══════════════════════════════════════════════════
Phase 3A: 发票夹与报销系统

表：
  - invoices        发票主表（OCR 识别后存储）
  - expense_reports 报销单
"""
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, Date,
    Numeric, JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════
# 发票主表
# ═══════════════════════════════════════════════════

class Invoice(Base):
    """发票主表 — OCR 识别后存储全部字段"""
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # ── OCR 识别字段 ──
    invoice_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 专票 / 普票 / 电子发票 / 卷票 / 区块链发票 / 收据
    invoice_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    check_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 校验码后6位

    # 购销方信息
    buyer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    buyer_tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    seller_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    seller_tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 金额
    pre_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ocr_raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── 核验状态 ──
    # pending / verifying / verified / failed / duplicate
    verify_status: Mapped[str] = mapped_column(String(20), default="pending")
    verify_result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── 业务分类 ──
    business_type: Mapped[Optional[str]] = mapped_column(String(50), default="expense")
    # expense（报销采购）

    # ── 是否已提交报销 ──
    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # 关系
    expense_reports: Mapped[list] = relationship("ExpenseReport", back_populates="invoice")

    __table_args__ = (
        Index("ix_invoices_user_id", "user_id"),
        Index("ix_invoices_verify_status", "verify_status"),
        Index("ix_invoices_invoice_number", "invoice_number"),
    )


# ═══════════════════════════════════════════════════
# 报销单
# ═══════════════════════════════════════════════════

class ExpenseReport(Base):
    """报销单 — 员工提交报销申请"""
    __tablename__ = "expense_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # 报销内容
    purpose: Mapped[str] = mapped_column(String(200), nullable=False)  # 用途说明
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # 员工填报金额

    # 凭证类型
    voucher_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # invoice（发票）/ receipt（收据）
    invoice_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("invoices.id"), nullable=True)
    receipt_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ── 审核流程 ──
    # pending / auto_approved / manual_review / approved / rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 金额差异
    amount_diff_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)

    # 积分变动
    points_delta: Mapped[int] = mapped_column(Integer, default=0)  # +10 或 -5

    # ── 管会联动 ──
    # 审核通过后自动生成的成本流水 ID
    cost_ledger_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # 关系
    invoice: Mapped[Optional["Invoice"]] = relationship("Invoice", back_populates="expense_reports")

    __table_args__ = (
        Index("ix_expense_reports_user_id", "user_id"),
        Index("ix_expense_reports_status", "status"),
    )
