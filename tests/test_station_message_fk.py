"""站内信外键回归测试：验证 station_messages.from_user_id 外键指向 web_users.id。

根因：该外键曾指向已废弃的 admin_users(id)，而实际写入的是 web_users.id，
PG 强校验导致 INSERT 失败且错误被吞掉；同时 send_user_message 曾不检查
通知结果而谎报成功。
"""

import asyncio
import os
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models


@pytest.fixture()
def db():
    # StaticPool + check_same_thread=False：内存库用单连接跨线程共享。
    # send_user_message 内部经 run_in_threadpool 切线程，用默认池子线程会拿到
    # 一个全新的空内存库（"no such table" / 跨线程连接报错）。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_user(db, username, is_staff=False):
    u = models.WebUser(username=username, password_hash="x", is_staff=is_staff)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_from_user_id_fk_targets_web_users(db):
    """from_user_id 外键应指向 web_users：管理员发给普通用户的站内信可正常插入。"""
    admin = _make_user(db, "admin_a", is_staff=True)
    user = _make_user(db, "user_b")

    msg = models.StationMessage(from_user_id=admin.id, to_user_id=user.id, title="t", content="c")
    db.add(msg)
    db.commit()
    db.refresh(msg)

    assert msg.from_user.username == admin.username


def test_send_user_message_raises_500_when_in_app_fails(db):
    """站内通知失败时 send_user_message 应抛 HTTPException 500，而不是谎报成功。"""
    from unittest.mock import AsyncMock, patch
    from fastapi import HTTPException
    from backend.api.admin import send_user_message, UserMessageSendRequest

    admin = _make_user(db, "admin_a", is_staff=True)
    u = _make_user(db, "user_b")

    with patch("backend.api.admin.notify_admin_event", new=AsyncMock(return_value={"in_app": False})):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(send_user_message(user_id=u.id, request=UserMessageSendRequest(title="t", content="c"), current_admin=admin, db=db))

    assert exc_info.value.status_code == 500


def test_from_user_id_fk_enforced(db):
    """外键真实指向 web_users：不存在的 from_user_id 在强制外键下插入失败"""
    from sqlalchemy import event
    from sqlalchemy import text as _text
    from sqlalchemy.exc import IntegrityError
    engine = db.get_bind()

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, conn_record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # fixture 建表/插数据的连接可能早于监听注册，给当前连接也手动打开
    db.execute(_text("PRAGMA foreign_keys=ON"))
    to_user = _make_user(db, "to_user_fk")
    bad = models.StationMessage(from_user_id=99999, to_user_id=to_user.id,
                                title="t", content="c")
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_send_user_message_success_when_in_app_ok(db):
    """in_app 成功时返回成功（且不再有谎报成功的分支可走）"""
    from unittest.mock import AsyncMock, patch
    from backend.api.admin import send_user_message, UserMessageSendRequest
    admin = _make_user(db, "admin_ok", is_staff=True)
    u = _make_user(db, "user_ok")
    with patch("backend.api.admin.notify_admin_event",
               new=AsyncMock(return_value={"in_app": True})):
        result = asyncio.run(send_user_message(
            user_id=u.id,
            request=UserMessageSendRequest(title="t", content="c"),
            current_admin=admin, db=db))
    assert result == {"success": True, "message": "消息发送成功"}
