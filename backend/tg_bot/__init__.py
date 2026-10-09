"""Telegram bot 子包：轮询、调度、发送、身份解析与消息路由。"""
from __future__ import annotations

from backend.tg_bot.scheduler import start_tg_bot_poller

__all__ = ["start_tg_bot_poller"]
