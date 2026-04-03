"""
iCloush 智慧工厂 — 数据库连接管理
AsyncSession + SQLAlchemy 2.0 风格
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.APP_ENV == "development"),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    创建所有表（开发用，生产用 Alembic）
    使用 checkfirst=True 避免多 worker 并发建表冲突
    """
    async with engine.begin() as conn:
        # checkfirst=True: 先检查表是否存在，已存在则跳过
        # 这样即使多个 worker 同时执行也不会冲突
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
