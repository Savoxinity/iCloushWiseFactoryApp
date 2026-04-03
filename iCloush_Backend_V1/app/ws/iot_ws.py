"""
WebSocket 实时推送 — IoT 告警 + 任务通知
═══════════════════════════════════════════════════
WS /ws/iot — 连接后自动订阅：
  - IoT 告警广播（role >= 5）
  - 任务驳回通知（推送给 assignee）
  - 报销审核通知（Phase 3B 新增）
  - 催票通知（Phase 3C 新增）
"""
import json
import logging
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger("icloush.ws")


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # user_id -> WebSocket
        self.active_connections: Dict[int, WebSocket] = {}
        # 管理员连接（role >= 5）
        self.admin_connections: Set[int] = set()

    async def connect(self, websocket: WebSocket, user_id: int, role: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        if role >= 5:
            self.admin_connections.add(user_id)
        logger.info(f"WS 连接: user_id={user_id}, role={role}, 在线={len(self.active_connections)}")

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)
        self.admin_connections.discard(user_id)
        logger.info(f"WS 断开: user_id={user_id}, 在线={len(self.active_connections)}")

    async def send_to_user(self, user_id: int, message: dict):
        """推送给指定用户"""
        ws = self.active_connections.get(user_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(user_id)

    async def broadcast_to_admins(self, message: dict):
        """广播给所有管理员"""
        disconnected = []
        for uid in list(self.admin_connections):
            ws = self.active_connections.get(uid)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    disconnected.append(uid)
        for uid in disconnected:
            self.disconnect(uid)

    async def broadcast_all(self, message: dict):
        """广播给所有连接"""
        disconnected = []
        for uid, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(uid)
        for uid in disconnected:
            self.disconnect(uid)


# 全局连接管理器
manager = ConnectionManager()


@router.websocket("/ws/iot")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 连接入口
    查询参数：?user_id=1&role=5
    """
    raw_user_id = websocket.query_params.get("user_id", "0")
    try:
        user_id = int(raw_user_id)
    except (ValueError, TypeError):
        logger.warning(f"WS user_id 无法转换为整数: {raw_user_id}")
        # 必须先 accept 才能正常 close（FastAPI WebSocket 规范）
        await websocket.accept()
        await websocket.close(code=4001, reason="user_id 必须为整数")
        return

    raw_role = websocket.query_params.get("role", "1")
    try:
        role = int(raw_role)
    except (ValueError, TypeError):
        role = 1

    if not user_id or user_id <= 0:
        logger.warning(f"WS 连接被拒绝: user_id={user_id}")
        await websocket.accept()
        await websocket.close(code=4001, reason="缺少有效的 user_id")
        return

    await manager.connect(websocket, user_id, role)

    try:
        while True:
            # 保持连接，接收心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WS 异常: user_id={user_id}, error={e}")
        manager.disconnect(user_id)


# ── 供其他模块调用的推送函数 ──────────────────────

async def notify_task_rejected(assignee_id: int, task_id: int, task_title: str, reason: str):
    """推送任务驳回通知"""
    await manager.send_to_user(assignee_id, {
        "type": "task_rejected",
        "data": {
            "task_id": task_id,
            "title": task_title,
            "reason": reason,
        },
    })


async def notify_iot_alert(zone_name: str, device_name: str, alert_msg: str):
    """广播 IoT 告警给管理员"""
    await manager.broadcast_to_admins({
        "type": "iot_alert",
        "data": {
            "zone_name": zone_name,
            "device_name": device_name,
            "message": alert_msg,
        },
    })


async def notify_expense_approved(user_id: int, expense_id: int, amount: float):
    """推送报销审核通过通知（Phase 3B 新增）"""
    await manager.send_to_user(user_id, {
        "type": "expense_approved",
        "data": {
            "expense_id": expense_id,
            "amount": amount,
            "message": f"您的报销单（¥{amount:.2f}）已审核通过",
        },
    })


async def notify_invoice_reminder(user_id: int, missing_id: int, item_name: str):
    """推送催票通知（Phase 3C 新增）"""
    await manager.send_to_user(user_id, {
        "type": "invoice_reminder",
        "data": {
            "missing_id": missing_id,
            "item_name": item_name,
            "message": f"请尽快补交「{item_name}」的发票",
        },
    })
