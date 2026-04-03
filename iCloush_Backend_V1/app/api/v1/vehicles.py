"""
机动物流中台路由 — Phase 4 TMS (Transport Management System)
═══════════════════════════════════════════════════
功能模块：
  A. 车辆台账 CRUD + 四险一金预警
  B. 送货排线管理
  C. 出车调度单（车-线-人 三位一体）
  D. 仪表盘统计

接口清单：
  ── 车辆台账 ──
  GET    /fleet/list          车辆列表（支持状态筛选）
  GET    /fleet/{id}          车辆详情
  POST   /fleet/create        新增车辆（管理员）
  PUT    /fleet/{id}          编辑车辆（管理员）
  DELETE /fleet/{id}          删除车辆（管理员）
  GET    /fleet/alerts        四险一金预警列表

  ── 送货排线 ──
  GET    /routes/list         排线列表
  GET    /routes/{id}         排线详情
  POST   /routes/create       新增排线（管理员）
  PUT    /routes/{id}         编辑排线（管理员）
  DELETE /routes/{id}         删除排线（管理员）

  ── 出车调度 ──
  GET    /dispatch/list       调度单列表（按日期）
  GET    /dispatch/{id}       调度单详情
  POST   /dispatch/create     创建调度单（管理员）
  PUT    /dispatch/{id}/depart   出发打卡
  PUT    /dispatch/{id}/checkin  站点打卡
  PUT    /dispatch/{id}/return   返回打卡
  PUT    /dispatch/{id}/cancel   取消调度单

  ── 仪表盘 ──
  GET    /dashboard           物流仪表盘统计
"""
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import User, Vehicle
from app.models.logistics import (
    VehicleFleet, DeliveryRoute, LogisticsDispatch,
)

router = APIRouter()


# ═══════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════

# ── 车辆台账 ──

class VehicleFleetCreateRequest(BaseModel):
    plate_number: str = Field(..., min_length=1, max_length=20, description="车牌号")
    vehicle_type: str = Field(default="medium", description="车型: large/medium/small")
    brand: Optional[str] = Field(default=None, description="品牌型号")
    color: Optional[str] = Field(default=None, description="车身颜色")
    vin: Optional[str] = Field(default=None, description="车架号")
    mileage: int = Field(default=0, ge=0, description="当前里程(km)")
    inspection_due: Optional[str] = Field(default=None, description="年检到期日 YYYY-MM-DD")
    compulsory_ins_due: Optional[str] = Field(default=None, description="交强险到期日")
    commercial_ins_due: Optional[str] = Field(default=None, description="商业险到期日")
    maintenance_due: Optional[str] = Field(default=None, description="保养到期日")
    load_capacity: int = Field(default=60, ge=1, description="最大载重(袋)")
    load_unit: str = Field(default="袋")
    gps_device_id: Optional[str] = Field(default=None)
    remark: Optional[str] = Field(default=None)


class VehicleFleetUpdateRequest(BaseModel):
    plate_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None
    vin: Optional[str] = None
    mileage: Optional[int] = None
    inspection_due: Optional[str] = None
    compulsory_ins_due: Optional[str] = None
    commercial_ins_due: Optional[str] = None
    maintenance_due: Optional[str] = None
    load_capacity: Optional[int] = None
    load_unit: Optional[str] = None
    status: Optional[str] = None
    gps_device_id: Optional[str] = None
    remark: Optional[str] = None
    is_active: Optional[bool] = None


# ── 送货排线 ──

class RouteStopSchema(BaseModel):
    seq: int
    client_name: str
    address: Optional[str] = None
    expected_eta: Optional[str] = None
    contact_phone: Optional[str] = None
    remark: Optional[str] = None


class RouteCreateRequest(BaseModel):
    route_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    stops: List[RouteStopSchema] = Field(default_factory=list)
    estimated_duration_min: Optional[int] = None
    estimated_distance_km: Optional[float] = None


class RouteUpdateRequest(BaseModel):
    route_name: Optional[str] = None
    description: Optional[str] = None
    stops: Optional[List[RouteStopSchema]] = None
    estimated_duration_min: Optional[int] = None
    estimated_distance_km: Optional[float] = None
    is_active: Optional[bool] = None


# ── 出车调度 ──

class DispatchCreateRequest(BaseModel):
    work_date: str = Field(..., description="出车日期 YYYY-MM-DD")
    vehicle_id: int
    route_id: Optional[int] = None
    driver_id: int
    assistant_id: Optional[int] = None
    remark: Optional[str] = None


class CheckinRequest(BaseModel):
    stop_seq: int = Field(..., description="站点序号")


# ═══════════════════════════════════════════════════
# A. 车辆台账 CRUD
# ═══════════════════════════════════════════════════

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return date.fromisoformat(s)


def _serialize_vehicle(v: VehicleFleet) -> dict:
    return {
        "id": v.id,
        "plate_number": v.plate_number,
        "vehicle_type": v.vehicle_type,
        "brand": v.brand,
        "color": v.color,
        "vin": v.vin,
        "mileage": v.mileage,
        "inspection_due": v.inspection_due.isoformat() if v.inspection_due else None,
        "compulsory_ins_due": v.compulsory_ins_due.isoformat() if v.compulsory_ins_due else None,
        "commercial_ins_due": v.commercial_ins_due.isoformat() if v.commercial_ins_due else None,
        "maintenance_due": v.maintenance_due.isoformat() if v.maintenance_due else None,
        "load_capacity": v.load_capacity,
        "load_unit": v.load_unit,
        "status": v.status,
        "gps_device_id": v.gps_device_id,
        "last_gps_lat": v.last_gps_lat,
        "last_gps_lng": v.last_gps_lng,
        "last_gps_time": v.last_gps_time.isoformat() if v.last_gps_time else None,
        "remark": v.remark,
        "is_active": v.is_active,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


@router.get("/fleet/list")
async def list_fleet(
    status: Optional[str] = Query(None, description="状态筛选: idle/delivering/maintenance"),
    vehicle_type: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """车辆列表"""
    query = select(VehicleFleet).where(VehicleFleet.is_active == True)

    if status:
        query = query.where(VehicleFleet.status == status)
    if vehicle_type:
        query = query.where(VehicleFleet.vehicle_type == vehicle_type)

    query = query.order_by(VehicleFleet.plate_number)
    result = await db.execute(query)
    vehicles = result.scalars().all()

    return {
        "code": 200,
        "data": [_serialize_vehicle(v) for v in vehicles],
        "total": len(vehicles),
    }


@router.get("/fleet/alerts")
async def fleet_alerts(
    days: int = Query(default=30, ge=1, le=90, description="预警天数阈值"),
    current_user: User = Depends(require_role(3)),
    db: AsyncSession = Depends(get_db),
):
    """
    四险一金预警 — 核心痛点功能
    返回所有在 {days} 天内即将到期的车辆及其到期项目
    """
    today = date.today()
    deadline = today + timedelta(days=days)

    result = await db.execute(
        select(VehicleFleet).where(VehicleFleet.is_active == True)
    )
    all_vehicles = result.scalars().all()

    alerts = []
    for v in all_vehicles:
        vehicle_alerts = []
        # 检查四项到期日
        checks = [
            ("inspection", "年检", v.inspection_due),
            ("compulsory_insurance", "交强险", v.compulsory_ins_due),
            ("commercial_insurance", "商业险", v.commercial_ins_due),
            ("maintenance", "常规保养", v.maintenance_due),
        ]
        for key, label, due_date in checks:
            if due_date is None:
                continue
            remaining = (due_date - today).days
            if remaining <= days:
                level = "expired" if remaining < 0 else ("urgent" if remaining <= 7 else "warning")
                vehicle_alerts.append({
                    "type": key,
                    "label": label,
                    "due_date": due_date.isoformat(),
                    "remaining_days": remaining,
                    "level": level,  # expired / urgent / warning
                })

        if vehicle_alerts:
            alerts.append({
                "vehicle": _serialize_vehicle(v),
                "alerts": vehicle_alerts,
            })

    # 按最紧急排序
    alerts.sort(key=lambda x: min(a["remaining_days"] for a in x["alerts"]))

    return {
        "code": 200,
        "data": alerts,
        "total": len(alerts),
    }


@router.get("/fleet/{vehicle_id}")
async def get_fleet_detail(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """车辆详情"""
    result = await db.execute(
        select(VehicleFleet).where(VehicleFleet.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")

    return {"code": 200, "data": _serialize_vehicle(vehicle)}


@router.post("/fleet/create")
async def create_fleet(
    req: VehicleFleetCreateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """新增车辆（管理员）"""
    # 检查车牌号唯一性
    existing = await db.execute(
        select(VehicleFleet).where(VehicleFleet.plate_number == req.plate_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该车牌号已存在")

    vehicle = VehicleFleet(
        plate_number=req.plate_number,
        vehicle_type=req.vehicle_type,
        brand=req.brand,
        color=req.color,
        vin=req.vin,
        mileage=req.mileage,
        inspection_due=_parse_date(req.inspection_due),
        compulsory_ins_due=_parse_date(req.compulsory_ins_due),
        commercial_ins_due=_parse_date(req.commercial_ins_due),
        maintenance_due=_parse_date(req.maintenance_due),
        load_capacity=req.load_capacity,
        load_unit=req.load_unit,
        gps_device_id=req.gps_device_id,
        remark=req.remark,
    )
    db.add(vehicle)
    await db.flush()

    return {"code": 200, "message": "车辆添加成功", "data": _serialize_vehicle(vehicle)}


@router.put("/fleet/{vehicle_id}")
async def update_fleet(
    vehicle_id: int,
    req: VehicleFleetUpdateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """编辑车辆（管理员）"""
    result = await db.execute(
        select(VehicleFleet).where(VehicleFleet.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")

    # 逐字段更新
    update_fields = req.model_dump(exclude_unset=True)
    date_fields = ["inspection_due", "compulsory_ins_due", "commercial_ins_due", "maintenance_due"]
    for key, value in update_fields.items():
        if key in date_fields:
            setattr(vehicle, key, _parse_date(value))
        else:
            setattr(vehicle, key, value)

    await db.flush()
    return {"code": 200, "message": "车辆信息已更新", "data": _serialize_vehicle(vehicle)}


@router.delete("/fleet/{vehicle_id}")
async def delete_fleet(
    vehicle_id: int,
    current_user: User = Depends(require_role(7)),
    db: AsyncSession = Depends(get_db),
):
    """删除车辆（软删除，经理级别）"""
    result = await db.execute(
        select(VehicleFleet).where(VehicleFleet.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")

    vehicle.is_active = False
    await db.flush()
    return {"code": 200, "message": "车辆已删除"}


# ═══════════════════════════════════════════════════
# B. 送货排线管理
# ═══════════════════════════════════════════════════

def _serialize_route(r: DeliveryRoute) -> dict:
    return {
        "id": r.id,
        "route_name": r.route_name,
        "description": r.description,
        "stops": r.stops or [],
        "stop_count": len(r.stops or []),
        "estimated_duration_min": r.estimated_duration_min,
        "estimated_distance_km": r.estimated_distance_km,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/routes/list")
async def list_routes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """排线列表"""
    result = await db.execute(
        select(DeliveryRoute)
        .where(DeliveryRoute.is_active == True)
        .order_by(DeliveryRoute.route_name)
    )
    routes = result.scalars().all()
    return {
        "code": 200,
        "data": [_serialize_route(r) for r in routes],
        "total": len(routes),
    }


@router.get("/routes/{route_id}")
async def get_route_detail(
    route_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DeliveryRoute).where(DeliveryRoute.id == route_id)
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="排线不存在")
    return {"code": 200, "data": _serialize_route(route)}


@router.post("/routes/create")
async def create_route(
    req: RouteCreateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """新增排线（管理员）"""
    route = DeliveryRoute(
        route_name=req.route_name,
        description=req.description,
        stops=[s.model_dump() for s in req.stops],
        estimated_duration_min=req.estimated_duration_min,
        estimated_distance_km=req.estimated_distance_km,
    )
    db.add(route)
    await db.flush()
    return {"code": 200, "message": "排线创建成功", "data": _serialize_route(route)}


@router.put("/routes/{route_id}")
async def update_route(
    route_id: int,
    req: RouteUpdateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """编辑排线（管理员）"""
    result = await db.execute(
        select(DeliveryRoute).where(DeliveryRoute.id == route_id)
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="排线不存在")

    update_data = req.model_dump(exclude_unset=True)
    if "stops" in update_data and update_data["stops"] is not None:
        update_data["stops"] = [s.model_dump() if hasattr(s, 'model_dump') else s for s in update_data["stops"]]

    for key, value in update_data.items():
        setattr(route, key, value)

    await db.flush()
    return {"code": 200, "message": "排线已更新", "data": _serialize_route(route)}


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """删除排线（软删除）"""
    result = await db.execute(
        select(DeliveryRoute).where(DeliveryRoute.id == route_id)
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="排线不存在")

    route.is_active = False
    await db.flush()
    return {"code": 200, "message": "排线已删除"}


# ═══════════════════════════════════════════════════
# C. 出车调度单
# ═══════════════════════════════════════════════════

def _serialize_dispatch(
    d: LogisticsDispatch,
    vehicle: VehicleFleet = None,
    route: DeliveryRoute = None,
    driver: User = None,
    assistant: User = None,
) -> dict:
    data = {
        "id": d.id,
        "work_date": d.work_date.isoformat() if d.work_date else None,
        "vehicle_id": d.vehicle_id,
        "route_id": d.route_id,
        "driver_id": d.driver_id,
        "driver_name": driver.name if driver else None,
        "assistant_id": d.assistant_id,
        "assistant_name": assistant.name if assistant else None,
        "status": d.status,
        "stop_checkins": d.stop_checkins or [],
        "departed_at": d.departed_at.isoformat() if d.departed_at else None,
        "returned_at": d.returned_at.isoformat() if d.returned_at else None,
        "actual_mileage": d.actual_mileage,
        "remark": d.remark,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
    # 嵌套车辆信息
    if vehicle:
        data["vehicle"] = {
            "plate_number": vehicle.plate_number,
            "vehicle_type": vehicle.vehicle_type,
        }
    # 嵌套排线信息
    if route:
        data["route"] = {
            "route_name": route.route_name,
            "stop_count": len(route.stops or []),
        }
    return data


@router.get("/dispatch/list")
async def list_dispatches(
    work_date: Optional[str] = Query(None, description="出车日期 YYYY-MM-DD"),
    status: Optional[str] = Query(None),
    driver_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """调度单列表"""
    query = select(LogisticsDispatch)

    if work_date:
        query = query.where(LogisticsDispatch.work_date == date.fromisoformat(work_date))
    if status:
        query = query.where(LogisticsDispatch.status == status)
    if driver_id:
        query = query.where(LogisticsDispatch.driver_id == driver_id)

    # 非管理员只能看自己的调度单
    if current_user.role < 5:
        query = query.where(
            or_(
                LogisticsDispatch.driver_id == current_user.id,
                LogisticsDispatch.assistant_id == current_user.id,
            )
        )

    query = query.order_by(LogisticsDispatch.work_date.desc(), LogisticsDispatch.created_at.desc())
    result = await db.execute(query)
    dispatches = result.scalars().all()

    # 批量加载关联数据
    vehicle_ids = list(set(d.vehicle_id for d in dispatches))
    route_ids = list(set(d.route_id for d in dispatches if d.route_id))
    driver_ids = list(set(d.driver_id for d in dispatches))
    assistant_ids = list(set(d.assistant_id for d in dispatches if d.assistant_id))
    user_ids = list(set(driver_ids + assistant_ids))

    vehicles_map = {}
    if vehicle_ids:
        vr = await db.execute(select(VehicleFleet).where(VehicleFleet.id.in_(vehicle_ids)))
        vehicles_map = {v.id: v for v in vr.scalars().all()}

    routes_map = {}
    if route_ids:
        rr = await db.execute(select(DeliveryRoute).where(DeliveryRoute.id.in_(route_ids)))
        routes_map = {r.id: r for r in rr.scalars().all()}

    users_map = {}
    if user_ids:
        ur = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_map = {u.id: u for u in ur.scalars().all()}

    return {
        "code": 200,
        "data": [
            _serialize_dispatch(
                d,
                vehicle=vehicles_map.get(d.vehicle_id),
                route=routes_map.get(d.route_id),
                driver=users_map.get(d.driver_id),
                assistant=users_map.get(d.assistant_id),
            )
            for d in dispatches
        ],
        "total": len(dispatches),
    }


@router.get("/dispatch/{dispatch_id}")
async def get_dispatch_detail(
    dispatch_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """调度单详情"""
    result = await db.execute(
        select(LogisticsDispatch).where(LogisticsDispatch.id == dispatch_id)
    )
    dispatch = result.scalar_one_or_none()
    if not dispatch:
        raise HTTPException(status_code=404, detail="调度单不存在")

    # 加载关联车辆
    vr = await db.execute(select(VehicleFleet).where(VehicleFleet.id == dispatch.vehicle_id))
    vehicle = vr.scalar_one_or_none()

    # 加载关联排线
    route = None
    if dispatch.route_id:
        rr = await db.execute(select(DeliveryRoute).where(DeliveryRoute.id == dispatch.route_id))
        route = rr.scalar_one_or_none()

    # 加载司机和跟车员
    dr = await db.execute(select(User).where(User.id == dispatch.driver_id))
    driver = dr.scalar_one_or_none()

    assistant = None
    if dispatch.assistant_id:
        ar = await db.execute(select(User).where(User.id == dispatch.assistant_id))
        assistant = ar.scalar_one_or_none()

    return {"code": 200, "data": _serialize_dispatch(
        dispatch, vehicle=vehicle, route=route, driver=driver, assistant=assistant
    )}


@router.post("/dispatch/create")
async def create_dispatch(
    req: DispatchCreateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """创建调度单（管理员）"""
    # 校验车辆
    vr = await db.execute(select(VehicleFleet).where(VehicleFleet.id == req.vehicle_id))
    vehicle = vr.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")
    if vehicle.status == "maintenance":
        raise HTTPException(status_code=400, detail="该车辆正在维修中，无法调度")

    # 校验司机
    dr = await db.execute(select(User).where(User.id == req.driver_id))
    driver = dr.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="司机不存在")

    # 初始化站点打卡（从排线复制）
    stop_checkins = []
    route = None
    if req.route_id:
        rr = await db.execute(select(DeliveryRoute).where(DeliveryRoute.id == req.route_id))
        route = rr.scalar_one_or_none()
        if not route:
            raise HTTPException(status_code=404, detail="排线不存在")
        # 从排线模板复制站点
        for stop in (route.stops or []):
            stop_checkins.append({
                "seq": stop.get("seq"),
                "client_name": stop.get("client_name"),
                "expected_eta": stop.get("expected_eta"),
                "checked_in_at": None,
            })

    dispatch = LogisticsDispatch(
        work_date=date.fromisoformat(req.work_date),
        vehicle_id=req.vehicle_id,
        route_id=req.route_id,
        driver_id=req.driver_id,
        assistant_id=req.assistant_id,
        stop_checkins=stop_checkins,
        remark=req.remark,
    )
    db.add(dispatch)
    await db.flush()

    return {
        "code": 200,
        "message": "调度单创建成功",
        "data": _serialize_dispatch(dispatch, vehicle=vehicle, route=route, driver=driver),
    }


@router.put("/dispatch/{dispatch_id}/depart")
async def dispatch_depart(
    dispatch_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """出发打卡"""
    result = await db.execute(
        select(LogisticsDispatch).where(LogisticsDispatch.id == dispatch_id)
    )
    dispatch = result.scalar_one_or_none()
    if not dispatch:
        raise HTTPException(status_code=404, detail="调度单不存在")

    if dispatch.status != "pending":
        raise HTTPException(status_code=400, detail="调度单不在待出车状态")

    # 权限：只有司机或管理员可以打卡
    if current_user.id != dispatch.driver_id and current_user.role < 5:
        raise HTTPException(status_code=403, detail="无权操作")

    dispatch.status = "delivering"
    dispatch.departed_at = datetime.now(timezone.utc)

    # 同步更新车辆状态
    vr = await db.execute(select(VehicleFleet).where(VehicleFleet.id == dispatch.vehicle_id))
    vehicle = vr.scalar_one_or_none()
    if vehicle:
        vehicle.status = "delivering"

    await db.flush()
    return {"code": 200, "message": "已出发", "data": {"departed_at": dispatch.departed_at.isoformat()}}


@router.put("/dispatch/{dispatch_id}/checkin")
async def dispatch_checkin(
    dispatch_id: int,
    req: CheckinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """站点打卡"""
    result = await db.execute(
        select(LogisticsDispatch).where(LogisticsDispatch.id == dispatch_id)
    )
    dispatch = result.scalar_one_or_none()
    if not dispatch:
        raise HTTPException(status_code=404, detail="调度单不存在")

    if dispatch.status != "delivering":
        raise HTTPException(status_code=400, detail="调度单不在运送中状态")

    if current_user.id != dispatch.driver_id and current_user.role < 5:
        raise HTTPException(status_code=403, detail="无权操作")

    # 更新对应站点的打卡时间
    checkins = dispatch.stop_checkins or []
    found = False
    for stop in checkins:
        if stop.get("seq") == req.stop_seq:
            stop["checked_in_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if not found:
        raise HTTPException(status_code=400, detail=f"站点序号 {req.stop_seq} 不存在")

    dispatch.stop_checkins = checkins
    # 标记 JSON 字段已修改（SQLAlchemy 不会自动检测 JSON 内部变化）
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(dispatch, "stop_checkins")

    await db.flush()
    return {"code": 200, "message": f"站点 {req.stop_seq} 打卡成功", "data": {"stop_checkins": checkins}}


@router.put("/dispatch/{dispatch_id}/return")
async def dispatch_return(
    dispatch_id: int,
    actual_mileage: Optional[int] = Query(None, description="实际里程(km)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回打卡（完成出车）"""
    result = await db.execute(
        select(LogisticsDispatch).where(LogisticsDispatch.id == dispatch_id)
    )
    dispatch = result.scalar_one_or_none()
    if not dispatch:
        raise HTTPException(status_code=404, detail="调度单不存在")

    if dispatch.status != "delivering":
        raise HTTPException(status_code=400, detail="调度单不在运送中状态")

    if current_user.id != dispatch.driver_id and current_user.role < 5:
        raise HTTPException(status_code=403, detail="无权操作")

    dispatch.status = "completed"
    dispatch.returned_at = datetime.now(timezone.utc)
    if actual_mileage is not None:
        dispatch.actual_mileage = actual_mileage

    # 同步更新车辆状态为待命
    vr = await db.execute(select(VehicleFleet).where(VehicleFleet.id == dispatch.vehicle_id))
    vehicle = vr.scalar_one_or_none()
    if vehicle:
        vehicle.status = "idle"
        if actual_mileage:
            vehicle.mileage += actual_mileage

    await db.flush()
    return {"code": 200, "message": "出车完成", "data": {"returned_at": dispatch.returned_at.isoformat()}}


@router.put("/dispatch/{dispatch_id}/cancel")
async def dispatch_cancel(
    dispatch_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """取消调度单（管理员）"""
    result = await db.execute(
        select(LogisticsDispatch).where(LogisticsDispatch.id == dispatch_id)
    )
    dispatch = result.scalar_one_or_none()
    if not dispatch:
        raise HTTPException(status_code=404, detail="调度单不存在")

    if dispatch.status == "completed":
        raise HTTPException(status_code=400, detail="已完成的调度单无法取消")

    dispatch.status = "cancelled"

    # 如果车辆正在运送中，恢复为待命
    if dispatch.status == "delivering":
        vr = await db.execute(select(VehicleFleet).where(VehicleFleet.id == dispatch.vehicle_id))
        vehicle = vr.scalar_one_or_none()
        if vehicle and vehicle.status == "delivering":
            vehicle.status = "idle"

    await db.flush()
    return {"code": 200, "message": "调度单已取消"}


# ═══════════════════════════════════════════════════
# D. 仪表盘统计
# ═══════════════════════════════════════════════════

@router.get("/dashboard")
async def logistics_dashboard(
    current_user: User = Depends(require_role(3)),
    db: AsyncSession = Depends(get_db),
):
    """
    物流仪表盘 — 一屏总览
    返回：车辆状态分布、今日出车数、预警数、近7天出车趋势
    """
    today = date.today()

    # 1. 车辆状态分布
    fleet_result = await db.execute(
        select(VehicleFleet).where(VehicleFleet.is_active == True)
    )
    all_vehicles = fleet_result.scalars().all()
    fleet_stats = {
        "total": len(all_vehicles),
        "idle": sum(1 for v in all_vehicles if v.status == "idle"),
        "delivering": sum(1 for v in all_vehicles if v.status == "delivering"),
        "maintenance": sum(1 for v in all_vehicles if v.status == "maintenance"),
    }

    # 2. 今日出车数
    today_result = await db.execute(
        select(func.count(LogisticsDispatch.id)).where(
            LogisticsDispatch.work_date == today
        )
    )
    today_dispatches = today_result.scalar() or 0

    # 3. 预警数（30天内到期）
    deadline = today + timedelta(days=30)
    alert_count = 0
    for v in all_vehicles:
        for due in [v.inspection_due, v.compulsory_ins_due, v.commercial_ins_due, v.maintenance_due]:
            if due and due <= deadline:
                alert_count += 1

    # 4. 近7天出车趋势
    week_ago = today - timedelta(days=6)
    trend_result = await db.execute(
        select(
            LogisticsDispatch.work_date,
            func.count(LogisticsDispatch.id),
        )
        .where(LogisticsDispatch.work_date >= week_ago)
        .group_by(LogisticsDispatch.work_date)
        .order_by(LogisticsDispatch.work_date)
    )
    trend_rows = trend_result.all()
    trend = [{"date": row[0].isoformat(), "count": row[1]} for row in trend_rows]

    return {
        "code": 200,
        "data": {
            "fleet": fleet_stats,
            "today_dispatches": today_dispatches,
            "alert_count": alert_count,
            "trend_7d": trend,
        },
    }
