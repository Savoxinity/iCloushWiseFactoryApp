"""
iCloush 智慧工厂 — JWT 认证 & RBAC 权限控制
═══════════════════════════════════════════════════
- get_current_user: 从 JWT Token 或微信云托管 x-wx-openid 头获取当前用户
- require_role(min_role): 角色权限装饰器
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import User

security_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, role: int) -> str:
    """生成 JWT Token"""
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT Token"""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 Token")


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    获取当前登录用户
    优先级：
    1. 微信云托管 x-wx-openid 头（免鉴权内部链路）
    2. Authorization Bearer JWT Token
    """
    # ── 微信云托管内部链路 ──
    wx_openid = request.headers.get("x-wx-openid")
    if wx_openid:
        result = await db.execute(select(User).where(User.wechat_openid == wx_openid))
        user = result.scalar_one_or_none()
        if user:
            return user
        # 自动注册
        new_user = User(wechat_openid=wx_openid, name=f"员工_{wx_openid[-4:]}", role=1)
        db.add(new_user)
        await db.flush()
        return new_user

    # ── JWT Token ──
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证凭据")

    payload = decode_token(credentials.credentials)
    user_id = int(payload["sub"])

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")

    return user


def require_role(min_role: int):
    """角色权限依赖注入工厂"""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色等级 >= {min_role}",
            )
        return current_user
    return role_checker
