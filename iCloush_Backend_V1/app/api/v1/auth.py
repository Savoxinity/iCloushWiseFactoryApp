"""
认证路由 — 微信登录 + 账号密码登录
═══════════════════════════════════════════════════
修复：BUG-13 删除重复的 password_login 函数定义 + 清理死代码
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
from app.models.models import User

router = APIRouter()


class WechatLoginRequest(BaseModel):
    code: str


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: int
    name: str
    role: int


@router.post("/wechat", response_model=LoginResponse)
async def wechat_login(req: WechatLoginRequest, db: AsyncSession = Depends(get_db)):
    """微信小程序登录（code2session → openid → 查找/创建用户）"""
    if not settings.WX_APPID or not settings.WX_APPSECRET:
        raise HTTPException(status_code=500, detail="微信配置未设置")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": settings.WX_APPID,
                "secret": settings.WX_APPSECRET,
                "js_code": req.code,
                "grant_type": "authorization_code",
            },
        )
        data = resp.json()

    openid = data.get("openid")
    if not openid:
        raise HTTPException(status_code=400, detail=f"微信登录失败: {data.get('errmsg', '未知错误')}")

    # 查找或创建用户
    result = await db.execute(select(User).where(User.wechat_openid == openid))
    user = result.scalar_one_or_none()

    if not user:
        user = User(wechat_openid=openid, name=f"员工_{openid[-4:]}", role=1)
        db.add(user)
        await db.flush()

    token = create_access_token(user.id, user.role)
    return LoginResponse(token=token, user_id=user.id, name=user.name, role=user.role)


@router.post("/verify", response_model=LoginResponse)
async def password_login(req: PasswordLoginRequest, db: AsyncSession = Depends(get_db)):
    """账号密码登录（开发/调试用）"""
    try:
        result = await db.execute(select(User).where(User.username == req.username))
        user = result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库查询异常: {str(e)}")

    if not user or not user.password_hash:
        raise HTTPException(status_code=403, detail="账号或密码错误")

    if user.password_hash != req.password:
        raise HTTPException(status_code=403, detail="账号或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")

    token = create_access_token(user.id, user.role)
    return LoginResponse(token=token, user_id=user.id, name=user.name, role=user.role)


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "id": current_user.id,
        "name": current_user.name,
        "role": current_user.role,
        "avatar_key": current_user.avatar_key,
        "skill_tags": current_user.skill_tags,
        "current_zones": current_user.current_zones,
        "is_multi_post": current_user.is_multi_post,
        "total_points": current_user.total_points,
        "monthly_points": current_user.monthly_points,
        "task_completed": current_user.task_completed,
        "is_active": current_user.is_active,
    }
