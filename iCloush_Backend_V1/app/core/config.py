"""
iCloush 智慧工厂 — 配置管理
从 .env 文件或环境变量加载配置

注意：默认值已对齐 docker-compose.yml 中的服务名和密码，
      Docker 容器内可直接启动，无需额外配置。
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── 数据库 ──
    # 默认值对齐 docker-compose.yml：host=postgres, password=icloush_dev_2026
    DATABASE_URL: str = "postgresql+asyncpg://icloush:icloush_dev_2026@postgres:5432/icloush_db"

    # ── JWT ──
    JWT_SECRET: str = "icloush_super_secret_key_2026"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 168  # 7 天

    # ── 微信 ──
    WX_APPID: str = ""
    WX_APPSECRET: str = ""
    WX_CLOUD_RUN: bool = False  # 是否部署在微信云托管

    # ── 腾讯云API KEY ──
    TENCENT_SECRET_ID: str = ""
    TENCENT_SECRET_KEY: str = ""
    TENCENT_OCR_REGION: str = "ap-shanghai"

    # ── 腾讯云 COS ──
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_REGION: str = "ap-shanghai"
    COS_BUCKET: str = ""

    # ── Redis ──
    # 默认值对齐 docker-compose.yml：host=redis
    REDIS_URL: str = "redis://redis:6379/0"

    # ── 服务 ──
    APP_ENV: str = "development"
    APP_PORT: int = 80  # 微信云托管要求 80
    APP_HOST: str = "0.0.0.0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
