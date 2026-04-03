"""
iCloush 智慧工厂 — 数据模型汇总
导入所有模型以确保 Base.metadata.create_all 能创建全部表
"""
from app.models.models import (
    User, Zone, Task, TaskRecord, Vehicle,
    IoTDevice, PointLedger, MallItem, DailyProduction,
)
from app.models.finance import (
    Invoice, ExpenseReport, ManagementCostLedger, MissingInvoiceLedger,
    COST_CATEGORIES,
)

__all__ = [
    "User", "Zone", "Task", "TaskRecord", "Vehicle",
    "IoTDevice", "PointLedger", "MallItem", "DailyProduction",
    "Invoice", "ExpenseReport", "ManagementCostLedger", "MissingInvoiceLedger",
    "COST_CATEGORIES",
]
