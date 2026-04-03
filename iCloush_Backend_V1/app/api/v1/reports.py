"""
报表路由
═══════════════════════════════════════════════════
修复：
  BUG-10  DailyProductionCreate.efficiency_kpi 改为 Optional，后端自动计算
  BUG-14  /summary 返回前端需要的完整字段（total_output, done_tasks, running_tasks,
          rejected_tasks, pending_tasks, avg_efficiency, zone_ranking, staff_ranking）
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.security import require_role, get_current_user
from app.models.models import DailyProduction, User, Task, Zone
from pydantic import BaseModel


router = APIRouter()


class DailyProductionCreate(BaseModel):
    date: str
    total_sets: int
    worker_count: int
    work_hours: float
    efficiency_kpi: Optional[float] = None   # ← 改为 Optional，前端不传则自动计算


@router.post("/daily")
async def create_daily_production(
    req: DailyProductionCreate,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """提交每日产能数据"""
    # 自动计算 KPI（套/人·时）
    kpi = req.efficiency_kpi
    if kpi is None and req.worker_count > 0 and req.work_hours > 0:
        kpi = round(req.total_sets / (req.worker_count * req.work_hours), 1)
    elif kpi is None:
        kpi = 0.0

    # 检查是否已有当日记录（upsert）
    existing = await db.execute(
        select(DailyProduction).where(DailyProduction.date == req.date)
    )
    record = existing.scalar_one_or_none()

    if record:
        record.total_sets = req.total_sets
        record.worker_count = req.worker_count
        record.work_hours = req.work_hours
        record.efficiency_kpi = kpi
    else:
        record = DailyProduction(
            date=req.date,
            total_sets=req.total_sets,
            worker_count=req.worker_count,
            work_hours=req.work_hours,
            efficiency_kpi=kpi,
        )
        db.add(record)

    await db.flush()
    return {"code": 200, "message": "产能数据提交成功"}


@router.get("/daily")
async def daily_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取每日产能报表"""
    result = await db.execute(
        select(DailyProduction).order_by(DailyProduction.date.desc()).limit(30)
    )
    records = result.scalars().all()

    return {
        "code": 200,
        "data": [
            {
                "date": r.date,
                "total_sets": r.total_sets,
                "worker_count": r.worker_count,
                "work_hours": r.work_hours,
                "efficiency_kpi": r.efficiency_kpi,
            }
            for r in records
        ],
    }


@router.get("/summary")
async def report_summary(
    dim: str = "day",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    报表汇总 — 前端调用 GET /api/v1/reports/summary?dim=day|week|month
    返回前端需要的完整字段：
      total_output, done_tasks, running_tasks, rejected_tasks, pending_tasks,
      avg_efficiency, zone_ranking, staff_ranking
    """
    # ── 1. 任务统计 ──
    tasks_result = await db.execute(select(Task))
    all_tasks = tasks_result.scalars().all()

    done_tasks = sum(1 for t in all_tasks if t.status == 4)
    running_tasks = sum(1 for t in all_tasks if t.status == 2)
    pending_tasks = sum(1 for t in all_tasks if t.status in (0, 1))
    rejected_tasks = sum(1 for t in all_tasks if t.status == 5 or t.is_rejected)

    # ── 2. 产能数据 ──
    limit_days = {"day": 1, "week": 7, "month": 30}.get(dim, 1)
    prod_result = await db.execute(
        select(DailyProduction)
        .order_by(DailyProduction.date.desc())
        .limit(limit_days)
    )
    prod_records = prod_result.scalars().all()

    total_output = sum(r.total_sets for r in prod_records) if prod_records else 0
    avg_efficiency = (
        round(sum(r.efficiency_kpi for r in prod_records) / len(prod_records), 1)
        if prod_records
        else 0
    )

    # ── 3. 工区排名（按完成任务数） ──
    zones_result = await db.execute(select(Zone))
    all_zones = zones_result.scalars().all()
    zone_map = {z.id: z for z in all_zones}

    zone_task_count = {}
    for t in all_tasks:
        if t.status == 4:  # 已完成
            zone_task_count[t.zone_id] = zone_task_count.get(t.zone_id, 0) + 1

    zone_ranking = []
    for zone_id, count in sorted(zone_task_count.items(), key=lambda x: -x[1]):
        zone = zone_map.get(zone_id)
        if zone:
            zone_ranking.append({
                "zone_id": zone.id,
                "zone_name": zone.name,
                "count": count,
                "color": zone.color or "#3B82F6",
            })

    # ── 4. 员工排名（按完成任务数） ──
    user_task_count = {}
    for t in all_tasks:
        if t.status == 4 and t.assignee_id:
            user_task_count[t.assignee_id] = user_task_count.get(t.assignee_id, 0) + 1

    users_result = await db.execute(select(User))
    all_users = users_result.scalars().all()
    user_map = {u.id: u for u in all_users}

    staff_ranking = []
    for uid, count in sorted(user_task_count.items(), key=lambda x: -x[1]):
        user = user_map.get(uid)
        if user:
            # 获取用户所在工区名称
            user_zone_names = []
            for zc in (user.current_zones or []):
                for z in all_zones:
                    if z.code == zc:
                        user_zone_names.append(z.name)
                        break

            staff_ranking.append({
                "staff_id": user.id,
                "name": user.name,
                "zone_name": user_zone_names[0] if user_zone_names else "未分配",
                "done_count": count,
                "points_earned": user.total_points,
                "avatarColor": "#3B82F6",
                "initial": user.name[0] if user.name else "?",
            })

    return {
        "code": 200,
        "data": {
            "total_output": total_output,
            "done_tasks": done_tasks,
            "running_tasks": running_tasks,
            "rejected_tasks": rejected_tasks,
            "pending_tasks": pending_tasks,
            "avg_efficiency": avg_efficiency,
            "zone_ranking": zone_ranking,
            "staff_ranking": staff_ranking[:10],  # 最多返回前 10 名
        },
    }
