# backend/tg_bot/identity.py
"""Telegram 用户身份解析模块：负责将 Telegram 用户映射到站内 Web 用户"""

from sqlalchemy.orm import Session

from backend.models import WebUser


def resolve(db: Session, tg_user_id: int) -> WebUser | None:
    """根据 Telegram 用户 ID 解析对应的站内 Web 用户

    Args:
        db: 数据库会话对象
        tg_user_id: Telegram 用户 ID

    Returns:
        WebUser: 找到的站内用户对象
        None: 未找到对应用户时返回 None
    """
    # 通过 telegram_id 字段精确查询，unique 约束保证最多一条记录
    return (
        db.query(WebUser)
        .filter(WebUser.telegram_id == tg_user_id)
        .first()
    )

