"""Telegram update 路由：命令解析、绑定码识别、限流与分发（业务入口）。"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass

from backend.database import SessionLocal
from backend.tg_bot.sender import TgSender

logger = logging.getLogger(__name__)

RATE_LIMIT_SECONDS = 3.0

# 限流内存表：{(telegram_id, 命令): 上次放行时间}，B1 简版
_rate_limits: dict[tuple[int, str], float] = {}
_rate_lock = threading.Lock()


@dataclass
class BotContext:
    """bot 运行上下文：发送器、bot 用户名、站点信息。"""

    sender: TgSender
    bot_username: str
    site_name: str
    site_base_url: str


def parse_command(text: str) -> tuple[str, list[str]] | None:
    """解析 "/cmd args" 文本；返回 (命令名小写去@后缀, 参数列表)，非命令返回 None。"""
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text.split()
    name = parts[0][1:].split("@", 1)[0].lower()
    if not name:
        return None
    return name, parts[1:]


def is_potential_bind_code(text: str) -> bool:
    """判断文本是否为 6 位纯数字（绑定码候选）。"""
    return re.fullmatch(r"\d{6}", text.strip()) is not None


def _allow(user_id: int, key: str) -> bool:
    """每用户每命令 3 秒限流，返回是否放行。"""
    now = time.monotonic()
    with _rate_lock:
        last = _rate_limits.get((user_id, key))
        if last is not None and now - last < RATE_LIMIT_SECONDS:
            return False
        _rate_limits[(user_id, key)] = now
        return True


def _reply(ctx: BotContext, chat_id: int | None, text: str) -> None:
    """尽力回复；chat_id 不可用时跳过。"""
    if chat_id is None:
        return
    ctx.sender.send_message(chat_id, text)


def _load_handler(cmd: str):
    """延迟导入 handlers 模块并取 handle_<cmd>（P2 生成），找不到返回 None。"""
    try:
        from backend.tg_bot import handlers
    except ImportError:
        logger.warning("handlers 模块尚未就绪 cmd=%s", cmd)
        return None
    return getattr(handlers, "handle_" + cmd, None)


def _load_bind_verifier():
    """延迟导入 bind 模块并取 verify_bind_code（P2 生成），找不到返回 None。"""
    try:
        from backend.tg_bot import bind as bind_module
    except ImportError:
        logger.warning("bind 模块尚未就绪")
        return None
    return getattr(bind_module, "verify_bind_code", None)


def dispatch(update: dict, ctx: BotContext) -> None:
    """分发单个 update；独立 DB session，异常只记日志不外抛。"""
    db = SessionLocal()
    chat_id: int | None = None
    try:
        if "message" in update:
            message = update.get("message") or {}
            chat_id = (message.get("chat") or {}).get("id")
            text = message.get("text")
            if not isinstance(text, str) or not text.strip():
                return  # 无文本消息忽略
            telegram_id = (message.get("from") or {}).get("id") or chat_id or 0
            text = text.strip()

            # 1) 命令分发
            parsed = parse_command(text)
            if parsed is not None:
                cmd, _args = parsed
                handler = _load_handler(cmd)
                if handler is None:
                    _reply(ctx, chat_id, "未知命令，发送 /help 查看")
                    return
                if not _allow(telegram_id, cmd):
                    _reply(ctx, chat_id, "操作太快了，稍后再试")
                    return
                # 约定签名（P2 实现）：handler(db, message, ctx)
                handler(db, message, ctx)
                return

            # 2) 6 位绑定码
            if is_potential_bind_code(text):
                verify = _load_bind_verifier()
                if verify is None:
                    return
                if not _allow(telegram_id, "bind"):
                    _reply(ctx, chat_id, "操作太快了，稍后再试")
                    return
                # 约定签名（P2 实现）：verify_bind_code(db, message, code, ctx)
                verify(db, message, text, ctx)
                return
            return

        # 3) 回调查询：B1 仅记录并占位回复（B3 实现抢红包）
        if "callback_query" in update:
            cb = update.get("callback_query") or {}
            chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
            logger.info("callback_query data=%s chat_id=%s", cb.get("data"), chat_id)
            _reply(ctx, chat_id, "即将上线")
            return

        # 其余 update 类型忽略
    except Exception:
        logger.exception("dispatch update 失败")
        _reply(ctx, chat_id, "服务开小差了，请稍后再试")
    finally:
        db.close()
