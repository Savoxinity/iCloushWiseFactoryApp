"""
员工路由
═══════════════════════════════════════════════════
修复：
  BUG-06  新增 PATCH /{user_id}/role
  BUG-07  新增 POST /{user_id}/disable
  BUG-11  UserUpdateRequest 字段名与前端对齐（skills→skill_tags, avatar→avatar_key, 新增 is_multi_post）
  BUG-12  _serialize_user 补充 avatar_key / phone / is_multi_post
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import User

router = APIRouter()


# ── Schemas ─────────────────────────────────────

class UserCreateRequest(BaseModel):
    name: str
    username: str
    password: str
    role: int = 1
    skill_tags: Optional[List[str]] = []
    skills: Optional[List[str]] = None        # 前端可能传 skills 也可能传 skill_tags
    avatar_key: Optional[str] = None
    is_multi_post: bool = False


class UserUpdateRequest(BaseModel):
    """与前端 staff-manage saveStaff 完全对齐：
       data: { name, role, avatar_key, skills, is_multi_post }
    """
    name: Optional[str] = None
    role: Optional[int] = None
    phone: Optional[str] = None
    skill_tags: Optional[List[str]] = None    # 兼容直接传 skill_tags
    skills: Optional[List[str]] = None        # 前端传 skills
    avatar_key: Optional[str] = None          # 前端传 avatar_key
    avatar: Optional[str] = None              # 兼容旧字段
    is_active: Optional[bool] = None
    is_multi_post: Optional[bool] = None


class RoleUpdateRequest(BaseModel):
    """权限管理页面 PATCH /users/{id}/role"""
    role: int


# ── 当前用户 ────────────────────────────────────

@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """获取当前登录用户信息（任何角色）"""
    return {"code": 200, "data": _serialize_user(current_user)}


# ── 员工列表 ────────────────────────────────────

@router.get("/")
async def list_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取全部员工（管理员看全部，员工看同工区）"""
    result = await db.execute(select(User).order_by(User.role.desc(), User.id))
    users = result.scalars().all()
    return {
        "code": 200,
        "data": [_serialize_user(u) for u in users],
    }


# ── 员工详情 ────────────────────────────────────

@router.get("/{user_id}")
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"code": 200, "data": _serialize_user(user)}


# ── 编辑员工（PUT） ─────────────────────────────

@router.put("/{user_id}")
async def update_user(
    user_id: int,
    req: UserUpdateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.name is not None:
        user.name = req.name
    if req.role is not None:
        user.role = req.role
    if req.phone is not None:
        user.phone = req.phone

    # 技能标签：前端传 skills 或 skill_tags 都接受
    new_skills = req.skills if req.skills is not None else req.skill_tags
    if new_skills is not None:
        user.skill_tags = new_skills

    # 头像：前端传 avatar_key 或 avatar 都接受
    new_avatar = req.avatar_key if req.avatar_key is not None else req.avatar
    if new_avatar is not None:
        user.avatar_key = new_avatar

    if req.is_active is not None:
        user.is_active = req.is_active
    if req.is_multi_post is not None:
        user.is_multi_post = req.is_multi_post

    await db.flush()
    return {"code": 200, "message": "更新成功", "data": _serialize_user(user)}


# ── 修改角色（PATCH）—— 权限管理页面专用 ────────

@router.patch("/{user_id}/role")
async def update_user_role(
    user_id: int,
    req: RoleUpdateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """权限管理页面：修改员工角色"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.role = req.role
    await db.flush()
    return {"code": 200, "message": "角色已更新", "data": _serialize_user(user)}


# ── 停用账号 ────────────────────────────────────

@router.post("/{user_id}/disable")
async def disable_user(
    user_id: int,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """停用员工账号"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = False
    await db.flush()
    return {"code": 200, "message": f"{user.name} 账号已停用"}


# ── 创建员工 ────────────────────────────────────

@router.post("/")
async def create_user(
    req: UserCreateRequest,
    current_user: User = Depends(require_role(5)),
    db: AsyncSession = Depends(get_db),
):
    """创建新员工"""
    # 检查用户名是否重复
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 前端可能传 skills 也可能传 skill_tags
    final_skills = req.skills if req.skills else req.skill_tags

    new_user = User(
        name=req.name,
        username=req.username,
        password_hash=req.password,  # 注意：当前系统使用明文密码
        role=req.role,
        skill_tags=final_skills or [],
        avatar_key=req.avatar_key or (req.name[0] if req.name else "?"),
        is_multi_post=req.is_multi_post,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    return {"code": 200, "message": "创建成功", "data": _serialize_user(new_user)}


# ── 序列化 ──────────────────────────────────────

def _serialize_user(u: User) -> dict:
    ROLE_MAP = {1: "普通员工", 3: "组长", 5: "主管", 7: "经理", 9: "超级管理员"}
    return {
        "id": u.id,
        "name": u.name,
        "username": u.username,
        "phone": u.phone,
        "role": u.role,
        "role_label": ROLE_MAP.get(u.role, "未知"),
        "avatar_key": u.avatar_key,
        "skill_tags": u.skill_tags or [],
        "skills": u.skill_tags or [],          # 前端有些地方用 skills
        "current_zones": u.current_zones or [],
        "is_multi_post": u.is_multi_post,
        "is_active": u.is_active,
        "total_points": u.total_points,
        "monthly_points": u.monthly_points,
        "task_completed": u.task_completed,
    }
