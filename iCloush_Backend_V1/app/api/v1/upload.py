"""
上传路由 — 文件上传中转 + 腾讯云 COS
═══════════════════════════════════════════════════
修复内容：
  1. 新增 POST /task-photo  — 任务拍照上传（watermark.js 调用）
  2. 新增 POST /image       — 通用图片上传（发票/收据等）
  3. 保留 GET  /sts         — COS STS 临时密钥（原有）

上传策略：
  - 优先尝试转存到腾讯云 COS（生产环境）
  - COS 不可用时降级为本地存储（开发环境）
  - 返回统一格式 { code: 200, data: { url: "..." } }
"""
import os
import time
import uuid
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from app.core.config import settings
from app.core.security import get_current_user
from app.models.models import User

router = APIRouter()
logger = logging.getLogger("icloush.upload")

# ── 本地存储目录（COS 不可用时的降级方案）──
UPLOAD_DIR = Path("/app/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _generate_filename(prefix: str, original_name: str) -> str:
    """生成唯一文件名: prefix/20260403/uuid8.ext"""
    ext = os.path.splitext(original_name or "photo.jpg")[1] or ".jpg"
    date_str = datetime.now().strftime("%Y%m%d")
    unique_id = uuid.uuid4().hex[:8]
    return f"{prefix}/{date_str}/{unique_id}{ext}"


async def _upload_to_cos(file_bytes: bytes, file_key: str, content_type: str) -> str:
    """
    上传到腾讯云 COS，返回公网 URL
    如果 COS 未配置或上传失败，抛出异常
    """
    if not getattr(settings, 'COS_SECRET_ID', None) or not getattr(settings, 'COS_SECRET_KEY', None):
        raise RuntimeError("COS 未配置")

    import httpx

    bucket = getattr(settings, 'COS_BUCKET', '')
    region = getattr(settings, 'COS_REGION', 'ap-shanghai')
    host = f"{bucket}.cos.{region}.myqcloud.com"
    url = f"https://{host}/{file_key}"

    # 简化签名（使用 PUT Object）
    now = int(time.time())
    expire = now + 300
    key_time = f"{now};{expire}"

    sign_key = hmac.new(
        settings.COS_SECRET_KEY.encode(), key_time.encode(), hashlib.sha1
    ).hexdigest()

    http_string = f"put\n/{file_key}\n\nhost={host}\n"
    sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()

    authorization = (
        f"q-sign-algorithm=sha1&q-ak={settings.COS_SECRET_ID}"
        f"&q-sign-time={key_time}&q-key-time={key_time}"
        f"&q-header-list=host&q-url-param-list=&q-signature={signature}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(
            url,
            content=file_bytes,
            headers={
                "Host": host,
                "Authorization": authorization,
                "Content-Type": content_type,
            },
        )
        if resp.status_code in (200, 204):
            return url
        else:
            raise RuntimeError(f"COS 上传失败: {resp.status_code} {resp.text[:200]}")


async def _save_file(file: UploadFile, prefix: str, base_url: str) -> str:
    """
    保存上传文件，优先 COS，降级本地
    返回公网可访问的 URL
    """
    file_bytes = await file.read()
    file_key = _generate_filename(prefix, file.filename)
    content_type = file.content_type or "image/jpeg"

    # 尝试 COS
    try:
        cos_url = await _upload_to_cos(file_bytes, file_key, content_type)
        logger.info(f"[上传] COS 成功: {file_key}")
        return cos_url
    except Exception as e:
        logger.warning(f"[上传] COS 不可用，降级本地存储: {e}")

    # 降级：本地存储
    local_path = UPLOAD_DIR / file_key
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    # 返回可访问的 URL（通过后端静态文件服务）
    public_url = f"{base_url}/uploads/{file_key}"
    logger.info(f"[上传] 本地存储: {local_path} → {public_url}")
    return public_url


# ═══════════════════════════════════════════════════
# POST /task-photo — 任务拍照上传（watermark.js 调用）
# ═══════════════════════════════════════════════════

@router.post("/task-photo")
async def upload_task_photo(
    file: UploadFile = File(...),
    task_id: str = Form(default="0"),
    current_user: User = Depends(get_current_user),
):
    """
    任务拍照上传
    接收 watermark.js 合成水印后的图片
    返回公网 URL 供前端展示和提交
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允许上传图片文件")

    # 限制文件大小 10MB
    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件大小不能超过 10MB")
    # 重置文件指针
    await file.seek(0)

    base_url = getattr(settings, 'BASE_URL', '') or 'http://localhost:8000'
    public_url = await _save_file(file, f"task-photos/{task_id}", base_url)

    return {
        "code": 200,
        "data": {"url": public_url},
        "message": "拍照上传成功",
    }


# ═══════════════════════════════════════════════════
# POST /image — 通用图片上传（发票/收据/其他）
# ═══════════════════════════════════════════════════

@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    category: str = Form(default="general"),
    current_user: User = Depends(get_current_user),
):
    """
    通用图片上传
    category: invoice / receipt / general
    返回公网 URL
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允许上传图片文件")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件大小不能超过 10MB")
    await file.seek(0)

    base_url = getattr(settings, 'BASE_URL', '') or 'http://localhost:8000'
    prefix = f"images/{category}/{current_user.id}"
    public_url = await _save_file(file, prefix, base_url)

    return {
        "code": 200,
        "data": {"url": public_url},
        "message": "图片上传成功",
    }


# ═══════════════════════════════════════════════════
# GET /sts — COS STS 临时密钥（原有接口，保留兼容）
# ═══════════════════════════════════════════════════

@router.get("/sts")
async def get_sts_token(
    current_user: User = Depends(get_current_user),
):
    """
    获取腾讯云 COS 临时密钥（STS）
    前端拿到凭证后直接上传图片到 COS，后端不处理图片字节流
    """
    cos_id = getattr(settings, 'COS_SECRET_ID', None)
    cos_key = getattr(settings, 'COS_SECRET_KEY', None)
    if not cos_id or not cos_key:
        raise HTTPException(status_code=500, detail="COS 配置未设置")
    try:
        from sts.sts import Sts
        config = {
            "url": "https://sts.tencentcloudapi.com/",
            "domain": "sts.tencentcloudapi.com",
            "duration_seconds": 1800,
            "secret_id": cos_id,
            "secret_key": cos_key,
            "bucket": getattr(settings, 'COS_BUCKET', ''),
            "region": getattr(settings, 'COS_REGION', 'ap-shanghai'),
            "allow_prefix": f"tasks/{current_user.id}/*",
            "allow_actions": [
                "name/cos:PutObject",
                "name/cos:PostObject",
                "name/cos:InitiateMultipartUpload",
                "name/cos:ListMultipartUploads",
                "name/cos:ListParts",
                "name/cos:UploadPart",
                "name/cos:CompleteMultipartUpload",
            ],
        }
        sts = Sts(config)
        response = sts.get_credential()
        return {
            "code": 200,
            "data": {
                "credentials": response["credentials"],
                "startTime": response["startTime"],
                "expiredTime": response["expiredTime"],
                "bucket": getattr(settings, 'COS_BUCKET', ''),
                "region": getattr(settings, 'COS_REGION', 'ap-shanghai'),
                "prefix": f"tasks/{current_user.id}/",
            },
        }
    except ImportError:
        return {
            "code": 200,
            "data": {
                "credentials": {
                    "tmpSecretId": "mock_secret_id",
                    "tmpSecretKey": "mock_secret_key",
                    "sessionToken": "mock_session_token",
                },
                "startTime": int(time.time()),
                "expiredTime": int(time.time()) + 1800,
                "bucket": getattr(settings, 'COS_BUCKET', '') or "mock-bucket",
                "region": getattr(settings, 'COS_REGION', 'ap-shanghai'),
                "prefix": f"tasks/{current_user.id}/",
            },
            "message": "开发模式：STS SDK 未安装，返回模拟凭证",
        }
