"""
任务路由 — RBAC 工区隔离 + 任务状态机引擎
═══════════════════════════════════════════════════
修复清单：
  BUG-1  POST / 创建任务 500 — 前端发 target / assigned_to / zone_name
         后端 TaskCreateRequest 用的是 target_count / assignee_id，无 zone_name
         → 字段对齐前端，兼容两种写法
  BUG-2  POST /{id}/edit — TaskEditRequest 同样缺少 target / assigned_to / zone_name
         → 字段对齐前端
  BUG-3  _serialize_task 缺少 target / assigned_to 字段
         前端 task-edit 需要这些字段
         → 补齐返回字段
  BUG-4  create_task 权限 require_role(5) 过高
         前端 task-create 允许 role>=3（班组长）
         → 降低为 require_role(3)
"""
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import Task, TaskRecord, User, Zone

router = APIRouter()


# ── Schemas（与前端字段完全对齐） ──────────────────

class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str = "routine"
    zone_id: int
    zone_name: Optional[str] = None       # 前端会发，后端忽略即可
    priority: int = 2
    points_reward: int = 50
    target_count: Optional[int] = None     # 后端原字段
    target: Optional[int] = None           # 前端发 target
    unit: str = "件"
    requires_photo: bool = False
    assignee_id: Optional[int] = None      # 后端原字段
    assigned_to: Optional[List[int]] = None  # 前端发 assigned_to（数组）
    deadline: Optional[str] = None


class TaskEditRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    zone_id: Optional[int] = None
    zone_name: Optional[str] = None        # 前端会发，后端忽略
    priority: Optional[int] = None
    points_reward: Optional[int] = None
    target_count: Optional[int] = None
    target: Optional[int] = None           # 前端发 target
    unit: Optional[str] = None
    requires_photo: Optional[bool] = None
    assignee_id: Optional[int] = None
    assigned_to: Optional[List[int]] = None  # 前端发 assigned_to（数组）
    deadline: Optional[str] = None
    status: Optional[int] = None


class CountRequest(BaseModel):
    delta: int = 1


class SubmitRequest(BaseModel):
    photo_urls: List[str] = []
    remark: Optional[str] = None


class ReviewRequest(BaseModel):
    result: str  # "pass" | "fail"
    remark: Optional[str] = None


# ── 任务统计 ────────────────────────────────────

@router.get("/stats")
async def task_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    任务统计（与前端 loadTaskStats 对齐）
    - role=1 员工：只统计自己工区的任务
    - role>=5 管理员：统计全厂任务
    """
    query = select(Task)

    # RBAC 工区隔离
    if current_user.role < 5:
        user_zones = current_user.current_zones or []
        if not user_zones:
            return {"code": 200, "data": {"total": 0, "pending": 0, "running": 0, "reviewing": 0, "done": 0}}
        zone_result = await db.execute(select(Zone).where(Zone.code.in_(user_zones)))
        accessible_zones = zone_result.scalars().all()
        zone_ids = [z.id for z in accessible_zones]
        if not zone_ids:
            return {"code": 200, "data": {"total": 0, "pending": 0, "running": 0, "reviewing": 0, "done": 0}}
        query = query.where(Task.zone_id.in_(zone_ids))

    result = await db.execute(query)
    tasks = result.scalars().all()

    total = len(tasks)
    pending = sum(1 for t in tasks if t.status == 0)
    running = sum(1 for t in tasks if t.status in (1, 2))
    reviewing = sum(1 for t in tasks if t.status == 3)
    done = sum(1 for t in tasks if t.status == 4)

    return {
        "code": 200,
        "data": {
            "total": total,
            "pending": pending,
            "running": running,
            "reviewing": reviewing,
            "done": done,
        },
    }


# ── 任务列表（RBAC 工区隔离） ──────────────────

@router.get("/")
async def list_tasks(
    status: Optional[int] = Query(None),
    task_type: Optional[str] = Query(None),
    zone_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取任务列表
    - role=1 员工：只返回 current_zones 内的任务
    - role>=5 管理员：返回全厂任务
    """
    query = select(Task).options(
        selectinload(Task.zone),
        selectinload(Task.assignee),
    )

    # RBAC 工区隔离
    if current_user.role < 5:
        user_zones = current_user.current_zones or []
        if not user_zones:
            return {"code": 200, "data": [], "total": 0}
        # 通过 zone_code 匹配 zone_id
        zone_result = await db.execute(select(Zone).where(Zone.code.in_(user_zones)))
        accessible_zones = zone_result.scalars().all()
        zone_ids = [z.id for z in accessible_zones]
        if not zone_ids:
            return {"code": 200, "data": [], "total": 0}
        query = query.where(Task.zone_id.in_(zone_ids))

    # 可选筛选
    if status is not None:
        query = query.where(Task.status == status)
    if task_type:
        query = query.where(Task.task_type == task_type)
    if zone_id:
        query = query.where(Task.zone_id == zone_id)

    query = query.order_by(Task.priority.desc(), Task.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()

    return {
        "code": 200,
        "data": [_serialize_task(t) for t in tasks],
        "total": len(tasks),
    }


# ── 任务详情 ─────────────────────────────────────

@router.get("/{task_id}")
async def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task_or_404(task_id, db)
    return {"code": 200, "data": _serialize_task(task)}

@router.get("/{task_id}/records")
async def get_task_records(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取任务执行记录"""
    result = await db.execute(
        select(TaskRecord)
        .where(TaskRecord.task_id == task_id)
        .order_by(TaskRecord.created_at.desc())
    )
    records = result.scalars().all()

    return {
        "code": 200,
        "data": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "user_id": r.user_id,
                "action_type": r.action_type,
                "delta_count": r.delta_count,
                "photo_urls": r.photo_urls,
                "remark": r.remark,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


# ── 接单 ─────────────────────────────────────────

@router.post("/{task_id}/accept")
async def accept_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """接单：status 0 → 2，绑定 assignee"""
    task = await _get_task_or_404(task_id, db)

    if task.status != 0:
        raise HTTPException(status_code=400, detail="该任务不在待接单状态")

    task.status = 2
    task.assignee_id = current_user.id
    task.accepted_at = datetime.now(timezone.utc)

    # 记录流水
    record = TaskRecord(
        task_id=task_id,
        user_id=current_user.id,
        action_type="accept",
        remark=f"{current_user.name} 接单",
    )
    db.add(record)
    await db.flush()

    return {"code": 200, "message": "接单成功", "data": _serialize_task(task)}


# ── 计件 ─────────────────────────────────────────

@router.post("/{task_id}/count")
async def count_task(
    task_id: int,
    req: CountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """计件：累加进度"""
    task = await _get_task_or_404(task_id, db)

    if task.status != 2:
        raise HTTPException(status_code=400, detail="任务不在进行中状态")
    if task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="你不是该任务的负责人")

    task.current_progress = min(task.current_progress + req.delta, task.target_count)

    record = TaskRecord(
        task_id=task_id,
        user_id=current_user.id,
        action_type="count",
        delta_count=req.delta,
        remark=f"计件 +{req.delta}",
    )
    db.add(record)
    await db.flush()

    return {
        "code": 200,
        "message": "计件成功",
        "data": {"progress": task.current_progress, "target": task.target_count},
    }


# ── 提交审核 ─────────────────────────────────────

@router.post("/{task_id}/submit")
async def submit_task(
    task_id: int,
    req: SubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交审核：status 2 → 3"""
    task = await _get_task_or_404(task_id, db)

    if task.status != 2:
        raise HTTPException(status_code=400, detail="任务不在进行中状态")
    if task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="你不是该任务的负责人")

    task.status = 3
    task.is_rejected = False
    task.submitted_at = datetime.now(timezone.utc)

    record = TaskRecord(
        task_id=task_id,
        user_id=current_user.id,
        action_type="submit",
        photo_urls=req.photo_urls,
        remark=req.remark or "提交审核",
    )
    db.add(record)
    await db.flush()

    return {"code": 200, "message": "已提交审核", "data": _serialize_task(task)}


# ── 审核 ─────────────────────────────────────────

@router.post("/{task_id}/review")
async def review_task(
    task_id: int,
    req: ReviewRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """审核：pass → 3→4，fail → 3→2 + is_rejected"""
    task = await _get_task_or_404(task_id, db)

    if task.status != 3:
        raise HTTPException(status_code=400, detail="任务不在待审核状态")

    now = datetime.now(timezone.utc)

    if req.result == "pass":
        task.status = 4
        task.reviewed_at = now
        task.is_rejected = False
        action_type = "review_pass"

        # 加积分
        if task.assignee_id:
            assignee_result = await db.execute(select(User).where(User.id == task.assignee_id))
            assignee = assignee_result.scalar_one_or_none()
            if assignee:
                assignee.total_points += task.points_reward
                assignee.monthly_points += task.points_reward
                assignee.task_completed += 1

    elif req.result == "fail":
        task.status = 2
        task.is_rejected = True
        task.reject_reason = req.remark
        task.rejected_at = now
        action_type = "review_fail"
    else:
        raise HTTPException(status_code=400, detail="result 必须为 pass 或 fail")

    record = TaskRecord(
        task_id=task_id,
        user_id=current_user.id,
        action_type=action_type,
        remark=req.remark or ("审核通过" if req.result == "pass" else "审核驳回"),
    )
    db.add(record)
    await db.flush()

    return {"code": 200, "message": "审核完成", "data": _serialize_task(task)}


# ── 创建任务（班组长及以上） ───────────────────────────

@router.post("/")
async def create_task(
    req: TaskCreateRequest,
    current_user: User = Depends(require_role(3)),   # ← 前端允许 role>=3
    db: AsyncSession = Depends(get_db),
):
    """创建任务"""
    # 兼容前端 target / assigned_to 字段
    actual_target = req.target_count or req.target or 1
    actual_assignee = None
    if req.assignee_id:
        actual_assignee = req.assignee_id
    elif req.assigned_to and len(req.assigned_to) > 0:
        actual_assignee = req.assigned_to[0]  # 取第一个

    task = Task(
        title=req.title,
        description=req.description,
        task_type=req.task_type,
        zone_id=req.zone_id,
        priority=req.priority,
        points_reward=req.points_reward,
        target_count=actual_target,
        unit=req.unit,
        requires_photo=req.requires_photo,
        status=0 if not actual_assignee else 2,
        assignee_id=actual_assignee,
    )
    if req.deadline:
        try:
            task.deadline = datetime.fromisoformat(req.deadline)
        except ValueError:
            pass  # 忽略无效日期

    db.add(task)
    await db.flush()

    return {"code": 200, "message": "任务创建成功", "data": {"id": task.id}}

@router.post("/{task_id}/edit")
async def edit_task(
    task_id: int,
    req: TaskEditRequest,
    current_user: User = Depends(require_role(3)),   # ← 前端允许 role>=3
    db: AsyncSession = Depends(get_db),
):
    """编辑任务（班组长及以上）"""
    task = await _get_task_or_404(task_id, db)

    # 只更新前端传入的非 None 字段
    update_fields = req.model_dump(exclude_none=True)

    # 处理前端 target → 后端 target_count
    if "target" in update_fields:
        task.target_count = update_fields.pop("target")
    if "target_count" in update_fields:
        task.target_count = update_fields.pop("target_count")

    # 处理前端 assigned_to → 后端 assignee_id
    if "assigned_to" in update_fields:
        assigned = update_fields.pop("assigned_to")
        if isinstance(assigned, list) and len(assigned) > 0:
            task.assignee_id = assigned[0]
        elif isinstance(assigned, int):
            task.assignee_id = assigned

    # 忽略 zone_name（前端会发但数据库不存储）
    update_fields.pop("zone_name", None)

    for field, value in update_fields.items():
        if field == "deadline" and value:
            try:
                setattr(task, field, datetime.fromisoformat(value))
            except ValueError:
                pass
        elif hasattr(task, field):
            setattr(task, field, value)

    await db.flush()

    return {"code": 200, "message": "任务修改成功", "data": _serialize_task(task)}


# ── 工具函数 ─────────────────────────────────────

async def _get_task_or_404(task_id: int, db: AsyncSession) -> Task:
    result = await db.execute(
        select(Task).options(
            selectinload(Task.zone),
            selectinload(Task.assignee),
            selectinload(Task.records),
        ).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _serialize_task(task: Task) -> dict:
    STATUS_MAP = {0: "待接单", 1: "已接单", 2: "进行中", 3: "待审核", 4: "已完成", 5: "已驳回"}
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "zone_id": task.zone_id,
        "zone_name": task.zone.name if task.zone else None,
        "zone_code": task.zone.code if task.zone else None,
        "status": task.status,
        "status_label": STATUS_MAP.get(task.status, "未知"),
        "priority": task.priority,
        "points_reward": task.points_reward,
        "target_count": task.target_count,
        "target": task.target_count,          # 前端 task-edit 读 target
        "current_progress": task.current_progress,
        "unit": task.unit,
        "requires_photo": task.requires_photo,
        "assignee_id": task.assignee_id,
        "assigned_to": task.assignee_id,      # 前端 task-edit 读 assigned_to
        "assignee_name": task.assignee.name if task.assignee else None,
        "is_rejected": task.is_rejected,
        "reject_reason": task.reject_reason,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
