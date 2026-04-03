"""
iCloush 智慧工厂 — 管理会计数据模型
═══════════════════════════════════════════════════
Phase 3C / Phase 4: 管理会计引擎

表：
  - management_cost_ledger   管理会计成本流水（超级流水表）
  - missing_invoice_ledger   欠票看板
"""
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, Text, DateTime, Date,
    Numeric, JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════
# 成本分类码参考
# ═══════════════════════════════════════════════════
# E-0    折旧摊销（固定）
# E-1-1  工资（固定/变动）
# E-1-2  外包劳务（变动）
# E-2    社保公积金（固定）
# E-3    能源水电（变动）
# E-4    化料洗涤剂（变动）
# E-5    设备维修（变动）
# E-6    运输物流（变动）
# E-7    房租物业（固定）
# E-8    行政办公（固定）
# E-9    营销推广（固定）
# E-10   员工报销（变动）
# ═══════════════════════════════════════════════════

CATEGORY_CODES = {
    "E-0":   {"name": "折旧摊销",   "default_behavior": "fixed",    "default_center": "manufacturing_overhead"},
    "E-1-1": {"name": "工资",       "default_behavior": "fixed",    "default_center": "direct_labor"},
    "E-1-2": {"name": "外包劳务",   "default_behavior": "variable", "default_center": "direct_labor"},
    "E-2":   {"name": "社保公积金", "default_behavior": "fixed",    "default_center": "period_expense"},
    "E-3":   {"name": "能源水电",   "default_behavior": "variable", "default_center": "manufacturing_overhead"},
    "E-4":   {"name": "化料洗涤剂", "default_behavior": "variable", "default_center": "direct_material"},
    "E-5":   {"name": "设备维修",   "default_behavior": "variable", "default_center": "manufacturing_overhead"},
    "E-6":   {"name": "运输物流",   "default_behavior": "variable", "default_center": "period_expense"},
    "E-7":   {"name": "房租物业",   "default_behavior": "fixed",    "default_center": "period_expense"},
    "E-8":   {"name": "行政办公",   "default_behavior": "fixed",    "default_center": "period_expense"},
    "E-9":   {"name": "营销推广",   "default_behavior": "fixed",    "default_center": "period_expense"},
    "E-10":  {"name": "员工报销",   "default_behavior": "variable", "default_center": "period_expense"},
}


# ═══════════════════════════════════════════════════
# 管理会计成本流水表（超级流水表）
# ═══════════════════════════════════════════════════

class ManagementCostLedger(Base):
    """
    管理会计成本流水 — 每一笔成本发生都记录在此表
    
    来源类型：
      - manual:            手动录入
      - expense_report:    报销单审核通过后自动生成
      - iot_auto:          IoT 化料消耗自动捕获
      - schedule_auto:     排班工时自动结算
      - depreciation_auto: 每月折旧定时任务
    """
    __tablename__ = "management_cost_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 基础信息 ──
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # ── 金额与税控 ──
    pre_tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))  # 税点百分比，如 6.00 = 6%
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    post_tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # 发票状态
    invoice_status: Mapped[str] = mapped_column(String(20), default="none")
    # special_vat（专票）/ general_vat（普票）/ none（无票）

    # ── 管会分类（核心） ──
    category_code: Mapped[str] = mapped_column(String(20), nullable=False)
    # E-0 至 E-10，参见 CATEGORY_CODES

    cost_behavior: Mapped[str] = mapped_column(String(10), nullable=False)
    # variable（变动成本）/ fixed（固定成本）

    cost_center: Mapped[str] = mapped_column(String(30), nullable=False)
    # direct_material / direct_labor / manufacturing_overhead / period_expense

    is_sunk_cost: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── 来源追溯 ──
    source_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # manual / expense_report / iot_auto / schedule_auto / depreciation_auto
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── 审核 ──
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    # confirmed / pending_review

    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_mcl_trade_date", "trade_date"),
        Index("ix_mcl_category_code", "category_code"),
        Index("ix_mcl_cost_behavior", "cost_behavior"),
        Index("ix_mcl_invoice_status", "invoice_status"),
        Index("ix_mcl_source_type", "source_type"),
    )


# ═══════════════════════════════════════════════════
# 欠票看板
# ═══════════════════════════════════════════════════

class MissingInvoiceLedger(Base):
    """
    欠票看板 — 现金支出但未收到发票的记录
    
    当员工用收据报销（无发票）时自动生成。
    系统每 15 天检查一次，对未核销记录生成追票任务并扣积分。
    员工上传发票后 OCR 碰对核销。
    """
    __tablename__ = "missing_invoice_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # 来源
    source_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # expense_report / manual
    expense_report_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("expense_reports.id"), nullable=True)

    # 追票状态
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending / reminded / received / written_off
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    responsible_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # 核销
    matched_invoice_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("invoices.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_mil_status", "status"),
        Index("ix_mil_responsible_user_id", "responsible_user_id"),
    )
