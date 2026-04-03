"""
积分商城路由
═══════════════════════════════════════════════════
修复：
  BUG-01  新增 POST /exchange 路由（前端调用 /api/v1/mall/exchange，body: {item_id}）
  BUG-02  修复兑换记录返回格式，包含 name/icon/points_cost/status 字段
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import MallItem, User, PointLedger

router = APIRouter()


class ExchangeRequest(BaseModel):
    item_id: int


@router.get("/items")
async def list_items(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MallItem).order_by(MallItem.points_cost))
    items = result.scalars().all()
    return {
        "code": 200,
        "data": [
            {
                "id": i.id,
                "name": i.name,
                "category": i.category,
                "points_cost": i.points_cost,
                "stock": i.stock,
                "description": i.description,
                "icon": i.icon,
            }
            for i in items
        ],
    }


@router.post("/exchange")
async def exchange_item(
    req: ExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    兑换商品 — 前端调用 POST /api/v1/mall/exchange  body: { item_id: int }
    """
    result = await db.execute(select(MallItem).where(MallItem.id == req.item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在")
    if item.stock <= 0:
        raise HTTPException(status_code=400, detail="库存不足")
    if current_user.total_points < item.points_cost:
        raise HTTPException(status_code=400, detail="积分不足")

    current_user.total_points -= item.points_cost
    item.stock -= 1

    # 记录积分流水，reason 中编码商品信息以便兑换记录查询
    ledger = PointLedger(
        user_id=current_user.id,
        delta=-item.points_cost,
        reason=f"兑换商品：{item.name}||{item.icon}||{item.points_cost}",
    )
    db.add(ledger)
    await db.flush()

    return {"code": 200, "message": f"兑换成功：{item.name}"}


@router.post("/redeem/{item_id}")
async def redeem_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """兑换商品（旧路由，保持兼容）"""
    result = await db.execute(select(MallItem).where(MallItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在")
    if item.stock <= 0:
        raise HTTPException(status_code=400, detail="库存不足")
    if current_user.total_points < item.points_cost:
        raise HTTPException(status_code=400, detail="积分不足")

    current_user.total_points -= item.points_cost
    item.stock -= 1

    ledger = PointLedger(
        user_id=current_user.id,
        delta=-item.points_cost,
        reason=f"兑换商品：{item.name}||{item.icon}||{item.points_cost}",
    )
    db.add(ledger)
    await db.flush()

    return {"code": 200, "message": f"兑换成功：{item.name}"}


@router.get("/records")
async def exchange_records(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    兑换记录 — 前端调用 GET /api/v1/exchange/records
    从 PointLedger 中筛选兑换记录（delta < 0 且 reason 包含 '兑换商品'）
    返回前端需要的 name / icon / points_cost / status 字段
    """
    result = await db.execute(
        select(PointLedger)
        .where(
            PointLedger.user_id == current_user.id,
            PointLedger.delta < 0,
            PointLedger.reason.like("兑换商品%"),
        )
        .order_by(PointLedger.created_at.desc())
        .limit(50)
    )
    records = result.scalars().all()

    data = []
    for r in records:
        # reason 格式: "兑换商品：{name}||{icon}||{points_cost}"
        name = "未知商品"
        icon = "🎁"
        points_cost = abs(r.delta)
        try:
            parts = r.reason.split("：", 1)
            if len(parts) > 1:
                info_parts = parts[1].split("||")
                if len(info_parts) >= 3:
                    name = info_parts[0]
                    icon = info_parts[1]
                    points_cost = int(info_parts[2])
                elif len(info_parts) == 1:
                    name = info_parts[0]
        except Exception:
            pass

        data.append({
            "id": r.id,
            "name": name,
            "icon": icon,
            "points_cost": points_cost,
            "status": "completed",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"code": 200, "data": data}
