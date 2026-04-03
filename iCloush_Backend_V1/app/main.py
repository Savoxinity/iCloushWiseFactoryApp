"""
iCloush 智慧工厂 — FastAPI 入口
═══════════════════════════════════════════════════
Phase 4 更新：新增 vehicles 路由（机动物流中台）
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db

# ── 核心路由 ──
from app.api.v1 import auth, tasks, zones, users, schedule, iot, upload, reports, mall, points
# ── Phase 3: 业财一体化 ──
from app.api.v1 import invoice, expense, accounting, missing_invoice
# ── Phase 4: 机动物流中台 ──
from app.api.v1 import vehicles

from app.ws.iot_ws import router as ws_router

logger = logging.getLogger("icloush")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 iCloush 智慧工厂后端启动中...")
    try:
        await init_db()
        logger.info("✅ 数据库表已同步")
    except Exception as e:
        logger.warning(f"⚠️ 建表时出现异常（可忽略）: {e}")
    yield
    logger.info("🛑 iCloush 后端关闭")


app = FastAPI(
    title="iCloush 智慧工厂 API",
    description="洗涤工厂智能管理系统后端服务",
    version="4.0.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为小程序域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════
# API 路由注册
# ═══════════════════════════════════════════════════

# ── 核心模块 ──
app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["认证"])
app.include_router(tasks.router,    prefix="/api/v1/tasks",    tags=["任务"])
app.include_router(zones.router,    prefix="/api/v1/zones",    tags=["工区"])
app.include_router(users.router,    prefix="/api/v1/users",    tags=["员工"])
app.include_router(schedule.router, prefix="/api/v1/schedule", tags=["排班"])
app.include_router(iot.router,      prefix="/api/v1/iot",      tags=["IoT"])
app.include_router(upload.router,   prefix="/api/v1/upload",   tags=["上传"])
app.include_router(reports.router,  prefix="/api/v1/reports",  tags=["报表"])
app.include_router(mall.router,     prefix="/api/v1/mall",     tags=["商城"])
app.include_router(points.router,   prefix="/api/v1/points",   tags=["积分"])
app.include_router(reports.router,  prefix="/api/v1/production", tags=["产能"])
app.include_router(mall.router,     prefix="/api/v1/exchange", tags=["兑换"])

# ── Phase 3: 业财一体化 ──
app.include_router(invoice.router,         prefix="/api/v1/invoices",         tags=["发票"])
app.include_router(expense.router,         prefix="/api/v1/expenses",         tags=["报销"])
app.include_router(accounting.router,      prefix="/api/v1/accounting",       tags=["管理会计"])
app.include_router(missing_invoice.router, prefix="/api/v1/missing-invoices", tags=["欠票看板"])

# ── Phase 4: 机动物流中台 ──
app.include_router(vehicles.router, prefix="/api/v1/vehicles", tags=["物流车辆"])

# ── WebSocket ──
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "iCloush Backend", "version": "4.0.0"}
