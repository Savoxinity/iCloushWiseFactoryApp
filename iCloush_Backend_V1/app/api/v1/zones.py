"""
工区路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Zone, Task, User

router = APIRouter()


@router.get("/")
async def list_zones(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取全部工区（含在岗人数统计）"""
    result = await db.execute(select(Zone).order_by(Zone.pipeline_order))
    zones = result.scalars().all()

    # 统计每个工区在岗人数
    all_users_result = await db.execute(select(User).where(User.is_active == True))
    all_users = all_users_result.scalars().all()

    zone_staff_count = {}
    for u in all_users:
        for zc in (u.current_zones or []):
            zone_staff_count[zc] = zone_staff_count.get(zc, 0) + 1

    data = []
    for z in zones:
        data.append({
            "id": z.id,
            "name": z.name,
            "code": z.code,
            "floor": z.floor,
            "color": z.color,
            "zone_type": z.zone_type,
            "capacity": z.capacity,
            "pipeline_order": z.pipeline_order,
            "pos_left": z.pos_left,
            "pos_top": z.pos_top,
            "pos_width": z.pos_width,
            "pos_height": z.pos_height,
            "iot_summary": z.iot_summary,
            "iot_summary_text": z.iot_summary_text,
            "status": z.status,
            "staff_count": zone_staff_count.get(z.code, 0),
        })

    return {"code": 200, "data": data}


@router.get("/{zone_id}")
async def get_zone(
    zone_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单个工区详情"""
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="工区不存在")

    # 该工区的任务统计
    task_result = await db.execute(
        select(func.count()).select_from(Task).where(Task.zone_id == zone_id)
    )
    task_count = task_result.scalar() or 0

    return {
        "code": 200,
        "data": {
            "id": zone.id,
            "name": zone.name,
            "code": zone.code,
            "floor": zone.floor,
            "zone_type": zone.zone_type,
            "capacity": zone.capacity,
            "status": zone.status,
            "task_count": task_count,
        },
    }
