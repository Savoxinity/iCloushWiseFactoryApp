"""
欠票看板路由 — Phase 3C 欠票看板闭环
═══════════════════════════════════════════════════
核心功能：
  1. 欠票看板列表：管理员查看待收/已催/已补交的欠票
  2. 一键催票：自动生成红色紧急任务(priority=4)给欠票员工
  3. 手动销账：管理员确认发票已补交
  4. 自动销账：员工上传发票后自动匹配并销账
  5. 欠票统计：汇总欠票金额和数量

接口清单：
  GET  /list                      欠票列表（支持状态筛选）
  GET  /{id}                      欠票详情
  POST /{id}/remind               一键催票（生成紧急任务）
  POST /{id}/resolve              手动销账
  POST /auto-resolve              自动销账（发票上传后调用）
  GET  /stats                     欠票统计
  POST /create                    手动创建欠票记录

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
from app.core.security import get_current_user, require_role
from app.models.models import User, Task, Zone
from app.models.finance import MissingInvoiceLedger, Invoice

router = APIRouter()


# ═══════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════

class MissingInvoiceCreateRequest(BaseModel):
    """手动创建欠票记录"""
    trade_date: str = Field(..., description="交易日期 YYYY-MM-DD")
    item_name: str = Field(..., min_length=1, max_length=200, description="事项名称")
    supplier_name: Optional[str] = Field(default=None, description="供应商")
    amount: float = Field(..., gt=0, description="金额")
    responsible_user_id: int = Field(..., description="责任人ID")


class ResolveRequest(BaseModel):
    """手动销账"""
    invoice_id: Optional[int] = Field(default=None, description="补交的发票ID")
    note: Optional[str] = Field(default=None, description="备注")


class AutoResolveRequest(BaseModel):
    """自动销账（发票上传后触发）"""
    invoice_id: int = Field(..., description="新上传的发票ID")


# ═══════════════════════════════════════════════════
# 欠票列表
# ═══════════════════════════════════════════════════

@router.get("/list")
async def list_missing_invoices(
    status: Optional[str] = Query(default=None, description="状态筛选: pending/reminded/received/written_off"),
    responsible_user_id: Optional[int] = Query(default=None, description="责任人ID"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """欠票看板列表"""
    query = select(MissingInvoiceLedger)

    if status:
        query = query.where(MissingInvoiceLedger.status == status)
    if responsible_user_id:
        query = query.where(MissingInvoiceLedger.responsible_user_id == responsible_user_id)

    # 总数
    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar() or 0

    # 排序：待处理优先，然后按日期倒序
    query = query.order_by(
        # pending 排最前
        func.case(
            (MissingInvoiceLedger.status == "pending", 0),
            (MissingInvoiceLedger.status == "reminded", 1),
            else_=2,
        ),
        MissingInvoiceLedger.trade_date.desc(),
    )
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    records = result.scalars().all()

    # 批量获取责任人姓名
    user_ids = list(set(r.responsible_user_id for r in records))
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        user_map = {u.id: u.name for u in users_result.scalars().all()}
    else:
        user_map = {}

    data = []
    for r in records:
        d = _serialize_missing(r)
        d["responsible_user_name"] = user_map.get(r.responsible_user_id, "未知")
        data.append(d)

    return {
        "code": 200,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ═══════════════════════════════════════════════════
# 欠票详情
# ═══════════════════════════════════════════════════

@router.get("/{record_id}")
async def get_missing_invoice(
    record_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """欠票详情"""
    result = await db.execute(
        select(MissingInvoiceLedger).where(MissingInvoiceLedger.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="欠票记录不存在")

    data = _serialize_missing(record)

    # 获取责任人信息
    user_result = await db.execute(select(User).where(User.id == record.responsible_user_id))
    user = user_result.scalar_one_or_none()
    data["responsible_user_name"] = user.name if user else "未知"

    # 如果有关联的催票任务
    if record.reminder_task_id:
        task_result = await db.execute(select(Task).where(Task.id == record.reminder_task_id))
        task = task_result.scalar_one_or_none()
        if task:
            data["reminder_task"] = {
                "id": task.id,
                "title": task.title,
                "status": task.status,
            }

    return {"code": 200, "data": data}


# ═══════════════════════════════════════════════════
# 一键催票（生成紧急任务）
# ═══════════════════════════════════════════════════

@router.post("/{record_id}/remind")
async def remind_missing_invoice(
    record_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """
    一键催票
    自动生成红色紧急任务(priority=4)给欠票员工
    任务完成后通过 auto-resolve 自动销账
    """
    result = await db.execute(
        select(MissingInvoiceLedger).where(MissingInvoiceLedger.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="欠票记录不存在")
    if record.status in ("received", "written_off"):
        raise HTTPException(status_code=400, detail="该欠票已核销，无需催票")

    # 获取责任人信息
    user_result = await db.execute(select(User).where(User.id == record.responsible_user_id))
    responsible_user = user_result.scalar_one_or_none()
    if not responsible_user:
        raise HTTPException(status_code=404, detail="责任人不存在")

    # 获取责任人所在工区（用于创建任务）
    zone_id = 1  # 默认工区
    if responsible_user.current_zones:
        zone_result = await db.execute(
            select(Zone).where(Zone.code == responsible_user.current_zones[0])
        )
        zone = zone_result.scalar_one_or_none()
        if zone:
            zone_id = zone.id

    # 创建紧急催票任务
    task = Task(
        title=f"【催票】{record.item_name} ¥{record.amount}",
        description=(
            f"请尽快补交发票。\n"
            f"事项：{record.item_name}\n"
            f"金额：¥{record.amount}\n"
            f"日期：{record.trade_date}\n"
            f"{'供应商：' + record.supplier_name if record.supplier_name else ''}\n"
            f"请在发票管理中上传对应发票，系统将自动核销。"
        ),
        task_type="specific",
        zone_id=zone_id,
        priority=4,  # 特急（红色）
        points_reward=15,  # 补票奖励积分
        target_count=1,
        unit="张",
        requires_photo=True,  # 需要拍照上传发票
        status=2,  # 直接指派，跳过待接单
        assignee_id=record.responsible_user_id,
    )
    db.add(task)
    await db.flush()

    # 更新欠票记录
    record.status = "reminded"
    record.reminder_count += 1
    record.last_reminder_at = datetime.now(timezone.utc)
    record.reminder_task_id = task.id

    await db.flush()

    return {
        "code": 200,
        "message": f"已向 {responsible_user.name} 发送催票任务",
        "data": {
            "missing_invoice": _serialize_missing(record),
            "task_id": task.id,
            "task_title": task.title,
        },
    }


# ═══════════════════════════════════════════════════
# 手动销账
# ═══════════════════════════════════════════════════

@router.post("/{record_id}/resolve")
async def resolve_missing_invoice(
    record_id: int,
    req: ResolveRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """
    手动销账
    管理员确认发票已补交或核销
    """
    result = await db.execute(
        select(MissingInvoiceLedger).where(MissingInvoiceLedger.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="欠票记录不存在")
    if record.status in ("received", "written_off"):
        raise HTTPException(status_code=400, detail="该欠票已核销")

    now = datetime.now(timezone.utc)

    if req.invoice_id:
        # 有补交发票 → received
        inv_result = await db.execute(select(Invoice).where(Invoice.id == req.invoice_id))
        invoice = inv_result.scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="发票不存在")
        record.status = "received"
        record.matched_invoice_id = req.invoice_id
    else:
        # 无发票核销（如供应商确认不开票）→ written_off
        record.status = "written_off"

    record.resolved_at = now
    record.resolved_by = current_user.id

    # 如果有关联的催票任务，标记为完成
    if record.reminder_task_id:
        task_result = await db.execute(select(Task).where(Task.id == record.reminder_task_id))
        task = task_result.scalar_one_or_none()
        if task and task.status != 4:
            task.status = 4
            task.reviewed_at = now

    await db.flush()

    return {
        "code": 200,
        "message": "欠票已核销",
        "data": _serialize_missing(record),
    }


# ═══════════════════════════════════════════════════
# 自动销账（发票上传后触发）
# ═══════════════════════════════════════════════════

@router.post("/auto-resolve")
async def auto_resolve(
    req: AutoResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    自动销账
    员工上传发票后，系统自动匹配未核销的欠票记录
    匹配规则：同一员工 + 金额相近（±5%）+ 状态为 pending/reminded
    """
    # 获取发票信息
    inv_result = await db.execute(select(Invoice).where(Invoice.id == req.invoice_id))
    invoice = inv_result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")

    # 查找该员工的未核销欠票
    missing_result = await db.execute(
        select(MissingInvoiceLedger).where(
            and_(
                MissingInvoiceLedger.responsible_user_id == invoice.user_id,
                MissingInvoiceLedger.status.in_(["pending", "reminded"]),
            )
        ).order_by(MissingInvoiceLedger.trade_date.desc())
    )
    pending_records = missing_result.scalars().all()

    if not pending_records:
        return {"code": 200, "message": "无匹配的欠票记录", "data": {"resolved_count": 0}}

    resolved = []
    now = datetime.now(timezone.utc)

    for record in pending_records:
        # 金额匹配（±5%容差）
        if invoice.total_amount:
            inv_amount = float(invoice.total_amount)
            record_amount = float(record.amount)
            if record_amount > 0:
                diff_pct = abs(inv_amount - record_amount) / record_amount
                if diff_pct <= 0.05:
                    # 匹配成功
                    record.status = "received"
                    record.matched_invoice_id = invoice.id
                    record.resolved_at = now
                    record.resolved_by = current_user.id

                    # 完成关联的催票任务
                    if record.reminder_task_id:
                        task_result = await db.execute(
                            select(Task).where(Task.id == record.reminder_task_id)
                        )
                        task = task_result.scalar_one_or_none()
                        if task and task.status != 4:
                            task.status = 4
                            task.reviewed_at = now

                    resolved.append(record.id)
                    break  # 一张发票只匹配一条欠票

    await db.flush()

    return {
        "code": 200,
        "message": f"自动核销 {len(resolved)} 条欠票记录",
        "data": {
            "resolved_count": len(resolved),
            "resolved_ids": resolved,
        },
    }


# ═══════════════════════════════════════════════════
# 欠票统计
# ═══════════════════════════════════════════════════

@router.get("/stats")
async def missing_invoice_stats(
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """
    欠票统计
    返回各状态的数量和金额汇总
    """
    result = await db.execute(select(MissingInvoiceLedger))
    all_records = result.scalars().all()

    stats = {
        "pending": {"count": 0, "amount": 0.0},
        "reminded": {"count": 0, "amount": 0.0},
        "received": {"count": 0, "amount": 0.0},
        "written_off": {"count": 0, "amount": 0.0},
    }

    for r in all_records:
        if r.status in stats:
            stats[r.status]["count"] += 1
            stats[r.status]["amount"] += float(r.amount)

    # 未核销总额（pending + reminded）
    outstanding_amount = stats["pending"]["amount"] + stats["reminded"]["amount"]
    outstanding_count = stats["pending"]["count"] + stats["reminded"]["count"]

    # 按责任人汇总未核销金额
    by_user = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for r in all_records:
        if r.status in ("pending", "reminded"):
            by_user[r.responsible_user_id]["count"] += 1
            by_user[r.responsible_user_id]["amount"] += float(r.amount)

    # 获取用户名
    user_ids = list(by_user.keys())
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        user_map = {u.id: u.name for u in users_result.scalars().all()}
    else:
        user_map = {}

    user_ranking = [
        {
            "user_id": uid,
            "user_name": user_map.get(uid, "未知"),
            "count": data["count"],
            "amount": round(data["amount"], 2),
        }
        for uid, data in sorted(by_user.items(), key=lambda x: -x[1]["amount"])
    ]

    return {
        "code": 200,
        "data": {
            "outstanding_count": outstanding_count,
            "outstanding_amount": round(outstanding_amount, 2),
            "by_status": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in stats.items()},
            "user_ranking": user_ranking[:10],
            "total_records": len(all_records),
        },
    }


# ═══════════════════════════════════════════════════
# 手动创建欠票记录
# ═══════════════════════════════════════════════════

@router.post("/create")
async def create_missing_invoice(
    req: MissingInvoiceCreateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """手动创建欠票记录（非报销来源的欠票）"""
    # 验证责任人存在
    user_result = await db.execute(select(User).where(User.id == req.responsible_user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="责任人不存在")

    try:
        trade_date = date.fromisoformat(req.trade_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式错误，请使用 YYYY-MM-DD")

    record = MissingInvoiceLedger(
        trade_date=trade_date,
        item_name=req.item_name,
        supplier_name=req.supplier_name,
        amount=Decimal(str(req.amount)),
        source_type="manual",
        expense_report_id=None,
        status="pending",
        responsible_user_id=req.responsible_user_id,
    )
    db.add(record)
    await db.flush()

    return {
        "code": 200,
        "message": "欠票记录创建成功",
        "data": _serialize_missing(record),
    }


# ═══════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════

STATUS_LABELS = {
    "pending": "待追票",
    "reminded": "已催票",
    "received": "已补交",
    "written_off": "已核销",
}


def _serialize_missing(r: MissingInvoiceLedger) -> dict:
    return {
        "id": r.id,
        "trade_date": r.trade_date.isoformat() if r.trade_date else None,
        "item_name": r.item_name,
        "supplier_name": r.supplier_name,
        "amount": float(r.amount) if r.amount else 0,
        "source_type": r.source_type,
        "expense_report_id": r.expense_report_id,
        "status": r.status,
        "status_label": STATUS_LABELS.get(r.status, "未知"),
        "reminder_count": r.reminder_count,
        "last_reminder_at": r.last_reminder_at.isoformat() if r.last_reminder_at else None,
        "responsible_user_id": r.responsible_user_id,
        "reminder_task_id": r.reminder_task_id,
        "matched_invoice_id": r.matched_invoice_id,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "resolved_by": r.resolved_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
