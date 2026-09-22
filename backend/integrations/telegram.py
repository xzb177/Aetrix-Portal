"""能力：Telegram 通知（Bot Token）

通知服务里的 Telegram 渠道同样早就实现了投递（``backend/notifications.py`` 的
``TelegramChannel``），但只能靠手写数据库配置才能启用。这里补上配置与测试：
填 Bot Token 即启用，用户在个人中心绑定 Telegram 后就能收到站内通知。

配置键沿用既有的 ``telegram_bot_token``（通知服务按它判断渠道是否可用）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend import models

SPEC = {
    "title": "Telegram 通知",
    "desc": "填 Bot Token 即启用；用户在个人中心绑定 Telegram 后即可收到站内通知。",
    "group": "邮件与消息",
    "docs_hint": "Token 形如 123456:ABC-DEF…，从 @BotFather 获取。",
    "fields": [
        {"key": "telegram_bot_token", "label": "Bot Token", "type": "secret"},
    ],
    "test_label": "测试 Bot",
}


def token(db: Session) -> str:
    row = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "telegram_bot_token").first()
    return (row.value or "").strip() if row else ""


def is_configured(values: dict) -> bool:
    """填了发消息用的 Bot Token 才算配过"""
    return bool(str(values.get("telegram_bot_token") or "").strip())


def is_enabled(values: dict) -> bool:
    return is_configured(values)


def apply(db: Session) -> None:
    from backend.notifications import refresh_channels

    refresh_channels()


def test(db: Session, payload: dict) -> dict:
    """调 getMe 验证 Token（顺手把 Bot 名字报出来，便于确认没有填错 Bot）"""
    bot_token = token(db)
    if not bot_token:
        return {"ok": False, "message": "未填 Bot Token（保存后再测）"}
    import httpx

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
        body = resp.json() if resp.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Telegram 不可达：{type(exc).__name__}: {exc}"}
    if not body.get("ok"):
        return {"ok": False,
                "message": f"Token 无效：{body.get('description') or f'HTTP {resp.status_code}'}"}
    result = body.get("result") or {}
    return {"ok": True,
            "message": f"Token 有效：@{(result.get('username') or '').lstrip('@')}"
                       f"（{result.get('first_name') or 'Bot'}）",
            "detail": {"username": result.get("username"), "id": result.get("id")}}
