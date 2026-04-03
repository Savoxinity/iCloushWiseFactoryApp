"""
管理会计路由 — Phase 3B 纯财务直录台 + 利润表
═══════════════════════════════════════════════════
核心功能：
  1. 纯财务直录台：管理员手动录入成本（折旧、工资等无需发票的成本）
  2. 成本流水列表：多维筛选查询
  3. 实时贡献利润表：营收 - 变动成本 = 边际贡献 - 固定成本 = 经营净利润
  4. 税务漏洞追踪：无票成本 × 25% 企业所得税
  5. 成本分类汇总：按 category_code 聚合

接口清单：
  POST /cost/create               手动录入成本（纯财务直录台）
  GET  /cost/list                 成本流水列表
  GET  /cost/{id}                 成本流水详情
  PUT  /cost/{id}                 编辑成本流水
  DELETE /cost/{id}               删除成本流水
  GET  /profit-statement          实时贡献利润表
  GET  /tax-leakage               税务漏洞追踪
  GET  /cost-summary              成本分类汇总
  GET  /categories                成本分类配置

数据隔离：所有接口限制 role>=5
"""
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.models.models import User, DailyProduction
from app.models.finance import ManagementCostLedger, COST_CATEGORIES

router = APIRouter()


# ═══════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════

class CostCreateRequest(BaseModel):
    """手动录入成本（纯财务直录台）"""
    trade_date: str = Field(..., description="交易日期 YYYY-MM-DD")
    item_name: str = Field(..., min_length=1, max_length=200, description="明细名称")
    supplier_name: Optional[str] = Field(default=None, description="供应商/收款方")
    pre_tax_amount: float = Field(..., gt=0, description="不含税金额")
    tax_rate: float = Field(default=0, ge=0, le=100, description="税率（如 6 = 6%）")
    invoice_status: str = Field(default="none", description="发票状态: special_vat/general_vat/none")
    category_code: str = Field(..., description="成本分类代码: E-0~E-10")
    is_sunk_cost: bool = Field(default=False, description="是否为沉没成本")
    remark: Optional[str] = Field(default=None, description="备注")


class CostUpdateRequest(BaseModel):
    """编辑成本流水"""
    trade_date: Optional[str] = None
    item_name: Optional[str] = None
    supplier_name: Optional[str] = None
    pre_tax_amount: Optional[float] = None
    tax_rate: Optional[float] = None
    invoice_status: Optional[str] = None
    category_code: Optional[str] = None
    is_sunk_cost: Optional[bool] = None


# ═══════════════════════════════════════════════════
# 手动录入成本（纯财务直录台）
# ═══════════════════════════════════════════════════

@router.post("/cost/create")
async def create_cost_entry(
    req: CostCreateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """
    纯财务直录台 — 手动录入成本
    适用场景：折旧、工资、社保等无需发票的固定成本
    自动计算：tax_amount = pre_tax_amount × tax_rate / 100
              post_tax_amount = pre_tax_amount + tax_amount
    """
    if req.category_code not in COST_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"无效的成本分类代码: {req.category_code}")

    if req.invoice_status not in ("special_vat", "general_vat", "none"):
        raise HTTPException(status_code=422, detail="发票状态必须为 special_vat/general_vat/none")

    cat_config = COST_CATEGORIES[req.category_code]

    # 自动计算税额
    pre_tax = Decimal(str(req.pre_tax_amount))
    tax_rate = Decimal(str(req.tax_rate))
    tax_amount = (pre_tax * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    post_tax = pre_tax + tax_amount

    try:
        trade_date = date.fromisoformat(req.trade_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式错误，请使用 YYYY-MM-DD")

    entry = ManagementCostLedger(
        trade_date=trade_date,
        item_name=req.item_name,
        supplier_name=req.supplier_name,
        pre_tax_amount=pre_tax,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        post_tax_amount=post_tax,
        invoice_status=req.invoice_status,
        category_code=req.category_code,
        cost_behavior=cat_config["behavior"],
        cost_center=cat_config["center"],
        is_sunk_cost=req.is_sunk_cost,
        source_type="manual",
        source_id=None,
        status="confirmed",
        created_by=current_user.id,
    )
    db.add(entry)
    await db.flush()

    return {
        "code": 200,
        "message": "成本录入成功",
        "data": _serialize_cost(entry),
    }


# ═══════════════════════════════════════════════════
# 成本流水列表
# ═══════════════════════════════════════════════════

@router.get("/cost/list")
async def list_cost_entries(
    year: Optional[int] = Query(default=None, description="年份"),
    month: Optional[int] = Query(default=None, ge=1, le=12, description="月份"),
    category_code: Optional[str] = Query(default=None, description="成本分类"),
    cost_behavior: Optional[str] = Query(default=None, description="成本性态: variable/fixed"),
    source_type: Optional[str] = Query(default=None, description="来源: manual/expense_report"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """成本流水列表（多维筛选）"""
    query = select(ManagementCostLedger)

    # 时间筛选
    if year:
        query = query.where(extract("year", ManagementCostLedger.trade_date) == year)
    if month:
        query = query.where(extract("month", ManagementCostLedger.trade_date) == month)

    # 分类筛选
    if category_code:
        query = query.where(ManagementCostLedger.category_code == category_code)
    if cost_behavior:
        query = query.where(ManagementCostLedger.cost_behavior == cost_behavior)
    if source_type:
        query = query.where(ManagementCostLedger.source_type == source_type)

    # 总数
    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar() or 0

    # 排序 + 分页
    query = query.order_by(ManagementCostLedger.trade_date.desc(), ManagementCostLedger.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    entries = result.scalars().all()

    return {
        "code": 200,
        "data": [_serialize_cost(e) for e in entries],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ═══════════════════════════════════════════════════
# 成本流水详情
# ═══════════════════════════════════════════════════

@router.get("/cost/{entry_id}")
async def get_cost_entry(
    entry_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """成本流水详情"""
    result = await db.execute(
        select(ManagementCostLedger).where(ManagementCostLedger.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="成本记录不存在")
    return {"code": 200, "data": _serialize_cost(entry)}


# ═══════════════════════════════════════════════════
# 编辑成本流水
# ═══════════════════════════════════════════════════

@router.put("/cost/{entry_id}")
async def update_cost_entry(
    entry_id: int,
    req: CostUpdateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """编辑成本流水（仅手动录入的可编辑）"""
    result = await db.execute(
        select(ManagementCostLedger).where(ManagementCostLedger.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="成本记录不存在")
    if entry.source_type != "manual":
        raise HTTPException(status_code=400, detail="仅手动录入的成本可编辑")

    if req.trade_date:
        try:
            entry.trade_date = date.fromisoformat(req.trade_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="日期格式错误")
    if req.item_name is not None:
        entry.item_name = req.item_name
    if req.supplier_name is not None:
        entry.supplier_name = req.supplier_name
    if req.invoice_status is not None:
        entry.invoice_status = req.invoice_status
    if req.is_sunk_cost is not None:
        entry.is_sunk_cost = req.is_sunk_cost

    # 如果分类变了，更新关联的 behavior 和 center
    if req.category_code is not None:
        if req.category_code not in COST_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"无效的成本分类代码: {req.category_code}")
        cat_config = COST_CATEGORIES[req.category_code]
        entry.category_code = req.category_code
        entry.cost_behavior = cat_config["behavior"]
        entry.cost_center = cat_config["center"]

    # 如果金额或税率变了，重新计算
    if req.pre_tax_amount is not None or req.tax_rate is not None:
        pre_tax = Decimal(str(req.pre_tax_amount)) if req.pre_tax_amount else entry.pre_tax_amount
        tax_rate = Decimal(str(req.tax_rate)) if req.tax_rate is not None else entry.tax_rate
        tax_amount = (pre_tax * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
        entry.pre_tax_amount = pre_tax
        entry.tax_rate = tax_rate
        entry.tax_amount = tax_amount
        entry.post_tax_amount = pre_tax + tax_amount

    await db.flush()
    return {"code": 200, "message": "更新成功", "data": _serialize_cost(entry)}


# ═══════════════════════════════════════════════════
# 删除成本流水
# ═══════════════════════════════════════════════════

@router.delete("/cost/{entry_id}")
async def delete_cost_entry(
    entry_id: int,
    current_user: User = Depends(require_role(7)),  # 经理级别才能删除
    db: AsyncSession = Depends(get_db),
):
    """删除成本流水（仅手动录入的可删除，需经理权限）"""
    result = await db.execute(
        select(ManagementCostLedger).where(ManagementCostLedger.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="成本记录不存在")
    if entry.source_type != "manual":
        raise HTTPException(status_code=400, detail="仅手动录入的成本可删除")

    await db.delete(entry)
    await db.flush()
    return {"code": 200, "message": "成本记录已删除"}


# ═══════════════════════════════════════════════════
# 实时贡献利润表
# ═══════════════════════════════════════════════════

@router.get("/profit-statement")
async def profit_statement(
    year: int = Query(..., description="年份"),
    month: int = Query(..., ge=1, le=12, description="月份"),
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """
    实时贡献利润表
    公式：
      营收（从产能报表估算）
      - 变动成本 = 边际贡献
      - 固定成本 = 经营净利润
    """
    # 1. 查询该月所有成本流水
    result = await db.execute(
        select(ManagementCostLedger).where(
            and_(
                extract("year", ManagementCostLedger.trade_date) == year,
                extract("month", ManagementCostLedger.trade_date) == month,
            )
        )
    )
    costs = result.scalars().all()

    # 2. 分类汇总
    variable_costs = sum(float(c.post_tax_amount) for c in costs if c.cost_behavior == "variable")
    fixed_costs = sum(float(c.post_tax_amount) for c in costs if c.cost_behavior == "fixed")
    total_costs = variable_costs + fixed_costs

    # 3. 按 category_code 细分
    by_category = defaultdict(float)
    for c in costs:
        cat_name = COST_CATEGORIES.get(c.category_code, {}).get("name", c.category_code)
        by_category[cat_name] += float(c.post_tax_amount)

    # 4. 按 cost_center 细分
    by_center = defaultdict(float)
    CENTER_LABELS = {
        "direct_material": "直接材料",
        "direct_labor": "直接人工",
        "manufacturing_overhead": "制造费用",
        "period_expense": "期间费用",
    }
    for c in costs:
        center_label = CENTER_LABELS.get(c.cost_center, c.cost_center)
        by_center[center_label] += float(c.post_tax_amount)

    # 5. 营收估算（从产能报表获取，按 200元/套 估算）
    month_str_start = f"{year}-{month:02d}-01"
    month_str_end = f"{year}-{month:02d}-31"
    prod_result = await db.execute(
        select(DailyProduction).where(
            and_(
                DailyProduction.date >= month_str_start,
                DailyProduction.date <= month_str_end,
            )
        )
    )
    productions = prod_result.scalars().all()
    total_sets = sum(p.total_sets for p in productions)
    # 默认单价 200 元/套（可配置）
    revenue = total_sets * 200.0

    # 6. 计算利润
    contribution_margin = revenue - variable_costs
    net_operating_profit = contribution_margin - fixed_costs

    # 7. 税务漏洞
    no_invoice_total = sum(
        float(c.post_tax_amount) for c in costs if c.invoice_status == "none"
    )
    estimated_tax_loss = no_invoice_total * 0.25  # 企业所得税25%

    return {
        "code": 200,
        "data": {
            "period": f"{year}-{month:02d}",
            "revenue": round(revenue, 2),
            "total_sets": total_sets,
            "variable_costs": round(variable_costs, 2),
            "fixed_costs": round(fixed_costs, 2),
            "total_costs": round(total_costs, 2),
            "contribution_margin": round(contribution_margin, 2),
            "net_operating_profit": round(net_operating_profit, 2),
            "by_category": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
            "by_center": {k: round(v, 2) for k, v in sorted(by_center.items(), key=lambda x: -x[1])},
            "tax_leakage": {
                "no_invoice_total": round(no_invoice_total, 2),
                "estimated_tax_loss": round(estimated_tax_loss, 2),
            },
            "cost_entry_count": len(costs),
        },
    }


# ═══════════════════════════════════════════════════
# 税务漏洞追踪
# ═══════════════════════════════════════════════════

@router.get("/tax-leakage")
async def tax_leakage(
    year: int = Query(..., description="年份"),
    month: Optional[int] = Query(default=None, ge=1, le=12, description="月份（不传则全年）"),
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """
    税务漏洞追踪
    列出所有无票成本，计算潜在税务损失
    """
    query = select(ManagementCostLedger).where(
        and_(
            extract("year", ManagementCostLedger.trade_date) == year,
            ManagementCostLedger.invoice_status == "none",
        )
    )
    if month:
        query = query.where(extract("month", ManagementCostLedger.trade_date) == month)

    query = query.order_by(ManagementCostLedger.trade_date.desc())
    result = await db.execute(query)
    entries = result.scalars().all()

    total_no_invoice = sum(float(e.post_tax_amount) for e in entries)
    estimated_tax_loss = total_no_invoice * 0.25

    # 按分类汇总无票金额
    by_category = defaultdict(float)
    for e in entries:
        cat_name = COST_CATEGORIES.get(e.category_code, {}).get("name", e.category_code)
        by_category[cat_name] += float(e.post_tax_amount)

    return {
        "code": 200,
        "data": {
            "total_no_invoice": round(total_no_invoice, 2),
            "estimated_tax_loss": round(estimated_tax_loss, 2),
            "entry_count": len(entries),
            "by_category": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
            "entries": [_serialize_cost(e) for e in entries[:50]],  # 最多返回50条
        },
    }


# ═══════════════════════════════════════════════════
# 成本分类汇总
# ═══════════════════════════════════════════════════

@router.get("/cost-summary")
async def cost_summary(
    year: int = Query(..., description="年份"),
    month: Optional[int] = Query(default=None, ge=1, le=12, description="月份"),
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """成本分类汇总（饼图/柱状图数据源）"""
    query = select(ManagementCostLedger).where(
        extract("year", ManagementCostLedger.trade_date) == year
    )
    if month:
        query = query.where(extract("month", ManagementCostLedger.trade_date) == month)

    result = await db.execute(query)
    entries = result.scalars().all()

    # 按 category_code 汇总
    by_category = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for e in entries:
        by_category[e.category_code]["amount"] += float(e.post_tax_amount)
        by_category[e.category_code]["count"] += 1

    summary = []
    for code, data in sorted(by_category.items(), key=lambda x: -x[1]["amount"]):
        cat_config = COST_CATEGORIES.get(code, {})
        summary.append({
            "category_code": code,
            "category_name": cat_config.get("name", code),
            "behavior": cat_config.get("behavior", "unknown"),
            "center": cat_config.get("center", "unknown"),
            "total_amount": round(data["amount"], 2),
            "entry_count": data["count"],
        })

    return {
        "code": 200,
        "data": {
            "period": f"{year}" + (f"-{month:02d}" if month else ""),
            "total_amount": round(sum(d["amount"] for d in by_category.values()), 2),
            "total_entries": sum(d["count"] for d in by_category.values()),
            "categories": summary,
        },
    }


# ═══════════════════════════════════════════════════
# 成本分类配置
# ═══════════════════════════════════════════════════

@router.get("/categories")
async def list_categories(
    current_user: User = Depends(require_role(5)),
):
    """获取成本分类配置列表"""
    categories = [
        {
            "code": code,
            "name": config["name"],
            "behavior": config["behavior"],
            "behavior_label": "变动成本" if config["behavior"] == "variable" else "固定成本",
            "center": config["center"],
        }
        for code, config in COST_CATEGORIES.items()
    ]
    return {"code": 200, "data": categories}


# ═══════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════

def _serialize_cost(e: ManagementCostLedger) -> dict:
    cat_config = COST_CATEGORIES.get(e.category_code, {})
    SOURCE_LABELS = {
        "manual": "手动录入",
        "expense_report": "报销自动",
        "iot_auto": "IoT自动",
        "schedule_auto": "排班自动",
        "depreciation_auto": "折旧自动",
    }
    return {
        "id": e.id,
        "trade_date": e.trade_date.isoformat() if e.trade_date else None,
        "item_name": e.item_name,
        "supplier_name": e.supplier_name,
        "pre_tax_amount": float(e.pre_tax_amount) if e.pre_tax_amount else 0,
        "tax_rate": float(e.tax_rate) if e.tax_rate else 0,
        "tax_amount": float(e.tax_amount) if e.tax_amount else 0,
        "post_tax_amount": float(e.post_tax_amount) if e.post_tax_amount else 0,
        "invoice_status": e.invoice_status,
        "invoice_status_label": {"special_vat": "专票", "general_vat": "普票", "none": "无票"}.get(e.invoice_status, "未知"),
        "category_code": e.category_code,
        "category_name": cat_config.get("name", e.category_code),
        "cost_behavior": e.cost_behavior,
        "cost_behavior_label": "变动成本" if e.cost_behavior == "variable" else "固定成本",
        "cost_center": e.cost_center,
        "is_sunk_cost": e.is_sunk_cost,
        "source_type": e.source_type,
        "source_label": SOURCE_LABELS.get(e.source_type, "未知"),
        "source_id": e.source_id,
        "status": e.status,
        "created_by": e.created_by,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
