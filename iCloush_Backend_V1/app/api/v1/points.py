"""
积分路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import PointLedger, User

router = APIRouter()


@router.get("/my")
async def my_points(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户积分信息"""
    result = await db.execute(
        select(PointLedger)
        .where(PointLedger.user_id == current_user.id)
        .order_by(PointLedger.created_at.desc())
        .limit(50)
    )
    records = result.scalars().all()

    return {
        "code": 200,
        "data": {
            "total_points": current_user.total_points,
            "monthly_points": current_user.monthly_points,
            "task_completed": current_user.task_completed,
            "history": [
                {
                    "id": r.id,
                    "delta": r.delta,
                    "reason": r.reason,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ],
        },
    }

@router.get("/summary")
async def points_summary(
    current_user: User = Depends(get_current_user),
):
    """积分摘要（兼容前端 /points/summary）"""
    return {
        "code": 200,
        "data": {
            "total_points": current_user.total_points,
            "monthly_points": current_user.monthly_points,
            "task_completed": current_user.task_completed,
        },
    }


@router.get("/ledger")
async def points_ledger(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """积分流水（兼容前端 /points/ledger）"""
    result = await db.execute(
        select(PointLedger)
        .where(PointLedger.user_id == current_user.id)
        .order_by(PointLedger.created_at.desc())
        .limit(50)
    )
    records = result.scalars().all()
    return {
        "code": 200,
        "data": [
            {
                "id": r.id,
                "delta": r.delta,
                "reason": r.reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ],
    }
