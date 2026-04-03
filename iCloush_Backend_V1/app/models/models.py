"""
iCloush 智慧工厂 — 数据库模型 (SQLAlchemy 2.0)
═══════════════════════════════════════════════════
核心表：users, zones, tasks, task_records, vehicles, iot_devices, point_ledger
"""
import enum
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, Enum, JSON,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ═══════════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════════

class TaskStatus(int, enum.Enum):
    """任务状态机"""
    PENDING = 0       # 待接单
    ACCEPTED = 1      # 已接单
    IN_PROGRESS = 2   # 进行中
    REVIEWING = 3     # 待审核
    COMPLETED = 4     # 已完成
    REJECTED = 5      # 已驳回（保留，实际用 is_rejected 标记）


class TaskType(str, enum.Enum):
    ROUTINE = "routine"      # 日常计件
    PERIODIC = "periodic"    # 周期巡检
    SPECIFIC = "specific"    # 特定任务


class ActionType(str, enum.Enum):
    START = "start"
    ACCEPT = "accept"
    COUNT = "count"
    PHOTO = "photo"
    SUBMIT = "submit"
    REVIEW_PASS = "review_pass"
    REVIEW_FAIL = "review_fail"


class ZoneType(str, enum.Enum):
    WASH = "wash"
    IRON = "iron"
    FOLD = "fold"
    LOGISTICS = "logistics"
    SORT = "sort"
    DRY_CLEAN = "dry_clean"
    HAND_WASH = "hand_wash"
    STORAGE = "storage"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════
# 员工表
# ═══════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wechat_openid: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    avatar_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 角色：1=普通员工, 3=组长, 5=主管, 7=经理, 9=超级管理员
    role: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    skill_tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    current_zones: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    is_multi_post: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 积分
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    monthly_points: Mapped[int] = mapped_column(Integer, default=0)
    task_completed: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # 关系
    assigned_tasks: Mapped[List["Task"]] = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")
    task_records: Mapped[List["TaskRecord"]] = relationship("TaskRecord", back_populates="user")
    point_ledger: Mapped[List["PointLedger"]] = relationship("PointLedger", back_populates="user")

    __table_args__ = (
        Index("ix_users_role", "role"),
    )


# ═══════════════════════════════════════════════════
# 工区表
# ═══════════════════════════════════════════════════

class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    floor: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    zone_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    pipeline_order: Mapped[int] = mapped_column(Integer, default=0)

    # 沙盘定位
    pos_left: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pos_top: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pos_width: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pos_height: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # IoT 摘要（JSON 存储，定时更新）
    iot_summary: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    iot_summary_text: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="running")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # 关系
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="zone")


# ═══════════════════════════════════════════════════
# 任务表
# ═══════════════════════════════════════════════════

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(16), default="routine")
    zone_id: Mapped[int] = mapped_column(Integer, ForeignKey("zones.id"), nullable=False)

    # 状态机：0=待接单, 1=已接单, 2=进行中, 3=待审核, 4=已完成
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1=普通, 2=重要, 3=紧急, 4=特急
    points_reward: Mapped[int] = mapped_column(Integer, default=50)

    # 计件
    target_count: Mapped[int] = mapped_column(Integer, default=1)
    current_progress: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="件")

    # 拍照
    requires_photo: Mapped[bool] = mapped_column(Boolean, default=False)

    # 负责人
    assignee_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # 驳回
    is_rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 时间戳
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # 关系
    zone: Mapped["Zone"] = relationship("Zone", back_populates="tasks")
    assignee: Mapped[Optional["User"]] = relationship("User", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    records: Mapped[List["TaskRecord"]] = relationship("TaskRecord", back_populates="task", order_by="TaskRecord.created_at.desc()")

    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_zone_id", "zone_id"),
        Index("ix_tasks_assignee_id", "assignee_id"),
    )


# ═══════════════════════════════════════════════════
# 执行流水表（极度重要）
# ═══════════════════════════════════════════════════

class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(16), nullable=False)  # start/accept/count/photo/submit/review_pass/review_fail

    delta_count: Mapped[int] = mapped_column(Integer, default=0)
    photo_urls: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # 关系
    task: Mapped["Task"] = relationship("Task", back_populates="records")
    user: Mapped["User"] = relationship("User", back_populates="task_records")

    __table_args__ = (
        Index("ix_task_records_task_id", "task_id"),
        Index("ix_task_records_user_id", "user_id"),
    )


# ═══════════════════════════════════════════════════
# 车辆表
# ═══════════════════════════════════════════════════

class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="in")  # in/out
    driver_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    load_current: Mapped[int] = mapped_column(Integer, default=0)
    load_max: Mapped[int] = mapped_column(Integer, default=60)
    unit: Mapped[str] = mapped_column(String(8), default="袋")
    last_update: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


# ═══════════════════════════════════════════════════
# IoT 设备表
# ═══════════════════════════════════════════════════

class IoTDevice(Base):
    __tablename__ = "iot_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_id: Mapped[int] = mapped_column(Integer, ForeignKey("zones.id"), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running")
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    chemical_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cycle_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    alerts: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_iot_devices_zone_id", "zone_id"),
    )


# ═══════════════════════════════════════════════════
# 积分账本
# ═══════════════════════════════════════════════════

class PointLedger(Base):
    __tablename__ = "point_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="point_ledger")

    __table_args__ = (
        Index("ix_point_ledger_user_id", "user_id"),
    )


# ═══════════════════════════════════════════════════
# 积分商城
# ═══════════════════════════════════════════════════

class MallItem(Base):
    __tablename__ = "mall_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


# ═══════════════════════════════════════════════════
# 每日产能
# ═══════════════════════════════════════════════════

class DailyProduction(Base):
    __tablename__ = "daily_production"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    total_sets: Mapped[int] = mapped_column(Integer, default=0)
    worker_count: Mapped[int] = mapped_column(Integer, default=0)
    work_hours: Mapped[float] = mapped_column(Float, default=8.0)
    efficiency_kpi: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
