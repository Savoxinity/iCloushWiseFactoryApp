"""
IoT 设备路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.models.models import IoTDevice, User
from pydantic import BaseModel

router = APIRouter()


@router.get("/dashboard")
async def iot_dashboard(
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """IoT 总览仪表盘"""
    result = await db.execute(select(IoTDevice))
    devices = result.scalars().all()

    running = sum(1 for d in devices if d.status == "running")
    warning = sum(1 for d in devices if d.status == "warning")
    stopped = sum(1 for d in devices if d.status == "stopped")
    alert_count = sum(len(d.alerts or []) for d in devices)

    return {
        "code": 200,
        "data": {
            "total": len(devices),
            "running": running,
            "warning": warning,
            "stopped": stopped,
            "alert": alert_count,
            "devices": [
                {
                    "id": d.id,
                    "name": d.name,
                    "zone_id": d.zone_id,
                    "device_type": d.device_type,
                    "status": d.status,
                    "temp": d.temp,
                    "speed": d.speed,
                    "chemical_pct": d.chemical_pct,
                    "cycle_count": d.cycle_count,
                    "alerts": d.alerts,
                }
                for d in devices
            ],
        },
    }


@router.get("/devices/{device_id}")
async def get_device(
    device_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IoTDevice).where(IoTDevice.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="设备不存在")

    return {
        "code": 200,
        "data": {
            "id": device.id,
            "name": device.name,
            "zone_id": device.zone_id,
            "device_type": device.device_type,
            "status": device.status,
            "temp": device.temp,
            "speed": device.speed,
            "chemical_pct": device.chemical_pct,
            "cycle_count": device.cycle_count,
            "alerts": device.alerts,
        },
    }

@router.get("/devices")
async def list_devices(
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """IoT 设备列表（兼容前端 /iot/devices 请求）"""
    result = await db.execute(select(IoTDevice))
    devices = result.scalars().all()
    return {
        "code": 200,
        "data": [
            {
                "id": d.id,
                "name": d.name,
                "zone_id": d.zone_id,
                "device_type": d.device_type,
                "status": d.status,
                "temp": d.temp,
                "speed": d.speed,
                "chemical_pct": d.chemical_pct,
                "cycle_count": d.cycle_count,
                "alerts": d.alerts,
            }
            for d in devices
        ],
    }


@router.get("/devices/{device_id}/alerts")
async def get_device_alerts(
    device_id: str,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """获取设备告警（兼容前端字符串 device_id）"""
    # 尝试按整数 ID 查询
    try:
        did = int(device_id)
        result = await db.execute(select(IoTDevice).where(IoTDevice.id == did))
    except ValueError:
        # 前端可能传 "d001" 格式，按名称模糊匹配
        result = await db.execute(select(IoTDevice).where(IoTDevice.name.contains(device_id)))

    device = result.scalar_one_or_none()
    if not device:
        return {"code": 200, "data": []}

    return {"code": 200, "data": device.alerts or []}