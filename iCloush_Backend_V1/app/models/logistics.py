"""
iCloush 智慧工厂 — 机动物流中台数据模型
═══════════════════════════════════════════════════
Phase 4: Vehicle Fleet Management / Route Planning / Dispatching

三表：
  1. Vehicle          — 车辆台账（含四险一金倒计时）
  2. DeliveryRoute    — 送货排线
  3. LogisticsDispatch — 出车调度单（车-线-人 三位一体）

所有表使用 SQLAlchemy 2.0 Mapped 风格，与 models.py / finance.py 保持一致。
"""
import enum
from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, Date,
    JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════════

class VehicleStatus(str, enum.Enum):
    """车辆状态"""
    IDLE = "idle"                 # 待命
    DELIVERING = "delivering"     # 运送中
    MAINTENANCE = "maintenance"   # 维修/保养中


class VehicleType(str, enum.Enum):
    """车型"""
    LARGE = "large"       # 大厢式货车
    MEDIUM = "medium"     # 中厢式货车
    SMALL = "small"       # 小厢式货车


class DispatchStatus(str, enum.Enum):
    """出车单状态"""
    PENDING = "pending"         # 待出车
    DELIVERING = "delivering"   # 运送中
    COMPLETED = "completed"     # 已完成
    CANCELLED = "cancelled"     # 已取消


# ═══════════════════════════════════════════════════
# 1. 车辆台账 (Vehicle Fleet)
# ═══════════════════════════════════════════════════

class VehicleFleet(Base):
    """
    车辆台账 — 管理车辆全生命周期
    注意：使用 vehicle_fleet 表名，避免与现有 vehicles 表冲突。
    现有 vehicles 表保留用于沙盘实时状态，本表用于车辆资产管理。
    """
    __tablename__ = "vehicle_fleet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 基本信息 ──
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    vehicle_type: Mapped[str] = mapped_column(String(20), default="medium")
    # large / medium / small
    brand: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)       # 品牌型号
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)       # 车身颜色
    vin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)         # 车架号

    # ── 里程 ──
    mileage: Mapped[int] = mapped_column(Integer, default=0)                      # 当前里程数(km)

    # ── 四险一金倒计时（核心痛点） ──
    inspection_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)       # 年检到期日
    compulsory_ins_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)   # 交强险到期日
    commercial_ins_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)   # 商业险到期日
    maintenance_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)      # 常规保养到期日

    # ── 载重 ──
    load_capacity: Mapped[int] = mapped_column(Integer, default=60)               # 最大载重(袋)
    load_unit: Mapped[str] = mapped_column(String(8), default="袋")

    # ── 状态 ──
    status: Mapped[str] = mapped_column(String(20), default="idle")
    # idle / delivering / maintenance

    # ── 关联现有 vehicles 表的 id（可选，用于沙盘联动） ──
    legacy_vehicle_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vehicles.id"), nullable=True
    )

    # ── GPS 预留字段 ──
    gps_device_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)   # GPS设备编号
    last_gps_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_gps_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_gps_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── 备注 ──
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # ── 关系 ──
    dispatches: Mapped[list["LogisticsDispatch"]] = relationship(
        "LogisticsDispatch", back_populates="vehicle"
    )

    __table_args__ = (
        Index("ix_vehicle_fleet_status", "status"),
    )


# ═══════════════════════════════════════════════════
# 2. 送货排线 (Delivery Route)
# ═══════════════════════════════════════════════════

class DeliveryRoute(Base):
    """
    送货排线 — 固化的客户节点与标准时效(SLA)
    stops 字段为 JSON 数组，每个元素：
    {
        "seq": 1,
        "client_name": "珀丽酒店",
        "address": "浦东新区xx路xx号",
        "expected_eta": "09:30",
        "contact_phone": "13800138000",
        "remark": "后门卸货"
    }
    """
    __tablename__ = "delivery_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    route_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 如 "市区南线-早班", "郊区北线-午班"

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 途经站点（JSON 数组）
    stops: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # 预计总时长(分钟)
    estimated_duration_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 预计总里程(km)
    estimated_distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # ── 关系 ──
    dispatches: Mapped[list["LogisticsDispatch"]] = relationship(
        "LogisticsDispatch", back_populates="route"
    )


# ═══════════════════════════════════════════════════
# 3. 出车调度单 (Logistics Dispatch)
# ═══════════════════════════════════════════════════

class LogisticsDispatch(Base):
    """
    出车调度单 — 车-线-人 三位一体
    每次出车生成一条记录，关联：
      - 哪辆车 (vehicle_id)
      - 走哪条线 (route_id)
      - 谁开车 (driver_id)
      - 谁跟车 (assistant_id, 可选)
      - 哪天 (work_date)

    stop_checkins 字段记录司机到达每个站点的实际打卡时间：
    [
        {"seq": 1, "client_name": "珀丽酒店", "checked_in_at": "2026-04-03T09:35:00"},
        {"seq": 2, "client_name": "希尔顿", "checked_in_at": null}
    ]
    """
    __tablename__ = "logistics_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 出车日期 ──
    work_date: Mapped[date] = mapped_column(Date, nullable=False)

    # ── 三位一体关联 ──
    vehicle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vehicle_fleet.id"), nullable=False
    )
    route_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("delivery_routes.id"), nullable=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    assistant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending / delivering / completed / cancelled

    # ── 站点打卡记录（JSON） ──
    stop_checkins: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # ── 出发/返回时间 ──
    departed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── 实际里程 ──
    actual_mileage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── 备注 ──
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # ── 关系 ──
    vehicle: Mapped["VehicleFleet"] = relationship("VehicleFleet", back_populates="dispatches")
    route: Mapped[Optional["DeliveryRoute"]] = relationship("DeliveryRoute", back_populates="dispatches")

    __table_args__ = (
        Index("ix_dispatch_work_date", "work_date"),
        Index("ix_dispatch_vehicle", "vehicle_id"),
        Index("ix_dispatch_driver", "driver_id"),
        Index("ix_dispatch_status", "status"),
    )
