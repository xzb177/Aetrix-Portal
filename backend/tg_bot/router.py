"""Telegram 消息路由：把 getUpdates 的单个 update 分发到命令处理器。"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# 命令级限流：每用户每命令 3 秒 1 次（B1 简版内存实现）
_RATE_LIMIT_SECONDS = 3.0
_rate_limits: dict[tuple[int, str], float] = {}
_rate_lock = threading.Lock()


def _allow(tg_user_id: int, cmd: str) -> bool:
    """限流检查，通过返回 True"""
    now = time.monotonic()
    with _rate_lock:
        last = _rate_limits.get((tg_user_id, cmd))
        if last is not None and now - last < _RATE_LIMIT_SECONDS:
            return False
        _rate_limits[(tg_user_id, cmd)] = now
        if len(_rate_limits) > 10000:
            cutoff = now - _RATE_LIMIT_SECONDS
            for k, v in list(_rate_limits.items()):
                if v < cutoff:
                    del _rate_limits[k]
        return True


def _verify_bind_code(db, update: dict) -> None:
    """验证网页端发起的绑定码（流程 A）。

    用户在网页点"绑定"生成码（user_id 已填），然后给 bot 发 6 位码。
    验证通过后设置 WebUser.telegram_id。
    """
    from backend.models import TgBindCode, WebUser
    from backend.tg_bot import sender

    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    tg_user = msg.get("from") or {}
    tg_user_id = tg_user.get("id")
    chat_id = (msg.get("chat") or {}).get("id")
    if not tg_user_id or not chat_id:
        return

    now = datetime.now()
    record = (
        db.query(TgBindCode)
        .filter(
            TgBindCode.code == text,
            TgBindCode.user_id.isnot(None),
            TgBindCode.telegram_id.is_(None),
            TgBindCode.used_at.is_(None),
            TgBindCode.expires_at > now,
        )
        .order_by(TgBindCode.id.desc())
        .first()
    )
    if not record:
        return  # 不是有效的绑定码，静默忽略

    user = db.query(WebUser).filter(WebUser.id == record.user_id).first()
    if not user:
        return
    # 检查该 TG 账号是否已被其他用户绑定
    existing = (
        db.query(WebUser)
        .filter(WebUser.telegram_id == tg_user_id, WebUser.id != user.id)
        .first()
    )
    if existing:
        sender.send_message(db, chat_id, "该 Telegram 账号已被其他用户绑定")
        return

    user.telegram_id = tg_user_id
    record.telegram_id = tg_user_id
    record.used_at = now
    db.commit()
    sender.send_message(db, chat_id, "绑定成功！现在可以使用公益服功能了。")
    logger.info("tg bind success: user_id=%s tg_id=%s", user.id, tg_user_id)


def dispatch(db, update: dict) -> None:
    """分发单个 update 到对应的处理器。"""
    from backend.tg_bot import handlers, sender

    try:
        # callback_query 走 B3
        if "callback_query" in update:
            from backend.tg_bot import callbacks
            callbacks.handle_callback(db, update["callback_query"])
            return

        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        tg_user = msg.get("from") or {}
        if not chat_id:
            return

        # 6 位纯数字 → 绑定码验证
        if text.isdigit() and len(text) == 6:
            _verify_bind_code(db, update)
            return

        # 非命令文本忽略
        if not text.startswith("/"):
            return

        # 解析命令（去掉 @bot 后缀）
        first_token = text.split()[0]
        cmd = first_token.split("@")[0].lower()
        args = text[len(first_token):].strip()

        commands = {
            "/start": handlers.handle_start,
            "/help": handlers.handle_help,
            "/bind": handlers.handle_bind,
        }
        fn = commands.get(cmd)
        tg_uid = tg_user.get("id") or 0
        if fn:
            if not _allow(tg_uid, cmd):
                sender.send_message(db, chat_id, "操作太快了，稍后再试")
                return
            reply = fn(db, tg_user, chat_id, args)
        else:
            reply = "未知命令，发送 /help 查看可用命令"
        # handler 可返回 str 或 (text, reply_markup) 元组（一键登录按钮）
        if isinstance(reply, tuple):
            text, markup = reply
        else:
            text, markup = reply, None
        sender.send_message(db, chat_id, text, reply_markup=markup)
    except Exception as exc:  # noqa: BLE001
        logger.error("tg dispatch failed: %s", exc, exc_info=True)
