"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base
import os

# 数据库配置
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'sqlite:///royalbot.db'  # 默认使用 SQLite
)

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化数据库表"""
    from . import models
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
